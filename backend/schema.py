"""Per-model datapoint schema.

Every HomeRun / Tuya laser vacuum speaks the same protocol family, but the DP
numbers, enum ranges and optional features differ per model. Rather than hard-
coding the XU7100's numbers, the schema is resolved in this order:

  1. backend/models/<product_id>.json   generated from the device's own cloud
                                        thing model (tools/learn_dps.py model)
  2. backend/dp_schema.json             the hand-verified XU7100 schema

Each entry is keyed by a semantic name the rest of the code uses ("fan",
"battery", ...) and carries the DP id plus whatever the thing model told us:
enum `values`, int `min`/`max`/`unit`, bitmap `labels`.
"""
from __future__ import annotations
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODELS = os.path.join(HERE, "models")

# Tuya DP code -> semantic name. Covers the codes seen on the XU7100 plus the
# aliases Tuya's standard 'sd' (robot vacuum) category uses on other models.
CODE_TO_SEMANTIC = {
    "switch_go": "power", "power_go": "power",
    "pause": "pause",
    "switch_charge": "return_home",
    "mode": "mode",
    "status": "status",
    "clean_time": "clean_time",
    "clean_area": "clean_area",
    "battery_percentage": "battery", "electricity_left": "battery",
    "residual_electricity": "battery",
    "suction": "fan",
    "cistern": "water",
    "seek": "locate",
    "direction_control": "direction",
    "path_data": "path_data",
    "command_trans": "command_trans",
    "request": "request",
    "edge_brush_life": "edge_brush_life", "edge_brush": "edge_brush_life",
    "edge_brush_life_reset": "edge_brush_reset", "reset_edge_brush": "edge_brush_reset",
    "roll_brush_life": "roll_brush_life", "roll_brush": "roll_brush_life",
    "roll_brush_life_reset": "roll_brush_reset", "reset_roll_brush": "roll_brush_reset",
    "filter_life": "filter_life", "filter": "filter_life",
    "filter_reset": "filter_reset", "reset_filter": "filter_reset",
    "rag_life": "rag_life", "duster_cloth": "rag_life",
    "rag_life_reset": "rag_reset", "reset_duster_cloth": "rag_reset",
    "do_not_disturb": "do_not_disturb", "switch_disturb": "do_not_disturb",
    "volume_set": "volume",
    "break_clean": "break_clean",
    "fault": "fault",
    "clean_area_total": "total_area", "total_clean_area": "total_area",
    "clean_count_total": "total_count", "total_clean_count": "total_count",
    "clean_time_total": "total_time", "total_clean_time": "total_time",
    "device_timer": "device_timer",
    "disturb_time_set": "disturb_time",
    "device_info": "device_info",
    "voice_data": "voice_data",
    "language": "language",
    "dust_collection_num": "dust_collect_num",
    "dust_collection_switch": "dust_collect",
    "customize_mode_switch": "customize_mode", "custom_mode_switch": "customize_mode",
    "mop_state": "mop_state",
    "work_mode": "work_mode",
    "auto_boost": "auto_boost",
    "child_lock": "child_lock",
    "y_mop": "y_mop",
    "vibration_switch": "vibration",
    "clean_count": "clean_count",
    "remote_control_mode": "remote_mode",
    "create_map": "create_map",
    "sweep_count": "sweep_count", "clean_times": "sweep_count",
    "skip_room": "skip_room",
    "mop_seated": "mop_seated",
    "map_id": "map_id",
    "no_mopping_zones": "no_mop_zones",
    "remaining_charging_time": "charge_time_left",
    "map_num": "map_num",
}

_TYPE = {"bool": "bool", "enum": "enum", "value": "int", "bitmap": "bitmap",
         "raw": "raw", "string": "string"}


def from_thing_model(model: dict) -> dict:
    """Build a semantic schema from /v2.0/cloud/thing/{id}/model's result.

    Unknown codes are kept under their own code name, so nothing the robot
    reports is lost and it can be mapped later.
    """
    if isinstance(model.get("model"), str):
        model = json.loads(model["model"])
    out = {}
    for service in model.get("services", []):
        for prop in service.get("properties", []):
            code = prop.get("code")
            dp = prop.get("abilityId")
            if not code or dp is None:
                continue
            spec = prop.get("typeSpec") or {}
            entry = {"dp": str(dp), "code": code,
                     "type": _TYPE.get(spec.get("type"), spec.get("type")),
                     "access": prop.get("accessMode")}
            if "range" in spec:
                entry["values"] = spec["range"]
            for k in ("min", "max", "unit", "scale", "step"):
                if k in spec:
                    entry[k] = spec[k]
            # some models (XU2000) only publish bit numbers; don't pass those
            # off as names, the controller then labels them fault_bit_<n>
            if spec.get("label") and not all(str(l).isdigit() for l in spec["label"]):
                entry["labels"] = spec["label"]
            elif spec.get("type") == "bitmap":
                entry["maxlen"] = spec.get("maxlen") or len(spec.get("label") or [])
            name = CODE_TO_SEMANTIC.get(code, code)
            if name in out:     # two codes for one meaning: keep the first
                name = code
            out[name] = entry
    return out


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _product_id():
    for name in ("robot_secrets.json", "config.json"):
        cfg = _load_json(os.path.join(ROOT, name)) or {}
        pid = cfg.get("product_id") or cfg.get("product_key")
        if pid and not str(pid).startswith("your_"):
            return pid
    return None


def load() -> tuple[dict, str, str]:
    """Return (schema, source description, model name)."""
    pid = _product_id()
    if pid:
        path = os.path.join(MODELS, f"{pid}.json")
        data = _load_json(path)
        if data:
            model = data.get("_model") or pid
            data = {k: v for k, v in data.items() if not k.startswith("_")}
            return data, f"models/{pid}.json", model
    data = _load_json(os.path.join(HERE, "dp_schema.json")) or {}
    return ({k: v for k, v in data.items() if not k.startswith("_")},
            "dp_schema.json", "HomeRun XU7100")
