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
    """Describes a HomeRun sensor. value_fn gets (state, diagnostics)."""

    value_fn: Callable[[dict[str, Any], dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None


def _consumable(name: str) -> Callable[[dict, dict], Any]:
    def _fn(_s: dict, d: dict) -> Any:
        for c in d.get("consumables", []):
            if c.get("name") == name:
                return c.get("percent")
        return None
    return _fn


def _consumable_attrs(name: str) -> Callable[[dict, dict], dict]:
    def _fn(_s: dict, d: dict) -> dict:
        for c in d.get("consumables", []):
            if c.get("name") == name:
                return {"hours_left": c.get("hours_left")}
        return {}
    return _fn


def _total(key: str) -> Callable[[dict, dict], Any]:
    return lambda _s, d: (d.get("totals", {}).get(key, {}) or {}).get("value")


SENSORS: tuple[HomeRunSensorDescription, ...] = (
    HomeRunSensorDescription(
        key="battery",
        translation_key="battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s, _d: s.get("battery"),
    ),
    HomeRunSensorDescription(
        key="clean_area",
        translation_key="clean_area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s, _d: s.get("clean_area"),
    ),
    HomeRunSensorDescription(
        key="clean_time",
        translation_key="clean_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s, _d: s.get("clean_time"),
    ),
    HomeRunSensorDescription(
        key="status",
        translation_key="status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s, _d: s.get("state"),
    ),
    HomeRunSensorDescription(
        key="fault",
        translation_key="fault",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _s, d: ", ".join(d.get("faults", [])) or "OK",
    ),
    # --- consumable wear (percent remaining) ---
    HomeRunSensorDescription(
        key="side_brush", translation_key="side_brush",
        native_unit_of_measurement=PERCENTAGE, entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_consumable("Side brush"), attrs_fn=_consumable_attrs("Side brush"),
    ),
    HomeRunSensorDescription(
        key="main_brush", translation_key="main_brush",
        native_unit_of_measurement=PERCENTAGE, entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_consumable("Main brush"), attrs_fn=_consumable_attrs("Main brush"),
    ),
    HomeRunSensorDescription(
        key="filter", translation_key="filter",
        native_unit_of_measurement=PERCENTAGE, entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_consumable("Filter"), attrs_fn=_consumable_attrs("Filter"),
    ),
    HomeRunSensorDescription(
        key="mop_cloth", translation_key="mop_cloth",
        native_unit_of_measurement=PERCENTAGE, entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_consumable("Mop cloth"), attrs_fn=_consumable_attrs("Mop cloth"),
    ),
    # --- lifetime totals ---
    HomeRunSensorDescription(
        key="total_area", translation_key="total_area",
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=_total("total_area"),
    ),
    HomeRunSensorDescription(
        key="total_cleans", translation_key="total_cleans",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=_total("total_cleans"),
    ),
    HomeRunSensorDescription(
        key="total_time", translation_key="total_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC, value_fn=_total("total_time"),
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
    """A single value read from the HomeRun state or diagnostics."""

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
        return self.entity_description.value_fn(self.data, self.diag)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "status":
            return {"source": self.data.get("source")}
        if self.entity_description.attrs_fn:
            return self.entity_description.attrs_fn(self.data, self.diag)
        return None
