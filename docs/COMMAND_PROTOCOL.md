# Navigation command protocol (DP 15 `command_trans`) — VERIFIED on this robot

Frame layout:
```
AA | ver(00) | LEN | CMD | DATA... | CHK
  LEN = len(CMD + DATA)
  CHK = (CMD + sum(DATA)) & 0xFF        # header/ver/len excluded
```
Coordinates are **signed int16, big-endian**, X then Y, 4 bytes per point —
the same coordinate space as `path_data`, so a point read out of `path_data`
can be fed straight back into a command with no conversion.

Map pixel -> command coordinate (origin_* are the RAW uint16 header values):
```
cmd_x = pixel_x * 10 - origin_x
cmd_y = origin_y - pixel_y * 10        # note: Y is inverted
```
Charger from the map header: `cmd = (pile_x - origin_x, origin_y - pile_y)`

## Verified against frames captured from THIS robot (2026-07-25)
```
aa0002130013    cmd=0x13  chk VALID   virtual-wall config echo
aa00021b001b    cmd=0x1b  chk VALID   no-go-zone v1.1 config echo
aa000355010056  cmd=0x55  chk VALID
aa00015757      cmd=0x57  chk VALID
```
Checksum rule holds and two frames decode as known commands => framing confirmed.

## Command codes (setters are even; robot echoes state back on cmd+1)
| Cmd | Meaning | Echo |
|---|---|---|
| `0x10` | zone clean v1 | `0x11` |
| `0x12` | virtual wall | `0x13` |
| `0x14` | room clean | `0x15` |
| **`0x16`** | **goto point ("pose")** | **`0x17`** |
| `0x18` | no-go zone v1 | `0x19` |
| `0x1a` | no-go zone v1.1 (sweep/mop split) | `0x1b` |
| `0x28` | zone clean v1.1 (with pass count) | `0x29` |

Payloads after CMD:
- `0x16` goto: `x(2) y(2)` — exactly one point, no count byte
- `0x12` wall: `nWalls(1)` then 2 points per wall (8 B)
- `0x1a` no-go: `nAreas(1)` then `mode(1) nVerts(1)` + 4 points (18 B)
- `0x28` zone: `passes(1) nZones(1)` then `nVerts(1)` + 4 points (17 B)
- count = 0 clears (e.g. `aa00021a001a` clears all no-go zones)

Zero-risk queries (read-only, safe to send anytime):
```
aa00011717   query current goto target      (expect 0x17 echo)
aa00013b3b   query zone-clean config
aa00011515   query room-clean config
```

## To command motion
1. write DP 15 = the frame (tinytuya takes hex for raw DPs)
2. set DP 4 `mode` = `pose` (goto) / `zone` / `part`
3. set DP 1 `power_go` = true
4. expect DP 5 `status` -> `goto_pos`, then `pos_arrived` / `pos_unarrive`

Caveats: the robot generally only accepts new coordinates **after it undocks**;
room-select (`0x14`) may require a cloud-issued session token while `pose` and
`zone` replay fine locally. Use two's-complement for negatives (Tuya's own
reference encoder has an off-by-one `% 65535` bug worth ~5 mm).

Sources: Tuya's own `tuya-panel-demo/examples/laserSweepRobot` encoder, and
`bennesp/robottino-rs` (device-validated on a Rowenta X-Plorer). Independently
cross-checked against two captured payloads from other Tuya laser vacuums.
Not published by Tuya as a spec — treat as a strong, tested hypothesis.

## 0xAB frame family (voice / multi-map management) — DECODED 2026-07-25

```
ab | reserved(4) | len(data) | cmd | data | chk
  len = len(data)  (excludes cmd, unlike the 0xAA family)
  chk = (cmd + sum(data)) & 0xFF   (same rule as 0xAA)
```

### Voice pack status — cmd 0x35 on DP 35 `voice_data`
data = `flag(1) pack_id(4 BE) status(1) progress(1)`

Captured live while switching language in the vendor app (all checksums verified):
```
ab000000000735010000000103649e   pack 1  status 3 progress 100   English, installed
ab0000000007350100000017012a78   pack 23 status 1 progress 42    Arabic, downloading
ab0000000007350100000017030050   pack 23 status 3                Arabic, installed
ab000000000735010000000103003a   pack 1  status 3                English, installed
```
status: 1 = downloading, 3 = installed.
Known pack ids: **1 = English, 23 (0x17) = Arabic**. Sparse space -> other ids
likely exist beyond what the vendor app exposes.

### Custom audio: NOT possible via this datapoint
The frame carries only a pack ID — no URL, no filename (verified by full hex +
ASCII scan). The robot resolves the id to Tuya's CDN internally and downloads it
itself. Injecting custom recordings would require MITM of that HTTPS fetch, i.e.
a CA trusted by the robot, i.e. root. No public root vector for this board.

Setter is presumed cmd **0x34** (setters are even, status echoes odd, per the
0xAA family) — NOT yet confirmed on this device.

### Custom voice install — cmd 0x34 on DP 35  ** WORKING, VERIFIED 2026-07-25 **

Method credit: github.com/SinfreeX/Tuya-robots-custom-voice

```
ab 00 | len(body):4BE | body | chk
body = 0x34 + flag(1) + languageId(4BE) + md5len(1) + md5(ascii32) + urllen(4BE) + url
chk  = sum(body) & 0xFF
```

**The leading flag byte (0x01) is REQUIRED on this robot** and is the single
difference from the upstream reference implementation, which emits languageId
first with no flag. Verified empirically:

| variant | result |
|---|---|
| `languageId(4)…` (upstream) | robot mis-parses, announces "language changed to english", reports its own pack id 1, **never fetches the URL** |
| `flag(1) languageId(4)…`    | robot **downloads immediately** (confirmed: 709334 bytes pulled from 192.168.3.241) |

Why: this robot's 0x35 status frames are `flag(1) id(4) status(1) progress(1)`, so
the command shares that layout. Without the flag the robot reads the first byte of
languageId as the flag, the id shifts by one byte, and the md5 length byte lands on
an ASCII digit of the md5 -> garbage -> fallback.

Serve the package over plain HTTP from the LAN. URL path shape used:
`http://<our-ip>:8781/smart/product/voice/custom.tar.gz?`  (trailing `?` retained
from the reference; the query string is ignored by our handler).

Package: `.tar.gz`, MP3s at the ARCHIVE ROOT, filenames matching the originals
(`C001..C025`, `D001..D006`, `E001..E002`). Reference audio format measured from a
known-good pack: **MPEG1 Layer III, 64 kbps, 48000 Hz, mono**.

`languageId` MUST differ from the currently-installed id each time or the robot
treats it as a duplicate and skips the download. `voice/state.json` rotates 8..250.

### CORRECTION 2026-07-25: the pack is a ZIP, not tar.gz — and how we know

The custom install DOWNLOADS with a tar.gz (robot fetches it) but does NOT
ACTIVATE — it keeps the official voice. Root cause found by capturing the robot's
REAL download and inspecting it:

Capture method (robot is on Wi‑Fi, so passive sniffing sees nothing — the AP only
delivers each client its own frames):
1. ARP-spoof the robot so its traffic routes through this PC (`arpspoof` + ip_forward).
2. The official pack downloads over HTTPS from a **CloudFront CDN**
   (`euimagesd2h2yqnfpu4gl5.cdn5th.com/smart/product/voice/<id>.zip`), NOT Tuya's
   pinned API. The robot does **not validate the CDN cert**, so a transparent
   mitmproxy (`--ignore-hosts '(tuya|wgine)'` to leave pinned connections alone)
   reads the download in the clear.
3. Trigger a fresh language in the app -> capture the 5 MB body.

The official pack:
- **ZIP** (with harmless `__MACOSX/._*` junk from whoever built it on a Mac)
- MP3s named `01.mp3`,`02.mp3`,`04.mp3`… at the root (75 files, gaps in numbering)
- audio: **44.1 kHz, mono, ~192 kbps** (NOT 48k/64k)
- no manifest / config file

Building a ZIP with those exact filenames + audio format, served at a `.zip` URL,
**activates correctly** — VERIFIED (robot spoke the custom clip on every prompt).
Valid languageId range is ~8..30 on this model (42 was rejected outright).
