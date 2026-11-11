"""Semantic control layer for Philips HomeRun robots (Tuya category 'sd').

Two interchangeable backends behind one interface:
  * TuyaBackend  - real robot over the LAN (tinytuya, no cloud needed for control)
  * SimBackend   - in-memory state machine, so the whole UI/HA stack is testable
                   before the local_key exists.

The semantic <-> DP mapping is per model: backend/models/<product_id>.json,
generated from the robot's cloud thing model by tools/learn_dps.py, with the
hand-verified XU7100 schema (dp_schema.json) as the fallback. See schema.py.
"""
from __future__ import annotations
import functools, json, os, threading, time, copy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def _load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default

from schema import load as _load_schema
SCHEMA, SCHEMA_SOURCE, MODEL = _load_schema()

# Canonical states we normalise every backend into (mirrors HA vacuum states)
IDLE, CLEANING, PAUSED, RETURNING, DOCKED, CHARGING, ERROR = \
    "idle", "cleaning", "paused", "returning", "docked", "charging", "error"



def _with_job_lock(fn):
    """Run a command that starts a job under the backend's job_lock."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self.job_lock:
            return fn(self, *args, **kwargs)
    return wrapper


def _same_schedules(a, b):
    """Same schedules, ignoring the derived 'enabled' flag."""
    def norm(lst):
        return [{k: v for k, v in s.items() if k != "enabled"} for s in lst]
    return norm(a) == norm(b)


def _schema_dp(name):
    e = SCHEMA.get(name)
    return e.get("dp") if isinstance(e, dict) else None


def _schema_values(name):
    e = SCHEMA.get(name)
    return list(e.get("values") or []) if isinstance(e, dict) else []


class BaseBackend:
    """Common shape. Subclasses implement _read_raw() and _write(dp, value)."""
    source = "base"

    def __init__(self):
        self._lock = threading.Lock()
        self._raw = {}
        self._last_update = 0.0
        self.connected = False
        # last zones / walls the robot reported on DP 15 (frames.overlays shape)
        self._overlays = {"zones": None, "walls": None, "ts": 0.0}
        self._raw_b64 = None    # True when the robot reports raw DPs as base64
        # cleaning schedules from DP 32 (schedule.decode shape)
        self._schedules = {"max": 8, "schedules": None, "ts": 0.0}
        # Held around "is the robot idle? then write zones" and around commands
        # that start a job, so a job can't start between the check and the write;
        # also serialises zone writes from the UI and the watchdog.
        self.job_lock = threading.RLock()

    def _note_raw(self, raw):
        """Pick the zones/walls echoes out of DP 15 and the schedules out of DP 32."""
        import frames
        self._note_schedules(raw.get(str(_schema_dp("device_timer"))))
        dp = _schema_dp("command_trans")
        val = raw.get(str(dp)) if dp else None
        buf, kind = frames.decode_raw_kind(val)
        if buf is None:
            return
        # answer in the encoding the robot reports in (the XU7100 uses hex)
        self._raw_b64 = kind == "b64"
        ov = frames.overlays(buf)
        with self._lock:
            for k in ("zones", "walls"):
                if ov[k] is not None:
                    self._overlays[k] = ov[k]
                    self._overlays["ts"] = time.time()

    def _note_schedules(self, val, ts=None):
        import base64
        import schedule
        if not isinstance(val, str) or not val:
            return False
        try:
            fr = schedule.parse_frame(base64.b64decode(val))
        except Exception:
            return False
        if not fr or fr[0] not in (schedule.REPORT, schedule.SET):
            return False
        d = schedule.decode(fr[1])
        with self._lock:
            self._schedules = {**d, "ts": ts or time.time()}
        return True

    def schedules(self, max_age=600) -> dict:
        """The robot's cleaning schedules; from its last cloud report when ours
        are older than max_age (it reports DP 32 rarely, e.g. after app edits)."""
        with self._lock:
            cur = dict(self._schedules)
        if time.time() - cur["ts"] >= max_age:
            p = self._cloud_dp("device_timer", 0)
            if not (p and self._note_schedules(p["value"], time.time())):
                with self._lock:
                    self._schedules["ts"] = time.time()   # retry in max_age
            with self._lock:
                cur = dict(self._schedules)
        return cur

    def set_schedules(self, schedules, timeout=12.0) -> bool:
        """Replace the robot's schedules and wait until it reports them back."""
        import base64
        import schedule
        dp = _schema_dp("device_timer")
        if not dp:
            raise ValueError("this model has no schedules")
        data = schedule.encode(schedules, self._schedules.get("max") or 8)
        want = schedule.decode(data)["schedules"]
        before = self._schedules["ts"]
        sent = time.time()
        self._write(dp, base64.b64encode(schedule.build(schedule.SET, data)).decode())
        end = sent + timeout
        while time.time() < end:
            time.sleep(0.5)
            with self._lock:
                cur = dict(self._schedules)
            if cur["ts"] <= before and time.time() - sent > 3:
                time.sleep(1.5)
                p = self._cloud_dp("device_timer", sent)
                if p:
                    self._note_schedules(p["value"], p["time"])
                with self._lock:
                    cur = dict(self._schedules)
            if cur["ts"] > before:
                return _same_schedules(cur["schedules"] or [], want)
        return False

    def _cloud_dp(self, code, since, timeout=20):
        """{'value', 'time'} of a DP's last cloud report, if newer than `since`."""
        if timeout <= 0:
            return None
        try:
            from tuya_cloud import TuyaCloud, load_cfg
            cfg = load_cfg()
            r = TuyaCloud(cfg).get(f"/v2.0/cloud/thing/{cfg['device_id']}/shadow/properties?codes={code}",
                                   timeout=timeout)
            p = (r.get("result") or {}).get("properties", [{}])[0]
        except Exception:
            return None
        if not p.get("time") or p["time"] / 1000 < since - 1:
            return None
        return {"value": p.get("value"), "time": p["time"] / 1000}

    def live_overlays(self) -> dict:
        with self._lock:
            return dict(self._overlays)

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

    # Consumable life counters: value = minutes remaining. The full life comes
    # from the model's DP spec ("max"); these defaults are the XU7100's.
    CONSUMABLES = {
        "edge_brush_life": ("Side brush", 9000),
        "roll_brush_life": ("Main brush", 18000),
        "filter_life": ("Filter", 9000),
        "rag_life": ("Mop cloth", 9000),
    }
    # Toggles worth surfacing in the UI (semantic name -> label)
    TOGGLES = {
        "auto_boost": "Carpet boost", "do_not_disturb": "Do not disturb",
        "child_lock": "Child lock", "y_mop": "Y-pattern mop",
        "vibration": "Vibration mop", "customize_mode": "Custom mode",
        "dust_collect": "Auto-empty dock",
    }
    # Fault bitmap — AUTHORITATIVE labels, pulled from the XU7100's own Tuya
    # DP specification (status 'fault', type Bitmap). Do not guess these. A
    # model schema with its own bitmap labels overrides this list.
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

    def capabilities(self) -> dict:
        """What this model supports, so the UI and HA only offer real controls."""
        return {
            "model": MODEL,
            # the robot's own name from the cloud (robot_secrets.json), if known
            "name": (getattr(self, "cfg", None) or {}).get("name") or None,
            "schema": SCHEMA_SOURCE,
            "fan_levels": _schema_values("fan"),
            "water_levels": _schema_values("water"),
            "modes": _schema_values("mode"),
            "features": sorted(n for n, e in SCHEMA.items()
                               if isinstance(e, dict) and e.get("dp")),
        }

    def diagnostics(self) -> dict:
        """Everything the robot actually exposes about its own health."""
        raw = self.raw()
        d = {"consumables": [], "faults": [], "totals": {}, "device": {}, "components": {},
             "capabilities": self.capabilities()}

        for sem, (name, full) in self.CONSUMABLES.items():
            dp = _schema_dp(sem)
            if not dp:
                continue
            full = SCHEMA[sem].get("max") or full
            v = raw.get(dp)
            if isinstance(v, (int, float)):
                d["consumables"].append({
                    "name": name, "remaining_min": int(v), "full_min": full,
                    "percent": round(100.0 * v / full, 1) if full else None,
                    "hours_left": round(v / 60.0, 1),
                })

        f = self._get(raw, "fault")
        if isinstance(f, int):
            d["fault_code"] = f
            fs = SCHEMA.get("fault") or {}
            if fs.get("labels"):
                bits = fs["labels"]
            elif SCHEMA_SOURCE == "dp_schema.json":
                bits = self.FAULT_BITS
            else:   # model publishes no names: don't guess with the XU7100's
                bits = [f"fault_bit_{i}" for i in range(max(fs.get("maxlen") or 0, f.bit_length()))]
            names = [n for i, n in enumerate(bits) if f & (1 << i)]
            d["faults"] = names
            d["fault_detail"] = [
                {"name": n, "hint": self.FAULT_HINTS.get(n, "")} for n in names
            ]

        for sem, key, unit in (("total_area", "total_area", "m2"),
                               ("total_count", "total_cleans", "runs"),
                               ("total_time", "total_time", "min")):
            dp = _schema_dp(sem)
            if dp and dp in raw:
                d["totals"][key] = {"value": raw[dp], "unit": unit}

        # device_info blob (wifi/rssi/ip/mac/firmware) arrives as base64 JSON
        info = self._get(raw, "device_info")
        if isinstance(info, str):
            try:
                import base64 as _b64
                d["device"] = json.loads(_b64.b64decode(info).decode())
            except Exception:
                pass

        for sem, label in (("mop_state", "mop"), ("work_mode", "work mode"),
                           ("no_mop_zones", "clean type"), ("fan", "suction"),
                           ("water", "water"), ("remote_mode", "remote mode")):
            dp = _schema_dp(sem)
            if dp and dp in raw:
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
            # the XU2000 reports "amicro_collect_dust" while the base empties its bin
            if "collect_dust" in s or "dust_collect" in s:
                return DOCKED
            if "charg" in s:
                return CHARGING
            # firmware reports states Tuya's spec doesn't document (e.g. "positioning";
            # the XU2000 spells it "repositing"). It relocalises on the way home
            # too, so follow the mode it was given.
            if ("position" in s or "reposit" in s or "locat" in s or "relocat" in s
                    or "goto_pos" in s):
                return RETURNING if self._get(raw, "mode") == "chargego" else CLEANING
            if "paus" in s:
                return PAUSED
            if ("clean" in s or "smart" in s or "zone" in s or "part" in s or "spot" in s
                    or "room" in s or "wall_follow" in s or "map" in s
                    or "direction" in s):
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
    @_with_job_lock
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
    def empty_bin(self):
        """dust_collection_switch — tell the auto-empty base to empty the bin."""
        dp = _schema_dp("dust_collect")
        if not dp:
            raise ValueError("this model has no auto-empty dock")
        self._write(dp, True)

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

    def _raw_value(self, frame: bytes) -> str:
        # The XU2000 reports DP 15 as base64 and only acts on base64 (hex is
        # ignored, verified). The original XU7100 code sent hex, so the
        # hand-made XU7100 schema keeps hex until the robot reports a frame.
        import base64
        b64 = self._raw_b64 if self._raw_b64 is not None else SCHEMA_SOURCE != "dp_schema.json"
        return base64.b64encode(frame).decode() if b64 else frame.hex()

    def _send_frame(self, cmd, data=b""):
        f = self._frame(cmd, data)
        dp = _schema_dp("command_trans")
        if dp:
            self._write(dp, self._raw_value(f))
        return f.hex()

    def query_overlays(self):
        """Ask the robot to report its no-go zones and virtual walls (read-only)."""
        import frames
        self._send_frame(frames.ZONES_GET)
        self._send_frame(frames.WALLS_GET)

    def set_overlays(self, zones=None, walls=None, timeout=12.0) -> dict:
        """Write no-go zones and/or virtual walls (command coordinates) and wait
        for the robot to echo them back. Returns {'zones': ok, 'walls': ok}."""
        want = {"zones": zones, "walls": walls}
        prev = self.live_overlays()
        ok = self._write_overlays(want, timeout)
        # All or nothing: when only part of the change was confirmed, put the
        # confirmed part back the way it was, so the robot isn't left half-edited.
        if not all(ok.values()) and any(ok.values()):
            undo = {k: (prev.get(k) if ok.get(k) else None) for k in ("zones", "walls")}
            if all(undo[k] is not None for k in undo if ok.get(k)):
                self._write_overlays(undo, timeout)
        return ok

    def _write_overlays(self, want, timeout) -> dict:
        import frames
        from stored_map import same_overlays
        before = self.live_overlays()["ts"]
        if want.get("zones") is not None:
            self._send_frame(frames.ZONES_SET, frames.encode_zones(want["zones"]))
        if want.get("walls") is not None:
            self._send_frame(frames.WALLS_SET, frames.encode_walls(want["walls"]))
        result = {k: None for k, v in want.items() if v is not None}
        sent = time.time()
        end = sent + timeout
        while time.time() < end and None in result.values():
            time.sleep(0.5)
            live = self.live_overlays()
            if live["ts"] <= before:
                # The robot answers with a DP 15 report that the LAN status poll
                # doesn't always pass on; the cloud has it within a second or two.
                # The lookup is bounded by what is left of the timeout.
                if time.time() - sent > 3:
                    time.sleep(min(1.5, max(0.0, end - time.time())))
                    live = self._cloud_overlays(sent, timeout=end - time.time()) or live
                if live["ts"] <= before:
                    continue
            for k in result:
                if live.get(k) is not None:
                    result[k] = same_overlays({k: live[k]}, {k: want[k]})
        ok = {k: bool(v) for k, v in result.items()}
        with self._lock:
            for k, good in ok.items():
                if good:
                    self._overlays[k] = want[k]
                    self._overlays["ts"] = time.time()
        return ok

    def refresh_overlays(self, max_age=600):
        """Take the robot's zones/walls from its last cloud report when ours are
        older than max_age (edits made in the Smart Life app, missed LAN reports)."""
        if time.time() - self.live_overlays()["ts"] < max_age:
            return
        if time.time() < getattr(self, "_overlays_retry", 0):
            return   # the last cloud lookup failed moments ago
        ov = self._cloud_overlays(0)
        with self._lock:
            if not ov:
                self._overlays_retry = time.time() + 60   # retry soon, not in max_age
                return
            # a LAN report that arrived during the lookup is newer: keep it
            if ov["ts"] >= self._overlays["ts"] or self._overlays["zones"] is None:
                for k in ("zones", "walls"):
                    if ov[k] is not None:
                        self._overlays[k] = ov[k]
            self._overlays["ts"] = max(self._overlays["ts"], time.time() - 1)

    def _cloud_overlays(self, since, timeout=20):
        """The robot's last DP 15 report from the cloud, if it is newer than `since`."""
        import frames
        p = self._cloud_dp("command_trans", since, timeout=timeout)
        buf = frames.decode_raw(p.get("value")) if p else None
        if buf is None:
            return None
        return {**frames.overlays(buf), "ts": p["time"]}

    @_with_job_lock
    def resume(self):
        """Carry on with the interrupted job (unlike start(), which begins a new one)."""
        p = _schema_dp("pause")
        if p: self._write(p, False)
        g = _schema_dp("power")
        if g: self._write(g, True)

    @_with_job_lock
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

    @_with_job_lock
    def goto(self, x, y):
        """DP 15 command_trans, cmd 0x16 — navigate to a map coordinate.
        Frame: AA 00 05 16 <x:int16be> <y:int16be> <chk>. See docs/COMMAND_PROTOCOL.md"""
        body = bytes([0x16]) + int(x).to_bytes(2, "big", signed=True) \
                             + int(y).to_bytes(2, "big", signed=True)
        frame = bytes([0xAA, 0x00, len(body)]) + body + bytes([sum(body) & 0xFF])
        dp = _schema_dp("command_trans")
        if dp:
            self._write(dp, self._raw_value(frame))
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
        # status() returns the NEXT message on the persistent socket. The robot
        # also pushes changes by itself (and answers every write), so reading
        # one message per poll falls further and further behind: the app showed
        # "charging, 73%" while the robot was at 83% and off the dock. Drain
        # everything queued after the query and apply it in arrival order.
        msgs = [self.dev.status()]
        self.dev.set_socketTimeout(0.4)
        try:
            for _ in range(100):
                m = self.dev.receive()
                if not m or not isinstance(m, dict) or "Err" in m:
                    break
                msgs.append(m)
        except Exception:
            pass
        finally:
            self.dev.set_socketTimeout(6)
        got = False
        for data in msgs:
            if isinstance(data, dict) and isinstance(data.get("dps"), dict):
                dps = {str(k): v for k, v in data["dps"].items()}
                # merge: pushes carry only the DPs that changed
                with self._lock:
                    self._raw.update(dps)
                self._note_raw(dps)
                got = True
        if got:
            with self._lock:
                self._last_update = time.time()
                self.connected = True
        elif isinstance(msgs[0], dict) and msgs[0].get("Error"):
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
        except Exception as e:
            print(f"[controller] real backend failed ({e}); using simulator")
            return SimBackend()
        # An asleep or briefly unreachable robot must not swap in the simulator
        # for good: keep the real backend, the poll loop retries.
        try:
            b.refresh()
        except Exception as e:
            print(f"[controller] robot not reachable yet ({e}); retrying in the poll loop")
        return b
    return SimBackend()


if __name__ == "__main__":
    c = make_controller()
    print("backend:", c.source)
    import json as _j
    print(_j.dumps(c.state(), indent=2))
