"""Simulation services for Ampæra Energy integration.

Provides HA-side simulation controls that work with the existing
simulated_devices package. These services control the input_boolean
and input_number helpers defined in packages/simulated_devices.yaml.

Services:
- connect_ev: Set EV charger to connected state
- disconnect_ev: Set EV charger to disconnected state
- simulate_shower: Drop water heater temperature
- set_ev_charge_limit: Set charging current limit
- boost_water_heater: Set water heater to boost mode
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Service names
SERVICE_CONNECT_EV = "connect_ev"
SERVICE_DISCONNECT_EV = "disconnect_ev"
SERVICE_SIMULATE_SHOWER = "simulate_shower"
SERVICE_SET_EV_CHARGE_LIMIT = "set_ev_charge_limit"
SERVICE_BOOST_WATER_HEATER = "boost_water_heater"

# Service schemas - device_id is optional since we have single devices
CONNECT_EV_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Optional("battery_soc", default=30): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
    }
)

DISCONNECT_EV_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
    }
)

SIMULATE_SHOWER_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Optional("liters", default=50): vol.All(vol.Coerce(int), vol.Range(min=10, max=200)),
    }
)

SET_EV_CHARGE_LIMIT_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Required("current_limit"): vol.All(vol.Coerce(int), vol.Range(min=6, max=32)),
    }
)

BOOST_WATER_HEATER_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up simulation services that control existing HA helpers."""
    # Don't register if already registered
    if hass.services.has_service(DOMAIN, SERVICE_CONNECT_EV):
        return

    async def handle_connect_ev(call: ServiceCall) -> None:  # noqa: ARG001
        """Handle connect_ev service call.

        Sets input_boolean.ev_charger_connected to on and
        updates the charger status to 'Connected - Waiting'.
        """
        _LOGGER.info("Simulating EV connection")

        # Turn on the connected boolean
        await hass.services.async_call(
            "input_boolean",
            "turn_on",
            {"entity_id": "input_boolean.ev_charger_connected"},
        )

        # Set status to waiting
        await hass.services.async_call(
            "input_select",
            "select_option",
            {
                "entity_id": "input_select.ev_charger_status",
                "option": "Connected - Waiting",
            },
        )

        # Reset session energy
        await hass.services.async_call(
            "input_number",
            "set_value",
            {"entity_id": "input_number.ev_charger_session_energy", "value": 0},
        )

    async def handle_disconnect_ev(call: ServiceCall) -> None:  # noqa: ARG001
        """Handle disconnect_ev service call.

        Sets input_boolean.ev_charger_connected to off and
        stops any active charging.
        """
        _LOGGER.info("Simulating EV disconnection")

        # Turn off connected boolean (automation handles the rest)
        await hass.services.async_call(
            "input_boolean",
            "turn_off",
            {"entity_id": "input_boolean.ev_charger_connected"},
        )

    async def handle_simulate_shower(call: ServiceCall) -> None:
        """Handle simulate_shower service call.

        Drops water heater temperature based on liters used.
        Typical shower uses 40-60L of hot water.
        Also reports the shower event to the Ampæra backend.
        """
        liters = call.data.get("liters", 50)
        _LOGGER.info("Simulating shower usage: %d liters", liters)

        # Get current temperature
        current_temp_state = hass.states.get("input_number.water_heater_current_temp")
        if current_temp_state is None:
            _LOGGER.warning("Water heater temperature entity not found")
            return

        current_temp = float(current_temp_state.state)

        # Each liter of hot water drops temp by ~0.3-0.5C for 200L tank
        # Using 0.4C per liter as reasonable estimate
        temp_drop = liters * 0.4
        new_temp = max(20.0, current_temp - temp_drop)

        await hass.services.async_call(
            "input_number",
            "set_value",
            {"entity_id": "input_number.water_heater_current_temp", "value": new_temp},
        )

        _LOGGER.info(
            "Water heater temp dropped from %.1f°C to %.1f°C",
            current_temp,
            new_temp,
        )

        # Report shower event to Ampæra backend
        # Find the event service and water heater device ID from hass.data
        for entry_data in hass.data.get(DOMAIN, {}).values():
            if isinstance(entry_data, dict):
                event_service = entry_data.get("event_service")
                device_sync_service = entry_data.get("device_sync_service")

                if event_service and device_sync_service:
                    # Find water heater device ID from entity mappings
                    water_heater_device_id = None
                    for entity_id, mapping in device_sync_service.entity_mappings.items():
                        # Look for water heater entities
                        if "water_heater" in entity_id.lower():
                            water_heater_device_id = mapping.device_id
                            break

                    if water_heater_device_id:
                        try:
                            await event_service.report_shower_event(
                                device_id=water_heater_device_id,
                                liters=liters,
                                temp_drop=temp_drop,
                            )
                            _LOGGER.debug(
                                "Reported shower event for device %s",
                                water_heater_device_id,
                            )
                        except Exception as err:
                            _LOGGER.warning("Failed to report shower event: %s", err)
                    else:
                        _LOGGER.debug("No water heater device found for shower event reporting")
                    break  # Only report once

    async def handle_set_ev_charge_limit(call: ServiceCall) -> None:
        """Handle set_ev_charge_limit service call.

        Sets input_number.ev_charger_current_limit to the specified value.
        """
        current_limit = call.data["current_limit"]
        _LOGGER.info("Setting EV charge limit to %dA", current_limit)

        await hass.services.async_call(
            "input_number",
            "set_value",
            {
                "entity_id": "input_number.ev_charger_current_limit",
                "value": current_limit,
            },
        )

        # If currently charging, update the power based on new limit
        charging_state = hass.states.get("input_boolean.ev_charger_charging")
        if charging_state and charging_state.state == "on":
            # Power = Current * Voltage (single phase)
            new_power = current_limit * 230
            await hass.services.async_call(
                "input_number",
                "set_value",
                {"entity_id": "input_number.ev_charger_power", "value": new_power},
            )

    async def handle_boost_water_heater(call: ServiceCall) -> None:  # noqa: ARG001
        """Handle boost_water_heater service call.

        Sets water heater to boost mode (75°C target).
        """
        _LOGGER.info("Activating water heater boost mode")

        # Set mode to Boost
        await hass.services.async_call(
            "input_select",
            "select_option",
            {"entity_id": "input_select.water_heater_mode", "option": "Boost"},
        )

        # Set target temperature to 75°C
        await hass.services.async_call(
            "input_number",
            "set_value",
            {"entity_id": "input_number.water_heater_target_temp", "value": 75},
        )

        # Turn on heating
        await hass.services.async_call(
            "input_boolean",
            "turn_on",
            {"entity_id": "input_boolean.water_heater_heating"},
        )

        # Set power to max
        await hass.services.async_call(
            "input_number",
            "set_value",
            {"entity_id": "input_number.water_heater_power", "value": 3000},
        )

    # Register all simulation services
    hass.services.async_register(
        DOMAIN, SERVICE_CONNECT_EV, handle_connect_ev, schema=CONNECT_EV_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DISCONNECT_EV, handle_disconnect_ev, schema=DISCONNECT_EV_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SIMULATE_SHOWER,
        handle_simulate_shower,
        schema=SIMULATE_SHOWER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_EV_CHARGE_LIMIT,
        handle_set_ev_charge_limit,
        schema=SET_EV_CHARGE_LIMIT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BOOST_WATER_HEATER,
        handle_boost_water_heater,
        schema=BOOST_WATER_HEATER_SCHEMA,
    )

    _LOGGER.info("Ampæra simulation services registered")


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload simulation services."""
    # Only unload if no entries remain
    if hass.data.get(DOMAIN):
        return

    services_to_remove = [
        SERVICE_CONNECT_EV,
        SERVICE_DISCONNECT_EV,
        SERVICE_SIMULATE_SHOWER,
        SERVICE_SET_EV_CHARGE_LIMIT,
        SERVICE_BOOST_WATER_HEATER,
    ]

    for service in services_to_remove:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)

    _LOGGER.info("Ampæra simulation services unloaded")
