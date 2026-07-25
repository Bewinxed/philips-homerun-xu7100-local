#!/usr/bin/env python3
"""Local control backend for the Philips HomeRun XU7100 (Tuya v3.3).
Pure LAN — no cloud needed once we have the local_key.

Reads robot_secrets.json:
  {"device_id": "...", "ip": "192.168.3.241", "local_key": "...", "version": 3.3}

Usage:
  robot.py status          # dump all datapoints (DPs)
  robot.py raw             # pretty raw DP map
  robot.py set <dp> <val>  # set a datapoint (val auto-typed: true/false/int/str)
  robot.py monitor         # live-follow status changes
"""
import sys, os, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pylib"))
import tinytuya

SECRETS = os.path.join(os.path.dirname(HERE), "robot_secrets.json")

def load():
    if not os.path.exists(SECRETS):
        sys.exit(f"missing {SECRETS} — run the key-grab first")
    with open(SECRETS) as f:
        s = json.load(f)
    d = tinytuya.Device(
        s["device_id"], s.get("ip", "192.168.3.241"), s["local_key"],
        version=float(s.get("version", 3.3)),
    )
    d.set_socketPersistent(True)
    d.set_socketTimeout(6)
    return d, s

def coerce(v):
    if v.lower() in ("true", "on", "1"):  return True
    if v.lower() in ("false", "off", "0"): return False
    try:    return int(v)
    except: return v

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    d, s = load()

    if cmd in ("status", "raw"):
        data = d.status()
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif cmd == "set":
        dp, val = sys.argv[2], coerce(sys.argv[3])
        print(f"setting DP {dp} = {val!r}")
        print(json.dumps(d.set_value(dp, val, nowait=False), indent=2))
    elif cmd == "monitor":
        print("monitoring (Ctrl-C to stop)...")
        d.set_socketPersistent(True)
        last = None
        print(json.dumps(d.status(), indent=2))
        while True:
            d.heartbeat()
            data = d.receive()
            if data and data != last:
                print(time.strftime("%H:%M:%S"), json.dumps(data, ensure_ascii=False))
                last = data
    else:
        sys.exit(__doc__)

if __name__ == "__main__":
    main()
