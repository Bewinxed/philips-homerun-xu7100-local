#!/usr/bin/env python3
"""Show firmware state for the robot (and what Tuya will/won't let us do).

    ./homerun fw
"""
import os, sys, json, time, base64
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "pylib"))
from tuya_cloud import TuyaCloud, load_cfg

cfg = load_cfg(); did = cfg["device_id"]
c = TuyaCloud(cfg); c.ping()

print("=== firmware modules (Tuya cloud) ===")
r = c.get(f"/v2.0/cloud/thing/{did}/firmware")
for m in r.get("result", []):
    lu = m.get("last_upgrade_time") or 0
    when = time.strftime("%Y-%m-%d", time.localtime(lu)) if lu else "never"
    stat = {0: "up to date / idle"}.get(m.get("upgrade_status"), m.get("upgrade_status"))
    print(f"  {m.get('type_desc','?'):<14} v{m.get('current_version','?'):<10} "
          f"last upgrade: {when:<12} status: {stat}")

print("\n=== device ===")
d = c.get(f"/v1.0/devices/{did}").get("result", {})
for k in ("name", "model", "product_name", "product_id", "category", "online"):
    print(f"  {k:<13} {d.get(k)}")

print("\n=== live device_info (over LAN, no cloud) ===")
try:
    import tinytuya
    s = json.load(open(os.path.join(ROOT, "robot_secrets.json")))
    dev = tinytuya.Device(s["device_id"], s["ip"], s["local_key"], version=3.3)
    dev.set_socketPersistent(True); dev.set_socketTimeout(6)
    resp = dev.set_value("11", "stop", nowait=False)
    blob = (resp or {}).get("dps", {}).get("34")
    if blob:
        for k, v in json.loads(base64.b64decode(blob).decode()).items():
            print(f"  {k:<15} {v}")
except Exception as e:
    print("  (unavailable:", e, ")")

print("""
=== rollback reality check ===
Tuya OTA is one-way and signed: the cloud only ever advertises the *newest*
build for a firmware_key, and there is no public downgrade endpoint. The list of
historical builds lives in the OEM's (Versuni's) private console, not in ours.
So: we can SEE the version, we cannot pick or roll back to an older one.
""")
