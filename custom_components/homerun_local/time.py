"""Time platform for Philips HomeRun (Local) — when each schedule starts."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry
from .schedule import HomeRunScheduleEntity, setup_schedule_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    setup_schedule_platform(hass, entry, async_add_entities, HomeRunScheduleTime)


class HomeRunScheduleTime(HomeRunScheduleEntity, TimeEntity):
    """Start time of a schedule."""

    _key = "time"
    _attr_translation_key = "schedule_time"
    _attr_icon = "mdi:clock-outline"

    @property
    def native_value(self) -> time | None:
        s = self.schedule
        if not s:
            return None
        hh, mm = (int(x) for x in s["time"].split(":"))
        return time(hh, mm)

    async def async_set_value(self, value: time) -> None:
        await self._edit(time=f"{value.hour:02d}:{value.minute:02d}")
