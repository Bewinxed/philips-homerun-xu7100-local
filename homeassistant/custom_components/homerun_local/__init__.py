"""The Philips HomeRun (Local) integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HomeRunApiClient, HomeRunApiError
from .const import (
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
    PLATFORMS,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

type HomeRunConfigEntry = ConfigEntry["HomeRunCoordinator"]


class HomeRunCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls GET /api/state on the local backend every few seconds."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HomeRunApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_state()
        except HomeRunApiError as err:
            raise UpdateFailed(str(err)) from err


async def async_setup_entry(hass: HomeAssistant, entry: HomeRunConfigEntry) -> bool:
    """Set up Philips HomeRun (Local) from a config entry."""
    session = async_get_clientsession(hass)
    client = HomeRunApiClient(
        session,
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
    )

    coordinator = HomeRunCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeRunConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: HomeRunConfigEntry
) -> None:
    """Reload the entry when its options change (e.g. fan speed list)."""
    await hass.config_entries.async_reload(entry.entry_id)
