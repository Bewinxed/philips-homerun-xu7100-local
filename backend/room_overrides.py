"""Local room labels + merges.

The robot won't accept rename/merge over the LAN (those are cloud map-structure
edits on this hardware), and our map is re-traced from the robot's raster every
few seconds — so a robot-side change wouldn't stick in our view anyway. Instead
we keep the user's edits ourselves and overlay them on every vector-map read:

  * a rename is a persistent label
  * a merge groups room ids so they share one colour, one name, and clean as one

This is honest — it changes what YOU see and how "clean these" batches the ids,
without pretending the robot restructured its own map.
"""
from __future__ import annotations
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILE = os.path.join(ROOT, "maps", "room_overrides.json")


def _file() -> str:
    """Room ids restart on every floor of a multi-floor robot, so each floor's
    edits live in their own file: the selected floor, or the one the map views
    show by default (the newest upload) when none was chosen."""
    try:
        from stored_map import current_floor_id
        fid = current_floor_id()
    except Exception:
        fid = None
    if fid is None:
        return FILE
    path = os.path.join(ROOT, "maps", f"room_overrides_{fid}.json")
    # Edits made before per-floor files existed belong to the floor that was
    # shown then; the first floor without a file of its own adopts them, once.
    if not os.path.exists(path) and os.path.exists(FILE):
        try:
            os.replace(FILE, path)
        except OSError:
            pass
    return path


def _load(path: str | None = None) -> dict:
    try:
        with open(path or _file()) as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("labels", {})   # {group_root_id: name}
    d.setdefault("groups", [])   # [[room_id, room_id, ...], ...]
    d.setdefault("splits", {})   # {parent_room_id: [x1, y1, x2, y2]}  (map pixels)
    return d


def _edit():
    """(overrides, path) for one read-modify-write: the floor is resolved once,
    so a floor switch in between can't save one floor's edits into another's."""
    path = _file()
    return _load(path), path


def _save(d: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, path)


def _root_map(groups: list[list[int]]) -> dict[int, int]:
    """room id -> the group's root id (its smallest member)."""
    root = {}
    for g in groups:
        if not g:
            continue
        r = min(g)
        for m in g:
            root[int(m)] = r
    return root


def group_root(rid: int) -> int:
    return _root_map(_load()["groups"]).get(int(rid), int(rid))


def apply(rooms: list[dict]) -> list[dict]:
    """Overlay labels + group membership onto freshly traced rooms.

    Works on COPIES — the caller's rooms come from a cached map build, so
    mutating them would make an override stick even after it's removed.
    """
    ov = _load()
    labels, groups = ov["labels"], ov["groups"]
    root = _root_map(groups)
    member_ids = {int(x) for g in groups for x in g}
    out = []
    for src in rooms:
        room = dict(src)
        rid = int(room["id"])
        gid = root.get(rid, rid)
        room["group"] = gid
        room["merged"] = rid in member_ids
        name = labels.get(str(gid)) or labels.get(str(rid))
        if name:
            room["name"] = name
        out.append(room)
    return out


def rename(rid: int, name: str):
    ov, path = _edit()
    root = _root_map(ov["groups"]).get(int(rid), int(rid))
    ov["labels"][str(root)] = str(name)[:40]
    _save(ov, path)


def merge(a: int, b: int):
    a, b = int(a), int(b)
    ov, path = _edit()
    groups = [set(map(int, g)) for g in ov["groups"]]
    # collect every existing group touching a or b, plus {a,b}, into one set
    union, rest = {a, b}, []
    for g in groups:
        if g & union:
            union |= g
        else:
            rest.append(g)
    rest.append(union)
    ov["groups"] = [sorted(g) for g in rest if len(g) > 1]
    _save(ov, path)


def unmerge(rid: int):
    """Drop `rid`'s group entirely (splits the whole merged set back apart)."""
    rid = int(rid)
    ov, path = _edit()
    ov["groups"] = [g for g in ov["groups"] if rid not in [int(x) for x in g]]
    _save(ov, path)


# ---- splits (a user-drawn line that cuts one room into two) ------------------
SPLIT_OFFSET = 100000   # must match map_vector.SPLIT_OFFSET


def get_splits() -> dict[int, list]:
    return {int(k): v for k, v in _load()["splits"].items()}


def set_split(parent_id: int, line: list):
    ov, path = _edit()
    ov["splits"][str(int(parent_id))] = [float(v) for v in line][:4]
    _save(ov, path)


def clear_split(rid: int):
    """Undo a split; accepts either half (child id maps back to its parent)."""
    rid = int(rid)
    parent = rid - SPLIT_OFFSET if rid >= SPLIT_OFFSET else rid
    ov, path = _edit()
    ov["splits"].pop(str(parent), None)
    _save(ov, path)
