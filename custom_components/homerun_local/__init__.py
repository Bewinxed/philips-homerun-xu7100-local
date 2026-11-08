"""The Philips HomeRun (Local) integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HomeRunApiClient, HomeRunApiError
from .proxy import HomeRunProxyView
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    DEFAULT_PORT,
    DOMAIN,
    PLATFORMS,
    UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

type HomeRunConfigEntry = ConfigEntry["HomeRunCoordinator"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAYS_SCHEMA = vol.All(cv.ensure_list, [vol.In(DAYS)])
_TIME = vol.Match(r"^\d{1,2}:\d{2}(:\d{2})?$")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the map card's pass-through and the schedule actions."""
    hass.http.register_view(HomeRunProxyView())

    def _client(call: ServiceCall) -> HomeRunApiClient:
        entries = [e for e in hass.config_entries.async_loaded_entries(DOMAIN)]
        wanted = call.data.get("config_entry_id")
        entry = next((e for e in entries if e.entry_id == wanted), None) if wanted else (entries[0] if entries else None)
        if entry is None:
            raise HomeAssistantError("No Philips HomeRun (Local) robot is set up")
        return entry.runtime_data

    async def _run(call: ServiceCall, coro_fn) -> None:
        coordinator = _client(call)
        try:
            await coro_fn(coordinator.client)
        except HomeRunApiError as err:
            raise HomeAssistantError(f"HomeRun schedule: {err}") from err
        await coordinator.async_request_refresh()

    def _fields(call: ServiceCall) -> dict:
        data = {k: call.data[k] for k in ("enabled", "days") if k in call.data}
        if "time" in call.data:
            data["time"] = str(call.data["time"])[:5]
        return data

    async def add_schedule(call: ServiceCall) -> None:
        await _run(call, lambda c: c.async_add_schedule(_fields(call)))

    async def set_schedule(call: ServiceCall) -> None:
        await _run(call, lambda c: c.async_edit_schedule(call.data["schedule"] - 1, _fields(call)))

    async def delete_schedule(call: ServiceCall) -> None:
        await _run(call, lambda c: c.async_delete_schedule(call.data["schedule"] - 1))

    entry_field = {vol.Optional("config_entry_id"): cv.string}
    hass.services.async_register(DOMAIN, "add_schedule", add_schedule, schema=vol.Schema({
        **entry_field, vol.Required("time"): _TIME, vol.Optional("days", default=[]): _DAYS_SCHEMA,
        vol.Optional("enabled", default=True): cv.boolean}))
    hass.services.async_register(DOMAIN, "set_schedule", set_schedule, schema=vol.Schema({
        **entry_field, vol.Required("schedule"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("time"): _TIME, vol.Optional("days"): _DAYS_SCHEMA, vol.Optional("enabled"): cv.boolean}))
    hass.services.async_register(DOMAIN, "delete_schedule", delete_schedule, schema=vol.Schema({
        **entry_field, vol.Required("schedule"): vol.All(vol.Coerce(int), vol.Range(min=1))}))
    return True


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
        self.diagnostics: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            state = await self.client.async_get_state()
        except HomeRunApiError as err:
            raise UpdateFailed(str(err)) from err
        # Diagnostics are best-effort: keep the last good copy if this poll fails,
        # so switches/sensors don't drop out on a transient hiccup.
        try:
            self.diagnostics = await self.client.async_get_diagnostics()
        except HomeRunApiError:
            pass
        return state


async def async_setup_entry(hass: HomeAssistant, entry: HomeRunConfigEntry) -> bool:
    """Set up Philips HomeRun (Local) from a config entry."""
    session = async_get_clientsession(hass)
    client = HomeRunApiClient(
        session,
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data.get(CONF_TOKEN),
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
