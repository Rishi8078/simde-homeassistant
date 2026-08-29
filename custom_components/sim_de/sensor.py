"""Support for sim.de sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_URL, DOMAIN, KEY_CURRENT, KEY_PLAN, KEY_PREVIOUS
from .coordinator import SimDeDataUpdateCoordinator
from .models import Plan, Usage


@dataclass(frozen=True, kw_only=True)
class SimDeSensorDescription(SensorEntityDescription):
    """Describes a sim.de sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _current(data: dict[str, Any]) -> Usage:
    return data[KEY_CURRENT]


def _previous(data: dict[str, Any]) -> Usage:
    return data[KEY_PREVIOUS]


def _plan(data: dict[str, Any]) -> Plan:
    return data[KEY_PLAN]


SENSORS: tuple[SimDeSensorDescription, ...] = (
    SimDeSensorDescription(
        key="data_used",
        translation_key="data_used",
        icon="mdi:download-network",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        # The counter resets when the billing month rolls over.
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: _current(data).used_gb,
        attributes_fn=lambda data: _current(data).as_attributes(),
    ),
    SimDeSensorDescription(
        key="data_remaining",
        translation_key="data_remaining",
        icon="mdi:gauge",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: _current(data).remaining_gb,
    ),
    SimDeSensorDescription(
        key="data_allowance",
        translation_key="data_allowance",
        icon="mdi:sim",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _current(data).allowance_gb,
    ),
    SimDeSensorDescription(
        key="data_usage",
        translation_key="data_usage",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: _current(data).usage_percent,
    ),
    SimDeSensorDescription(
        key="previous_data_used",
        translation_key="previous_data_used",
        icon="mdi:calendar-arrow-left",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _previous(data).used_gb,
        attributes_fn=lambda data: _previous(data).as_attributes(),
    ),
    SimDeSensorDescription(
        key="previous_data_usage",
        translation_key="previous_data_usage",
        icon="mdi:percent-outline",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _previous(data).usage_percent,
    ),
    SimDeSensorDescription(
        key="plan",
        translation_key="plan",
        icon="mdi:card-account-details-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _plan(data).name,
        attributes_fn=lambda data: _plan(data).as_attributes(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sim.de sensors based on a config entry."""
    coordinator: SimDeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        SimDeSensor(coordinator, entry, description) for description in SENSORS
    )


class SimDeSensor(CoordinatorEntity[SimDeDataUpdateCoordinator], SensorEntity):
    """A single figure read off the Servicewelt."""

    _attr_has_entity_name = True

    entity_description: SimDeSensorDescription

    def __init__(
        self,
        coordinator: SimDeDataUpdateCoordinator,
        entry: ConfigEntry,
        description: SimDeSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Drillisch Online GmbH",
            model=self._plan_name or "sim.de",
            configuration_url=BASE_URL,
        )

    @property
    def _plan_name(self) -> str | None:
        """Return the tariff name, once a poll has produced one."""
        data = self.coordinator.data

        return data[KEY_PLAN].name if data else None

    @property
    def available(self) -> bool:
        """Return True while the figure this sensor shows is known."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> Any:
        """Return the value of the sensor."""
        if not self.coordinator.data:
            return None

        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the extra details this sensor carries, if any."""
        if not self.coordinator.data or self.entity_description.attributes_fn is None:
            return {}

        return self.entity_description.attributes_fn(self.coordinator.data)
