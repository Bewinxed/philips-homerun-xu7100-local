#!/usr/bin/env python3
"""Learn the real DP schema of THIS robot. Two modes:

  spec   : derive semantic mapping from the cloud DP specification (device_specs.json)
  live   : connect over LAN, poll DPs, and (optionally) watch values change while
           you press buttons in the app, to confirm which DP is which.

    .venv/bin/python tools/learn_dps.py spec
    .venv/bin/python tools/learn_dps.py live
"""
import os, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "pylib"))

# Heuristics: map Tuya standard sweeper DP codes -> our semantic names
CODE_TO_SEMANTIC = {
    "switch": "power", "power": "power", "switch_go": "start_pause",
    "mode": "mode", "work_mode": "mode",
    "status": "status", "device_status": "status", "robot_status": "status",
    "direction_control": "direction",
    "suction": "fan", "fan": "fan", "suck": "fan", "windpower": "fan", "clean_speed": "fan",
    "cistern": "water", "water": "water", "water_set": "water", "tank": "water",
    "electricity_left": "battery", "battery_percentage": "battery", "residual_electricity": "battery",
    "clean_area": "clean_area", "clean_time": "clean_time",
    "seek": "locate", "find_robot": "locate",
    "fault": "fault", "alarm": "fault",
    "map_reset": "map_reset",
}
RETURN_CODES = {"switch_charge", "charge", "back_charge", "mode_return", "chargego"}


def learn_spec():
    p = os.path.join(ROOT, "backend", "device_specs.json")
    if not os.path.exists(p):
        sys.exit("no device_specs.json — run tools/pull_key.py first")
    spec = json.load(open(p))
    functions = spec.get("functions", [])
    status = spec.get("status", [])
    by_code = {}
    for item in functions + status:
        by_code[item["code"]] = item
    print(f"{len(functions)} functions, {len(status)} status points\n")

    mapping = {}
    for code, item in by_code.items():
        sem = CODE_TO_SEMANTIC.get(code)
        if code in RETURN_CODES:
            sem = "return_home"
        vals = ""
        try:
            v = json.loads(item.get("values", "{}"))
            if "range" in v: vals = "enum:" + ",".join(v["range"])
            elif "min" in v: vals = f"int:{v['min']}..{v['max']}"
            else: vals = item.get("type", "")
        except Exception:
            vals = item.get("type", "")
        flag = f"  -> {sem}" if sem else ""
        print(f"  DP {item.get('dp_id','?'):>4}  {code:<24} {item.get('type',''):<8} {vals}{flag}")
        if sem:
            mapping[sem] = {"dp": str(item.get("dp_id")), "code": code,
                            "type": item.get("type", "").lower()}
    out = os.path.join(ROOT, "backend", "dp_schema.learned.json")
    json.dump(mapping, open(out, "w"), indent=2)
    print(f"\n[OK] wrote {out}")
    print("Review it, then copy the good bits into backend/dp_schema.json")


def learn_live():
    secrets = os.path.join(ROOT, "robot_secrets.json")
    if not os.path.exists(secrets):
        sys.exit("no robot_secrets.json — run tools/pull_key.py first")
    import tinytuya
    s = json.load(open(secrets))
    d = tinytuya.Device(s["device_id"], s["ip"], s["local_key"], version=float(s.get("version", 3.3)))
    d.set_socketPersistent(True)
    print("polling current DPs...")
    data = d.status()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("\nNow watching for changes for 120s — press buttons in the Philips/SmartLife")
    print("app (start, dock, change suction) and note which DP id changes.\n")
    last = data.get("dps", {}) if isinstance(data, dict) else {}
    t0 = time.time()
    while time.time() - t0 < 120:
        d.heartbeat()
        upd = d.receive()
        if isinstance(upd, dict) and "dps" in upd:
            for k, v in upd["dps"].items():
                if last.get(k) != v:
                    print(f"  {time.strftime('%H:%M:%S')}  DP {k}: {last.get(k)!r} -> {v!r}")
                    last[k] = v


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "spec"
    (learn_live if mode == "live" else learn_spec)()
