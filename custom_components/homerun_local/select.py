"""Select platform for Philips HomeRun (Local) — water tank level, map floor and
the cleaning settings of each schedule."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry, HomeRunCoordinator
from .api import HomeRunApiError
from .const import SCHEDULE_SETTINGS, WATER_LEVELS
from .entity import HomeRunEntity
from .schedule import HomeRunScheduleEntity, setup_schedule_platform

_LOGGER = logging.getLogger(__name__)


def _label(level: str) -> str:
    return WATER_LEVELS.get(level, level.replace("_", " ").title())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the water level select (if the model has one) and the floor select
    (if the robot stores more than one map)."""
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = []
    caps = coordinator.diagnostics.get("capabilities") or {}
    if "capabilities" not in coordinator.diagnostics or caps.get("water_levels"):
        levels = caps.get("water_levels") or list(WATER_LEVELS)
        entities.append(HomeRunWaterSelect(coordinator, entry, levels))
    async_add_entities(entities)

    # The floor select appears once the robot has more than one floor, also
    # when a floor is added later; it follows diagnostics["floors"].
    added = False

    @callback
    def _add_floor_select() -> None:
        nonlocal added
        if not added and len(_floors(coordinator).get("floors") or []) > 1:
            added = True
            async_add_entities([HomeRunFloorSelect(coordinator, entry)])

    _add_floor_select()
    entry.async_on_unload(coordinator.async_add_listener(_add_floor_select))

    # per schedule: mode, suction, water, repeat
    for cls in (HomeRunScheduleMode, HomeRunScheduleSuction, HomeRunScheduleWater, HomeRunScheduleRepeat):
        setup_schedule_platform(hass, entry, async_add_entities, cls)


def _floors(coordinator: HomeRunCoordinator) -> dict:
    return (coordinator.diagnostics or {}).get("floors") or {}


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


class HomeRunFloorSelect(HomeRunEntity, SelectEntity):
    """Which stored floor map the camera and map card show.

    Only changes the view: the robot picks its own map when it relocalises."""

    _attr_translation_key = "floor"
    _attr_icon = "mdi:floor-plan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HomeRunCoordinator, entry: HomeRunConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_floor"

    @property
    def _ids(self) -> dict[str, int]:
        return {f["name"]: f["id"] for f in _floors(self.coordinator).get("floors") or []}

    @property
    def options(self) -> list[str]:
        return list(self._ids)

    @property
    def available(self) -> bool:
        return super().available and len(self._ids) > 1

    @property
    def current_option(self) -> str | None:
        sel = _floors(self.coordinator).get("selected")
        return next((n for n, i in self._ids.items() if i == sel), None)

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.async_select_floor(self._ids[option])
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun select floor %s failed: %s", option, err)
            raise
        await self.coordinator.async_request_refresh()


class _HomeRunScheduleSetting(HomeRunScheduleEntity, SelectEntity):
    """One cleaning setting of a schedule (for a room schedule: of all its rooms)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HomeRunCoordinator, entry: HomeRunConfigEntry, index: int) -> None:
        super().__init__(coordinator, entry, index)
        self._attr_options = list(SCHEDULE_SETTINGS[self._key])

    @property
    def current_option(self) -> str | None:
        s = self.schedule
        value = s.get(self._key) if s else None
        return None if value is None else str(value)

    async def async_select_option(self, option: str) -> None:
        await self._edit(**{self._key: int(option) if self._key == "repeat" else option})


class HomeRunScheduleMode(_HomeRunScheduleSetting):
    _key = "mode"
    _attr_translation_key = "schedule_mode"
    _attr_icon = "mdi:robot-vacuum"


class HomeRunScheduleSuction(_HomeRunScheduleSetting):
    _key = "suction"
    _attr_translation_key = "schedule_suction"
    _attr_icon = "mdi:fan"


class HomeRunScheduleWater(_HomeRunScheduleSetting):
    _key = "water"
    _attr_translation_key = "schedule_water"
    _attr_icon = "mdi:water"


class HomeRunScheduleRepeat(_HomeRunScheduleSetting):
    _key = "repeat"
    _attr_translation_key = "schedule_repeat"
    _attr_icon = "mdi:repeat"
