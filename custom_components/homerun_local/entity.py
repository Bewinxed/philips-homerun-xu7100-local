"""Shared base entity for the Philips HomeRun (Local) integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HomeRunCoordinator
from .const import DOMAIN, MANUFACTURER, MODEL


class HomeRunEntity(CoordinatorEntity[HomeRunCoordinator]):
    """Base entity tying everything to a single device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HomeRunCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Philips HomeRun",
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=coordinator.client.base_url,
        )

    @property
    def data(self) -> dict:
        """Latest state object from the coordinator (never None after setup)."""
        return self.coordinator.data or {}

    @property
    def diag(self) -> dict:
        """Latest diagnostics blob (consumables, toggles, totals, faults)."""
        return self.coordinator.diagnostics or {}
