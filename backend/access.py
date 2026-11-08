"""Who may use the backend's /api.

The backend listens on every interface, so on its own anyone on the LAN could
drive the robot, change its no-go zones or send notifications. A request to
/api is allowed when it comes from a trusted network, or carries the API token:

  trusted_networks  config.json "trusted_networks" or HOMERUN_TRUSTED_NETWORKS
                    (comma-separated CIDRs). Default: this machine only. The
                    Home Assistant app adds Home Assistant's internal network,
                    which ingress and the integration use.
  api_token         config.json "api_token" or HOMERUN_API_TOKEN. Without one, a
                    random token is created on first start and kept in api_token
                    next to config.json. Sent as "Authorization: Bearer <token>",
                    an "X-HomeRun-Token" header, or the "homerun_token" cookie the
                    web UI sets after asking for it once.

Browsers on other sites get no CORS access unless their origin is listed in
config.json "cors_origins" or HOMERUN_CORS_ORIGINS.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import secrets

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOKEN_FILE = os.path.join(ROOT, "api_token")
DEFAULT_TRUSTED = "127.0.0.0/8,::1/128"


def _list(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip() for v in value or [] if str(v).strip()]


class Access:
    def __init__(self, config: dict | None = None):
        config = config or {}
        nets = _list(os.environ.get("HOMERUN_TRUSTED_NETWORKS") or config.get("trusted_networks")
                     or DEFAULT_TRUSTED)
        self.trusted = [ipaddress.ip_network(n, strict=False) for n in nets]
        self.origins = set(_list(os.environ.get("HOMERUN_CORS_ORIGINS") or config.get("cors_origins")))
        self.token = os.environ.get("HOMERUN_API_TOKEN") or config.get("api_token") or self._stored_token()

    @staticmethod
    def _stored_token() -> str:
        try:
            with open(TOKEN_FILE) as f:
                token = f.read().strip()
            if token:
                return token
        except OSError:
            pass
        token = secrets.token_urlsafe(24)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        print(f"[access] created an API token in {TOKEN_FILE}", flush=True)
        return token

    def trusted_address(self, addr: str | None) -> bool:
        try:
            ip = ipaddress.ip_address((addr or "").split("%")[0])
        except ValueError:
            return False
        return any(ip in net for net in self.trusted)

    def presented_token(self, request) -> str | None:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return request.headers.get("X-HomeRun-Token") or request.cookies.get("homerun_token")

    def allowed(self, request) -> bool:
        if self.trusted_address(request.remote_addr):
            return True
        given = self.presented_token(request)
        return bool(given) and hmac.compare_digest(given.encode(), self.token.encode())

    def cors_headers(self, request) -> dict:
        origin = request.headers.get("Origin")
        if not origin or origin not in self.origins:
            return {}
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-HomeRun-Token"}
