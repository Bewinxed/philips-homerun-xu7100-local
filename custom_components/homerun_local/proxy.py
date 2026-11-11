"""Authenticated pass-through from Home Assistant to the HomeRun backend.

The map card runs in the browser. Calling the backend directly needs its port
open on the LAN and fails on https (Home Assistant Cloud, a reverse proxy) as
mixed content. Through this view the card uses the logged-in user's Home
Assistant session instead:

    /api/homerun_local/proxy/api/map/vector  ->  http://<backend>/api/map/vector
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.http import KEY_HASS

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Only what the map card needs. Anything else (raw datapoint writes, zones,
# schedules, voice packs) stays with the integration's own entities and actions,
# so a Home Assistant login doesn't become raw robot access.
_ALLOWED = {
    "GET": {"api/state", "api/floors", "api/map/vector", "api/map", "api/capabilities"},
    "POST": {"api/command", "api/rooms/clean", "api/floors/select"},
}


class HomeRunProxyView(HomeAssistantView):
    """Forward /api/homerun_local/proxy/api/... to the backend of a config entry."""

    url = "/api/homerun_local/proxy/{path:.*}"
    name = "api:homerun_local:proxy"
    requires_auth = True

    async def get(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._forward(request, path)

    async def post(self, request: web.Request, path: str) -> web.StreamResponse:
        return await self._forward(request, path)

    async def _forward(self, request: web.Request, path: str) -> web.StreamResponse:
        if path not in _ALLOWED.get(request.method, ()):
            return web.json_response({"ok": False, "error": "not available through the proxy"}, status=403)
        hass: HomeAssistant = request.app[KEY_HASS]
        entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
        ]
        wanted = request.query.get("entry")
        entry = next((e for e in entries if e.entry_id == wanted), None) or (
            entries[0] if entries and not wanted else None
        )
        if entry is None:
            return web.json_response({"ok": False, "error": "no HomeRun backend"}, status=404)

        params = {k: v for k, v in request.query.items() if k != "entry"}
        url = f"{entry.runtime_data.client.base_url}/{path}"
        body = await request.read() if request.method == "POST" else None
        headers = {"Content-Type": request.content_type} if body else {}
        headers.update(entry.runtime_data.client.auth_headers)
        try:
            async with asyncio.timeout(30):
                async with async_get_clientsession(hass).request(
                    request.method, url, params=params, data=body, headers=headers
                ) as resp:
                    data = await resp.read()
                    return web.Response(
                        body=data,
                        status=resp.status,
                        content_type=resp.content_type,
                        headers={"Cache-Control": "no-store"},
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("HomeRun proxy %s %s failed: %s", request.method, url, err)
            return web.json_response({"ok": False, "error": "backend unreachable"}, status=502)
