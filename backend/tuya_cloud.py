"""Minimal Tuya Cloud OpenAPI client (HMAC-SHA256 signing) + high-level helpers.

Used for the two things the LAN protocol can't give us:
  * the device's local_key + full DP spec  (one-time, to enable LAN control)
  * the realtime map / path                (ongoing, laser vacuums stream via cloud)

Pure requests + hashlib/hmac. Region endpoint from config.json.
"""
from __future__ import annotations
import json, os, time, uuid, hmac, hashlib
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EMPTY_BODY_HASH = hashlib.sha256(b"").hexdigest()


def load_cfg():
    with open(os.path.join(ROOT, "config.json")) as f:
        return json.load(f)


class TuyaCloud:
    def __init__(self, cfg=None):
        cfg = cfg or load_cfg()
        c = cfg["cloud"]
        self.endpoint = c["endpoint"].rstrip("/")
        self.client_id = c["client_id"]
        self.client_secret = c["client_secret"]
        self._token = None
        self._token_exp = 0

    # ---- signing ----------------------------------------------------------
    def _sign(self, str_to_sign):
        return hmac.new(
            self.client_secret.encode(), str_to_sign.encode(), hashlib.sha256
        ).hexdigest().upper()

    @staticmethod
    def _canonical(path):
        """Tuya signs the path with query params sorted alphabetically by key.
        Passing them unsorted yields code 1004 'sign invalid' on any multi-param
        request, so normalise here rather than at every call site."""
        if "?" not in path:
            return path
        base, qs = path.split("?", 1)
        parts = [p for p in qs.split("&") if p]
        parts.sort(key=lambda kv: kv.split("=", 1)[0])
        return base + "?" + "&".join(parts)

    def _headers(self, method, path, body="", with_token=True):
        t = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        token = self._access_token() if with_token else ""
        body_hash = hashlib.sha256(body.encode()).hexdigest() if body else EMPTY_BODY_HASH
        cpath = self._canonical(path)
        str_to_sign = (
            self.client_id + token + t + nonce + method + "\n"
            + body_hash + "\n" + "" + "\n" + cpath
        )
        headers = {
            "client_id": self.client_id,
            "sign": self._sign(str_to_sign),
            "sign_method": "HMAC-SHA256",
            "t": t,
            "nonce": nonce,
            "lang": "en",
        }
        if with_token:
            headers["access_token"] = token
        return headers

    def _access_token(self):
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        path = "/v1.0/token?grant_type=1"
        r = requests.get(self.endpoint + path,
                         headers=self._headers("GET", path, with_token=False), timeout=15)
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"token error: {data}")
        self._token = data["result"]["access_token"]
        self._token_exp = time.time() + int(data["result"].get("expire_time", 7200))
        return self._token

    def get(self, path):
        cpath = self._canonical(path)
        r = requests.get(self.endpoint + cpath,
                         headers=self._headers("GET", cpath), timeout=20)
        return r.json()

    # ---- high level -------------------------------------------------------
    def ping(self):
        """Validate creds + region. Returns the access token on success."""
        return self._access_token()

    def list_devices_by_user(self, uid):
        return self.get(f"/v1.0/users/{uid}/devices")

    def list_app_users(self):
        # Smart Home projects: list the linked app-account users
        for p in ("/v1.0/apps/schema/users?page_no=1&page_size=50",
                  "/v2.0/apps/schema/users?page_no=1&page_size=50"):
            d = self.get(p)
            if d.get("success"):
                return d
        return d

    def device_detail(self, device_id):
        return self.get(f"/v1.0/devices/{device_id}")

    def device_factory_infos(self, device_id):
        return self.get(f"/v1.0/devices/factory-infos?device_ids={device_id}")

    def device_functions(self, device_id):
        return self.get(f"/v1.0/devices/{device_id}/functions")

    def device_specs(self, device_id):
        return self.get(f"/v1.0/devices/{device_id}/specifications")


if __name__ == "__main__":
    import sys
    c = TuyaCloud()
    try:
        tok = c.ping()
        print("CLOUD AUTH OK — region + credentials valid.")
        print("access_token:", tok[:8] + "…")
    except Exception as e:
        print("CLOUD AUTH FAILED:", e)
        sys.exit(1)
    # If a device is already linked, show it
    cfg = load_cfg()
    did = cfg["device_id"]
    d = c.device_detail(did)
    print("\ndevice_detail:", json.dumps(d, indent=2)[:1200])
