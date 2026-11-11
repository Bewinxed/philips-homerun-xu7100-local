"""Cleaning schedules: shared base for the per-schedule switch, time and text.

The schedules come with /api/diagnostics (diagnostics["schedules"]); each one
gets an on/off switch, a time, a days text and selects for its cleaning
settings (mode, suction, water, repeat). All 8 slots the robot has get their
entities up front, so dashboards can refer to them before a schedule exists; a
slot without a schedule is unavailable (and becomes available on the next poll
after one is added in the app, the sidebar UI or with homerun_local.add_schedule).
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry, HomeRunCoordinator
from .api import HomeRunApiError
from .entity import HomeRunEntity

_LOGGER = logging.getLogger(__name__)

# The robot keeps at most 8 schedules (the "max" byte of its DP 32 frame)
MAX_SCHEDULES = 8


def schedules(coordinator: HomeRunCoordinator) -> list[dict[str, Any]]:
    return (coordinator.diagnostics or {}).get("schedules") or []


def setup_schedule_platform(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[HomeRunCoordinator, HomeRunConfigEntry, int], HomeRunEntity],
) -> None:
    """Add one entity per schedule slot now, and for any slot past 8 as it appears."""
    coordinator = entry.runtime_data
    added: set[int] = set()

    @callback
    def _add_new() -> None:
        slots = max(MAX_SCHEDULES, len(schedules(coordinator)))
        new = [i for i in range(slots) if i not in added]
        if new:
            added.update(new)
            async_add_entities(factory(coordinator, entry, i) for i in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class HomeRunScheduleEntity(HomeRunEntity):
    """One schedule, by its position in the robot's list."""

    _key = ""

    def __init__(self, coordinator: HomeRunCoordinator, entry: HomeRunConfigEntry, index: int) -> None:
        super().__init__(coordinator)
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_schedule_{index}_{self._key}"
        self._attr_translation_placeholders = {"number": str(index + 1)}

    @property
    def schedule(self) -> dict[str, Any] | None:
        lst = schedules(self.coordinator)
        return lst[self._index] if self._index < len(lst) else None

    @property
    def available(self) -> bool:
        return super().available and self.schedule is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        s = self.schedule
        if not s:
            return None
        return {"days": s["days"], "time": s["time"], "whole_floor": s["whole_floor"],
                "other_map": s["other_map"], "rooms": s["rooms"],
                **{k: s.get(k) for k in ("mode", "suction", "water", "repeat")}}

    async def _edit(self, **patch: Any) -> None:
        try:
            await self.coordinator.client.async_edit_schedule(self._index, patch)
        except HomeRunApiError as err:
            _LOGGER.error("HomeRun schedule %s: %s", self._index + 1, err)
            raise
        await self.coordinator.async_request_refresh()
