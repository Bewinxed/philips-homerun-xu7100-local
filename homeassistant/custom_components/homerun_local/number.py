"""Number platform for Philips HomeRun (Local) — speaker volume."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry, HomeRunCoordinator
from .api import HomeRunApiError
from .entity import HomeRunEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the volume number."""
    async_add_entities([HomeRunVolume(entry.runtime_data, entry)])


class HomeRunVolume(HomeRunEntity, NumberEntity):
    """The robot's voice-prompt volume (0-100)."""

    _attr_translation_key = "volume"
    _attr_icon = "mdi:volume-high"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 10
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: HomeRunCoordinator, entry: HomeRunConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_volume"

    @property
    def native_value(self) -> float | None:
        value = self.diag.get("settings", {}).get("volume")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.client.async_set_volume(int(value))
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun set volume failed: %s", err)
            raise
        await self.coordinator.async_request_refresh()
