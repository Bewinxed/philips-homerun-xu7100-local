"""Vacuum platform for Philips HomeRun (Local)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry, HomeRunCoordinator
from .api import HomeRunApiError
from .const import CONF_FAN_SPEEDS, DEFAULT_FAN_SPEEDS
from .entity import HomeRunEntity

_LOGGER = logging.getLogger(__name__)

# Map the backend's semantic state strings to HA's VacuumActivity enum.
STATE_TO_ACTIVITY: dict[str, VacuumActivity] = {
    "idle": VacuumActivity.IDLE,
    "cleaning": VacuumActivity.CLEANING,
    "paused": VacuumActivity.PAUSED,
    "returning": VacuumActivity.RETURNING,
    "docked": VacuumActivity.DOCKED,
    "charging": VacuumActivity.DOCKED,
    "error": VacuumActivity.ERROR,
}

SUPPORTED_FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.FAN_SPEED
    | VacuumEntityFeature.BATTERY
    | VacuumEntityFeature.LOCATE
    | VacuumEntityFeature.STATE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the vacuum entity from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([HomeRunVacuum(coordinator, entry)])


class HomeRunVacuum(HomeRunEntity, StateVacuumEntity):
    """A Philips HomeRun robot vacuum controlled over the local backend."""

    _attr_name = None  # main feature of the device -> use the device name
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, coordinator: HomeRunCoordinator, entry: HomeRunConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_vacuum"
        self._fan_speeds: list[str] = list(
            entry.options.get(CONF_FAN_SPEEDS, DEFAULT_FAN_SPEEDS)
        )

    @property
    def activity(self) -> VacuumActivity | None:
        """Return the current HA vacuum activity."""
        raw = self.data.get("state")
        if raw is None:
            return None
        return STATE_TO_ACTIVITY.get(str(raw), VacuumActivity.IDLE)

    @property
    def battery_level(self) -> int | None:
        """Return the battery level (0-100)."""
        value = self.data.get("battery")
        return int(value) if value is not None else None

    @property
    def fan_speed(self) -> str | None:
        """Return the current fan speed reported by the backend."""
        return self.data.get("fan")

    @property
    def fan_speed_list(self) -> list[str]:
        """Return the selectable fan speeds.

        Starts from the configured list and merges in whatever the live state
        reports, so an unexpected level from the robot is still selectable.
        """
        speeds = list(self._fan_speeds)
        live = self.data.get("fan")
        if live and live not in speeds:
            speeds.append(live)
        return speeds

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.data
        return {
            "source": data.get("source"),
            "connected": data.get("connected"),
            "water": data.get("water"),
            "mode": data.get("mode"),
            "clean_area": data.get("clean_area"),
            "clean_time": data.get("clean_time"),
            "fault": data.get("fault"),
        }

    async def _command(self, action: str) -> None:
        try:
            await self.coordinator.client.async_command(action)
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun command %s failed: %s", action, err)
            raise
        await self.coordinator.async_request_refresh()

    async def async_start(self) -> None:
        await self._command("start")

    async def async_pause(self) -> None:
        await self._command("pause")

    async def async_stop(self, **kwargs: Any) -> None:
        await self._command("stop")

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self._command("home")

    async def async_locate(self, **kwargs: Any) -> None:
        await self._command("locate")

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.async_set_fan(fan_speed)
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun set fan %s failed: %s", fan_speed, err)
            raise
        await self.coordinator.async_request_refresh()
