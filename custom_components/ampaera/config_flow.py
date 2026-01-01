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
    ConfigFlowResult,
    OptionsFlow,
)
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
    CONF_ENABLE_VOLTAGE_SENSORS,
    CONF_GRID_REGION,
    CONF_HA_INSTANCE_ID,
    CONF_POLLING_INTERVAL,
    CONF_SELECTED_ENTITIES,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DEFAULT_API_BASE_URL,
    DEFAULT_COMMAND_POLL_INTERVAL,
    DEFAULT_DEVICE_SYNC_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    GRID_REGIONS,
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
                    # Move to location configuration
                    return await self.async_step_location()

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

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle site location configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._site_name = user_input.get(CONF_SITE_NAME, "Home")
            self._grid_region = user_input.get(CONF_GRID_REGION, "NO1")

            # Move to device selection
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
        """Handle device selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._selected_entities = user_input.get(CONF_SELECTED_ENTITIES, [])

            if not self._selected_entities:
                errors["base"] = "no_devices_selected"
            else:
                # Register site and devices on Ampæra
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
            discovery = AmperaDeviceDiscovery(self.hass)
            devices_to_register = discovery.get_devices_by_ids(self._selected_entities)

            device_data = [d.to_dict() for d in devices_to_register]

            # Register devices
            _LOGGER.info("Registering %d devices", len(device_data))
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
            return self.async_create_entry(
                title=self._site_name,
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_API_URL: self._api_url,
                    CONF_SITE_ID: self._site_id,
                    CONF_SITE_NAME: self._site_name,
                    CONF_GRID_REGION: self._grid_region,
                    CONF_HA_INSTANCE_ID: self._ha_instance_id,
                    CONF_SELECTED_ENTITIES: self._selected_entities,
                    CONF_DEVICE_MAPPINGS: self._device_mappings,
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

        # If we got here, there was an error - go back to devices step
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
        config_entry: ConfigEntry,  # noqa: ARG004 - required by HA
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return AmperaOptionsFlow()


class AmperaOptionsFlow(OptionsFlow):
    """Handle options flow for Ampæra Energy.

    Allows users to configure:
    - Telemetry push interval
    - Command polling interval
    - Voltage sensor visibility
    - Developer mode (simulation dashboard)
    """

    # Note: config_entry is provided by the base OptionsFlow class
    # Do NOT set self.config_entry in __init__ - it's a read-only property

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step of options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current options with defaults
        current_options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
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
                        CONF_ENABLE_VOLTAGE_SENSORS,
                        default=current_options.get(
                            CONF_ENABLE_VOLTAGE_SENSORS, False
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_DEV_MODE,
                        default=current_options.get(CONF_DEV_MODE, False),
                    ): bool,
                }
            ),
        )
