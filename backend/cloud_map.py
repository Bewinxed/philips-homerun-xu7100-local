"""Fetch + render the robot's live map via Tuya Cloud (laser vacuums only
expose the map through the cloud, never the LAN). Produces a PNG plus metadata
(dimensions, resolution, room list, charger + robot position) for the UI.

Requires config.json -> cloud creds + a linked device.
"""
from __future__ import annotations
import os, json, time, io

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _cfg():
    with open(os.path.join(ROOT, "config.json")) as f:
        return json.load(f)


class MapService:
    def __init__(self, cfg=None):
        self.cfg = cfg or _cfg()
        c = self.cfg["cloud"]
        self.endpoint = c["endpoint"]
        self.client_id = c["client_id"]
        self.client_secret = c["client_secret"]
        self.device_id = self.cfg["device_id"]
        self._vac = None
        self._last = 0.0
        self._cache_png = os.path.join(ROOT, "web", "static", "map.png")
        os.makedirs(os.path.dirname(self._cache_png), exist_ok=True)

    def _vacuum(self):
        if self._vac is None:
            from tuya_vacuum import Vacuum
            self._vac = Vacuum(
                origin=self.endpoint,
                client_id=self.client_id,
                client_secret=self.client_secret,
                device_id=self.device_id,
            )
        return self._vac

    def fetch(self, save=True):
        """Return dict with png bytes + metadata, or {'ok': False, 'error': ...}."""
        try:
            m = self._vacuum().fetch_map()
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        meta = {"ok": True, "ts": time.time()}
        layout = getattr(m, "layout", None)
        path = getattr(m, "path", None)
        if layout is not None:
            meta.update({
                "width": layout.width, "height": layout.height,
                "resolution_mm": getattr(layout, "map_resolution", None),
                "origin": [getattr(layout, "origin_x", None), getattr(layout, "origin_y", None)],
                "charger": [getattr(layout, "pile_x", None), getattr(layout, "pile_y", None)],
                "rooms": [
                    {"id": r.id, "name": getattr(r, "name", ""), }
                    for r in getattr(layout, "rooms", []) or []
                ],
            })
        if path is not None:
            pts = getattr(path, "_path_data", []) or []
            if pts:
                meta["robot"] = [pts[-1]["x"], pts[-1]["y"]]
                meta["path_points"] = len(pts)

        try:
            img = m.to_image()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png = buf.getvalue()
            if save:
                with open(self._cache_png, "wb") as f:
                    f.write(png)
                # Keep a timestamped archive: this robot has a history of wiping
                # maps, so every successfully fetched map is preserved on disk.
                try:
                    arc = os.path.join(ROOT, "maps", "archive")
                    os.makedirs(arc, exist_ok=True)
                    with open(os.path.join(arc, f"map_{int(time.time())}.png"), "wb") as f:
                        f.write(png)
                except Exception:
                    pass
            meta["png_bytes"] = len(png)
            meta["png_path"] = self._cache_png
            self._last = time.time()
            return {**meta, "_png": png}
        except Exception as e:
            return {"ok": False, "error": f"render failed: {type(e).__name__}: {e}", **meta}


if __name__ == "__main__":
    import sys
    r = MapService().fetch()
    r.pop("_png", None)
    print(json.dumps(r, indent=2))
    if not r.get("ok"):
        sys.exit(1)
