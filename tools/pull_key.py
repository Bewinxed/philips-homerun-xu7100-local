#!/usr/bin/env python3
"""After the app account is linked in the Tuya project, this pulls the robot's
local_key + DP spec from the cloud and writes robot_secrets.json so LAN control
works. Run once (re-run if you ever re-pair, which rotates the key).

    .venv/bin/python tools/pull_key.py
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
from tuya_cloud import TuyaCloud, load_cfg

cfg = load_cfg()
did = cfg["device_id"]
c = TuyaCloud(cfg)

print("authenticating to Tuya cloud...")
try:
    c.ping()
except Exception as e:
    sys.exit(f"cloud auth failed: {e}")

detail = c.device_detail(did)
if not detail.get("success"):
    print(json.dumps(detail, indent=2))
    if detail.get("code") == 1106:
        sys.exit("\n>> Device not linked yet. In the Tuya project: Devices > Link App "
                 ">> Account > Add App Account, and scan the QR with the Smart Life app "
                 ">> that has the robot paired. Then re-run this.")
    sys.exit("could not read device detail")

res = detail["result"]
local_key = res.get("local_key")
if not local_key:
    sys.exit(f"device found but no local_key in response: {json.dumps(res)[:400]}")

secrets = {
    "device_id": did,
    "ip": cfg.get("ip", "192.168.3.241"),
    "version": cfg.get("version", 3.3),
    "local_key": local_key,
    "name": res.get("name", ""),
    "product_id": res.get("product_id", ""),
    "online": res.get("online"),
}
with open(os.path.join(ROOT, "robot_secrets.json"), "w") as f:
    json.dump(secrets, f, indent=2)
print(f"\n[OK] wrote robot_secrets.json — local_key = {local_key[:4]}… (len {len(local_key)})")
print(f"     device online: {res.get('online')}, name: {res.get('name','')}")

# Pull DP specification to refine the semantic schema
specs = c.device_specs(did)
if specs.get("success"):
    with open(os.path.join(ROOT, "backend", "device_specs.json"), "w") as f:
        json.dump(specs["result"], f, indent=2)
    funcs = specs["result"].get("functions", [])
    status = specs["result"].get("status", [])
    print(f"     pulled DP spec: {len(funcs)} functions, {len(status)} status points "
          f"-> backend/device_specs.json")
    print("     (run tools/learn_dps.py to map these to live values)")
else:
    print("     note: could not pull DP spec:", specs.get("msg"))

print("\nNext: .venv/bin/python tools/learn_dps.py   then start the server.")
