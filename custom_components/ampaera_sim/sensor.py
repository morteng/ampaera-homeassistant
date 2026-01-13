"""Sensor platform for Ampæra Simulation.

Creates sensor entities for all simulated devices with proper
device registry entries and state classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    AMS_METER_MODEL,
    DEVICE_AMS_METER,
    DEVICE_EV_CHARGER,
    DEVICE_HOUSEHOLD,
    DEVICE_WATER_HEATER,
    DOMAIN,
    EV_CHARGER_MODEL,
    HOUSEHOLD_MODEL,
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
    """Set up sensor platform."""
    coordinator: SimulationCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[SensorEntity] = []

    # Water heater sensors
    if DEVICE_WATER_HEATER in coordinator.devices:
        entities.extend([
            WaterHeaterTemperatureSensor(coordinator),
            WaterHeaterPowerSensor(coordinator),
            WaterHeaterEnergySensor(coordinator),
        ])

    # EV charger sensors
    if DEVICE_EV_CHARGER in coordinator.devices:
        entities.extend([
            EVChargerPowerSensor(coordinator),
            EVChargerSessionEnergySensor(coordinator),
            EVChargerTotalEnergySensor(coordinator),
            EVChargerBatterySOCSensor(coordinator),
        ])

    # Power meter sensors
    if DEVICE_AMS_METER in coordinator.devices:
        entities.extend([
            PowerMeterPowerSensor(coordinator),
            PowerMeterVoltageL1Sensor(coordinator),
            PowerMeterVoltageL2Sensor(coordinator),
            PowerMeterVoltageL3Sensor(coordinator),
            PowerMeterCurrentL1Sensor(coordinator),
            PowerMeterCurrentL2Sensor(coordinator),
            PowerMeterCurrentL3Sensor(coordinator),
            PowerMeterEnergyImportSensor(coordinator),
        ])

    # Household sensors
    if DEVICE_HOUSEHOLD in coordinator.devices:
        entities.extend([
            HouseholdPowerSensor(coordinator),
            HouseholdEnergySensor(coordinator),
            HouseholdActivitySensor(coordinator),
            HouseholdPresenceModeSensor(coordinator),
            HouseholdBuildingTypeSensor(coordinator),
            HouseholdOccupantsSensor(coordinator),
        ])

    async_add_entities(entities)


# =============================================================================
# Water Heater Sensors
# =============================================================================


class WaterHeaterBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for water heater sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)

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


class WaterHeaterTemperatureSensor(WaterHeaterBaseSensor):
    """Water heater current temperature sensor."""

    _attr_name = "Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_water_heater_temperature"

    @property
    def native_value(self) -> float | None:
        """Return current temperature."""
        if self.coordinator.water_heater:
            return round(self.coordinator.water_heater.current_temp, 1)
        return None


class WaterHeaterPowerSensor(WaterHeaterBaseSensor):
    """Water heater power consumption sensor."""

    _attr_name = "Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_water_heater_power"

    @property
    def native_value(self) -> float | None:
        """Return current power."""
        if self.coordinator.water_heater:
            return self.coordinator.water_heater.power_w
        return None


class WaterHeaterEnergySensor(WaterHeaterBaseSensor):
    """Water heater cumulative energy sensor."""

    _attr_name = "Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_water_heater_energy"

    @property
    def native_value(self) -> float | None:
        """Return cumulative energy."""
        if self.coordinator.water_heater:
            return round(self.coordinator.water_heater.energy_kwh, 2)
        return None


# =============================================================================
# EV Charger Sensors
# =============================================================================


class EVChargerBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for EV charger sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)

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


class EVChargerPowerSensor(EVChargerBaseSensor):
    """EV charger power sensor."""

    _attr_name = "Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ev_charger_power"

    @property
    def native_value(self) -> float | None:
        """Return current power."""
        if self.coordinator.ev_charger:
            return round(self.coordinator.ev_charger.power_w, 0)
        return None


class EVChargerSessionEnergySensor(EVChargerBaseSensor):
    """EV charger session energy sensor."""

    _attr_name = "Session Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ev_charger_session_energy"

    @property
    def native_value(self) -> float | None:
        """Return session energy."""
        if self.coordinator.ev_charger:
            return round(self.coordinator.ev_charger.session_energy_kwh, 2)
        return None


class EVChargerTotalEnergySensor(EVChargerBaseSensor):
    """EV charger total energy sensor."""

    _attr_name = "Total Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ev_charger_total_energy"

    @property
    def native_value(self) -> float | None:
        """Return total energy."""
        if self.coordinator.ev_charger:
            return round(self.coordinator.ev_charger.total_energy_kwh, 2)
        return None


class EVChargerBatterySOCSensor(EVChargerBaseSensor):
    """EV charger battery state of charge sensor."""

    _attr_name = "Battery SOC"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ev_charger_battery_soc"

    @property
    def native_value(self) -> float | None:
        """Return battery SOC."""
        if self.coordinator.ev_charger:
            return round(self.coordinator.ev_charger.battery_soc, 0)
        return None


# =============================================================================
# Power Meter Sensors
# =============================================================================


class PowerMeterBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for power meter sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, "ams_meter")},
            name="Simulated AMS Meter",
            manufacturer=MANUFACTURER,
            model=AMS_METER_MODEL,
            sw_version="1.0.0",
        )


class PowerMeterPowerSensor(PowerMeterBaseSensor):
    """Power meter total power sensor."""

    _attr_name = "Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ams_meter_power"

    @property
    def native_value(self) -> float | None:
        """Return total power."""
        if self.coordinator.power_meter:
            return round(self.coordinator.power_meter.power_w, 0)
        return None


class PowerMeterVoltageL1Sensor(PowerMeterBaseSensor):
    """Power meter L1 voltage sensor."""

    _attr_name = "Voltage L1"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ams_meter_voltage_l1"

    @property
    def native_value(self) -> float | None:
        """Return L1 voltage."""
        if self.coordinator.power_meter:
            return round(self.coordinator.power_meter.voltage_l1, 1)
        return None


class PowerMeterVoltageL2Sensor(PowerMeterBaseSensor):
    """Power meter L2 voltage sensor."""

    _attr_name = "Voltage L2"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ams_meter_voltage_l2"

    @property
    def native_value(self) -> float | None:
        """Return L2 voltage."""
        if self.coordinator.power_meter:
            return round(self.coordinator.power_meter.voltage_l2, 1)
        return None


class PowerMeterVoltageL3Sensor(PowerMeterBaseSensor):
    """Power meter L3 voltage sensor."""

    _attr_name = "Voltage L3"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ams_meter_voltage_l3"

    @property
    def native_value(self) -> float | None:
        """Return L3 voltage."""
        if self.coordinator.power_meter:
            return round(self.coordinator.power_meter.voltage_l3, 1)
        return None


class PowerMeterCurrentL1Sensor(PowerMeterBaseSensor):
    """Power meter L1 current sensor."""

    _attr_name = "Current L1"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ams_meter_current_l1"

    @property
    def native_value(self) -> float | None:
        """Return L1 current."""
        if self.coordinator.power_meter:
            return round(self.coordinator.power_meter.current_l1, 1)
        return None


class PowerMeterCurrentL2Sensor(PowerMeterBaseSensor):
    """Power meter L2 current sensor."""

    _attr_name = "Current L2"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ams_meter_current_l2"

    @property
    def native_value(self) -> float | None:
        """Return L2 current."""
        if self.coordinator.power_meter:
            return round(self.coordinator.power_meter.current_l2, 1)
        return None


class PowerMeterCurrentL3Sensor(PowerMeterBaseSensor):
    """Power meter L3 current sensor."""

    _attr_name = "Current L3"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ams_meter_current_l3"

    @property
    def native_value(self) -> float | None:
        """Return L3 current."""
        if self.coordinator.power_meter:
            return round(self.coordinator.power_meter.current_l3, 1)
        return None


class PowerMeterEnergyImportSensor(PowerMeterBaseSensor):
    """Power meter energy import sensor."""

    _attr_name = "Energy Import"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_ams_meter_energy_import"

    @property
    def native_value(self) -> float | None:
        """Return energy import."""
        if self.coordinator.power_meter:
            return round(self.coordinator.power_meter.energy_import_kwh, 2)
        return None


# =============================================================================
# Household Sensors
# =============================================================================


class HouseholdBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for household sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, "household")},
            name="Simulated Household",
            manufacturer=MANUFACTURER,
            model=HOUSEHOLD_MODEL,
            sw_version="1.0.0",
        )


class HouseholdPowerSensor(HouseholdBaseSensor):
    """Household power consumption sensor."""

    _attr_name = "Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_household_power"

    @property
    def native_value(self) -> float | None:
        """Return current power."""
        if self.coordinator.household:
            return round(self.coordinator.household.power_w, 0)
        return None


class HouseholdEnergySensor(HouseholdBaseSensor):
    """Household cumulative energy sensor."""

    _attr_name = "Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_household_energy"

    @property
    def native_value(self) -> float | None:
        """Return cumulative energy."""
        if self.coordinator.household:
            return round(self.coordinator.household.energy_kwh, 2)
        return None


class HouseholdActivitySensor(HouseholdBaseSensor):
    """Household current activity sensor."""

    _attr_name = "Activity"
    _attr_icon = "mdi:home-automation"

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_household_activity"

    @property
    def native_value(self) -> str | None:
        """Return current activity."""
        if self.coordinator.household:
            return self.coordinator.household.activity
        return None


class HouseholdPresenceModeSensor(HouseholdBaseSensor):
    """Household presence mode sensor (read-only mirror of select)."""

    _attr_name = "Presence Mode Status"
    _attr_icon = "mdi:home-account"

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_household_presence_mode_status"

    @property
    def native_value(self) -> str | None:
        """Return current presence mode."""
        if self.coordinator.household:
            return self.coordinator.household.presence_mode
        return None


class HouseholdBuildingTypeSensor(HouseholdBaseSensor):
    """Household building type sensor (read-only mirror of select)."""

    _attr_name = "Building Type Status"
    _attr_icon = "mdi:home-variant"

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_household_building_type_status"

    @property
    def native_value(self) -> str | None:
        """Return current building type."""
        if self.coordinator.household:
            return self.coordinator.household.building_type
        return None


class HouseholdOccupantsSensor(HouseholdBaseSensor):
    """Household occupants count sensor."""

    _attr_name = "Occupants"
    _attr_icon = "mdi:account-group"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SimulationCoordinator) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_household_occupants"

    @property
    def native_value(self) -> int | None:
        """Return current occupants count."""
        if self.coordinator.household:
            return self.coordinator.household.occupants
        return None
