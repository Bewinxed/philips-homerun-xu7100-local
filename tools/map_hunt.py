#!/usr/bin/env python3
"""Decisive test: while the robot is moving, capture the CORRECT datapoints
(DP 14 path_data, DP 32/33/35 0xab multi-map frames) over the LAN *and* poll the
cloud realtime-map endpoint at the same time.

Answers two questions in one run:
  1. Does DP 14 carry map/path data locally?  (earlier captures watched DP 15
     by mistake, so this was never actually tested)
  2. Is the cloud realtime-map endpoint session-gated, i.e. does it only return
     data while a run is in progress?

    ./homerun maphunt [seconds]           # assumes robot already running
    ./homerun maphunt [seconds] --start   # start a run first, dock at the end
"""
import os, sys, json, time, base64, threading
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pylib"))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import tinytuya
from tuya_cloud import TuyaCloud, load_cfg

OUT = os.path.join(ROOT, "maps", "hunt")
os.makedirs(OUT, exist_ok=True)
WATCH = {"14": "path_data", "15": "command_trans", "32": "dp32",
         "33": "dp33", "35": "dp35", "36": "dp36", "38": "dp38"}

cloud_hits = []


def poll_cloud(did, stop):
    c = TuyaCloud(); c.ping()
    while not stop.is_set():
        try:
            r = c.get(f"/v1.0/users/sweepers/file/{did}/realtime-map")
            res = r.get("result") or []
            print(f"  [cloud] realtime-map parts={len(res)}"
                  + (f"  {json.dumps(res)[:200]}" if res else ""), flush=True)
            if res:
                cloud_hits.append(res)
        except Exception as e:
            print(f"  [cloud] err {e}", flush=True)
        stop.wait(10)


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 180
    do_start = "--start" in sys.argv
    cfg = load_cfg(); did = cfg["device_id"]
    s = json.load(open(os.path.join(ROOT, "robot_secrets.json")))
    d = tinytuya.Device(s["device_id"], s["ip"], s["local_key"], version=3.3)
    d.set_socketPersistent(True); d.set_socketTimeout(10)

    stop = threading.Event()
    threading.Thread(target=poll_cloud, args=(did, stop), daemon=True).start()

    if do_start:
        print("-> starting a run (switch_go=True)", flush=True)
        try: d.set_value("1", True, nowait=False)
        except Exception as e: print("   start failed:", e, flush=True)
        time.sleep(8)

    frames = {}
    stamp = int(time.time())
    print(f"\ncapturing {secs}s — watching DP {', '.join(WATCH)}\n", flush=True)
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            d.heartbeat(); msg = d.receive()
        except Exception:
            time.sleep(0.5); continue
        dps = (msg or {}).get("dps") if isinstance(msg, dict) else None
        if not dps:
            try: dps = (d.status() or {}).get("dps", {})
            except Exception: continue
        for k, v in (dps or {}).items():
            if k in WATCH and isinstance(v, str) and len(v) > 6:
                try: raw = base64.b64decode(v)
                except Exception: continue
                frames.setdefault(k, []).append(raw)
                print(f"  [lan] DP {k:>3} {WATCH[k]:<14} {len(raw):>6}B  {raw[:24].hex()}",
                      flush=True)

    stop.set()
    print("\n=== RESULT ===", flush=True)
    if frames:
        for k, fl in sorted(frames.items(), key=lambda x: -sum(len(f) for f in x[1])):
            blob = b"".join(fl); p = os.path.join(OUT, f"dp{k}_{stamp}.bin")
            open(p, "wb").write(blob)
            print(f"  DP {k} ({WATCH[k]}): {len(fl)} frames, {len(blob)} bytes -> {p}",
                  flush=True)
    else:
        print("  no raw LAN frames captured", flush=True)
    print(f"  cloud realtime-map non-empty responses: {len(cloud_hits)}", flush=True)
    if cloud_hits:
        json.dump(cloud_hits[-1], open(os.path.join(OUT, f"cloud_{stamp}.json"), "w"), indent=2)
        print("  -> cloud map reference saved", flush=True)

    if do_start:
        print("\n-> sending it home (switch_charge=True)", flush=True)
        try: d.set_value("3", True, nowait=False)
        except Exception as e: print("   dock failed:", e, flush=True)


if __name__ == "__main__":
    main()
