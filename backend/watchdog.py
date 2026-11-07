"""Stuck watchdog: free the robot, learn where it gets stuck, ask for help.

1. Detect: while a job runs, the robot reports status 'fault' (or a fault bit).
2. Free it: reverse a little, turn (alternating left/right), then resume the
   interrupted job. Up to `attempts` tries, each checked for ~25 s.
3. Still stuck: notify the people who are home (notifier.py).
4. Learn: the robot has no live position on the LAN or in the cloud, so each
   incident is placed on the map after the run, from the cleaning record's
   route: exactly (the run's last point) when the run ended stuck, estimated
   (by elapsed cleaning time) when it was freed mid-run.
5. Patterns: incidents on one floor within ~0.75 m of each other count up; at
   `threshold` a no-go zone of `zone_m` around them is suggested, or with
   mode 'apply' written to the robot once it is docked on that floor.

State lives in maps/stuck.json (part of the app's backups).
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = os.path.join(ROOT, "maps", "stuck.json")

DEFAULTS = {
    "enabled": True,
    "attempts": 2,          # freeing tries before notifying
    "mode": "suggest",      # off | suggest | apply  (what to do with a pattern)
    "threshold": 3,         # incidents (exact ones count 1.5) that make a pattern
    "radius_m": 0.75,       # incidents this close belong together
    "zone_m": 0.8,          # side of a learned no-go zone
    "route_delay_s": 180,   # wait for the cleaning record to reach the cloud
    "check_s": 25,          # how long a freeing try waits for the robot to move on
}
ACTIVE = ("cleaning", "returning", "paused")


def _load():
    try:
        with open(STORE) as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("incidents", [])
    d.setdefault("suggestions", [])
    return d


def _save(d):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, STORE)


def clusters(incidents, radius_px_exact, radius_px_approx):
    """Greedy clustering of located incidents per floor -> [(floor, cx, cy, weight, ids)]."""
    out = []
    by_floor = {}
    for inc in incidents:
        if inc.get("px") and inc.get("floor"):
            by_floor.setdefault(inc["floor"], []).append(inc)
    for floor, items in by_floor.items():
        groups = []
        for inc in items:
            x, y = inc["px"]
            r = radius_px_exact if inc.get("exact") else radius_px_approx
            for g in groups:
                if math.hypot(g["cx"] - x, g["cy"] - y) <= r:
                    g["items"].append(inc)
                    n = len(g["items"])
                    g["cx"] += (x - g["cx"]) / n
                    g["cy"] += (y - g["cy"]) / n
                    break
            else:
                groups.append({"cx": x, "cy": y, "items": [inc]})
        for g in groups:
            w = sum(1.5 if i.get("exact") else 1.0 for i in g["items"])
            out.append((floor, round(g["cx"], 1), round(g["cy"], 1), w, [i["id"] for i in g["items"]]))
    return out


class Watchdog(threading.Thread):
    def __init__(self, controller, notifier, cfg=None, robot_name="The robot"):
        super().__init__(daemon=True, name="stuck-watchdog")
        self.c = controller
        self.n = notifier
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.name_ = robot_name
        self._lock = threading.Lock()
        self.data = _load()
        self.status = "idle"        # idle | watching | freeing | stuck
        self._run = None            # {"start", "floor", "clean_time", "incidents": [...]}
        self._prev = None
        self._cooldown = 0.0

    # ---- public ---------------------------------------------------------
    def snapshot(self, floor=None) -> dict:
        with self._lock:
            inc = [i for i in self.data["incidents"] if floor is None or i.get("floor") == floor]
            sug = [s for s in self.data["suggestions"] if floor is None or s.get("floor") == floor]
            return {"status": self.status, "mode": self.cfg["mode"], "enabled": self.cfg["enabled"],
                    "incidents": inc[-200:], "suggestions": sug}

    def decide(self, sid, action) -> dict:
        """User action on a suggestion: 'apply' (write to the robot) or 'dismiss'."""
        with self._lock:
            s = next((s for s in self.data["suggestions"] if s["id"] == sid), None)
        if not s:
            raise ValueError("unknown suggestion")
        if action == "dismiss":
            s["status"] = "dismissed"
        elif action == "apply":
            ok, why = self._apply(s)
            if not ok:
                raise RuntimeError(why)
        else:
            raise ValueError("action must be apply or dismiss")
        with self._lock:
            _save(self.data)
        return s

    # ---- loop -----------------------------------------------------------
    def run(self):
        while True:
            try:
                if self.cfg["enabled"]:
                    self._tick()
            except Exception as e:
                print(f"[watchdog] {type(e).__name__}: {e}", flush=True)
            time.sleep(2.0)

    def _stuck(self, st) -> bool:
        raw_status = str(st["raw"].get(str(self._dp("status")), "")).lower()
        fault = st.get("fault")
        return raw_status == "fault" or (isinstance(fault, int) and fault != 0)

    def _dp(self, name):
        from controller import _schema_dp
        return _schema_dp(name)

    def _tick(self):
        st = self.c.state()
        if not st.get("connected"):
            return
        state = st["state"]
        if self._run is None and state == "cleaning" and self._prev != "cleaning":
            self._run = {"start": time.time(), "floor": self._floor_id(), "clean_time": 0,
                         "incidents": [], "ended_stuck": False}
            self.status = "watching"
        if self._run is not None:
            if isinstance(st.get("clean_time"), int):
                self._run["clean_time"] = max(self._run["clean_time"], st["clean_time"])
            if self._stuck(st) and time.time() > self._cooldown:
                self._handle_stuck(st)
            elif state in ("docked", "charging", "idle") and not self._stuck(st):
                self._end_run()
        self._prev = state

    def _floor_id(self):
        try:
            from stored_map import active_floor
            fl = active_floor(self.c.live_overlays())
            return fl["id"] if fl else None
        except Exception:
            return None

    # ---- freeing --------------------------------------------------------
    def _handle_stuck(self, st):
        inc = {"id": uuid.uuid4().hex[:8], "ts": time.time(), "floor": self._run["floor"],
               "clean_time": st.get("clean_time") or self._run["clean_time"],
               "fault": st.get("fault"), "attempts": 0, "recovered": None, "px": None}
        self.status = "freeing"
        print(f"[watchdog] stuck (fault {inc['fault']}); trying to free it", flush=True)
        for k in range(int(self.cfg["attempts"])):
            inc["attempts"] = k + 1
            if self._free(k):
                inc["recovered"] = True
                break
            if self.c.state()["state"] in ("docked", "charging"):
                break   # someone sent it home
        else:
            inc["recovered"] = False
        self._run["incidents"].append(inc)
        with self._lock:
            self.data["incidents"].append(inc)
            _save(self.data)
        if inc["recovered"]:
            self.status = "watching"
            self._cooldown = time.time() + 30
        else:
            self.status = "stuck"
            self._run["ended_stuck"] = True
            self._cooldown = time.time() + 600   # don't keep wiggling a robot nobody freed
            who = self.n.send(f"{self.name_} is stuck",
                              f"{self.name_} got stuck and couldn't free itself after "
                              f"{inc['attempts']} tries. Please help it out.", tag="homerun_stuck")
            print(f"[watchdog] still stuck; notified {', '.join(who) or 'nobody (no phone found)'}", flush=True)

    def _free(self, k) -> bool:
        c = self.c
        try:
            c.drive("backward"); time.sleep(1.5); c.drive("stop"); time.sleep(0.5)
            c.drive("turn_left" if k % 2 == 0 else "turn_right"); time.sleep(1.2); c.drive("stop")
            time.sleep(0.5)
            c.resume()
        except Exception as e:
            print(f"[watchdog] freeing move failed: {e}", flush=True)
        end = time.time() + self.cfg["check_s"]
        while time.time() < end:
            time.sleep(min(2, self.cfg["check_s"] / 5))
            st = c.state()
            if not self._stuck(st) and st["state"] in ("cleaning", "returning"):
                return True
        return False

    # ---- after a run ----------------------------------------------------
    def _end_run(self):
        run, self._run = self._run, None
        self.status = "idle"
        if run["incidents"]:
            threading.Timer(self.cfg["route_delay_s"], self._locate, args=(run,)).start()

    def _locate(self, run):
        from stored_map import latest_route
        r = latest_route()
        if not r.get("points") or (r.get("at") or 0) < run["start"] - 60:
            print(f"[watchdog] no cleaning record for the run ({r.get('error', 'too old')})", flush=True)
            return
        pts = r["points"]
        total = max(run["clean_time"], 1)
        with self._lock:
            for inc in run["incidents"]:
                stored = next((i for i in self.data["incidents"] if i["id"] == inc["id"]), inc)
                if run["ended_stuck"] and inc is run["incidents"][-1] and not inc["recovered"]:
                    stored["px"], stored["exact"] = pts[-1], True
                else:
                    idx = min(len(pts) - 1, int(len(pts) * min(1.0, inc["clean_time"] / total)))
                    stored["px"], stored["exact"] = pts[idx], False
                stored["floor"] = stored.get("floor") or run["floor"] or self._floor_for_slot(r.get("map_id"))
            _save(self.data)
        self._patterns()

    def _patterns(self):
        res = self._resolution_cm()
        r_exact = self.cfg["radius_m"] * 100 / res
        r_approx = r_exact * 1.6
        with self._lock:
            new = []
            for floor, cx, cy, w, ids in clusters(self.data["incidents"], r_exact, r_approx):
                if w < self.cfg["threshold"] or any(set(ids) & set(s["incidents"]) for s in self.data["suggestions"]):
                    continue
                half = self.cfg["zone_m"] * 100 / res / 2
                s = {"id": uuid.uuid4().hex[:8], "floor": floor, "status": "suggested", "ts": time.time(),
                     "incidents": ids, "center": [cx, cy],
                     "px": [[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half], [cx - half, cy + half]]}
                self.data["suggestions"].append(s)
                new.append(s)
            _save(self.data)
        for s in new:
            if self.cfg["mode"] == "apply":
                ok, why = self._apply(s)
                self.n.send(f"{self.name_}: no-go zone added" if ok else f"{self.name_}: no-go zone suggested",
                            f"{self.name_} got stuck {len(s['incidents'])} times in the same spot. " +
                            ("A no-go zone was added there." if ok else f"Couldn't add a no-go zone yet ({why}); "
                             "open HomeRun to add it."), tag="homerun_zone")
            elif self.cfg["mode"] == "suggest":
                self.n.send(f"{self.name_}: suggested no-go zone",
                            f"{self.name_} got stuck {len(s['incidents'])} times in the same spot. "
                            "Open HomeRun to add a no-go zone there.", tag="homerun_zone")

    def _floor_for_slot(self, slot):
        """Floor id whose stored map has this header map_id (the robot's map slot)."""
        from stored_map import floors, floor_map_bytes, parse_header
        for fl in floors():
            b = floor_map_bytes(fl)
            if b and parse_header(b)["map_id"] == slot:
                return fl["id"]
        return None

    def _resolution_cm(self):
        return 5   # every HomeRun map seen so far; the header's value when a floor is known

    # ---- writing a zone -------------------------------------------------
    def _apply(self, s):
        """Add the suggestion's zone to the robot. Only on the floor the robot is
        on, and only while it is docked, so a running job isn't disturbed."""
        from stored_map import floors, floor_map_bytes, parse_header, px_to_cmd, active_floor
        st = self.c.state()
        if st["state"] not in ("docked", "charging"):
            return False, "the robot is not docked"
        live = self.c.live_overlays()
        here = active_floor(live)
        if not here or here["id"] != s["floor"]:
            return False, "the robot is on another floor"
        fl = next((f for f in floors() if f["id"] == s["floor"]), None)
        hdr = parse_header(floor_map_bytes(fl))
        zone = {"mode": 0, "cmd": [px_to_cmd(hdr, x, y) for x, y in s["px"]]}
        res = self.c.set_overlays(zones=list(live.get("zones") or []) + [zone])
        if not res.get("zones"):
            return False, "the robot did not confirm the zone"
        s["status"] = "applied"
        s["applied_ts"] = time.time()
        from stored_map import invalidate_floors
        invalidate_floors()   # the robot uploads the changed map; pick it up
        return True, ""
