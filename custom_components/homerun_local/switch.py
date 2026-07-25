"""Switch platform for Philips HomeRun (Local) — the robot's mode toggles.

Toggles (carpet boost, do-not-disturb, child lock, Y-pattern mop, vibration mop,
custom mode, auto-empty dock) are created from whatever the robot actually
reports in /api/diagnostics, so nothing is hardcoded to one firmware.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Create one switch per mode toggle the robot exposes."""
    coordinator = entry.runtime_data
    toggles: dict[str, Any] = (coordinator.diagnostics or {}).get("toggles", {})
    async_add_entities(
        HomeRunToggle(coordinator, entry, name, meta.get("label", name))
        for name, meta in toggles.items()
    )


class HomeRunToggle(HomeRunEntity, SwitchEntity):
    """A single robot mode toggle."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: HomeRunCoordinator,
        entry: HomeRunConfigEntry,
        name: str,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self._name = name
        self._attr_name = label
        self._attr_unique_id = f"{entry.entry_id}_toggle_{name}"

    @property
    def is_on(self) -> bool | None:
        meta = self.diag.get("toggles", {}).get(self._name)
        return bool(meta.get("on")) if meta else None

    async def _set(self, on: bool) -> None:
        try:
            await self.coordinator.client.async_toggle(self._name, on)
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun toggle %s failed: %s", self._name, err)
            raise
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
