#!/usr/bin/env python3
"""Watch a cleaning run: log every status change, and grab the map as soon as
the cloud has one. Everything is archived so a run is never lost.

    ./homerun watch [minutes]
"""
import os, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "pylib"))
import tinytuya
from tuya_cloud import TuyaCloud, load_cfg

LOG = os.path.join(ROOT, "maps", "run_log.jsonl")
os.makedirs(os.path.dirname(LOG), exist_ok=True)

DP = {"5": "status", "8": "battery", "7": "area", "6": "time", "4": "mode", "28": "fault"}


def main(minutes=45):
    s = json.load(open(os.path.join(ROOT, "robot_secrets.json")))
    d = tinytuya.Device(s["device_id"], s["ip"], s["local_key"], version=3.3)
    d.set_socketPersistent(True); d.set_socketTimeout(8)
    cloud = TuyaCloud(); cloud.ping()
    did = s["device_id"]

    last = {}
    map_seen = False
    t0 = time.time()
    next_map_check = 0.0

    def emit(rec):
        rec["ts"] = time.time()
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(time.strftime("%H:%M:%S"), json.dumps(rec, ensure_ascii=False), flush=True)

    while time.time() - t0 < minutes * 60:
        try:
            st = (d.status() or {}).get("dps", {})
        except Exception as e:
            time.sleep(5); continue

        cur = {DP[k]: st.get(k) for k in DP if k in st}
        if cur and cur != last:
            emit({"event": "state", **cur})
            last = cur

        # once it's actually moving, poll the cloud for a map
        if time.time() > next_map_check:
            next_map_check = time.time() + 20
            try:
                r = cloud.get(f"/v1.0/users/sweepers/file/{did}/realtime-map")
                n = len(r.get("result", []) or [])
                if n and not map_seen:
                    emit({"event": "MAP_AVAILABLE", "parts": n})
                    map_seen = True
                if n:
                    from cloud_map import MapService
                    m = MapService().fetch()
                    m.pop("_png", None)
                    if m.get("ok"):
                        emit({"event": "map", "w": m.get("width"), "h": m.get("height"),
                              "rooms": len(m.get("rooms") or []),
                              "charger": m.get("charger"), "robot": m.get("robot"),
                              "path_points": m.get("path_points")})
            except Exception as e:
                pass

        # stop early if it finished and docked
        if last.get("status") in ("charge_done", "charging") and time.time() - t0 > 120:
            emit({"event": "DOCKED", "final": last})
            break
        time.sleep(6)

    print("watch finished")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 45)
