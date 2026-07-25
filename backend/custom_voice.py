"""Install CUSTOM voice packs on the robot — over the LAN, no cloud, no root.

Credit: method from github.com/SinfreeX/Tuya-robots-custom-voice

The install command on DP 35 `voice_data` is cmd 0x34 and it carries a full URL
plus an MD5. So we can serve our own .tar.gz of MP3s from this machine and point
the robot at it. (The frames we captured earlier were only cmd 0x35 *status*
reports, which carry just a pack id — that's why it looked like URLs weren't
involved.)

Frame:
    ab 00 | len(body):4BE | body | chk
    body  = 0x34 + languageId(4BE) + md5len(1) + md5(ascii) + urllen(4BE) + url
    chk   = sum(body) & 0xFF

The URL path must look like the vendor's, and languageId must CHANGE each time or
the robot treats it as a duplicate and skips the download.
"""
from __future__ import annotations
import os, io, json, time, base64, hashlib, zipfile, socket, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VOICE_DIR = os.path.join(ROOT, "voice")
PKG_DIR = os.path.join(VOICE_DIR, "packages")
STATE = os.path.join(VOICE_DIR, "state.json")
# The official packs are ZIPs served at /smart/product/voice/<name>.zip
# (captured from this robot's real download). MP3s named 01.mp3, 02.mp3 … at the
# archive root; audio is 44.1 kHz mono 192 kbps. This differs from the upstream
# reference tool, which built .tar.gz with C001.mp3 naming (an RP38 layout).
URL_PATH = "/smart/product/voice/custom.zip"
SERVE_PORT = 8781
LANG_MIN, LANG_MAX = 8, 30


def _checksum(b: bytes) -> int:
    return sum(b) & 0xFF


def encode_install(language_id: int, md5: str, url: str, flag: int = 1) -> bytes:
    """cmd 0x34 install command.

    IMPORTANT — this robot (XU7100) needs a LEADING FLAG BYTE before the
    language id:   flag(1) languageId(4) md5len(1) md5 urllen(4) url
    The upstream reference implementation omits the flag and emits languageId
    first. VERIFIED on this device: without the flag the robot mis-parses the
    frame, falls back to its own pack 1 (it even announces "language changed to
    english") and never fetches the URL. With the flag it downloads immediately.
    Set flag=None to reproduce the upstream layout.
    """
    md5_b = md5.encode(); url_b = url.encode()
    head = b"" if flag is None else bytes([flag])
    payload = (head + int(language_id).to_bytes(4, "big")
               + bytes([len(md5_b)]) + md5_b
               + len(url_b).to_bytes(4, "big") + url_b)
    body = bytes([0x34]) + payload
    return b"\xab\x00" + len(body).to_bytes(4, "big") + body + bytes([_checksum(body)])


def decode_report(b64: str) -> dict:
    try:
        p = base64.b64decode(b64)
    except Exception:
        return {"valid": False}
    if len(p) < 13 or p[:2] != b"\xab\x00" or p[6] != 0x35:
        return {"valid": False, "hex": p.hex(), "cmd": p[6] if len(p) > 6 else None}
    # Layout verified against frames captured from THIS robot while switching
    # language in the vendor app. Note the leading flag byte: the reference
    # implementation reads language_id at payload[0:4], which is off by one for
    # our frames (it yields 0x01000000). Ours is flag(1) id(4) status(1) prog(1).
    #   ab000000000735 01 00000001 03 64 9e  -> id 1  (English) installed 100%
    #   ab000000000735 01 00000017 01 2a 78  -> id 23 (Arabic) downloading 42%
    pl = p[7:]
    declared = int.from_bytes(p[2:6], "big")   # length of payload, excludes cmd
    body = p[6:6 + 1 + declared]
    ok = (sum(body) & 0xFF) == p[-1]
    st = pl[5] if len(pl) > 5 else None
    return {"valid": True, "hex": p.hex(), "checksum_ok": ok,
            "flag": pl[0],
            "language_id": int.from_bytes(pl[1:5], "big"),
            "status": st, "progress": pl[6] if len(pl) > 6 else None,
            "status_text": {1: "downloading", 2: "installing", 3: "installed",
                            4: "failed"}.get(st, f"unknown({st})")}


def _next_language_id(current=None) -> int:
    os.makedirs(VOICE_DIR, exist_ok=True)
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    base = current if isinstance(current, int) else st.get("last_language_id", LANG_MIN - 1)
    nxt = int(base) + 1
    if nxt > LANG_MAX or nxt < LANG_MIN:
        nxt = LANG_MIN
    if isinstance(current, int) and nxt == current:
        nxt = nxt + 1 if nxt < LANG_MAX else LANG_MIN
    st["last_language_id"] = nxt
    st["last_used_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(st, open(STATE, "w"), indent=2)
    return nxt


def build_package(folder: str) -> tuple[str, str, int, int]:
    """ZIP of every mp3 in `folder`, at the archive root. -> (path, md5, size, n)

    Matches the official pack format captured from this robot: a plain .zip with
    MP3s (01.mp3, 02.mp3 …) at the root, no subfolders, no manifest.
    """
    if not os.path.isdir(folder):
        raise ValueError(f"not a folder: {folder}")
    mp3s = sorted([f for f in os.listdir(folder) if f.lower().endswith(".mp3")],
                  key=str.lower)
    if not mp3s:
        raise ValueError("no .mp3 files in that folder")
    os.makedirs(PKG_DIR, exist_ok=True)
    out = os.path.join(PKG_DIR, f"voice_{time.strftime('%Y%m%d_%H%M%S')}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in mp3s:
            z.write(os.path.join(folder, name), arcname=name)
    data = open(out, "rb").read()
    return out, hashlib.md5(data).hexdigest(), len(data), len(mp3s)


class _Handler(BaseHTTPRequestHandler):
    package_path = None
    hits = []

    requests_log = []

    def _record(self, method, served):
        _Handler.requests_log.append({
            "t": time.time(), "method": method, "path": self.path,
            "client": self.client_address[0], "served": served,
            "headers": {k: v for k, v in self.headers.items()},
        })

    def do_HEAD(self):
        self._record("HEAD", False)
        self.send_response(200)
        if self.package_path and os.path.exists(self.package_path):
            self.send_header("Content-Length", str(os.path.getsize(self.package_path)))
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if not self.package_path or not os.path.exists(self.package_path):
            self._record("GET", False); self.send_error(404); return
        if path != URL_PATH:
            # Log anything the robot asks for that we don't serve — a manifest or
            # an expected filename here would tell us what structure it wants.
            self._record("GET", False)
            self.send_error(404); return
        self._record("GET", True)
        data = open(self.package_path, "rb").read()
        _Handler.hits.append({"t": time.time(), "ua": self.headers.get("User-Agent", ""),
                              "client": self.client_address[0], "bytes": len(data)})
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


_server = None


def start_server(package_path):
    global _server
    _Handler.package_path = package_path
    _Handler.hits = []
    if _server is None:
        _server = ThreadingHTTPServer(("0.0.0.0", SERVE_PORT), _Handler)
        threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _server


def local_ip_towards(ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((ip, 1))
        return s.getsockname()[0]
    finally:
        s.close()


def install(folder: str, listen_seconds: int = 150, device=None) -> dict:
    """Build, serve, and tell the robot to install. Returns a report."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "pylib"))
    import tinytuya

    secrets = json.load(open(os.path.join(ROOT, "robot_secrets.json")))
    pkg, md5, size, n = build_package(folder)
    start_server(pkg)

    ip = secrets["ip"]
    url = f"http://{local_ip_towards(ip)}:{SERVE_PORT}{URL_PATH}?"
    d = device or tinytuya.Device(secrets["device_id"], ip, secrets["local_key"],
                                  version=float(secrets.get("version", 3.3)))
    d.set_socketPersistent(True); d.set_socketTimeout(10)

    cur = None
    try:
        cur = (d.status() or {}).get("dps", {}).get("36")
        cur = int(cur) if isinstance(cur, int) else None
    except Exception:
        pass
    lang = _next_language_id(cur)

    packet = encode_install(lang, md5, url)
    out = {"package": os.path.basename(pkg), "files": n, "size": size, "md5": md5,
           "url": url, "language_id": lang, "frame": packet.hex(), "reports": []}

    res = d.set_value("35", base64.b64encode(packet).decode(), nowait=False)
    out["set_value"] = res
    first = ((res or {}).get("dps") or {}).get("35")
    if first:
        out["reports"].append(decode_report(first))

    end = time.time() + listen_seconds
    last = first
    while time.time() < end:
        try:
            d.heartbeat(); m = d.receive()
        except Exception:
            time.sleep(0.5); continue
        dps = (m or {}).get("dps") if isinstance(m, dict) else None
        v = (dps or {}).get("35")
        if v and v != last:
            last = v
            rep = decode_report(v)
            out["reports"].append(rep)
            if rep.get("status") in (3, 4):
                break
    out["http_hits"] = _Handler.hits
    out["downloaded"] = bool(_Handler.hits)
    return out


if __name__ == "__main__":
    import sys
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VOICE_DIR, "custom")
    print(json.dumps(install(folder), indent=2, default=str))
