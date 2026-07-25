"""Select platform for Philips HomeRun (Local) — water tank level."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry, HomeRunCoordinator
from .api import HomeRunApiError
from .const import WATER_LEVELS
from .entity import HomeRunEntity

_LOGGER = logging.getLogger(__name__)

# friendly label <-> backend enum
_LABEL_TO_ENUM = {v: k for k, v in WATER_LEVELS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the water level select."""
    async_add_entities([HomeRunWaterSelect(entry.runtime_data, entry)])


class HomeRunWaterSelect(HomeRunEntity, SelectEntity):
    """Mop water flow, which the vacuum entity itself does not expose."""

    _attr_translation_key = "water"
    _attr_icon = "mdi:water"
    _attr_options = list(WATER_LEVELS.values())

    def __init__(self, coordinator: HomeRunCoordinator, entry: HomeRunConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_water"

    @property
    def current_option(self) -> str | None:
        raw = str(self.data.get("water") or "").lower()
        return WATER_LEVELS.get(raw)

    async def async_select_option(self, option: str) -> None:
        enum = _LABEL_TO_ENUM.get(option, "middle")
        try:
            await self.coordinator.client.async_set_water(enum)
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun set water %s failed: %s", enum, err)
            raise
        await self.coordinator.async_request_refresh()
