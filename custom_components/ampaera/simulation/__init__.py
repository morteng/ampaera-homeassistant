"""Embedded simulation module for Ampæra integration.

When simulation mode is selected during setup, this module creates
simulated smart home devices with proper device registry entries:
- Water Heater (200L, 3kW) - temperature control and physics simulation
- EV Charger (32A, single-phase) - charging simulation with SOC tracking
- AMS Power Meter (3-phase) - aggregated power readings

These entities appear directly in Home Assistant without requiring
a separate ampaera_sim integration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform

from .coordinator import SimulationCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# Simulation platforms
SIMULATION_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
    Platform.NUMBER,
    Platform.SELECT,
]

# Storage key for simulation data
SIMULATION_DATA_KEY = "simulation"


async def async_setup_simulation(
    hass: HomeAssistant,
    entry: ConfigEntry,
    devices: list[str] | None = None,
) -> SimulationCoordinator:
    """Set up simulation coordinator and entities.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        devices: List of device types to simulate. Defaults to all devices.

    Returns:
        The simulation coordinator instance.
    """
    if devices is None:
        devices = ["ams_meter", "water_heater", "ev_charger"]

    _LOGGER.info("Setting up Ampæra simulation with devices: %s", devices)

    # Get simulation options from config entry
    options = {
        "household_profile": entry.data.get("simulation_household_profile", "family"),
        "water_heater_type": entry.data.get("simulation_water_heater_type", "smart"),
    }

    # Create the simulation coordinator
    coordinator = SimulationCoordinator(hass, devices, options)

    # Perform initial data fetch
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.info(
        "Ampæra simulation started with %d device(s): %s",
        len(devices),
        ", ".join(devices),
    )

    return coordinator


async def async_unload_simulation(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,  # noqa: ARG001
) -> bool:
    """Unload simulation entities."""
    _LOGGER.info("Unloading Ampæra simulation")
    return True


async def async_setup_simulation_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    coordinator: SimulationCoordinator,
) -> None:
    """Set up simulation sensor entities."""
    from .sensor import async_setup_simulation_sensors as setup_sensors

    await setup_sensors(hass, entry, async_add_entities, coordinator)


async def async_setup_simulation_switches(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    coordinator: SimulationCoordinator,
) -> None:
    """Set up simulation switch entities."""
    from .switch import async_setup_simulation_switches as setup_switches

    await setup_switches(hass, entry, async_add_entities, coordinator)


async def async_setup_simulation_water_heaters(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    coordinator: SimulationCoordinator,
) -> None:
    """Set up simulation water heater entities."""
    from .water_heater import async_setup_simulation_water_heaters as setup_water_heaters

    await setup_water_heaters(hass, entry, async_add_entities, coordinator)


async def async_setup_simulation_numbers(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    coordinator: SimulationCoordinator,
) -> None:
    """Set up simulation number entities."""
    from .number import async_setup_simulation_numbers as setup_numbers

    await setup_numbers(hass, entry, async_add_entities, coordinator)


async def async_setup_simulation_selects(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    coordinator: SimulationCoordinator,
) -> None:
    """Set up simulation select entities."""
    from .select import async_setup_simulation_selects as setup_selects

    await setup_selects(hass, entry, async_add_entities, coordinator)
