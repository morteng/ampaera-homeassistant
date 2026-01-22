"""Number platform for Ampæra Simulation.

Creates number entities for adjustable setpoints like
water heater target temperature and EV charger current limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfElectricCurrent, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_EV_CHARGER,
    DEVICE_WATER_HEATER,
    DOMAIN,
    EV_CHARGER_MAX_CURRENT,
    EV_CHARGER_MIN_CURRENT,
    EV_CHARGER_MODEL,
    MANUFACTURER,
    WATER_HEATER_MODEL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SimulationCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number platform."""
    coordinator: SimulationCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[NumberEntity] = []

    # Water heater numbers
    if DEVICE_WATER_HEATER in coordinator.devices:
        entities.append(WaterHeaterTargetTemperature(coordinator))

    # EV charger numbers
    if DEVICE_EV_CHARGER in coordinator.devices:
        entities.append(EVChargerCurrentLimit(coordinator))

    async_add_entities(entities)


class WaterHeaterTargetTemperature(CoordinatorEntity, NumberEntity):
    """Water heater target temperature number entity.

    Allows setting the target temperature for the water heater.
    Works alongside the operating mode to control heating behavior.
    """

    _attr_has_entity_name = True
    _attr_name = "Target Temperature"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 40.0
    _attr_native_max_value = 75.0
    _attr_native_step = 1.0
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize number entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_water_heater_target_temp"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, "water_heater")},
            name="Simulated Water Heater",
            manufacturer=MANUFACTURER,
            model=WATER_HEATER_MODEL,
            sw_version="1.0.0",
        )

    @property
    def native_value(self) -> float | None:
        """Return current target temperature."""
        if self.coordinator.water_heater:
            return self.coordinator.water_heater.target_temp
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set target temperature."""
        self.coordinator.set_water_heater_target(value)
        await self.coordinator.async_request_refresh()


class EVChargerCurrentLimit(CoordinatorEntity, NumberEntity):
    """EV charger current limit number entity.

    Controls the maximum charging current in amps.
    Affects charging power: Power = Voltage × Current.
    """

    _attr_has_entity_name = True
    _attr_name = "Current Limit"
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_min_value = float(EV_CHARGER_MIN_CURRENT)
    _attr_native_max_value = float(EV_CHARGER_MAX_CURRENT)
    _attr_native_step = 1.0
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize number entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ev_charger_current_limit"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, "ev_charger")},
            name="Simulated EV Charger",
            manufacturer=MANUFACTURER,
            model=EV_CHARGER_MODEL,
            sw_version="1.0.0",
        )

    @property
    def native_value(self) -> float | None:
        """Return current limit."""
        if self.coordinator.ev_charger:
            return float(self.coordinator.ev_charger.current_limit)
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set current limit."""
        self.coordinator.set_ev_current_limit(int(value))
        await self.coordinator.async_request_refresh()
