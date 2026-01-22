"""Sensor platform for Ampæra Energy integration.

When simulation mode is enabled, creates simulated device sensors:
- Water heater temperature, power, energy
- EV charger power, energy, SOC
- Power meter readings (3-phase)

When in real device mode, this platform is not used (devices are synced via push).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_INSTALLATION_MODE, DOMAIN, INSTALLATION_MODE_SIMULATION

if TYPE_CHECKING:
    from .simulation.coordinator import SimulationCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ampæra sensors from a config entry."""
    # Check if simulation mode is enabled
    installation_mode = entry.data.get(CONF_INSTALLATION_MODE)
    if installation_mode != INSTALLATION_MODE_SIMULATION:
        _LOGGER.debug("Sensor platform: not in simulation mode, skipping")
        return

    # Get simulation coordinator
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator: SimulationCoordinator | None = entry_data.get("coordinator")

    if coordinator is None:
        _LOGGER.warning("Sensor platform: simulation coordinator not found")
        return

    # Import and setup simulation sensors
    from .simulation.sensor import (
        EVChargerBatterySOCSensor,
        EVChargerPowerSensor,
        EVChargerSessionEnergySensor,
        EVChargerTotalEnergySensor,
        PowerMeterCurrentL1Sensor,
        PowerMeterCurrentL2Sensor,
        PowerMeterCurrentL3Sensor,
        PowerMeterEnergyImportSensor,
        PowerMeterPowerSensor,
        PowerMeterVoltageL1Sensor,
        PowerMeterVoltageL2Sensor,
        PowerMeterVoltageL3Sensor,
        WaterHeaterEnergySensor,
        WaterHeaterPowerSensor,
        WaterHeaterTemperatureSensor,
    )
    from .simulation.const import DEVICE_AMS_METER, DEVICE_EV_CHARGER, DEVICE_WATER_HEATER

    entities = []

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

    _LOGGER.info("Adding %d simulation sensor entities", len(entities))
    async_add_entities(entities)
