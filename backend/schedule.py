"""Cleaning schedules on DP 32 (device_timer), decoded from an XU2000.

The robot reports its schedules as one 0xAB frame (see docs/COMMAND_PROTOCOL.md):

    AB 00000000 | LEN | 0x31 | DATA | CHK      LEN = len(cmd + data), CHK = sum(cmd + data) & 0xFF

    DATA = version(1)=0x01  max(1)=0x08  count(1)  schedule * count
    schedule = status(1) days(1) hour(1) minute(1) 0x00 type(1) nRooms(1) [room * nRooms | settings]
      status   1 = on, 0 = off, 2 = belongs to another map (the app shows it disabled)
      days     bit 0 = Monday ... bit 6 = Sunday (0 = once); checked against the app
      type     0 = the whole floor the robot is on: nRooms 0, then one 11-byte settings block
               1 = selected rooms: per room id(1) + an 11-byte settings block

    settings (11 bytes), values as in the robot's thing model:
      0  mode     work_mode:  0 both_work (vacuum + mop), 1 only_sweep, 2 only_mop,
                              3 intensive, 4 quiet
      1  repeat   index into clean_times [1, 2, 5]  (1x = 0; 2x/5x not yet seen from the app)
      2  order    position of a room in a room schedule
      5  suction  suction:    0 closed, 1 gentle, 2 normal, 3 strong, 4 max
      6  water    cistern:    0 closed, 1 low, 2 middle, 3 high
      3, 4 = 0 and 7..10 = FF on every schedule seen; kept as the robot sent them

The app writes the same layout with cmd 0x30.
"""
from __future__ import annotations

REPORT, SET = 0x31, 0x30
ON, OFF, OTHER_MAP = 1, 0, 2
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

MODES = ["both_work", "only_sweep", "only_mop", "intensive", "quiet"]
SUCTION = ["closed", "gentle", "normal", "strong", "max"]
WATER = ["closed", "low", "middle", "high"]
REPEAT = [1, 2, 5]
# byte -> (field, values); the field's value is values[byte]
_FIELDS = {0: ("mode", MODES), 1: ("repeat", REPEAT), 5: ("suction", SUCTION), 6: ("water", WATER)}
SETTING_FIELDS = tuple(f for f, _ in _FIELDS.values())

# A new whole-floor schedule, as the app makes one: vacuum only, strong suction, 1x
DEFAULT_SETTINGS = bytes.fromhex("0100000000" "0300" "ffffffff")


def build(cmd: int, data: bytes) -> bytes:
    body = bytes([cmd]) + data
    return b"\xab\x00\x00\x00\x00" + bytes([len(body)]) + body + bytes([sum(body) & 0xFF])


def parse_frame(buf: bytes) -> tuple[int, bytes] | None:
    if len(buf) < 8 or buf[0] != 0xAB:
        return None
    ln = buf[5]
    body = buf[6:6 + ln]
    if len(body) != ln or (sum(body) & 0xFF) != buf[6 + ln]:
        return None
    return body[0], body[1:]


def days_to_list(mask: int) -> list[str]:
    return [d for i, d in enumerate(DAYS) if mask & (1 << i)]


def list_to_days(days) -> int:
    mask = 0
    for d in days:
        mask |= 1 << DAYS.index(str(d)[:3].lower())
    return mask


def read_settings(block: str | bytes) -> dict:
    """11-byte settings block -> {'mode', 'repeat', 'suction', 'water'} (None = unknown value)."""
    b = bytes.fromhex(block) if isinstance(block, str) else block
    out = {}
    for i, (field, values) in _FIELDS.items():
        out[field] = values[b[i]] if i < len(b) and b[i] < len(values) else None
    return out


def write_settings(block: str | bytes | None, fields: dict) -> str:
    """Set the given fields in a settings block (hex); the other bytes stay as they are."""
    b = bytearray(bytes.fromhex(block) if isinstance(block, str) else (block or DEFAULT_SETTINGS))
    for i, (field, values) in _FIELDS.items():
        if fields.get(field) is None:
            continue
        v = fields[field]
        try:
            v = int(v) if field == "repeat" else str(v).lower()
        except (TypeError, ValueError):
            v = None
        if v not in values:
            raise ValueError(f"{field} must be one of {', '.join(map(str, values))}")
        b[i] = values.index(v)
    return bytes(b).hex()


def decode(data: bytes) -> dict:
    """DATA of a 0x31/0x30 frame -> {'max': n, 'schedules': [...]}.

    Each schedule carries its settings as fields (mode, repeat, suction, water);
    for a room schedule those are the first room's, per room in 'rooms'."""
    out, o = [], 3
    for _ in range(data[2]):
        status, days, hour, minute, _zero, typ = data[o:o + 6]
        o += 6
        s = {"enabled": status == ON, "status": status, "days": days_to_list(days),
             "time": f"{hour:02d}:{minute:02d}", "whole_floor": typ == 0}
        n = data[o]
        o += 1
        if typ == 0:
            s["settings"] = data[o:o + 11].hex()
            o += 11
            s.update(read_settings(s["settings"]))
        else:
            s["rooms"] = []
            for k in range(n):
                block = data[o + 12 * k + 1:o + 12 * (k + 1)]
                s["rooms"].append({"id": data[o + 12 * k], "settings": block.hex(), **read_settings(block)})
            o += 12 * n
            s.update({f: s["rooms"][0][f] if s["rooms"] else None for f in SETTING_FIELDS})
        out.append(s)
    return {"max": data[1], "schedules": out}


def apply_settings(s: dict, fields: dict) -> dict:
    """Set mode/repeat/suction/water on a schedule (on every room of a room schedule)."""
    fields = {k: v for k, v in fields.items() if k in SETTING_FIELDS and v is not None}
    if not fields:
        return s
    if s.get("whole_floor", not s.get("rooms")):
        s["settings"] = write_settings(s.get("settings"), fields)
        s.update(read_settings(s["settings"]))
    else:
        for r in s["rooms"]:
            r["settings"] = write_settings(r["settings"], fields)
            r.update(read_settings(r["settings"]))
        s.update({f: s["rooms"][0][f] if s["rooms"] else None for f in SETTING_FIELDS})
    return s


def encode(schedules: list[dict], max_count: int = 8) -> bytes:
    """Schedules (decode() shape; 'status' optional) -> DATA for cmd 0x30."""
    if len(schedules) > max_count:
        raise ValueError(f"the robot keeps at most {max_count} schedules")
    out = bytearray([0x01, max_count, len(schedules)])
    for s in schedules:
        hour, minute = (int(x) for x in s["time"].split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError(f"bad time {s['time']}")
        # a schedule of another map stays that way unless it is switched on here
        if s.get("status") == OTHER_MAP and not s.get("enabled"):
            status = OTHER_MAP
        else:
            status = ON if s.get("enabled", True) else OFF
        whole = s.get("whole_floor", not s.get("rooms"))
        out += bytes([status, list_to_days(s.get("days", [])), hour, minute, 0x00, 0 if whole else 1])
        if whole:
            out.append(0)
            out += bytes.fromhex(s.get("settings") or DEFAULT_SETTINGS.hex())
        else:
            rooms = s["rooms"]
            out.append(len(rooms))
            for r in rooms:
                out += bytes([int(r["id"])]) + bytes.fromhex(r["settings"])
    return bytes(out)
