"""Switch platform for Ampæra Energy integration.

When simulation mode is enabled, creates simulated device switches:
- Water heater heating switch
- EV charger connected/charging switches
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
    """Set up Ampæra switches from a config entry."""
    # Check if simulation mode is enabled
    installation_mode = entry.data.get(CONF_INSTALLATION_MODE)
    if installation_mode != INSTALLATION_MODE_SIMULATION:
        _LOGGER.debug("Switch platform: not in simulation mode, skipping")
        return

    # Get simulation coordinator
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator: SimulationCoordinator | None = entry_data.get("coordinator")

    if coordinator is None:
        _LOGGER.warning("Switch platform: simulation coordinator not found")
        return

    # Import and setup simulation switches
    from .simulation.switch import (
        EVChargerChargingSwitch,
        EVChargerConnectedSwitch,
        WaterHeaterHeatingSwitch,
    )
    from .simulation.const import DEVICE_EV_CHARGER, DEVICE_WATER_HEATER

    entities = []

    # Water heater switches
    if DEVICE_WATER_HEATER in coordinator.devices:
        entities.append(WaterHeaterHeatingSwitch(coordinator))

    # EV charger switches
    if DEVICE_EV_CHARGER in coordinator.devices:
        entities.extend([
            EVChargerConnectedSwitch(coordinator),
            EVChargerChargingSwitch(coordinator),
        ])

    _LOGGER.info("Adding %d simulation switch entities", len(entities))
    async_add_entities(entities)
