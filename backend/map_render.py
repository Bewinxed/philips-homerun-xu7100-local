"""Render the vector map to a modern-looking PNG for Home Assistant.

The old /api/map served the robot's raw grayscale raster. This draws the same
vector map the web UI shows: colour-filled rooms, walls, the cleaning path, and
the robot + dock markers. Home Assistant's camera entity points here, so the HA
card looks like our app instead of a bitmap.
"""
from __future__ import annotations
import os, glob, time, io

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# web-UI palette (MapView.svelte), indexed by room group
PALETTE = [(56, 189, 248), (244, 114, 182), (74, 222, 128), (251, 191, 36),
           (167, 139, 250), (251, 146, 60), (45, 212, 191), (248, 113, 113),
           (96, 165, 250), (192, 132, 252)]
BG = (14, 22, 38)
WALL = (9, 14, 26)
PATH = (255, 255, 255)
DOCK = (34, 197, 94)
ROBOT = (56, 189, 248)
NOGO = (239, 68, 68)
FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

_cache = {"ts": 0.0, "png": None}


def _vec():
    """Assemble the full vector map (rooms + overrides + route), like the API."""
    import sys
    sys.path.insert(0, HERE)
    from stored_map import current_map_bytes, latest_route
    from map_vector import build
    import room_overrides
    rb, floor = current_map_bytes()
    if not rb:
        return None
    vec = build(rb, splits=room_overrides.get_splits())
    vec["floor"] = floor["name"]
    try:
        r = latest_route() or {}
        # the last run may have been on another floor
        if r.get("points") and r.get("map_id", vec["map_id"]) == vec["map_id"]:
            vec["path"] = r["points"]
            vec["robot_px"] = r["last"]
    except Exception:
        pass
    vec["rooms"] = room_overrides.apply(vec.get("rooms", []))
    return vec


def render_png(force: bool = False) -> bytes | None:
    if not force and _cache["png"] and time.time() - _cache["ts"] < 45:
        return _cache["png"]
    from PIL import Image, ImageDraw, ImageFont

    vec = _vec()
    if not vec or not vec.get("ok"):
        return None

    w, h = vec["width"], vec["height"]
    SS = 2
    scale = max(1.0, (760.0 / max(w, h))) * SS
    pad = int(4 * scale)
    W, H = int(w * scale + 2 * pad), int(h * scale + 2 * pad)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    def tx(p):
        return (p[0] * scale + pad, p[1] * scale + pad)

    # room fills (outer ring), then outlines
    for room in vec.get("rooms", []):
        col = PALETTE[(room.get("group", room["id"])) % len(PALETTE)]
        rings = room.get("rings") or []
        if rings:
            outer = [tx(p) for p in rings[0]]
            if len(outer) >= 3:
                d.polygon(outer, fill=(*col, 140))
        for ring in rings:
            if len(ring) >= 2:
                d.line([tx(p) for p in ring] + [tx(ring[0])], fill=(*col, 235),
                       width=max(1, int(0.6 * scale)))

    # walls
    ws = max(1, int(scale))
    for (x, y) in vec.get("walls", []):
        px, py = x * scale + pad, y * scale + pad
        d.rectangle([px, py, px + ws, py + ws], fill=(*WALL, 235))

    # no-go zones (hatched red) and virtual walls (red lines)
    for z in vec.get("no_go_zones", []):
        poly = [tx(p) for p in z["px"]]
        if len(poly) >= 3:
            d.polygon(poly, fill=(*NOGO, 60), outline=(*NOGO, 220))
    for wall in vec.get("virtual_walls", []):
        x1, y1, x2, y2 = wall["px"]
        d.line([tx((x1, y1)), tx((x2, y2))], fill=(*NOGO, 235), width=max(2, int(0.8 * scale)))

    # cleaning path
    path = vec.get("path")
    if path and len(path) >= 2:
        d.line([tx(p) for p in path], fill=(*PATH, 170), width=max(1, int(0.5 * scale)))

    # dock + robot
    def marker(p, col):
        cx, cy = tx(p)
        r = 3.2 * scale
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*col, 70))
        r = 1.7 * scale
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*col, 255),
                  outline=(255, 255, 255, 230), width=max(1, int(0.4 * scale)))

    if vec.get("charger_px"):
        marker(vec["charger_px"], DOCK)
    if vec.get("robot_px"):
        marker(vec["robot_px"], ROBOT)

    # room labels
    try:
        font = ImageFont.truetype(FONT_PATH, int(4.6 * scale))
        for room in vec.get("rooms", []):
            if (room.get("group", room["id"])) != room["id"]:
                continue  # one label per merged group
            cx, cy = tx(room["centroid"])
            name = str(room.get("name", ""))
            bb = d.textbbox((0, 0), name, font=font)
            d.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2), name,
                   font=font, fill=(240, 245, 250, 255),
                   stroke_width=max(1, int(0.5 * scale)), stroke_fill=(8, 12, 20, 235))
    except Exception:
        pass

    img = img.resize((W // SS, H // SS), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    _cache.update(ts=time.time(), png=data)
    # also drop a copy where the old static handler expects it
    try:
        static = os.path.join(ROOT, "web", "static")
        os.makedirs(static, exist_ok=True)
        with open(os.path.join(static, "map.png"), "wb") as f:
            f.write(data)
    except Exception:
        pass
    return data


if __name__ == "__main__":
    b = render_png(force=True)
    print("rendered", len(b) if b else 0, "bytes")
