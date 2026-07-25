"""Button platform for Philips HomeRun (Local) — one-shot actions."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry, HomeRunCoordinator
from .api import HomeRunApiClient, HomeRunApiError
from .entity import HomeRunEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class HomeRunButtonDescription(ButtonEntityDescription):
    """A button and the client coroutine it triggers."""

    press_fn: Callable[[HomeRunApiClient], Coroutine[Any, Any, None]]


BUTTONS: tuple[HomeRunButtonDescription, ...] = (
    HomeRunButtonDescription(
        key="empty_bin", translation_key="empty_bin", icon="mdi:delete-empty",
        press_fn=lambda c: c.async_empty_bin(),
    ),
    HomeRunButtonDescription(
        key="start_mapping", translation_key="start_mapping", icon="mdi:map-search",
        press_fn=lambda c: c.async_start_mapping(),
    ),
    HomeRunButtonDescription(
        key="locate", translation_key="locate", icon="mdi:map-marker-radius",
        press_fn=lambda c: c.async_command("locate"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the action buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        HomeRunButton(coordinator, entry, description) for description in BUTTONS
    )


class HomeRunButton(HomeRunEntity, ButtonEntity):
    """A one-shot action button."""

    entity_description: HomeRunButtonDescription

    def __init__(
        self,
        coordinator: HomeRunCoordinator,
        entry: HomeRunConfigEntry,
        description: HomeRunButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    async def async_press(self) -> None:
        try:
            await self.entity_description.press_fn(self.coordinator.client)
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun button %s failed: %s", self.entity_description.key, err)
            raise
        await self.coordinator.async_request_refresh()
