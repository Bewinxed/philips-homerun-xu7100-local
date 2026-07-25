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


def _load() -> dict:
    try:
        with open(FILE) as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("labels", {})   # {group_root_id: name}
    d.setdefault("groups", [])   # [[room_id, room_id, ...], ...]
    d.setdefault("splits", {})   # {parent_room_id: [x1, y1, x2, y2]}  (map pixels)
    return d


def _save(d: dict):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, FILE)


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
    ov = _load()
    root = _root_map(ov["groups"]).get(int(rid), int(rid))
    ov["labels"][str(root)] = str(name)[:40]
    _save(ov)


def merge(a: int, b: int):
    a, b = int(a), int(b)
    ov = _load()
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
    _save(ov)


def unmerge(rid: int):
    """Drop `rid`'s group entirely (splits the whole merged set back apart)."""
    rid = int(rid)
    ov = _load()
    ov["groups"] = [g for g in ov["groups"] if rid not in [int(x) for x in g]]
    _save(ov)


# ---- splits (a user-drawn line that cuts one room into two) ------------------
SPLIT_OFFSET = 100000   # must match map_vector.SPLIT_OFFSET


def get_splits() -> dict[int, list]:
    return {int(k): v for k, v in _load()["splits"].items()}


def set_split(parent_id: int, line: list):
    ov = _load()
    ov["splits"][str(int(parent_id))] = [float(v) for v in line][:4]
    _save(ov)


def clear_split(rid: int):
    """Undo a split; accepts either half (child id maps back to its parent)."""
    rid = int(rid)
    parent = rid - SPLIT_OFFSET if rid >= SPLIT_OFFSET else rid
    ov = _load()
    ov["splits"].pop(str(parent), None)
    _save(ov)
