#!/usr/bin/env python3
"""Capture map/path data straight off the robot over the LAN — no Tuya cloud.

The robot answers a `request` DP (16) by pushing binary frames on path_data (15)
and command_trans (14). This listens for those frames, reassembles them, and dumps
them to maps/lan/ so we can decode them locally (same LZ4/Tuya layout format the
cloud serves). This is the path to being fully cloud-free.

    ./homerun lanmap [seconds]
"""
import os, sys, json, time, base64
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pylib"))
import tinytuya

OUT = os.path.join(ROOT, "maps", "lan")
os.makedirs(OUT, exist_ok=True)


def main(secs=60):
    s = json.load(open(os.path.join(ROOT, "robot_secrets.json")))
    d = tinytuya.Device(s["device_id"], s["ip"], s["local_key"],
                        version=float(s.get("version", 3.3)))
    d.set_socketPersistent(True)
    d.set_socketTimeout(6)

    frames = {}          # dp -> list of raw byte chunks
    def record(dps):
        for dp, val in (dps or {}).items():
            if not isinstance(val, str) or len(val) < 8:
                continue
            try:
                raw = base64.b64decode(val)
            except Exception:
                continue
            if not raw:
                continue
            frames.setdefault(dp, []).append(raw)
            print(f"  DP {dp}: +{len(raw)}B  head={raw[:12].hex()}")

    print("requesting map+path over LAN (DP 16 = get_both)...")
    try:
        r = d.set_value("16", "get_both", nowait=False)
        record((r or {}).get("dps"))
    except Exception as e:
        print("  request failed:", e)

    print(f"listening {secs}s for map frames...")
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            d.heartbeat()
            msg = d.receive()
        except Exception:
            time.sleep(0.5); continue
        if isinstance(msg, dict) and "dps" in msg:
            record(msg["dps"])

    if not frames:
        print("\nno map frames received — the robot has no map stored yet "
              "(run a clean first).")
        return 1

    stamp = str(int(time.time()))
    for dp, chunks in frames.items():
        blob = b"".join(chunks)
        p = os.path.join(OUT, f"dp{dp}_{stamp}.bin")
        with open(p, "wb") as f:
            f.write(blob)
        print(f"\nwrote {p}  ({len(blob)} bytes, {len(chunks)} frames)")
        print(f"  first bytes: {blob[:24].hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 60))
