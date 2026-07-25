"""Sensor platform for Philips HomeRun (Local)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeRunConfigEntry, HomeRunCoordinator
from .entity import HomeRunEntity


@dataclass(frozen=True, kw_only=True)
class HomeRunSensorDescription(SensorEntityDescription):
    """Describes a HomeRun sensor and how to read its value from the state."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSORS: tuple[HomeRunSensorDescription, ...] = (
    HomeRunSensorDescription(
        key="battery",
        translation_key="battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.get("battery"),
    ),
    HomeRunSensorDescription(
        key="clean_area",
        translation_key="clean_area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.get("clean_area"),
    ),
    HomeRunSensorDescription(
        key="clean_time",
        translation_key="clean_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.get("clean_time"),
    ),
    HomeRunSensorDescription(
        key="status",
        translation_key="status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("state"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRunConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HomeRun sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        HomeRunSensor(coordinator, entry, description) for description in SENSORS
    )


class HomeRunSensor(HomeRunEntity, SensorEntity):
    """A single value read from the HomeRun state object."""

    entity_description: HomeRunSensorDescription

    def __init__(
        self,
        coordinator: HomeRunCoordinator,
        entry: HomeRunConfigEntry,
        description: HomeRunSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        # The diagnostic status sensor also surfaces the data source.
        if self.entity_description.key == "status":
            return {"source": self.data.get("source")}
        return None
