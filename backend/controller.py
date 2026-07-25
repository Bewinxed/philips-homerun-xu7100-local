"""Semantic control layer for the Philips HomeRun XU7100 (Tuya category 'sd').

Two interchangeable backends behind one interface:
  * TuyaBackend  - real robot over the LAN (tinytuya, no cloud needed for control)
  * SimBackend   - in-memory state machine, so the whole UI/HA stack is testable
                   before the local_key exists.

The semantic <-> DP mapping lives in dp_schema.json and is refined by
tools/learn_dps.py once we can actually poll the robot.
"""
from __future__ import annotations
import json, os, threading, time, copy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def _load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default

SCHEMA = _load_json(os.path.join(HERE, "dp_schema.json"), {})

# Canonical states we normalise every backend into (mirrors HA vacuum states)
IDLE, CLEANING, PAUSED, RETURNING, DOCKED, CHARGING, ERROR = \
    "idle", "cleaning", "paused", "returning", "docked", "charging", "error"

FAN_LEVELS = ["quiet", "normal", "strong", "max"]
WATER_LEVELS = ["low", "middle", "high", "closed"]


def _schema_dp(name):
    e = SCHEMA.get(name)
    return e.get("dp") if isinstance(e, dict) else None


class BaseBackend:
    """Common shape. Subclasses implement _read_raw() and _write(dp, value)."""
    source = "base"

    def __init__(self):
        self._lock = threading.Lock()
        self._raw = {}
        self._last_update = 0.0
        self.connected = False

    # ---- semantic state ---------------------------------------------------
    def state(self) -> dict:
        raw = self.raw()
        return {
            "source": self.source,
            "connected": self.connected,
            "state": self._derive_state(raw),
            "battery": self._get(raw, "battery"),
            "fan": self._get(raw, "fan"),
            "water": self._get(raw, "water"),
            "mode": self._get(raw, "mode"),
            "clean_area": self._get(raw, "clean_area"),
            "clean_time": self._get(raw, "clean_time"),
            "fault": self._get(raw, "fault"),
            "raw": raw,
            "last_update": self._last_update,
        }

    # Consumable life counters: value = minutes remaining, max from the Tuya DP spec.
    CONSUMABLES = {
        "17": ("Side brush", 9000),
        "19": ("Main brush", 18000),
        "21": ("Filter", 9000),
        "23": ("Mop cloth", 9000),
    }
    # Toggles worth surfacing in the UI (semantic name -> label)
    TOGGLES = {
        "auto_boost": "Carpet boost", "do_not_disturb": "Do not disturb",
        "child_lock": "Child lock", "y_mop": "Y-pattern mop",
        "vibration": "Vibration mop", "customize_mode": "Custom mode",
        "dust_collect": "Auto-empty dock",
    }
    # Fault bitmap — AUTHORITATIVE labels, pulled from this device's own Tuya
    # DP specification (status 'fault', type Bitmap). Do not guess these.
    FAULT_BITS = [
        "lidar_shelter", "wheel_up", "low_battery", "dust_water", "ground_start",
        "cliff_ir", "co_sensor", "go_dock", "navigation", "escape", "wait_charge",
        "auto_power", "auto_power_b", "side_brush", "follow_ir", "dustbox",
        "water_level", "collection_bag", "dust_bag", "collection", "dust_bag_in",
        "collection_f", "on_collector", "collecting_box", "dust_frequently",
        "water_level_mop",
    ]
    # Human-readable hints for the ones that actually come up.
    FAULT_HINTS = {
        "lidar_shelter": "lidar blocked / dirty — clean the turret window",
        "wheel_up": "a drive wheel is off the ground",
        "auto_power": "motor overload cut-out — usually a jammed brush",
        "auto_power_b": "secondary motor overload cut-out",
        "side_brush": "side brush jammed",
        "dustbox": "dust bin missing or not seated",
        "cliff_ir": "cliff sensor — dirty, or a real drop",
        "navigation": "navigation/localisation failure",
        "go_dock": "could not reach the dock",
        "escape": "trapped, could not escape",
    }

    def diagnostics(self) -> dict:
        """Everything the robot actually exposes about its own health."""
        raw = self.raw()
        d = {"consumables": [], "faults": [], "totals": {}, "device": {}, "components": {}}

        for dp, (name, full) in self.CONSUMABLES.items():
            v = raw.get(dp)
            if isinstance(v, (int, float)):
                d["consumables"].append({
                    "name": name, "remaining_min": int(v), "full_min": full,
                    "percent": round(100.0 * v / full, 1) if full else None,
                    "hours_left": round(v / 60.0, 1),
                })

        f = raw.get("28")
        if isinstance(f, int):
            d["fault_code"] = f
            names = [n for i, n in enumerate(self.FAULT_BITS) if f & (1 << i)]
            d["faults"] = names
            d["fault_detail"] = [
                {"name": n, "hint": self.FAULT_HINTS.get(n, "")} for n in names
            ]

        for dp, key, unit in (("29", "total_area", "m2"), ("30", "total_cleans", "runs"),
                              ("31", "total_time", "min")):
            if dp in raw:
                d["totals"][key] = {"value": raw[dp], "unit": unit}

        # device_info blob (wifi/rssi/ip/mac/firmware) arrives on DP 34 as base64 JSON
        info = raw.get("34")
        if isinstance(info, str):
            try:
                import base64 as _b64
                d["device"] = json.loads(_b64.b64decode(info).decode())
            except Exception:
                pass

        for dp, label in (("40", "mop"), ("41", "work mode"), ("106", "clean type"),
                          ("9", "suction"), ("10", "water"), ("103", "remote mode")):
            if dp in raw:
                d["components"][label] = raw[dp]

        d["toggles"] = {}
        for name, label in self.TOGGLES.items():
            dp = _schema_dp(name)
            if dp and dp in raw:
                d["toggles"][name] = {"label": label, "on": bool(raw[dp])}

        for name, key in (("volume", "volume"), ("map_num", "maps_stored"),
                          ("charge_time_left", "charge_min_left"),
                          ("sweep_count", "passes")):
            dp = _schema_dp(name)
            if dp and dp in raw:
                d.setdefault("settings", {})[key] = raw[dp]
        return d

    def raw(self) -> dict:
        with self._lock:
            return dict(self._raw)

    def _get(self, raw, name):
        dp = _schema_dp(name)
        if dp is None:
            return None
        return raw.get(str(dp))

    def _derive_state(self, raw):
        # Prefer an explicit status DP; fall back to power/return flags.
        st = self._get(raw, "status")
        if st is not None:
            s = str(st).lower()
            # Order matters: "goto_charge" contains "charg", so the returning
            # check MUST come first or a robot driving home reads as "Charging".
            if "goto_charge" in s or "return" in s or "back_charge" in s:
                return RETURNING
            if "done" in s or "full" in s or ("charg" in s and "complet" in s):
                return DOCKED
            if "charg" in s:
                return CHARGING
            # firmware reports states Tuya's spec doesn't document (e.g. "positioning")
            if "position" in s or "locat" in s or "relocat" in s or "goto_pos" in s:
                return CLEANING
            if "paus" in s:
                return PAUSED
            if "clean" in s or "smart" in s or "zone" in s or "part" in s or "spot" in s:
                return CLEANING
            if "sleep" in s or "standby" in s or "idle" in s:
                return IDLE
            if "fault" in s or "error" in s or "alarm" in s:
                return ERROR
        fault = self._get(raw, "fault")
        if fault not in (None, 0, "0", "", "no_fault", "none"):
            return ERROR
        return IDLE

    # ---- commands ---------------------------------------------------------
    def start(self):    self._command("start")
    def pause(self):    self._command("pause")
    def stop(self):     self._command("stop")
    def home(self):     self._command("home")
    def locate(self):   self._command("locate")

    def set_fan(self, level):
        dp = _schema_dp("fan")
        if dp: self._write(dp, level)

    def set_water(self, level):
        dp = _schema_dp("water")
        if dp: self._write(dp, level)

    def set_dp(self, dp, value):
        self._write(str(dp), value)

    # ---- extended controls (all datapoints verified via cloud shadow) --------
    def start_mapping(self):
        """DP 104 create_map — build a fresh map without cleaning."""
        dp = _schema_dp("create_map")
        if dp: self._write(dp, True)

    def drive(self, direction):
        """DP 12 direction_control: forward|backward|turn_left|turn_right|stop.
        Lets us walk the robot home manually instead of carrying it (carrying
        triggers kidnap detection and throws the session map away)."""
        if direction not in ("forward", "backward", "turn_left", "turn_right", "stop"):
            raise ValueError(f"bad direction {direction}")
        dp = _schema_dp("direction")
        if dp: self._write(dp, direction)

    def set_toggle(self, name, on):
        if name not in self.TOGGLES:
            raise ValueError(f"unknown toggle {name}")
        dp = _schema_dp(name)
        if dp: self._write(dp, bool(on))

    def set_volume(self, level):
        dp = _schema_dp("volume")
        if dp: self._write(dp, max(0, min(100, int(level))))

    def reset_consumable(self, which):
        keys = {"edge_brush": "edge_brush_reset", "roll_brush": "roll_brush_reset",
                "filter": "filter_reset", "rag": "rag_reset"}
        if which not in keys:
            raise ValueError(f"unknown consumable {which}")
        dp = _schema_dp(keys[which])
        if dp: self._write(dp, True)

    # ---- room commands (DP 15 command_trans frames) -------------------------
    @staticmethod
    def _frame(cmd, data=b""):
        body = bytes([cmd]) + bytes(data)
        return bytes([0xAA, 0x00, len(body)]) + body + bytes([sum(body) & 0xFF])

    def _send_frame(self, cmd, data=b""):
        f = self._frame(cmd, data)
        dp = _schema_dp("command_trans")
        if dp:
            self._write(dp, f.hex())
        return f.hex()

    def clean_rooms(self, room_ids, passes=1):
        """cmd 0x14: clean selected rooms.
        payload: cleanCount(1) nRooms(1) roomIds…"""
        ids = [int(r) for r in room_ids]
        if not ids:
            raise ValueError("no rooms given")
        frame = self._send_frame(0x14, bytes([int(passes), len(ids)]) + bytes(ids))
        m = _schema_dp("mode")
        if m: self._write(m, "part")
        p = _schema_dp("power")
        if p: self._write(p, True)
        return frame

    def rename_room(self, room_id, name):
        """cmd 0x24: rename a room. payload: id(1) nameLen(1) utf8name…"""
        nb = str(name).encode()[:20]
        return self._send_frame(0x24, bytes([int(room_id), len(nb)]) + nb)

    def merge_rooms(self, room_a, room_b):
        """cmd 0x1e: merge two rooms."""
        return self._send_frame(0x1E, bytes([int(room_a), int(room_b)]))

    def split_room(self, room_id, x1, y1, x2, y2):
        """cmd 0x1c: split a room along a line (command coords, int16 BE)."""
        d = bytes([int(room_id)])
        for v in (x1, y1, x2, y2):
            d += int(v).to_bytes(2, "big", signed=True)
        return self._send_frame(0x1C, d)

    def set_room_attrs(self, room_id, fan=None, water=None, passes=None):
        """cmd 0x22: per-room attributes (suction / water / pass count)."""
        FAN = {"gentle": 0, "normal": 1, "strong": 2, "max": 3}
        WATER = {"closed": 0, "low": 1, "middle": 2, "high": 3}
        d = bytes([int(room_id),
                   FAN.get(fan, 2) if fan else 2,
                   WATER.get(water, 2) if water else 2,
                   int(passes or 1)])
        return self._send_frame(0x22, d)

    def query_rooms(self):
        """cmd 0x15 query — robot echoes its room-clean config on DP 15."""
        return self._send_frame(0x15)

    def goto(self, x, y):
        """DP 15 command_trans, cmd 0x16 — navigate to a map coordinate.
        Frame: AA 00 05 16 <x:int16be> <y:int16be> <chk>. See docs/COMMAND_PROTOCOL.md"""
        body = bytes([0x16]) + int(x).to_bytes(2, "big", signed=True) \
                             + int(y).to_bytes(2, "big", signed=True)
        frame = bytes([0xAA, 0x00, len(body)]) + body + bytes([sum(body) & 0xFF])
        dp = _schema_dp("command_trans")
        if dp:
            self._write(dp, frame.hex())
            m = _schema_dp("mode")
            if m: self._write(m, "pose")
            p = _schema_dp("power")
            if p: self._write(p, True)
        return frame.hex()

    def _command(self, action):
        raise NotImplementedError

    def _write(self, dp, value):
        raise NotImplementedError

    def refresh(self):
        raise NotImplementedError


class TuyaBackend(BaseBackend):
    source = "robot"

    def __init__(self, cfg):
        super().__init__()
        import sys
        sys.path.insert(0, os.path.join(ROOT, "pylib"))
        import tinytuya
        self._tt = tinytuya
        self.cfg = cfg
        self.dev = tinytuya.Device(
            cfg["device_id"], cfg.get("ip", "192.168.3.241"), cfg["local_key"],
            version=float(cfg.get("version", 3.3)),
        )
        self.dev.set_socketPersistent(True)
        self.dev.set_socketTimeout(6)

    def refresh(self):
        data = self.dev.status()
        if isinstance(data, dict) and "dps" in data:
            with self._lock:
                self._raw = {str(k): v for k, v in data["dps"].items()}
                self._last_update = time.time()
                self.connected = True
        elif isinstance(data, dict) and data.get("Error"):
            self.connected = False
        return self.raw()

    def _command(self, action):
        # Map semantic action -> DP writes. Values come from dp_schema.json.
        if action == "start":
            dp = _schema_dp("mode");  self._write(dp, "smart") if dp else None
            p = _schema_dp("power");  self._write(p, True) if p else None
        elif action == "pause":
            dp = _schema_dp("pause"); self._write(dp, True) if dp else None
        elif action == "stop":
            p = _schema_dp("power");  self._write(p, False) if p else None
        elif action == "home":
            # The robot IGNORES switch_charge while switch_go is true, so a dock
            # request mid-clean silently does nothing. Stop first, then dock.
            p = _schema_dp("power")
            if p:
                try: self._write(p, False)
                except Exception: pass
                time.sleep(2.0)
            dp = _schema_dp("return_home")
            if dp:
                self._write(dp, True)
        elif action == "locate":
            dp = _schema_dp("locate"); self._write(dp, True) if dp else None

    def _write(self, dp, value):
        if dp is None:
            return
        self.dev.set_value(dp, value, nowait=True)


class SimBackend(BaseBackend):
    """Believable robot so the UI/HA work before we have the key.
    Uses the same dp_schema.json so semantics match the real device."""
    source = "sim"

    def __init__(self):
        super().__init__()
        self.connected = True
        self._battery = 82
        self._status = "standby"
        self._fan = "normal"
        self._water = "middle"
        self._mode = "standby"
        self._area = 0
        self._time = 0
        self._t = threading.Thread(target=self._tick, daemon=True)
        self._t.start()

    def _sync_raw(self):
        def put(name, val):
            dp = _schema_dp(name)
            if dp is not None and val is not None:
                self._raw[str(dp)] = val
        with self._lock:
            put("status", self._status)
            put("battery", self._battery)
            put("fan", self._fan)
            put("water", self._water)
            put("mode", self._mode)
            put("clean_area", self._area)
            put("clean_time", self._time)
            put("fault", 0)
            self._last_update = time.time()

    def _tick(self):
        while True:
            if self._status in ("smart_clean", "cleaning"):
                self._battery = max(0, self._battery - 1)
                self._area += 1
                self._time += 1
                if self._battery <= 15:
                    self._status = "goto_charge"
            elif self._status == "goto_charge":
                # simulate travel then docking
                self._status = "charging"
            elif self._status == "charging":
                self._battery = min(100, self._battery + 2)
                if self._battery >= 100:
                    self._status = "charge_done"
            self._sync_raw()
            time.sleep(1.0)

    def refresh(self):
        self._sync_raw()
        return self.raw()

    def _command(self, action):
        if action == "start":
            self._status = "smart_clean"; self._mode = "smart"; self._area = 0; self._time = 0
        elif action == "pause":
            self._status = "paused"
        elif action == "stop":
            self._status = "standby"; self._mode = "standby"
        elif action == "home":
            self._status = "goto_charge"; self._mode = "chargego"
        elif action == "locate":
            pass
        self._sync_raw()

    def _write(self, dp, value):
        with self._lock:
            self._raw[str(dp)] = value
        if dp == _schema_dp("fan"):   self._fan = value
        if dp == _schema_dp("water"): self._water = value


def make_controller():
    """Pick backend: real robot if config has a local_key, else simulator."""
    cfg = _load_json(os.path.join(ROOT, "robot_secrets.json")) or \
          _load_json(os.path.join(ROOT, "config.json")) or {}
    if cfg.get("local_key"):
        try:
            b = TuyaBackend(cfg)
            b.refresh()
            return b
        except Exception as e:
            print(f"[controller] real backend failed ({e}); using simulator")
    return SimBackend()


if __name__ == "__main__":
    c = make_controller()
    print("backend:", c.source)
    import json as _j
    print(_j.dumps(c.state(), indent=2))
