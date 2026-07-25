"""Turn the robot's raster map into a VECTOR map: per-room outlines, labels,
walls, charger and robot position — everything the UI needs to draw borders and
let you click rooms.

Why this exists: this robot reports `vertex_num = 0` for every room, i.e. it does
NOT store room polygons. Rooms exist only as per-pixel ids inside the layout
raster. The vendor app is in exactly the same position, so it must derive room
outlines from the pixel grid too. This module does that derivation.

Pixel encoding (Tuya layout v1):
    value % 4 == 0  -> floor of room (value // 4)
    value 4n+1 / 4n+3 -> wall bordering that room
    243 / 255       -> background / unknown

Outline tracing: for each room we collect every unit edge that separates a room
pixel from a non-room pixel, then stitch those edges into closed rings. That is
exact (no smoothing error) and scales to any zoom as SVG.
"""
from __future__ import annotations
import os, json
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BG_VALUES = {243, 255}


def _header(b):
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


def _classify(v, valid_rooms=None):
    """-> ('room', id) | ('wall', None) | ('bg', None)

    valid_rooms bounds which derived ids count as real rooms. Without it, high
    pixel values (e.g. 244 -> id 61) masquerade as rooms and produce phantom
    entries; the map file's own room table is the authority.
    """
    if v in BG_VALUES:
        return ("bg", None)
    if v % 4 == 0:
        rid = v // 4
        if valid_rooms is None or rid in valid_rooms:
            return ("room", rid)
        return ("bg", None)
    if v % 4 in (1, 3):
        return ("wall", None)
    return ("wall", None)


def _rings_from_edges(edges):
    """Stitch unit edges {((x1,y1),(x2,y2))} into closed rings of points."""
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    unused = set()
    for a, b in edges:
        unused.add((a, b))
    rings = []
    remaining = dict()
    for a, b in edges:
        remaining.setdefault(a, set()).add(b)
        remaining.setdefault(b, set()).add(a)

    while any(remaining.get(k) for k in remaining):
        start = next(k for k in remaining if remaining[k])
        ring = [start]
        cur = start
        prev = None
        while True:
            nbrs = remaining.get(cur)
            if not nbrs:
                break
            # prefer to continue straight, so collinear runs collapse naturally
            nxt = None
            if prev is not None:
                dx, dy = cur[0] - prev[0], cur[1] - prev[1]
                cand = (cur[0] + dx, cur[1] + dy)
                if cand in nbrs:
                    nxt = cand
            if nxt is None:
                nxt = next(iter(nbrs))
            remaining[cur].discard(nxt)
            remaining[nxt].discard(cur)
            if nxt == start:
                break
            ring.append(nxt)
            prev, cur = cur, nxt
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def _simplify(ring):
    """Drop collinear midpoints so paths stay small."""
    if len(ring) < 3:
        return ring
    out = []
    n = len(ring)
    for i in range(n):
        p, c, q = ring[i - 1], ring[i], ring[(i + 1) % n]
        if (c[0] - p[0]) * (q[1] - c[1]) != (c[1] - p[1]) * (q[0] - c[0]):
            out.append(c)
    return out or ring


# A local "split" reassigns one side of a user-drawn line to a synthetic room id
# = parent + SPLIT_OFFSET, so the tracer emits two rooms. Must match room_overrides.
SPLIT_OFFSET = 100000


def build(robot_map_bytes, path_points=None, splits=None):
    """Return a JSON-serialisable vector map. `splits` = {parent_id: [x1,y1,x2,y2]}."""
    from tuya_vacuum.map.layout import Layout
    hdr = _header(robot_map_bytes)
    lay = Layout(robot_map_bytes)
    w, h = lay.width, lay.height
    grid = lay._map_data_array

    valid_rooms = {r.id for r in lay.rooms}
    room_pixels = defaultdict(int)
    room_edges = defaultdict(set)
    wall_cells = []
    sum_x = defaultdict(int)
    sum_y = defaultdict(int)

    def val(x, y):
        if x < 0 or y < 0 or x >= w or y >= h:
            return 255
        return grid[x + y * w]

    # 1. effective room id per pixel (None if not a room)
    eff = [None] * (w * h)
    for y in range(h):
        for x in range(w):
            kind, rid = _classify(val(x, y), valid_rooms)
            if kind == "wall":
                wall_cells.append((x, y))
            elif kind == "room":
                eff[x + y * w] = rid

    # 2. apply splits: pixels of the parent on the negative side of the line get
    #    a synthetic id, so the two halves trace as separate rooms.
    for srid, line in (splits or {}).items():
        srid = int(srid)
        x1, y1, x2, y2 = line
        for y in range(h):
            base = y * w
            for x in range(w):
                if eff[base + x] == srid:
                    if (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1) < 0:
                        eff[base + x] = srid + SPLIT_OFFSET

    def erid(x, y):
        if x < 0 or y < 0 or x >= w or y >= h:
            return None
        return eff[x + y * w]

    # 3. edges + area + centroid from the effective grid
    for y in range(h):
        for x in range(w):
            rid = eff[x + y * w]
            if rid is None:
                continue
            room_pixels[rid] += 1
            sum_x[rid] += x
            sum_y[rid] += y
            for dx, dy, e in ((0, -1, ((x, y), (x + 1, y))),
                              (0, 1, ((x, y + 1), (x + 1, y + 1))),
                              (-1, 0, ((x, y), (x, y + 1))),
                              (1, 0, ((x + 1, y), (x + 1, y + 1)))):
                if erid(x + dx, y + dy) != rid:
                    a, b = e
                    room_edges[rid].add((a, b))

    meta_by_id = {r.id: r for r in lay.rooms}
    FAN = {0: "gentle", 1: "normal", 2: "strong", 3: "max"}
    WATER = {0: "closed", 1: "low", 2: "middle", 3: "high"}

    rooms = []
    for rid in sorted(room_pixels):
        rings = [_simplify(r) for r in _rings_from_edges(room_edges[rid])]
        rings.sort(key=len, reverse=True)
        is_split = rid >= SPLIT_OFFSET
        parent = rid - SPLIT_OFFSET if is_split else rid
        m = meta_by_id.get(parent)
        base_name = getattr(m, "name", f"Room{parent + 1}") if m else f"Room{parent + 1}"
        area_m2 = round(room_pixels[rid] * (hdr["resolution_cm"] / 100.0) ** 2, 2)
        rooms.append({
            "id": rid,
            "name": f"{base_name} ·2" if is_split else base_name,
            "split": is_split or parent in {int(k) for k in (splits or {})},
            "split_of": parent if is_split else None,
            "pixels": room_pixels[rid],
            "area_m2": area_m2,
            "centroid": [round(sum_x[rid] / room_pixels[rid], 1),
                         round(sum_y[rid] / room_pixels[rid], 1)],
            "rings": rings,
            "settings": {
                "sweep_count": getattr(m, "sweep_count", None) if m else None,
                "mop_count": getattr(m, "mop_count", None) if m else None,
                "fan": FAN.get(getattr(m, "fan", None)) if m else None,
                "water": WATER.get(getattr(m, "water_level", None)) if m else None,
                "sweep_forbidden": bool(getattr(m, "sweep_forbidden", 0)) if m else False,
                "mop_forbidden": bool(getattr(m, "mop_forbidden", 0)) if m else False,
                "y_mode": getattr(m, "y_mode", None) if m else None,
                "order": getattr(m, "order", None) if m else None,
            },
        })

    res = hdr["resolution_cm"]
    out = {
        "ok": True,
        "width": w, "height": h,
        "resolution_cm": res,
        "size_m": [round(w * res / 100, 2), round(h * res / 100, 2)],
        "origin": [hdr["origin_x"], hdr["origin_y"]],
        "map_id": hdr["map_id"],
        "rooms": rooms,
        "walls": wall_cells,
        # charger in pixel space: pile is world*10, origin is world*10
        "charger_px": [round(hdr["pile_x"] / 10.0, 1), round(hdr["pile_y"] / 10.0, 1)],
        "charger_raw": [hdr["pile_x"], hdr["pile_y"]],
    }
    if path_points:
        out["path"] = path_points
        out["robot_px"] = path_points[-1] if path_points else None
    return out


def cmd_to_pixel(hdr_origin_x, hdr_origin_y, px, py, res_cm):
    """pixel -> command coordinate (see docs/COMMAND_PROTOCOL.md)."""
    return (int(px * 10 - hdr_origin_x), int(hdr_origin_y - py * 10))


if __name__ == "__main__":
    import glob
    f = sorted(glob.glob(os.path.join(ROOT, "maps", "stored", "*_robot_map.bin")))[-1]
    v = build(open(f, "rb").read())
    print(f"source: {f}")
    print(f"{v['width']}x{v['height']} @ {v['resolution_cm']}cm/px = {v['size_m']} m")
    print(f"charger px {v['charger_px']}  raw {v['charger_raw']}")
    print(f"walls: {len(v['walls'])} cells")
    for r in v["rooms"]:
        print(f"  room {r['id']} {r['name']:<8} {r['area_m2']:>6} m²  "
              f"rings={len(r['rings'])} pts={sum(len(x) for x in r['rings']):<5} "
              f"fan={r['settings']['fan']} water={r['settings']['water']} "
              f"passes={r['settings']['sweep_count']}")
