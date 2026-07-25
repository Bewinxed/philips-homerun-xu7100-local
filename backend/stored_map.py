"""Fetch + render the robot's STORED maps.

This is the working path. The documented `realtime-map` endpoint returns an empty
array on this robot because laser vacuums stream the live map over P2P (device
<-> app, via a STUN server) rather than persisting it to cloud storage — so there
is no object for that endpoint to link to, even mid-run.

The saved multi-floor maps, however, DO go through cloud file storage:

    GET /v1.0/users/sweepers/file/{dev}/list?fileType=collect_recode&pageNo=1&pageSize=20
        -> result.datas[] = [{id, extend, time}, ...]
    GET /v1.0/users/sweepers/file/{dev}/download?id={id}
        -> {app_map: <url>, robot_map: <url>}      (pre-signed, ~1h, no auth)

`robot_map` is the Tuya layout-v1 binary (24-byte header + LZ4 body) we can parse
into rooms and pixels. `app_map` is a zlib-compressed bitmap for app display.

NOTE the literal API typo: fileType value is `collect_recode` (not "record").
`fileType=pic` lists per-cleaning history records instead.
"""
from __future__ import annotations
import os, json, io, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = os.path.join(ROOT, "maps", "stored")
STATIC = os.path.join(ROOT, "web", "static")


def _cloud():
    from tuya_cloud import TuyaCloud, load_cfg
    cfg = load_cfg()
    return TuyaCloud(cfg), cfg["device_id"]


def list_maps(file_type="collect_recode", page_size=20):
    c, did = _cloud()
    r = c.get(f"/v1.0/users/sweepers/file/{did}/list"
              f"?fileType={file_type}&pageNo=1&pageSize={page_size}")
    if not r.get("success"):
        raise RuntimeError(f"list failed: {r.get('code')} {r.get('msg')}")
    return r.get("result", {}).get("datas", []) or []


def download_map(map_id):
    """Return {'app_map': bytes|None, 'robot_map': bytes|None} for a record id."""
    c, did = _cloud()
    r = c.get(f"/v1.0/users/sweepers/file/{did}/download?id={map_id}")
    if not r.get("success"):
        raise RuntimeError(f"download failed: {r.get('code')} {r.get('msg')}")
    res = r.get("result") or {}
    os.makedirs(STORE, exist_ok=True)
    out = {}
    for key in ("app_map", "robot_map"):
        url = res.get(key)
        if not url:
            out[key] = None
            continue
        blob = requests.get(url, timeout=30).content   # pre-signed, no auth
        with open(os.path.join(STORE, f"{map_id}_{key}.bin"), "wb") as f:
            f.write(blob)
        out[key] = blob
    return out


def latest_route():
    """Decode the route (cleaning path) from the newest cleaning record.

    Cleaning records (fileType=pic) return ONE file containing layout+route
    concatenated. The split point is encoded in the record's `extend` string:

        1784960654_20260725_145407_012_012_05172_02307_00001
                                          ^^^^^ ^^^^^
                                    layout_size  route_size

    Returns {"points": [[px,py],…], "last": [px,py], "count": n} in PIXEL space,
    or {"error": …}. Verified: the final point lands on the charger position
    from the layout header, which validates the transform.
    """
    import requests
    try:
        recs = list_maps(file_type="pic", page_size=5)
    except Exception as e:
        return {"error": f"list failed: {e}"}
    if not recs:
        return {"error": "no cleaning records"}
    rec = max(recs, key=lambda r: r.get("time", 0))
    parts = str(rec.get("extend", "")).split("_")
    if len(parts) < 7:
        return {"error": f"unexpected extend format: {rec.get('extend')}"}
    try:
        layout_size, route_size = int(parts[5]), int(parts[6])
    except ValueError:
        return {"error": f"bad sizes in extend: {rec.get('extend')}"}
    if route_size <= 0:
        return {"error": "record has no route"}

    c, did = _cloud()
    dl = c.get(f"/v1.0/users/sweepers/file/{did}/download?id={rec['id']}")
    if not dl.get("success"):
        return {"error": f"download failed: {dl.get('msg')}"}
    url = (dl.get("result") or {}).get("app_map")
    if not url:
        return {"error": "record has no app_map"}
    blob = requests.get(url, timeout=30).content
    layout, route = blob[:layout_size], blob[layout_size:layout_size + route_size]
    hdr = parse_header(layout)
    # path points are already world/10; pixel = point + origin/10
    ox, oy = hdr["origin_x"] / 10.0, hdr["origin_y"] / 10.0
    try:
        from tuya_vacuum.map.path import Path as TPath
        pts = [[round(p["x"] + ox, 1), round(p["y"] + oy, 1)]
               for p in getattr(TPath(route), "_path_data", [])]
    except Exception as e:
        return {"error": f"route parse failed: {type(e).__name__}: {e}"}
    if not pts:
        return {"error": "route decoded to zero points"}
    return {"points": pts, "last": pts[-1], "count": len(pts),
            "record_id": rec["id"], "at": rec.get("time")}


def parse_header(b):
    g = lambda i: (b[i] << 8) | b[i + 1]
    return {
        "version": b[0], "map_id": g(1), "type": b[3],
        "width": g(4), "height": g(6),
        "origin_x": g(8), "origin_y": g(10),
        "resolution_cm": g(12),
        "pile_x": g(14), "pile_y": g(16),
        "total_count": (b[18] << 24) | (b[19] << 16) | (b[20] << 8) | b[21],
        "compressed_length": g(22),
    }


def render_latest(save_png=True):
    """Grab the newest stored map, decode it, write web/static/map.png."""
    maps = list_maps()
    if not maps:
        return {"ok": False, "error": "no stored maps"}
    newest = max(maps, key=lambda m: m.get("time", 0))
    blobs = download_map(newest["id"])
    rb = blobs.get("robot_map")
    if not rb:
        return {"ok": False, "error": "record has no robot_map"}

    hdr = parse_header(rb)
    meta = {
        "ok": True, "map_id": newest["id"], "saved_at": newest.get("time"),
        "extend": newest.get("extend"), "maps_available": len(maps),
        "width": hdr["width"], "height": hdr["height"],
        "resolution_mm": hdr["resolution_cm"] * 10,
        "size_m": [round(hdr["width"] * hdr["resolution_cm"] / 100, 2),
                   round(hdr["height"] * hdr["resolution_cm"] / 100, 2)],
        "origin": [hdr["origin_x"], hdr["origin_y"]],
        "charger": [hdr["pile_x"], hdr["pile_y"]],
    }

    try:
        from tuya_vacuum.map.layout import Layout
        lay = Layout(rb)
        meta["rooms"] = [{"id": r.id, "name": getattr(r, "name", "")} for r in lay.rooms]
        if save_png:
            os.makedirs(STATIC, exist_ok=True)
            img = lay.to_image()
            img.save(os.path.join(STATIC, "map.png"))
            arc = os.path.join(ROOT, "maps", "archive")
            os.makedirs(arc, exist_ok=True)
            img.save(os.path.join(arc, f"map_{int(time.time())}.png"))
            meta["png"] = "/api/map"
    except Exception as e:
        meta["render_error"] = f"{type(e).__name__}: {e}"
    return meta


if __name__ == "__main__":
    print(json.dumps(render_latest(), indent=2))
