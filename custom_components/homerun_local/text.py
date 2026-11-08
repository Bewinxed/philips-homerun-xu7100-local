"""Text platform for Philips HomeRun (Local) — the days of each schedule."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry
from .schedule import HomeRunScheduleEntity, setup_schedule_platform

DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    setup_schedule_platform(hass, entry, async_add_entities, HomeRunScheduleDays)


class HomeRunScheduleDays(HomeRunScheduleEntity, TextEntity):
    """Days of a schedule as text, e.g. "mon,wed,fri" (empty = once)."""

    _key = "days"
    _attr_translation_key = "schedule_days"
    _attr_icon = "mdi:calendar-week"
    _attr_pattern = r"^((mon|tue|wed|thu|fri|sat|sun)(,(mon|tue|wed|thu|fri|sat|sun))*)?$"
    _attr_native_max = 27

    @property
    def native_value(self) -> str | None:
        s = self.schedule
        if not s:
            return None
        return ",".join(d for d in DAY_ORDER if d in s["days"])

    async def async_set_value(self, value: str) -> None:
        days = [d.strip().lower()[:3] for d in value.split(",") if d.strip()]
        await self._edit(days=days)
