#!/usr/bin/env python3
"""Capture everything the robot streams over the LAN while it's moving.

Goal: get live map + robot position with zero cloud. Dumps every raw datapoint
frame to maps/lan/stream_<ts>.jsonl plus per-DP .bin blobs for offline decoding.

    ./homerun stream [seconds]
"""
import os, sys, json, time, base64
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pylib"))
import tinytuya

OUT = os.path.join(ROOT, "maps", "lan")
os.makedirs(OUT, exist_ok=True)
RAW_DPS = {"14", "15", "32", "33", "35", "36", "38"}


def main(secs=60):
    s = json.load(open(os.path.join(ROOT, "robot_secrets.json")))
    d = tinytuya.Device(s["device_id"], s["ip"], s["local_key"], version=3.3)
    d.set_socketPersistent(True); d.set_socketTimeout(8)

    stamp = int(time.time())
    jl = open(os.path.join(OUT, f"stream_{stamp}.jsonl"), "w")
    seen = {}

    def note(dp, raw, src):
        seen.setdefault(dp, []).append(raw)
        rec = {"t": time.time(), "dp": dp, "len": len(raw),
               "hex": raw[:64].hex(), "src": src}
        jl.write(json.dumps(rec) + "\n"); jl.flush()
        print(f"{time.strftime('%H:%M:%S')} DP{dp:>3} {len(raw):>5}B  {raw[:28].hex()}",
              flush=True)

    for req in ("get_path", "get_map", "get_both"):
        try:
            r = d.set_value("16", req, nowait=False)
            for k, v in ((r or {}).get("dps") or {}).items():
                if isinstance(v, str) and len(v) > 6:
                    try: note(k, base64.b64decode(v), f"reply:{req}")
                    except Exception: pass
        except Exception as e:
            print(f"  request {req} failed: {e}", flush=True)
        time.sleep(1.5)

    print(f"\nlistening {secs}s…", flush=True)
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            d.heartbeat(); msg = d.receive()
        except Exception:
            time.sleep(0.5); continue
        dps = (msg or {}).get("dps") if isinstance(msg, dict) else None
        if not dps:
            continue
        for k, v in dps.items():
            if isinstance(v, str) and len(v) > 6:
                try: raw = base64.b64decode(v)
                except Exception: continue
                note(k, raw, "push")

    print("\n=== totals ===", flush=True)
    for k, frames in sorted(seen.items(), key=lambda x: -sum(len(f) for f in x[1])):
        blob = b"".join(frames)
        tot = len(blob)
        print(f"  DP{k}: {len(frames)} frames, {tot} bytes", flush=True)
        if k in RAW_DPS and tot:
            p = os.path.join(OUT, f"dp{k}_{stamp}.bin")
            open(p, "wb").write(blob)
            print(f"        -> {p}", flush=True)
    jl.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
