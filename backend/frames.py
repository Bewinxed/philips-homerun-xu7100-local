"""0xAA command frames on DP 15 (command_trans): parse and build.

    AA | 00 | LEN | CMD | DATA... | CHK      LEN = len(CMD+DATA), CHK = (CMD+sum(DATA)) & 0xFF

The robot reports its no-go zones and virtual walls with odd commands; the
even command one lower sets them (see docs/COMMAND_PROTOCOL.md):

    0x39 / 0x38  no-go zones    flag(1) n(1) then n x (mode(1) nVerts(1) + nVerts points)
    0x49 / 0x48  virtual walls  flag(1) n(1) then n x (x1 y1 x2 y2)

Points are int16 big-endian command coordinates. Zone mode: 0 = no-go (no
sweeping or mopping), 2 = no-mop. Seen on the XU2000; the stored maps carry the
same frames after their LZ4 block.
"""
from __future__ import annotations

import base64
import binascii

ZONES_GET, ZONES_SET = 0x39, 0x38
WALLS_GET, WALLS_SET = 0x49, 0x48
MODE_NO_GO, MODE_NO_MOP = 0, 2


def build(cmd: int, data: bytes = b"") -> bytes:
    body = bytes([cmd]) + bytes(data)
    return bytes([0xAA, 0x00, len(body)]) + body + bytes([sum(body) & 0xFF])


def parse(buf: bytes) -> list[tuple[int, bytes]]:
    """All well-formed frames in buf, as (cmd, data). Stops at the first non-frame."""
    out, i = [], 0
    while i + 4 <= len(buf) and buf[i] == 0xAA:
        ln = buf[i + 2]
        if i + 4 + ln > len(buf):
            break
        out.append((buf[i + 3], bytes(buf[i + 4:i + 3 + ln])))
        i += 4 + ln
    return out


def decode_raw_kind(value) -> tuple[bytes, str] | tuple[None, None]:
    """(bytes, "hex" | "b64") for a raw DP value, by which decoding yields a frame.
    Hex is tried first: a hex string is also valid base64, so the order matters."""
    if not isinstance(value, str) or not value:
        return None, None
    try:
        b = bytes.fromhex(value)
        if b[:1] in (b"\xaa", b"\xab"):
            return b, "hex"
    except ValueError:
        pass
    try:
        b = base64.b64decode(value, validate=True)
        if b[:1] in (b"\xaa", b"\xab"):
            return b, "b64"
    except (binascii.Error, ValueError):
        pass
    return None, None


def decode_raw(value) -> bytes | None:
    """A raw DP value as bytes: base64 (how the XU2000 reports it) or hex."""
    return decode_raw_kind(value)[0]


def _points(data: bytes, n: int) -> list[list[int]]:
    return [[int.from_bytes(data[k * 4:k * 4 + 2], "big", signed=True),
             int.from_bytes(data[k * 4 + 2:k * 4 + 4], "big", signed=True)] for k in range(n)]


def _pack(points) -> bytes:
    return b"".join(int(x).to_bytes(2, "big", signed=True) + int(y).to_bytes(2, "big", signed=True)
                    for x, y in points)


def decode_zones(data: bytes) -> list[dict]:
    zones, o = [], 2
    for _ in range(data[1] if len(data) >= 2 else 0):
        mode, nv = data[o], data[o + 1]
        zones.append({"mode": mode, "cmd": _points(data[o + 2:], nv)})
        o += 2 + nv * 4
    return zones


def decode_walls(data: bytes) -> list[dict]:
    n = data[1] if len(data) >= 2 else 0
    return [{"cmd": _points(data[2 + k * 8:], 2)} for k in range(n)]


def encode_zones(zones: list[dict]) -> bytes:
    out = bytes([0x01, len(zones)])
    for z in zones:
        pts = z["cmd"]
        out += bytes([int(z.get("mode", MODE_NO_GO)), len(pts)]) + _pack(pts)
    return out


def encode_walls(walls: list[dict]) -> bytes:
    return bytes([0x01, len(walls)]) + b"".join(_pack(w["cmd"]) for w in walls)


def overlays(buf: bytes) -> dict:
    """{'zones': [...] | None, 'walls': [...] | None} from the frames in buf."""
    res = {"zones": None, "walls": None}
    for cmd, data in parse(buf):
        if cmd == ZONES_GET:
            res["zones"] = decode_zones(data)
        elif cmd == WALLS_GET:
            res["walls"] = decode_walls(data)
    return res
