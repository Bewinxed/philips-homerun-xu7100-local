"""Local HTTP API + static host for the HomeRun control UI.

Endpoints:
  GET  /api/state          -> current semantic state (json)
  GET  /api/events         -> SSE stream, pushes state on change
  POST /api/command        -> {"action": "start|pause|stop|home|locate"}
  POST /api/fan            -> {"level": "..."}
  POST /api/water          -> {"level": "..."}
  POST /api/dp             -> {"dp": "3", "value": ...}   (raw escape hatch)
  GET  /api/map            -> latest map PNG (fetched via cloud, cached)
  GET  /api/map/meta       -> map metadata json
  GET  /                   -> built Svelte app (web/dist) if present, else status page

Runs the controller (real robot if robot_secrets.json has a local_key, else the
simulator) so the UI is fully exercised before the key exists.
"""
from __future__ import annotations
import os, sys, json, time, threading, queue
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "pylib"))

from flask import Flask, jsonify, request, Response, send_from_directory
from controller import make_controller

controller = make_controller()

# background poller pushes state to SSE subscribers
_subs: "list[queue.Queue]" = []
_subs_lock = threading.Lock()
_last_state = {}
# The robot accepts exactly ONE local connection at a time, so while we install a
# voice pack (which drives the same socket) we must stop the poller touching it.
_poll_paused = threading.Event()


def _poll_loop():
    global _last_state
    while True:
        if _poll_paused.is_set():
            time.sleep(0.5)
            continue
        try:
            controller.refresh()
        except Exception as e:
            pass
        st = controller.state()
        if st != _last_state:
            _last_state = st
            with _subs_lock:
                for q in list(_subs):
                    try: q.put_nowait(st)
                    except queue.Full: pass
        time.sleep(2.0)


threading.Thread(target=_poll_loop, daemon=True).start()

app = Flask(__name__, static_folder=None)
DIST = os.path.join(ROOT, "web", "dist")
STATIC = os.path.join(ROOT, "web", "static")


@app.get("/api/state")
def api_state():
    return jsonify(controller.state())


@app.get("/api/diagnostics")
def api_diagnostics():
    try:
        return jsonify(controller.diagnostics())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/events")
def api_events():
    q = queue.Queue(maxsize=10)
    with _subs_lock:
        _subs.append(q)
    def gen():
        try:
            yield f"data: {json.dumps(controller.state())}\n\n"
            while True:
                try:
                    st = q.get(timeout=15)
                    yield f"data: {json.dumps(st)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _subs_lock:
                if q in _subs: _subs.remove(q)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/command")
def api_command():
    action = (request.json or {}).get("action")
    fn = {"start": controller.start, "pause": controller.pause, "stop": controller.stop,
          "home": controller.home, "locate": controller.locate}.get(action)
    if not fn:
        return jsonify({"ok": False, "error": f"unknown action {action}"}), 400
    fn()
    return jsonify({"ok": True, "action": action})


@app.post("/api/fan")
def api_fan():
    controller.set_fan((request.json or {}).get("level"))
    return jsonify({"ok": True})


@app.post("/api/water")
def api_water():
    controller.set_water((request.json or {}).get("level"))
    return jsonify({"ok": True})


@app.post("/api/mapping")
def api_mapping():
    """Start a fresh mapping run (DP 104 create_map)."""
    controller.start_mapping()
    return jsonify({"ok": True})


@app.post("/api/drive")
def api_drive():
    """Manual drive — lets you walk it home instead of carrying it."""
    try:
        controller.drive((request.json or {}).get("direction"))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/toggle")
def api_toggle():
    b = request.json or {}
    try:
        controller.set_toggle(b.get("name"), b.get("on"))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/volume")
def api_volume():
    controller.set_volume((request.json or {}).get("level", 100))
    return jsonify({"ok": True})


@app.post("/api/reset-consumable")
def api_reset_consumable():
    try:
        controller.reset_consumable((request.json or {}).get("which"))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/goto")
def api_goto():
    b = request.json or {}
    try:
        frame = controller.goto(int(b["x"]), int(b["y"]))
        return jsonify({"ok": True, "frame": frame})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/language")
def api_language():
    lang = (request.json or {}).get("language")
    dp = None
    try:
        from controller import _schema_dp
        dp = _schema_dp("language")
    except Exception:
        pass
    if not dp or not lang:
        return jsonify({"ok": False, "error": "language dp or value missing"}), 400
    controller.set_dp(dp, lang)
    return jsonify({"ok": True, "language": lang})


@app.post("/api/empty")
def api_empty():
    """DP 38 dust_collection_switch — tell the base to empty the bin."""
    controller.set_dp("38", True)
    return jsonify({"ok": True})


@app.post("/api/dp")
def api_dp():
    b = request.json or {}
    controller.set_dp(b.get("dp"), b.get("value"))
    return jsonify({"ok": True})


_map_cache = {"ts": 0, "meta": {}}


def _refresh_map(force=False):
    if not force and time.time() - _map_cache["ts"] < 60:
        return _map_cache["meta"]
    try:
        from stored_map import render_latest
        r = render_latest()
        _map_cache.update(ts=time.time(), meta=r)
    except Exception as e:
        _map_cache.update(ts=time.time(), meta={"ok": False, "error": str(e)})
    return _map_cache["meta"]


@app.get("/api/map")
def api_map():
    _refresh_map()
    png = os.path.join(STATIC, "map.png")
    if os.path.exists(png):
        return send_from_directory(STATIC, "map.png", mimetype="image/png")
    return jsonify({"ok": False, "error": "no map yet — needs cloud link + a laser scan"}), 404


@app.get("/api/map/meta")
def api_map_meta():
    return jsonify(_refresh_map(force=request.args.get("force") == "1"))


_vec_cache = {"ts": 0, "data": None}
_route_cache = {"ts": 0, "data": None}


@app.get("/api/map/vector")
def api_map_vector():
    """Vector map: per-room outlines, labels, areas, settings, walls, charger."""
    force = request.args.get("force") == "1"
    if not force and _vec_cache["data"] and time.time() - _vec_cache["ts"] < 120:
        data = _vec_cache["data"]
    else:
        try:
            import glob
            from map_vector import build
            from stored_map import render_latest, STORE
            files = sorted(glob.glob(os.path.join(STORE, "*_robot_map.bin")))
            if not files:
                render_latest()
                files = sorted(glob.glob(os.path.join(STORE, "*_robot_map.bin")))
            if not files:
                return jsonify({"ok": False, "error": "no stored map yet"}), 404
            import room_overrides
            with open(files[-1], "rb") as f:
                data = build(f.read(), splits=room_overrides.get_splits())
            _vec_cache.update(ts=time.time(), data=data)
        except Exception as e:
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    out = dict(data)
    # Route replay: the live position is only available over Tuya P2P (there is
    # no local listener — the robot has exactly one open port), so we show the
    # last completed run's route and final position instead of a fake live dot.
    try:
        if not _route_cache["data"] or time.time() - _route_cache["ts"] > 120:
            from stored_map import latest_route
            _route_cache.update(ts=time.time(), data=latest_route())
        r = _route_cache["data"] or {}
        if r.get("points"):
            out["path"] = r["points"]
            out["robot_px"] = r["last"]
            out["route_info"] = {"points": r.get("count"), "at": r.get("at"),
                                 "live": False}
        elif r.get("error"):
            out["route_error"] = r["error"]
    except Exception as e:
        out["route_error"] = str(e)
    # overlay the user's local renames + merges (the robot won't do these itself)
    try:
        import room_overrides
        out["rooms"] = room_overrides.apply(list(out.get("rooms", [])))
    except Exception:
        pass
    return jsonify(out)


@app.post("/api/rooms/clean")
def api_rooms_clean():
    b = request.json or {}
    try:
        frame = controller.clean_rooms(b.get("rooms") or [], int(b.get("passes", 1)))
        return jsonify({"ok": True, "frame": frame})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/rooms/rename")
def api_rooms_rename():
    b = request.json or {}
    import room_overrides
    try:
        room_overrides.rename(b["id"], b["name"])   # persistent local label
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/rooms/merge")
def api_rooms_merge():
    b = request.json or {}
    import room_overrides
    try:
        room_overrides.merge(b["a"], b["b"])        # local grouping — see module docstring
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/rooms/unmerge")
def api_rooms_unmerge():
    b = request.json or {}
    import room_overrides
    try:
        room_overrides.unmerge(b["id"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/rooms/split")
def api_rooms_split():
    b = request.json or {}
    import room_overrides
    try:
        room_overrides.set_split(b["id"], [b["x1"], b["y1"], b["x2"], b["y2"]])
        _vec_cache["ts"] = 0        # geometry changed — force a rebuild
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/rooms/unsplit")
def api_rooms_unsplit():
    b = request.json or {}
    import room_overrides
    try:
        room_overrides.clear_split(b["id"])
        _vec_cache["ts"] = 0
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/rooms/attrs")
def api_rooms_attrs():
    b = request.json or {}
    try:
        return jsonify({"ok": True, "frame": controller.set_room_attrs(
            b["id"], b.get("fan"), b.get("water"), b.get("passes"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---- Voice Studio -----------------------------------------------------------
import voice_studio


@app.get("/api/voice/pack")
def api_voice_pack():
    return jsonify(voice_studio.pack())


@app.post("/api/voice/line")
def api_voice_line():
    b = request.json or {}
    num, text = str(b.get("num", "")), b.get("text", "")
    if num not in voice_studio.EVENTS:
        return jsonify({"ok": False, "error": f"unknown prompt {num}"}), 400
    voice_studio.save_line(num, text)
    return jsonify({"ok": True, "num": num})


@app.post("/api/voice/settings")
def api_voice_settings():
    return jsonify({"ok": True, "settings": voice_studio.save_settings(request.json or {})})


@app.post("/api/voice/key")
def api_voice_key():
    key = (request.json or {}).get("key", "")
    voice_studio.set_key(key)
    return jsonify({"ok": True, "key_set": bool(voice_studio.get_key())})


@app.get("/api/voice/audio/<num>")
def api_voice_audio(num):
    d = voice_studio.OUT_DIR
    fn = f"{num}.mp3"
    if os.path.exists(os.path.join(d, fn)):
        resp = send_from_directory(d, fn, mimetype="audio/mpeg")
        resp.headers["Cache-Control"] = "no-store"
        return resp
    return jsonify({"ok": False, "error": "no audio for this prompt yet"}), 404


@app.post("/api/voice/generate")
def api_voice_generate():
    b = request.json or {}
    if b.get("all"):
        nums = list(voice_studio.EVENTS.keys())
    else:
        nums = [str(n) for n in (b.get("nums") or [])]
    if not nums:
        return jsonify({"ok": False, "error": "no prompts to generate"}), 400
    try:
        jid = voice_studio.start_generate(nums)
        return jsonify({"ok": True, "job": jid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.post("/api/voice/install")
def api_voice_install():
    # Free the robot's single socket for the duration, and drive the install on
    # the controller's own device so we never open a second connection.
    dev = getattr(controller, "dev", None)
    if dev is None:
        return jsonify({"ok": False, "error": "no live robot (simulator) — nothing to install to"}), 400
    try:
        jid = voice_studio.start_install(
            device=dev, pause=_poll_paused.set, resume=_poll_paused.clear)
        return jsonify({"ok": True, "job": jid})
    except Exception as e:
        _poll_paused.clear()
        return jsonify({"ok": False, "error": str(e)}), 400


@app.get("/api/voice/job/<jid>")
def api_voice_job(jid):
    j = voice_studio.job(jid)
    if not j:
        return jsonify({"ok": False, "error": "unknown job"}), 404
    return jsonify(j)


@app.get("/")
@app.get("/<path:p>")
def spa(p="index.html"):
    if os.path.isdir(DIST) and os.path.exists(os.path.join(DIST, "index.html")):
        target = p if os.path.exists(os.path.join(DIST, p)) else "index.html"
        return send_from_directory(DIST, target)
    # fallback status page before the frontend is built
    st = controller.state()
    return Response(
        "<h2>HomeRun Local</h2><p>Backend up. Source: <b>%s</b>. "
        "Frontend not built yet (web/dist missing).</p><pre>%s</pre>"
        % (st["source"], json.dumps(st, indent=2)),
        mimetype="text/html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8787))
    print(f"HomeRun Local backend on http://0.0.0.0:{port}  (controller: {controller.source})")
    app.run(host="0.0.0.0", port=port, threaded=True)
