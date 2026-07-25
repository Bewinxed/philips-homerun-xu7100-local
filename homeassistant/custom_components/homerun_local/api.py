"""Thin async client for the HomeRun Local HTTP backend.

Only the endpoints documented in docs/API_CONTRACT.md are used:
  GET  /api/state
  POST /api/command  {"action": "start|pause|stop|home|locate"}
  POST /api/fan      {"level": "..."}
  POST /api/water    {"level": "..."}
  GET  /api/map      (image/png, or 404 when no map is available yet)
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class HomeRunApiError(Exception):
    """Raised when the backend cannot be reached or returns an error."""


class HomeRunApiClient:
    """Small wrapper around the local backend using the HA shared session."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int) -> None:
        self._session = session
        self._host = host
        self._port = int(port)

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def async_get_state(self) -> dict[str, Any]:
        """Fetch the semantic state object from GET /api/state."""
        url = f"{self.base_url}/api/state"
        try:
            async with asyncio.timeout(10):
                async with self._session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeRunApiError(f"Error fetching state from {url}: {err}") from err
        if not isinstance(data, dict):
            raise HomeRunApiError(f"Unexpected state payload from {url}: {data!r}")
        return data

    async def async_command(self, action: str) -> None:
        """POST /api/command with one of start|pause|stop|home|locate."""
        await self._post("/api/command", {"action": action})

    async def async_set_fan(self, level: str) -> None:
        """POST /api/fan with a fan level string."""
        await self._post("/api/fan", {"level": level})

    async def async_set_water(self, level: str) -> None:
        """POST /api/water with a water level string."""
        await self._post("/api/water", {"level": level})

    async def async_get_map_png(self) -> bytes | None:
        """Fetch the latest map PNG, or None when the backend returns 404."""
        url = f"{self.base_url}/api/map"
        try:
            async with asyncio.timeout(15):
                async with self._session.get(url) as resp:
                    if resp.status == 404:
                        return None
                    resp.raise_for_status()
                    return await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeRunApiError(f"Error fetching map from {url}: {err}") from err

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with asyncio.timeout(10):
                async with self._session.post(url, json=body) as resp:
                    resp.raise_for_status()
                    try:
                        return await resp.json()
                    except aiohttp.ContentTypeError:
                        return {}
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeRunApiError(f"Error posting to {url}: {err}") from err
