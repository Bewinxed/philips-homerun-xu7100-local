#!/usr/bin/env python3
"""Watch EVERY datapoint and report changes as they happen.

Use this to discover undocumented commands: run it, then press a button in the
vendor app (e.g. "start mapping"), and whatever DP flips is the command.

    ./homerun sniff [seconds]
"""
import os, sys, json, time, base64
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pylib"))
import tinytuya

KNOWN = {
    "1": "power_go", "2": "pause", "3": "switch_charge", "4": "mode", "5": "status",
    "6": "clean_time", "7": "clean_area", "8": "battery", "9": "suction", "10": "cistern",
    "17": "edge_brush_life", "19": "roll_brush_life", "21": "filter_life",
    "23": "duster_cloth_life", "26": "volume", "28": "fault", "29": "total_clean_area",
    "30": "total_clean_count", "31": "total_clean_time", "34": "device_info",
    "15": "path_data", "16": "request",
}


def pretty(dp, v):
    if dp == "34" and isinstance(v, str):
        try:
            return json.loads(base64.b64decode(v).decode())
        except Exception:
            return v
    if isinstance(v, str) and len(v) > 40:
        return v[:40] + f"…({len(v)}b64)"
    return v


def main(secs=300):
    s = json.load(open(os.path.join(ROOT, "robot_secrets.json")))
    d = tinytuya.Device(s["device_id"], s["ip"], s["local_key"], version=3.3)
    d.set_socketPersistent(True); d.set_socketTimeout(8)

    base = (d.status() or {}).get("dps", {})
    print(f"baseline: {len(base)} datapoints. watching {secs}s — "
          f"press buttons in the app now.\n")
    last = dict(base)
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            d.heartbeat()
            msg = d.receive()
        except Exception:
            time.sleep(1); continue
        dps = (msg or {}).get("dps") if isinstance(msg, dict) else None
        if not dps:
            # periodic full poll to catch anything push missed
            try:
                dps = (d.status() or {}).get("dps", {})
            except Exception:
                continue
        for k, v in (dps or {}).items():
            if last.get(k) != v:
                name = KNOWN.get(k, "*** UNKNOWN ***")
                print(f"{time.strftime('%H:%M:%S')}  DP {k:>4} {name:<20} "
                      f"{pretty(k, last.get(k))!r}  ->  {pretty(k, v)!r}", flush=True)
                last[k] = v
    print("\nsniff finished")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
