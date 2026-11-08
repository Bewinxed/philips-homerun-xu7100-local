"""Cleaning schedules on DP 32 (device_timer), decoded from an XU2000.

The robot reports its schedules as one 0xAB frame (see docs/COMMAND_PROTOCOL.md):

    AB 00000000 | LEN | 0x31 | DATA | CHK      LEN = len(cmd + data), CHK = sum(cmd + data) & 0xFF

    DATA = version(1)=0x01  max(1)=0x08  count(1)  schedule * count
    schedule = status(1) days(1) hour(1) minute(1) 0x00 type(1) nRooms(1) [room * nRooms | settings]
      status   1 = on, 0 = off, 2 = belongs to another map (the app shows it disabled)
      days     bit 0 = Sunday ... bit 6 = Saturday (0 = once)
      type     0 = the whole floor the robot is on: nRooms 0, then one 11-byte settings block
               1 = selected rooms: per room id(1) + an 11-byte settings block
      settings passes, water, order, ..., suction, ..., FF FF FF FF  (kept as the robot sent them)

The app writes the same layout with cmd 0x30. Room settings are passed through
unchanged; a new whole-floor schedule takes the settings block of an existing one.
"""
from __future__ import annotations

REPORT, SET = 0x31, 0x30
ON, OFF, OTHER_MAP = 1, 0, 2
DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
DEFAULT_SETTINGS = bytes.fromhex("0000000000020" "2ffffffff")   # seen on a new whole-floor schedule


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


def decode(data: bytes) -> dict:
    """DATA of a 0x31/0x30 frame -> {'max': n, 'schedules': [...]}."""
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
        else:
            s["rooms"] = [{"id": data[o + 12 * k], "settings": data[o + 12 * k + 1:o + 12 * (k + 1)].hex()}
                          for k in range(n)]
            o += 12 * n
        out.append(s)
    return {"max": data[1], "schedules": out}


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
