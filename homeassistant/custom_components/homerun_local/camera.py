"""Camera platform for Philips HomeRun (Local) — serves the live map PNG."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
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
    """Set up the map camera entity."""
    coordinator = entry.runtime_data
    async_add_entities([HomeRunMapCamera(coordinator, entry)])


class HomeRunMapCamera(HomeRunEntity, Camera):
    """Fetches GET /api/map so the robot's map shows up in Home Assistant."""

    _attr_translation_key = "map"
    _attr_content_type = "image/png"

    def __init__(
        self, coordinator: HomeRunCoordinator, entry: HomeRunConfigEntry
    ) -> None:
        HomeRunEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{entry.entry_id}_map"
        self._last_image: bytes | None = None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the latest map image, or None when no map is available yet."""
        try:
            image = await self.coordinator.client.async_get_map_png()
        except HomeRunApiError as err:
            _LOGGER.debug("HomeRun map fetch failed: %s", err)
            return self._last_image
        if image is not None:
            self._last_image = image
        return image
