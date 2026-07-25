"""Voice Studio — edit, generate (ElevenLabs), and install the robot's voice pack.

The robot's 75 prompts each have a number (01..99, with gaps). We keep the
editable script (Arabic, with ElevenLabs v3 audio tags) in voice/lines_ar.json,
generate audio per line via ElevenLabs, normalise it to the exact format the
robot wants (MP3, 44.1 kHz mono ~192 kbps), and install the pack over the LAN via
backend/custom_voice.py (DP35 cmd 0x34, no cloud, no root).

Everything long-running (TTS generation, robot install) runs as a background job
so the UI can poll progress.
"""
from __future__ import annotations
import os, io, json, time, uuid, base64, threading, subprocess, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VOICE = os.path.join(ROOT, "voice")
LINES = os.path.join(VOICE, "lines_ar.json")
PROMPTS_ES = os.path.join(VOICE, "prompts_es.json")
RAW_DIR = os.path.join(VOICE, "eleven_raw")     # ElevenLabs output, before normalise
OUT_DIR = os.path.join(VOICE, "custom")         # normalised, what gets zipped + installed
SETTINGS = os.path.join(VOICE, "studio_settings.json")
KEY_FILE = os.path.join(VOICE, "eleven_key.txt")

DEFAULT_VOICE_ID = "rFDdsCQRZCUL8cPOWtnP"       # the grumpy-maid voice
ELEVEN_MODEL = "eleven_v3"
API_BASE = "https://api.elevenlabs.io/v1/text-to-speech/"

# ---- the prompt catalogue (number -> what the robot says it for) -------------
# English event labels + a category so the UI can group and icon them. Derived
# from the captured official Spanish prompts (voice/prompts_es.json).
EVENTS = {
    "01": ("Powering on", "power"),
    "02": ("Powering off", "power"),
    "04": ("Welcome & app setup", "setup"),
    "05": ("Wi-Fi setup mode", "setup"),
    "06": ("Connecting to Wi-Fi", "setup"),
    "07": ("Wi-Fi connected", "setup"),
    "09": ("Change my language", "setup"),
    "10": ("Language changed", "setup"),
    "11": ("Volume set", "setup"),
    "12": ("Mapping the home", "mapping"),
    "13": ("Mapping done, docking", "mapping"),
    "15": ("Continue mapping", "mapping"),
    "16": ("Mapping failed", "error"),
    "17": ("Start cleaning", "cleaning"),
    "18": ("Zone clean — place me", "cleaning"),
    "19": ("Scheduled clean", "cleaning"),
    "20": ("Finding my location", "localize"),
    "21": ("Location found", "localize"),
    "22": ("New space — map & clean", "localize"),
    "23": ("Room not recognized", "localize"),
    "24": ("Cleaning paused", "cleaning"),
    "25": ("Paused", "cleaning"),
    "26": ("Resuming", "cleaning"),
    "28": ("Cleaning done, docking", "docking"),
    "29": ("Low battery, docking", "docking"),
    "30": ("Returning to dock", "docking"),
    "32": ("Can't find the dock", "error"),
    "33": ("Going to sleep", "sleep"),
    "34": ("Carry me to the dock", "docking"),
    "35": ("Emptying the bin", "empty"),
    "36": ("Stopped emptying", "empty"),
    "37": ("Install the dust bag", "maintenance"),
    "38": ("Close the bin lid", "maintenance"),
    "40": ("Dust bag full", "maintenance"),
    "41": ("Charging", "docking"),
    "42": ("Charged, resuming clean", "docking"),
    "43": ("Charged, resuming map", "docking"),
    "44": ("Low battery, carry me", "docking"),
    "45": ("Low battery, wait to charge", "docking"),
    "46": ("Idle too long, powering off", "power"),
    "47": ("Low battery, powering off", "power"),
    "48": ("Remove me to power off", "power"),
    "49": ("Can't work on a slope", "error"),
    "50": ("Bin removed", "maintenance"),
    "52": ("Bin installed", "maintenance"),
    "53": ("Check the bin", "maintenance"),
    "54": ("Water tank low", "maintenance"),
    "55": ("Water tank removed", "maintenance"),
    "56": ("Check the water tank", "maintenance"),
    "57": ("Water tank in", "maintenance"),
    "58": ("Check main brush", "maintenance"),
    "59": ("Check side brush", "maintenance"),
    "60": ("Clean the pre-filter", "maintenance"),
    "61": ("Dry the filter 24h", "maintenance"),
    "62": ("Hello, I'm here", "localize"),
    "63": ("Skipping this room", "cleaning"),
    "65": ("Installing update", "update"),
    "66": ("Update in progress", "update"),
    "67": ("Update busy, try later", "update"),
    "68": ("Update failed", "update"),
    "69": ("Update installed", "update"),
    "71": ("Factory reset", "reset"),
    "72": ("Reset complete", "reset"),
    "73": ("System reset", "reset"),
    "74": ("Can't reach that area", "error"),
    "76": ("Put me on the floor", "error"),
    "77": ("Move me to level ground", "error"),
    "78": ("Clear around me, retry", "error"),
    "82": ("Bumper stuck, help!", "error"),
    "87": ("Check my laser sensor", "error"),
    "89": ("Clean my cliff sensor", "error"),
    "90": ("Child lock on", "child"),
    "93": ("Child lock on", "child"),
    "94": ("Something's wrong", "error"),
    "99": ("Check Wi-Fi password", "error"),
}

# ElevenLabs v3 audio tags, grouped for a click-to-insert palette. `grumpy` marks
# the ones that fit the Bab el Hara housemaid; the character reads best sharp and
# annoyed, not sleepy.
TAG_GROUPS = [
    {"name": "Mood", "tags": [
        {"t": "annoyed", "grumpy": True}, {"t": "irritated", "grumpy": True},
        {"t": "exasperated", "grumpy": True}, {"t": "angry", "grumpy": True},
        {"t": "sarcastic", "grumpy": True}, {"t": "relieved"}, {"t": "tired"},
    ]},
    {"name": "Reaction", "tags": [
        {"t": "scoffs", "grumpy": True}, {"t": "grumbling", "grumpy": True},
        {"t": "mutters", "grumpy": True}, {"t": "huffs", "grumpy": True},
        {"t": "groans"}, {"t": "sighs"}, {"t": "laughs"},
    ]},
    {"name": "Delivery", "tags": [
        {"t": "flatly"}, {"t": "sharply", "grumpy": True},
        {"t": "whispering"}, {"t": "shouting", "grumpy": True},
    ]},
]

DEFAULT_SETTINGS = {
    "voice_id": DEFAULT_VOICE_ID,
    "stability": 0.3,
    "similarity_boost": 0.75,
    "speed": 1.12,          # applied both to the request and to ffmpeg atempo
}


# ---- small json helpers ------------------------------------------------------
def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_key() -> str | None:
    k = os.environ.get("ELEVENLABS_API_KEY")
    if k:
        return k.strip()
    try:
        with open(KEY_FILE) as f:
            k = f.read().strip()
            return k or None
    except Exception:
        return None


def set_key(key: str):
    os.makedirs(VOICE, exist_ok=True)
    with open(KEY_FILE, "w") as f:
        f.write((key or "").strip())
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass


def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(_read_json(SETTINGS, {}))
    return s


def save_settings(patch: dict) -> dict:
    s = get_settings()
    for k in ("voice_id", "stability", "similarity_boost", "speed"):
        if k in patch and patch[k] is not None:
            s[k] = patch[k]
    _write_json(SETTINGS, s)
    return s


def load_lines() -> dict:
    return _read_json(LINES, {})


def save_line(num: str, text: str):
    lines = load_lines()
    lines[str(num)] = text
    _write_json(LINES, lines)


def _audio_info(num: str) -> dict:
    p = os.path.join(OUT_DIR, f"{num}.mp3")
    if os.path.exists(p):
        st = os.stat(p)
        return {"has_audio": True, "audio_at": int(st.st_mtime), "bytes": st.st_size}
    return {"has_audio": False, "audio_at": None, "bytes": 0}


def pack() -> dict:
    """Everything the Voice Studio UI needs to render the 75-prompt editor."""
    lines = load_lines()
    meta = lines.get("_character", "")
    rows = []
    for num, (event, cat) in EVENTS.items():
        text = lines.get(num, "")
        info = _audio_info(num)
        rows.append({
            "num": num, "event": event, "category": cat,
            "text": text, "edited": num in lines and bool(text),
            **info,
            # stale = script exists but audio is older than the script edit, or missing
            "stale": (not info["has_audio"]),
        })
    return {
        "character": meta,
        "settings": get_settings(),
        "tag_groups": TAG_GROUPS,
        "voice_id_default": DEFAULT_VOICE_ID,
        "key_set": bool(get_key()),
        "lines": rows,
        "count": len(rows),
        "with_audio": sum(1 for r in rows if r["has_audio"]),
    }


# ---- ElevenLabs generation ---------------------------------------------------
class GenError(RuntimeError):
    pass


def _eleven_tts(text: str, s: dict) -> bytes:
    """One TTS call. Returns raw mp3 bytes. Retries without `speed` if the model
    rejects it (v3 sometimes 422s on speed — ffmpeg still applies it downstream)."""
    key = get_key()
    if not key:
        raise GenError("no ElevenLabs API key set")
    voice_id = s.get("voice_id") or DEFAULT_VOICE_ID
    url = f"{API_BASE}{voice_id}?output_format=mp3_44100_128"

    def _call(include_speed: bool) -> bytes:
        vs = {"stability": float(s["stability"]),
              "similarity_boost": float(s["similarity_boost"])}
        if include_speed:
            vs["speed"] = float(s["speed"])
        body = json.dumps({"text": text, "model_id": ELEVEN_MODEL,
                           "voice_settings": vs}).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "xi-api-key": key, "Content-Type": "application/json",
            "Accept": "audio/mpeg"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()

    try:
        return _call(include_speed=True)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:400]
        except Exception:
            pass
        if e.code == 422 and "speed" in detail.lower():
            return _call(include_speed=False)   # retry, let ffmpeg handle speed
        raise GenError(f"ElevenLabs HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise GenError(f"ElevenLabs unreachable: {e.reason}")


def _normalise(raw_path: str, out_path: str, speed: float):
    """Match the robot's required format: MP3 44.1 kHz mono ~192 kbps, and apply
    the playback speed via atempo (0.5..2.0 range is safe for our ~1.12)."""
    speed = max(0.5, min(2.0, float(speed)))
    cmd = ["ffmpeg", "-y", "-i", raw_path,
           "-filter:a", f"atempo={speed:.3f}",
           "-ac", "1", "-ar", "44100", "-b:a", "192k", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise GenError(f"ffmpeg failed: {r.stderr[-300:]}")


def generate_one(num: str, text: str | None = None, s: dict | None = None) -> dict:
    """Generate + normalise a single prompt. Returns a small result dict."""
    s = s or get_settings()
    if text is None:
        text = load_lines().get(str(num), "")
    text = (text or "").strip()
    if not text:
        raise GenError("no text for this prompt")
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    raw = os.path.join(RAW_DIR, f"{num}.mp3")
    out = os.path.join(OUT_DIR, f"{num}.mp3")
    audio = _eleven_tts(text, s)
    with open(raw, "wb") as f:
        f.write(audio)
    _normalise(raw, out, s.get("speed", 1.12))
    return {"num": num, **_audio_info(num)}


# ---- background jobs ---------------------------------------------------------
JOBS: dict[str, dict] = {}
_jlock = threading.Lock()


def _new_job(kind: str, items: list) -> str:
    jid = uuid.uuid4().hex[:12]
    with _jlock:
        JOBS[jid] = {
            "id": jid, "kind": kind, "state": "running",
            "total": len(items), "done": 0,
            "items": [{"num": n, "state": "pending", "error": None} for n in items],
            "error": None, "report": None, "started": time.time(),
        }
    return jid


def _update_item(jid, idx, **kw):
    with _jlock:
        job = JOBS.get(jid)
        if not job:
            return
        job["items"][idx].update(kw)
        job["done"] = sum(1 for it in job["items"] if it["state"] in ("done", "error"))


def _finish_job(jid, **kw):
    with _jlock:
        job = JOBS.get(jid)
        if job:
            job.update(**kw)


def job(jid: str) -> dict | None:
    with _jlock:
        j = JOBS.get(jid)
        return dict(j) if j else None


def start_generate(nums: list[str]) -> str:
    """Kick off generation for the given prompt numbers in the background."""
    s = get_settings()
    if not get_key():
        raise GenError("no ElevenLabs API key set")
    lines = load_lines()
    nums = [str(n) for n in nums if str(n) in EVENTS]
    jid = _new_job("generate", nums)

    def run():
        for i, num in enumerate(nums):
            _update_item(jid, i, state="running")
            try:
                generate_one(num, lines.get(num), s)
                _update_item(jid, i, state="done")
            except Exception as e:
                _update_item(jid, i, state="error", error=str(e))
        errs = [it for it in JOBS[jid]["items"] if it["state"] == "error"]
        _finish_job(jid, state="error" if errs and len(errs) == len(nums) else "done")

    threading.Thread(target=run, daemon=True).start()
    return jid


def start_install(device=None, pause=None, resume=None) -> str:
    """Build the pack from voice/custom and install it on the robot (background).
    `pause`/`resume` let the caller free the robot's single LAN socket first."""
    import custom_voice
    jid = _new_job("install", ["build", "download", "activate"])

    def run():
        if pause:
            try: pause()
            except Exception: pass
        try:
            _update_item(jid, 0, state="running")
            report = custom_voice.install(OUT_DIR, listen_seconds=90, device=device)
            _update_item(jid, 0, state="done")
            _update_item(jid, 1, state="done" if report.get("downloaded") else "error",
                         error=None if report.get("downloaded") else "robot never fetched the pack")
            reps = report.get("reports", [])
            activated = any(r.get("status") == 3 and r.get("language_id") == report.get("language_id")
                            for r in reps)
            # the robot echoes installed on the *new* languageId when it activates
            _update_item(jid, 2, state="done" if report.get("downloaded") else "error",
                         error=None if report.get("downloaded") else "not activated")
            _finish_job(jid, state="done" if report.get("downloaded") else "error",
                        report=report,
                        error=None if report.get("downloaded") else "robot did not download the pack")
        except Exception as e:
            _finish_job(jid, state="error", error=str(e))
        finally:
            if resume:
                try: resume()
                except Exception: pass

    threading.Thread(target=run, daemon=True).start()
    return jid


if __name__ == "__main__":
    print(json.dumps({k: (v if k != "lines" else f"{len(v)} rows")
                      for k, v in pack().items()}, ensure_ascii=False, indent=2))
