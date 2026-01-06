"""Config flow for Ampæra Energy integration (v2.0 Push Architecture).

Handles the setup wizard for adding the integration to Home Assistant:
1. User enters API key
2. User configures site (name, grid region)
3. User selects which HA devices to sync
4. Integration registers site and devices on Ampæra
5. Integration starts push services
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)

# ConfigFlowResult was added in HA 2024.5+, use FlowResult for older versions
try:
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AmperaApiClient,
    AmperaAuthError,
    AmperaConnectionError,
)
from .const import (
    CONF_API_KEY,
    CONF_API_URL,
    CONF_COMMAND_POLL_INTERVAL,
    CONF_DEV_MODE,
    CONF_DEVICE_MAPPINGS,
    CONF_DEVICE_SYNC_INTERVAL,
    CONF_ENABLE_SIMULATION,
    CONF_ENABLE_VOLTAGE_SENSORS,
    CONF_GRID_REGION,
    CONF_HA_INSTANCE_ID,
    CONF_INSTALLATION_MODE,
    CONF_POLLING_INTERVAL,
    CONF_SELECTED_ENTITIES,
    CONF_SIMULATION_HOUSEHOLD_PROFILE,
    CONF_SIMULATION_WATER_HEATER_TYPE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DEFAULT_API_BASE_URL,
    DEFAULT_COMMAND_POLL_INTERVAL,
    DEFAULT_DEVICE_SYNC_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    GRID_REGIONS,
    INSTALLATION_MODE_REAL,
    INSTALLATION_MODE_SIMULATION,
    INSTALLATION_MODES,
    SIMULATION_PROFILES,
    SIMULATION_WH_TYPES,
)
from .device_discovery import AmperaDeviceDiscovery

_LOGGER = logging.getLogger(__name__)


def _generate_ha_instance_id() -> str:
    """Generate a unique HA instance ID."""
    return str(uuid.uuid4())[:12]


class AmperaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ampæra Energy.

    The flow (v2.0 Push Architecture):
    1. user step: Enter API key
    2. location step: Configure site (name, grid region)
    3. devices step: Select HA devices to sync
    4. Register site and devices on Ampæra
    """

    VERSION = 2  # Bump version for new config structure

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api_key: str | None = None
        self._api_url: str = DEFAULT_API_BASE_URL
        self._site_name: str = "Home"
        self._grid_region: str = "NO1"
        self._ha_instance_id: str = _generate_ha_instance_id()
        self._discovered_devices: list[dict] = []
        self._selected_entities: list[str] = []
        self._site_id: str | None = None
        self._device_mappings: dict[str, str] = {}
        # Installation mode - mutually exclusive: "real" or "simulation"
        self._installation_mode: str = INSTALLATION_MODE_REAL
        # Simulation options (only used in simulation mode)
        self._enable_simulation: bool = False
        self._simulation_profile: str = "family"
        self._simulation_wh_type: str = "smart"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - API key entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            # Get API URL (optional, defaults to production)
            api_url = user_input.get(CONF_API_URL, DEFAULT_API_BASE_URL)
            if not api_url:
                api_url = DEFAULT_API_BASE_URL

            _LOGGER.info("Validating API key against %s...", api_url)

            # Validate the API key
            client = AmperaApiClient(api_key, base_url=api_url)
            try:
                # Just validate the token works
                valid = await client.async_validate_token()
                if not valid:
                    errors["base"] = "invalid_auth"
                else:
                    self._api_key = api_key
                    self._api_url = api_url
                    # Move to installation mode selection
                    return await self.async_step_mode()

            except AmperaAuthError as e:
                _LOGGER.error("Auth error: %s", e)
                errors["base"] = "invalid_auth"
            except AmperaConnectionError as e:
                _LOGGER.error("Connection error: %s", e)
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.exception("Unexpected error during API validation: %s", e)
                errors["base"] = "unknown"
            finally:
                await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_API_URL, default=""): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.URL,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"default_url": DEFAULT_API_BASE_URL},
        )

    async def async_step_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle installation mode selection.

        Users must choose between:
        - Real Devices: For production use with actual physical devices
        - Simulation: For demos and testing with simulated devices

        These modes are mutually exclusive to prevent mixing simulated
        and real devices in the same installation.
        """
        if user_input is not None:
            self._installation_mode = user_input.get(
                CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL
            )
            # Move to location configuration
            return await self.async_step_location()

        # Build mode options
        mode_options = [
            SelectOptionDict(value=code, label=name)
            for code, name in INSTALLATION_MODES
        ]

        return self.async_show_form(
            step_id="mode",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INSTALLATION_MODE, default=INSTALLATION_MODE_REAL
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=mode_options,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle site location configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._site_name = user_input.get(CONF_SITE_NAME, "Home")
            self._grid_region = user_input.get(CONF_GRID_REGION, "NO1")

            # Route based on installation mode
            if self._installation_mode == INSTALLATION_MODE_SIMULATION:
                # Simulation mode: skip device discovery, go to simulation options
                return await self.async_step_simulation()
            else:
                # Real device mode: go to device selection
                return await self.async_step_devices()

        # Get HA location info if available
        ha_location = self.hass.config.location_name or "Home"

        # Build grid region options
        region_options = [
            SelectOptionDict(value=code, label=name)
            for code, name in GRID_REGIONS
        ]

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SITE_NAME, default=ha_location): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_GRID_REGION, default="NO1"): SelectSelector(
                        SelectSelectorConfig(
                            options=region_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle device selection step (only in Real Device mode)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._selected_entities = user_input.get(CONF_SELECTED_ENTITIES, [])

            if not self._selected_entities:
                errors["base"] = "no_devices_selected"
            else:
                # In real mode, go directly to registration (no simulation)
                self._enable_simulation = False
                return await self._async_register_and_complete()

        # Discover devices
        discovery = AmperaDeviceDiscovery(self.hass)
        self._discovered_devices = discovery.discover_devices()

        if not self._discovered_devices:
            errors["base"] = "no_devices_found"
            # Still show the form so user can go back
            return self.async_show_form(
                step_id="devices",
                data_schema=vol.Schema({}),
                errors=errors,
                description_placeholders={"device_count": "0"},
            )

        # Build device options (use ha_device_id for device-based selection)
        device_options = [
            SelectOptionDict(
                value=device.ha_device_id,
                label=f"{device.name} ({device.device_type.value}) - {len(device.capabilities)} sensors",
            )
            for device in self._discovered_devices
        ]

        # Pre-select all devices by default
        default_selection = [d.ha_device_id for d in self._discovered_devices]

        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SELECTED_ENTITIES, default=default_selection
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=device_options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "device_count": str(len(self._discovered_devices))
            },
        )

    async def async_step_simulation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle simulation configuration step (only in Simulation mode).

        In simulation mode, this configures the simulated household:
        - Household profile (affects consumption patterns)
        - Water heater type (dumb vs smart)

        No device discovery happens - devices are created by simulation.
        """
        if user_input is not None:
            # In simulation mode, simulation is always enabled
            self._enable_simulation = True
            self._simulation_profile = user_input.get(
                CONF_SIMULATION_HOUSEHOLD_PROFILE, "family"
            )
            self._simulation_wh_type = user_input.get(
                CONF_SIMULATION_WATER_HEATER_TYPE, "smart"
            )

            # No devices selected in simulation mode - simulation creates them
            self._selected_entities = []

            # Proceed to registration
            return await self._async_register_and_complete()

        # Build profile options
        profile_options = [
            SelectOptionDict(value=code, label=name)
            for code, name in SIMULATION_PROFILES
        ]

        # Build water heater type options
        wh_type_options = [
            SelectOptionDict(value=code, label=name)
            for code, name in SIMULATION_WH_TYPES
        ]

        # In simulation mode, show configuration without enable checkbox
        # (simulation is always enabled when this step is shown)
        return self.async_show_form(
            step_id="simulation",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SIMULATION_HOUSEHOLD_PROFILE, default="family"
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=profile_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_SIMULATION_WATER_HEATER_TYPE, default="smart"
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=wh_type_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def _async_register_and_complete(self) -> ConfigFlowResult:
        """Register site and devices on Ampæra and complete setup."""
        errors: dict[str, str] = {}

        client = AmperaApiClient(self._api_key, base_url=self._api_url)
        try:
            # Register site
            _LOGGER.info(
                "Registering site '%s' with grid region %s",
                self._site_name,
                self._grid_region,
            )
            site_response = await client.async_register_site(
                name=self._site_name,
                ha_instance_id=self._ha_instance_id,
                grid_region=self._grid_region,
                city=self.hass.config.location_name,
                timezone=str(self.hass.config.time_zone),
            )
            self._site_id = site_response["site_id"]
            _LOGGER.info("Registered site: %s", self._site_id)

            # Prepare device data for registration
            # In simulation mode, no devices are selected - simulation creates them
            if self._selected_entities:
                discovery = AmperaDeviceDiscovery(self.hass)
                devices_to_register = discovery.get_devices_by_ids(
                    self._selected_entities
                )
                device_data = [d.to_dict() for d in devices_to_register]
            else:
                device_data = []

            # Register devices (may be empty in simulation mode)
            _LOGGER.info(
                "Registering %d devices (mode: %s)",
                len(device_data),
                self._installation_mode,
            )
            devices_response = await client.async_register_devices(
                site_id=self._site_id,
                devices=device_data,
            )
            self._device_mappings = devices_response["device_mappings"]
            _LOGGER.info(
                "Registered %d devices", devices_response["registered"]
            )

            # Check if already configured (by HA instance ID)
            await self.async_set_unique_id(self._ha_instance_id)
            self._abort_if_unique_id_configured()

            # Create the config entry
            # Include installation mode badge in title for clarity
            title_suffix = " (Simulation)" if self._installation_mode == INSTALLATION_MODE_SIMULATION else ""
            return self.async_create_entry(
                title=f"{self._site_name}{title_suffix}",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_API_URL: self._api_url,
                    CONF_SITE_ID: self._site_id,
                    CONF_SITE_NAME: self._site_name,
                    CONF_GRID_REGION: self._grid_region,
                    CONF_HA_INSTANCE_ID: self._ha_instance_id,
                    CONF_SELECTED_ENTITIES: self._selected_entities,
                    CONF_DEVICE_MAPPINGS: self._device_mappings,
                    # Installation mode - mutually exclusive
                    CONF_INSTALLATION_MODE: self._installation_mode,
                    # Simulation config (only used in simulation mode)
                    CONF_ENABLE_SIMULATION: self._enable_simulation,
                    CONF_SIMULATION_HOUSEHOLD_PROFILE: self._simulation_profile,
                    CONF_SIMULATION_WATER_HEATER_TYPE: self._simulation_wh_type,
                },
            )

        except AmperaAuthError as e:
            _LOGGER.error("Auth error during registration: %s", e)
            errors["base"] = "invalid_auth"
        except AmperaConnectionError as e:
            _LOGGER.error("Connection error during registration: %s", e)
            errors["base"] = "cannot_connect"
        except Exception as e:
            _LOGGER.exception("Failed to register: %s", e)
            errors["base"] = "registration_failed"
        finally:
            await client.close()

        # If we got here, there was an error - go back to appropriate step
        if self._installation_mode == INSTALLATION_MODE_SIMULATION:
            return await self.async_step_simulation()
        else:
            return await self.async_step_devices()

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]

            client = AmperaApiClient(api_key)
            try:
                valid = await client.async_validate_token()
                if not valid:
                    errors["base"] = "invalid_auth"
                else:
                    # Update the existing entry
                    reauth_entry = self._get_reauth_entry()
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data={**reauth_entry.data, CONF_API_KEY: api_key},
                    )

            except AmperaAuthError:
                errors["base"] = "invalid_auth"
            except AmperaConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reauthentication")
                errors["base"] = "unknown"
            finally:
                await client.close()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return AmperaOptionsFlow(config_entry)


class AmperaOptionsFlow(OptionsFlow):
    """Handle options flow for Ampæra Energy.

    Options available depend on installation mode:
    - Real Device Mode: Polling intervals, voltage sensors, dev mode
    - Simulation Mode: Household profile, water heater type

    Installation mode cannot be changed after setup - users must
    reconfigure the integration to switch modes.
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    @property
    def config_entry(self) -> ConfigEntry:
        """Return the config entry for this flow."""
        return self._config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step of options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current options with defaults (check both options and data)
        current_options = self.config_entry.options
        entry_data = self.config_entry.data

        # Check installation mode
        installation_mode = entry_data.get(
            CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL
        )
        is_simulation_mode = installation_mode == INSTALLATION_MODE_SIMULATION

        # Build common schema fields (available in both modes)
        schema_fields: dict[vol.Marker, Any] = {
            vol.Optional(
                CONF_POLLING_INTERVAL,
                default=current_options.get(
                    CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            vol.Optional(
                CONF_COMMAND_POLL_INTERVAL,
                default=current_options.get(
                    CONF_COMMAND_POLL_INTERVAL, DEFAULT_COMMAND_POLL_INTERVAL
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
            vol.Optional(
                CONF_DEVICE_SYNC_INTERVAL,
                default=current_options.get(
                    CONF_DEVICE_SYNC_INTERVAL, DEFAULT_DEVICE_SYNC_INTERVAL
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
            vol.Optional(
                CONF_DEV_MODE,
                default=current_options.get(CONF_DEV_MODE, False),
            ): bool,
        }

        # Add mode-specific options
        if is_simulation_mode:
            # Simulation mode: show simulation options (always enabled)
            profile_options = [
                SelectOptionDict(value=code, label=name)
                for code, name in SIMULATION_PROFILES
            ]
            wh_type_options = [
                SelectOptionDict(value=code, label=name)
                for code, name in SIMULATION_WH_TYPES
            ]

            schema_fields[vol.Optional(
                CONF_SIMULATION_HOUSEHOLD_PROFILE,
                default=current_options.get(
                    CONF_SIMULATION_HOUSEHOLD_PROFILE,
                    entry_data.get(CONF_SIMULATION_HOUSEHOLD_PROFILE, "family"),
                ),
            )] = SelectSelector(
                SelectSelectorConfig(
                    options=profile_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
            schema_fields[vol.Optional(
                CONF_SIMULATION_WATER_HEATER_TYPE,
                default=current_options.get(
                    CONF_SIMULATION_WATER_HEATER_TYPE,
                    entry_data.get(CONF_SIMULATION_WATER_HEATER_TYPE, "smart"),
                ),
            )] = SelectSelector(
                SelectSelectorConfig(
                    options=wh_type_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            # Real device mode: show voltage sensor option
            schema_fields[vol.Optional(
                CONF_ENABLE_VOLTAGE_SENSORS,
                default=current_options.get(CONF_ENABLE_VOLTAGE_SENSORS, False),
            )] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_fields),
        )
