"""Sensor platform for Ampæra Energy integration.

Provides sensors for:
- Power consumption (W)
- Energy consumption today (kWh)
- Cost today (NOK)
- Spot price (NOK/kWh)
- Voltage per phase (V)
- Current per phase (A)
"""

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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_ENABLE_VOLTAGE_SENSORS, DOMAIN
from .coordinator import AmperaDataCoordinator


@dataclass(frozen=True, kw_only=True)
class AmperaSensorEntityDescription(SensorEntityDescription):
    """Describes an Ampæra sensor entity."""

    value_fn: Callable[[dict[str, Any]], float | None]
    requires_option: str | None = None


# Sensor definitions
SENSOR_TYPES: tuple[AmperaSensorEntityDescription, ...] = (
    AmperaSensorEntityDescription(
        key="power",
        translation_key="power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.get("power_w"),
    ),
    AmperaSensorEntityDescription(
        key="energy_today",
        translation_key="energy_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("energy_today_kwh", data.get("today_kwh")),
    ),
    AmperaSensorEntityDescription(
        key="cost_today",
        translation_key="cost_today",
        native_unit_of_measurement="NOK",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("cost_today_nok", data.get("today_cost_nok")),
    ),
    AmperaSensorEntityDescription(
        key="spot_price",
        translation_key="spot_price",
        native_unit_of_measurement="NOK/kWh",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("spot_price_nok"),
    ),
    # Voltage sensors (optional, controlled by user option)
    AmperaSensorEntityDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("voltage_l1"),
        requires_option=CONF_ENABLE_VOLTAGE_SENSORS,
    ),
    AmperaSensorEntityDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("voltage_l2"),
        requires_option=CONF_ENABLE_VOLTAGE_SENSORS,
    ),
    AmperaSensorEntityDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("voltage_l3"),
        requires_option=CONF_ENABLE_VOLTAGE_SENSORS,
    ),
    # Current sensors (optional, controlled by user option)
    AmperaSensorEntityDescription(
        key="current_l1",
        translation_key="current_l1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("current_l1"),
        requires_option=CONF_ENABLE_VOLTAGE_SENSORS,
    ),
    AmperaSensorEntityDescription(
        key="current_l2",
        translation_key="current_l2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("current_l2"),
        requires_option=CONF_ENABLE_VOLTAGE_SENSORS,
    ),
    AmperaSensorEntityDescription(
        key="current_l3",
        translation_key="current_l3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("current_l3"),
        requires_option=CONF_ENABLE_VOLTAGE_SENSORS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ampæra sensors from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinators: dict[str, AmperaDataCoordinator] = data["coordinators"]
    options = entry.options

    entities: list[AmperaSensor] = []

    for site_id, coordinator in coordinators.items():
        for description in SENSOR_TYPES:
            # Check if sensor requires an option to be enabled
            if description.requires_option:
                if not options.get(description.requires_option, False):
                    continue

            entities.append(
                AmperaSensor(
                    coordinator=coordinator,
                    description=description,
                )
            )

    async_add_entities(entities)


class AmperaSensor(CoordinatorEntity[AmperaDataCoordinator], SensorEntity):
    """Representation of an Ampæra sensor."""

    entity_description: AmperaSensorEntityDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: AmperaDataCoordinator,
        description: AmperaSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.site_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this sensor."""
        site_data = self.coordinator.site_data
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.site_id)},
            name=self.coordinator.site_name,
            manufacturer="Ampæra",
            model="Energy Monitor",
            sw_version=site_data.get("gateway_version"),
            configuration_url="https://app.ampaera.no",
        )

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        telemetry = self.coordinator.telemetry_data
        if not telemetry:
            return None
        return self.entity_description.value_fn(telemetry)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.telemetry_data is not None
        )
