"""Config flow for Ampæra Simulation integration.

Provides a UI for selecting which devices to simulate.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_DEVICES,
    DEVICE_AMS_METER,
    DEVICE_EV_CHARGER,
    DEVICE_HOUSEHOLD,
    DEVICE_WATER_HEATER,
    DOMAIN,
)


class AmperaSimConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ampæra Simulation.

    Allows users to select which devices to simulate:
    - Water Heater (200L)
    - EV Charger (32A)
    - AMS Power Meter
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - select devices to simulate."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate that at least one device is selected
            devices = user_input.get(CONF_DEVICES, [])
            if not devices:
                errors["base"] = "no_devices_selected"
            else:
                # Create the config entry
                return self.async_create_entry(
                    title="Ampæra Simulation",
                    data={CONF_DEVICES: devices},
                )

        # Show the form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICES,
                        default=[DEVICE_WATER_HEATER, DEVICE_EV_CHARGER, DEVICE_HOUSEHOLD, DEVICE_AMS_METER],
                    ): cv.multi_select(
                        {
                            DEVICE_WATER_HEATER: "Water Heater (200L, 2kW)",
                            DEVICE_EV_CHARGER: "EV Charger (32A, Single-phase)",
                            DEVICE_HOUSEHOLD: "Household Load (Appliances, Lights, etc.)",
                            DEVICE_AMS_METER: "AMS Power Meter (3-phase)",
                        }
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_import(
        self, import_data: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle import from ampaera integration (automatic setup).

        This is called when the ampaera integration has simulation mode enabled
        and automatically creates the ampaera_sim config entry.
        """
        # Check if already configured
        await self.async_set_unique_id("ampaera_sim_auto")
        self._abort_if_unique_id_configured()

        # Use provided devices or default to all
        devices = (import_data or {}).get(
            CONF_DEVICES,
            [DEVICE_WATER_HEATER, DEVICE_EV_CHARGER, DEVICE_HOUSEHOLD, DEVICE_AMS_METER],
        )

        return self.async_create_entry(
            title="Ampæra Simulation",
            data={CONF_DEVICES: devices},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            devices = user_input.get(CONF_DEVICES, [])
            if not devices:
                errors["base"] = "no_devices_selected"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates={CONF_DEVICES: devices},
                )

        # Get current devices from existing entry
        entry = self._get_reconfigure_entry()
        current_devices = entry.data.get(CONF_DEVICES, [])

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEVICES,
                        default=current_devices,
                    ): cv.multi_select(
                        {
                            DEVICE_WATER_HEATER: "Water Heater (200L, 2kW)",
                            DEVICE_EV_CHARGER: "EV Charger (32A, Single-phase)",
                            DEVICE_HOUSEHOLD: "Household Load (Appliances, Lights, etc.)",
                            DEVICE_AMS_METER: "AMS Power Meter (3-phase)",
                        }
                    ),
                }
            ),
            errors=errors,
        )
