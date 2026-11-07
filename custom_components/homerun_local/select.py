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


def _label(level: str) -> str:
    return WATER_LEVELS.get(level, level.replace("_", " ").title())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the water level select, if this model has a water tank control."""
    coordinator = entry.runtime_data
    caps = coordinator.diagnostics.get("capabilities") or {}
    if "capabilities" in coordinator.diagnostics and not caps.get("water_levels"):
        return
    levels = caps.get("water_levels") or list(WATER_LEVELS)
    async_add_entities([HomeRunWaterSelect(coordinator, entry, levels)])


class HomeRunWaterSelect(HomeRunEntity, SelectEntity):
    """Mop water flow, which the vacuum entity itself does not expose."""

    _attr_translation_key = "water"
    _attr_icon = "mdi:water"
    def __init__(
        self, coordinator: HomeRunCoordinator, entry: HomeRunConfigEntry, levels: list[str]
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_water"
        self._label_to_enum = {_label(lv): lv for lv in levels}
        self._attr_options = list(self._label_to_enum)

    @property
    def current_option(self) -> str | None:
        raw = str(self.data.get("water") or "").lower()
        return _label(raw) if raw else None

    async def async_select_option(self, option: str) -> None:
        enum = self._label_to_enum[option]
        try:
            await self.coordinator.client.async_set_water(enum)
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun set water %s failed: %s", enum, err)
            raise
        await self.coordinator.async_request_refresh()
