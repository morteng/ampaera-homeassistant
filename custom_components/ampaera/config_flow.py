"""Config flow for Ampæra Energy integration (v2.0 Push Architecture).

Handles the setup wizard for adding the integration to Home Assistant:
1. User chooses authentication method (OAuth or API key)
2. User authenticates (OAuth flow or API key entry)
3. User configures site (name, grid region)
4. User selects which HA devices to sync
5. Integration registers site and devices on Ampæra
6. Integration starts push services
7. Optional: Auto-creates Lovelace dashboard

OAuth2 is the recommended authentication method - it's simpler for users.
API key is available as a fallback for advanced users or local setups.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    OptionsFlow,
)
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2FlowHandler,
    async_register_implementation,
)

# ConfigFlowResult was added in HA 2024.5+, use FlowResult for older versions
try:
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
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
from .application_credentials import AmperaOAuth2Implementation
from .const import (
    AUTH_METHOD_API_KEY,
    AUTH_METHOD_OAUTH,
    CAPABILITY_USAGE,
    CONF_API_KEY,
    CONF_API_URL,
    CONF_AUTH_METHOD,
    CONF_COMMAND_POLL_INTERVAL,
    CONF_DEV_MODE,
    CONF_DEVICE_MAPPINGS,
    CONF_DEVICE_SYNC_INTERVAL,
    CONF_ENABLE_SIMULATION,
    CONF_ENABLE_VOLTAGE_SENSORS,
    CONF_GRID_REGION,
    CONF_HA_INSTANCE_ID,
    CONF_INSTALLATION_MODE,
    CONF_OAUTH_REFRESH_TOKEN,
    CONF_OAUTH_TOKEN,
    CONF_POLLING_INTERVAL,
    CONF_SELECTED_ENTITIES,
    CONF_SENSOR_STREAM_ENTITIES,
    CONF_SHOW_ALL_DEVICES,
    CONF_SENSOR_STREAM_INTERVAL,
    CONF_SIMULATION_HOUSEHOLD_PROFILE,
    CONF_SIMULATION_WATER_HEATER_TYPE,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DEFAULT_API_BASE_URL,
    DEFAULT_COMMAND_POLL_INTERVAL,
    DEFAULT_DEVICE_SYNC_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_SENSOR_STREAM_INTERVAL,
    DOMAIN,
    GRID_REGIONS,
    INSTALLATION_MODE_REAL,
    INSTALLATION_MODE_SIMULATION,
    INSTALLATION_MODES,
    SIMULATION_PROFILES,
    SIMULATION_WH_TYPES,
)
from .discovery import (
    AmperaDeviceType,
    DiscoveredDevice,
    DiscoveryOrchestrator,
)
from .discovery.models import AmperaCapability
from .discovery.grouping import (
    DeviceGroup,
    collapse_to_group_ids,
    expand_group_selections,
    group_similar_devices,
)

_LOGGER = logging.getLogger(__name__)

# Authentication method options for config flow
AUTH_METHODS = [
    (AUTH_METHOD_OAUTH, "Connect with Ampæra Account (Recommended)"),
    (AUTH_METHOD_API_KEY, "Use API Key (Advanced)"),
]


def _generate_ha_instance_id() -> str:
    """Generate a unique HA instance ID."""
    return str(uuid.uuid4())[:12]


# Norwegian display labels for device types, shown in the picker.
_DEVICE_TYPE_LABELS: dict[AmperaDeviceType, str] = {
    AmperaDeviceType.POWER_METER: "strømmåler",
    AmperaDeviceType.EV_CHARGER: "elbillader",
    AmperaDeviceType.WATER_HEATER: "varmtvannsbereder",
    AmperaDeviceType.CLIMATE: "klima",
    AmperaDeviceType.SENSOR: "sensor",
    AmperaDeviceType.SWITCH: "bryter",
}

# Display order for grouping in the picker. Lower = shown first.
_DEVICE_TYPE_ORDER: dict[AmperaDeviceType, int] = {
    AmperaDeviceType.POWER_METER: 0,
    AmperaDeviceType.EV_CHARGER: 1,
    AmperaDeviceType.WATER_HEATER: 2,
    AmperaDeviceType.CLIMATE: 3,
    AmperaDeviceType.SENSOR: 4,
    AmperaDeviceType.SWITCH: 5,
}


_CAPABILITY_SUMMARY_LABELS: dict[AmperaCapability, str] = {
    AmperaCapability.POWER: "effekt",
    AmperaCapability.POWER_L1: "effekt L1",
    AmperaCapability.POWER_L2: "effekt L2",
    AmperaCapability.POWER_L3: "effekt L3",
    AmperaCapability.ENERGY: "energi",
    AmperaCapability.ENERGY_IMPORT: "import",
    AmperaCapability.ENERGY_EXPORT: "eksport",
    AmperaCapability.ENERGY_HOUR: "time-energi",
    AmperaCapability.ENERGY_DAY: "dag-energi",
    AmperaCapability.ENERGY_MONTH: "måned-energi",
    AmperaCapability.VOLTAGE: "spenning",
    AmperaCapability.VOLTAGE_L1: "spenning L1",
    AmperaCapability.VOLTAGE_L2: "spenning L2",
    AmperaCapability.VOLTAGE_L3: "spenning L3",
    AmperaCapability.CURRENT: "strøm",
    AmperaCapability.CURRENT_L1: "strøm L1",
    AmperaCapability.CURRENT_L2: "strøm L2",
    AmperaCapability.CURRENT_L3: "strøm L3",
    AmperaCapability.TEMPERATURE: "temperatur",
    AmperaCapability.TARGET_TEMPERATURE: "måltemp.",
    AmperaCapability.HUMIDITY: "fuktighet",
    AmperaCapability.ON_OFF: "på/av",
    AmperaCapability.CHARGE_LIMIT: "ladegrense",
    AmperaCapability.SESSION_ENERGY: "økt-energi",
    AmperaCapability.COST_DAY: "dagskost",
    AmperaCapability.PEAK_MONTH_1: "måned-peak 1",
    AmperaCapability.PEAK_MONTH_2: "måned-peak 2",
    AmperaCapability.PEAK_MONTH_3: "måned-peak 3",
}


def _collapse_capability_labels(caps: list[AmperaCapability]) -> list[str]:
    """Group 3-phase variants into single 'X (3-fase)' entries.

    Without collapsing, a 3-phase power meter would render six items in the
    picker summary (power_l1/l2/l3 + voltage_l1/l2/l3) and push the label
    past the 80-char picker width. Rolf wants to see *what* capabilities
    a device has, not every phase restated.
    """
    groups: dict[str, list[AmperaCapability]] = {
        "power_phase": [AmperaCapability.POWER_L1, AmperaCapability.POWER_L2, AmperaCapability.POWER_L3],
        "voltage_phase": [AmperaCapability.VOLTAGE_L1, AmperaCapability.VOLTAGE_L2, AmperaCapability.VOLTAGE_L3],
        "current_phase": [AmperaCapability.CURRENT_L1, AmperaCapability.CURRENT_L2, AmperaCapability.CURRENT_L3],
    }
    cap_set = set(caps)
    labels: list[str] = []
    consumed: set[AmperaCapability] = set()
    for group_caps in groups.values():
        present = [c for c in group_caps if c in cap_set]
        if len(present) >= 2:
            # Use the base name from the first member (e.g. "effekt L1" -> "effekt")
            base = _CAPABILITY_SUMMARY_LABELS.get(present[0], present[0].value).rsplit(" ", 1)[0]
            labels.append(f"{base} ({len(present)}-fase)")
            consumed.update(present)
    for cap in caps:
        if cap in consumed:
            continue
        labels.append(_CAPABILITY_SUMMARY_LABELS.get(cap, cap.value.replace("_", " ")))
    return labels


def _count_measurements(device: DiscoveredDevice) -> tuple[int, int]:
    """Return (mapped, total) measurement counts for a device.

    ``mapped`` is the number of entities that classified into an Ampæra
    capability — these are what actually reach the backend. ``total`` is
    the number of enabled HA entities scanned for the device. The gap
    between them is the entities HA exposes that Ampæra does not ingest
    (reactive power, frequency, power factor, vendor-specific counters…).

    Showing both numbers in the picker lets Rolf see at a glance that
    e.g. the AMS reader has 17 HA sensors but only 12 flow into Ampæra,
    instead of silently dropping the delta.
    """
    total = sum(1 for e in device.entities if e.enabled)
    mapped = len(device.entity_mapping)
    return mapped, total


def _format_measurement_count(mapped: int, total: int) -> str:
    """Render "M av N målinger" / "M målinger" depending on whether any were dropped."""
    if total > mapped:
        return f"{mapped} av {total} målinger"
    return f"{mapped} målinger"


def _format_device_label(device: DiscoveredDevice) -> str:
    """Render the picker label for a single device.

    Shows a compact capability summary ("effekt (3-fase), temperatur, energi")
    alongside a mapped/total measurement count so Rolf can tell at a glance
    both *what* each device reports and *how much* of its HA data actually
    flows into Ampæra.
    """
    type_label = _DEVICE_TYPE_LABELS.get(device.device_type, device.device_type.value)
    cap_labels = _collapse_capability_labels(device.capabilities)
    if not cap_labels:
        summary = "ingen sensorer"
    elif len(cap_labels) <= 3:
        summary = ", ".join(cap_labels)
    else:
        summary = f"{', '.join(cap_labels[:3])} +{len(cap_labels) - 3}"
    mapped, total = _count_measurements(device)
    count_str = _format_measurement_count(mapped, total)
    return f"{device.display_name()} – {type_label}, {count_str} · {summary}"


def _format_group_label(
    group: DeviceGroup, members: list[DiscoveredDevice] | None = None
) -> str:
    """Render the picker label for a device group.

    ``members`` optionally supplies the DiscoveredDevice instances this group
    contains so the label can list capability summaries and a rollup of
    mapped/total measurement counts alongside the device count.
    """
    type_label = _DEVICE_TYPE_LABELS.get(group.device_type, group.device_type.value)
    unit_word = "enhet" if group.count == 1 else "enheter"
    cap_union: list[AmperaCapability] = []
    total_mapped = 0
    total_scanned = 0
    if members:
        seen: set[AmperaCapability] = set()
        for member in members:
            for cap in member.capabilities:
                if cap not in seen:
                    seen.add(cap)
                    cap_union.append(cap)
            m, t = _count_measurements(member)
            total_mapped += m
            total_scanned += t
    cap_labels = _collapse_capability_labels(cap_union) if cap_union else []
    count_suffix = ""
    if total_scanned:
        count_suffix = f" · {_format_measurement_count(total_mapped, total_scanned)}"
    if cap_labels:
        summary = ", ".join(cap_labels[:3])
        if len(cap_labels) > 3:
            summary += f" +{len(cap_labels) - 3}"
        return (
            f"{group.base_name} – {type_label}, {group.count} {unit_word}"
            f"{count_suffix} · {summary}"
        )
    return f"{group.base_name} – {type_label}, {group.count} {unit_word}{count_suffix} (gruppert)"


def _build_device_picker_options(
    devices: list[DiscoveredDevice],
    show_all: bool,
) -> tuple[list[SelectOptionDict], list[str], list[DeviceGroup]]:
    """Build picker options + recommended default selection.

    Filters out non-energy devices unless ``show_all=True``, sorts by
    device type (power meters first, switches last), and uses the
    cleaned ``display_name()`` rather than the raw HA name.

    When ``show_all`` is False we also collapse clusters of near-identical
    devices (same base name, type, and model) into a single group option —
    this keeps multi-channel meters like em16 from flooding the picker
    with 18 almost-identical rows. When ``show_all`` is True we disable
    grouping so advanced users can cherry-pick individual channels.

    Returns:
        (options, default_selection, groups) — ``options`` is ready to
        hand to ``SelectSelectorConfig``, ``default_selection`` is a list
        of option values (device IDs and/or group IDs) to pre-check, and
        ``groups`` is the grouping metadata needed to expand submissions
        back to member device IDs.
    """
    visible = [d for d in devices if show_all or d.is_energy_relevant]
    visible.sort(
        key=lambda d: (
            _DEVICE_TYPE_ORDER.get(d.device_type, 99),
            d.display_name().lower(),
        )
    )

    if show_all:
        groups: list[DeviceGroup] = []
        ungrouped = visible
    else:
        groups, ungrouped = group_similar_devices(visible)
        groups.sort(
            key=lambda g: (
                _DEVICE_TYPE_ORDER.get(g.device_type, 99),
                g.base_name.lower(),
            )
        )

    options: list[SelectOptionDict] = []
    # Lookup table for resolving group.member_ids -> DiscoveredDevice so
    # group labels can include a capability summary, not just the count.
    device_by_id = {d.ha_device_id: d for d in visible}
    # Groups render first within each device type so the meaningful
    # rollups are at the top of the list.
    for group in groups:
        members = [device_by_id[mid] for mid in group.member_ids if mid in device_by_id]
        options.append(
            SelectOptionDict(
                value=group.group_id, label=_format_group_label(group, members)
            )
        )
    for device in ungrouped:
        options.append(
            SelectOptionDict(
                value=device.ha_device_id, label=_format_device_label(device)
            )
        )

    default_selection: list[str] = [g.group_id for g in groups if g.is_recommended]
    default_selection.extend(d.ha_device_id for d in ungrouped if d.is_recommended)
    return options, default_selection, groups


class AmperaOAuth2FlowHandler(AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Handle OAuth2 config flow for Ampæra Energy.

    Uses Home Assistant's built-in OAuth2 flow handler which properly
    manages state, PKCE, and callback routing.
    """

    DOMAIN = DOMAIN

    def __init__(self) -> None:
        """Initialize the OAuth2 flow handler."""
        super().__init__()
        # Site configuration
        self._site_name: str = "Home"
        self._grid_region: str = "NO1"
        self._ha_instance_id: str = _generate_ha_instance_id()
        self._discovered_devices: list[DiscoveredDevice] = []
        self._device_groups: list[DeviceGroup] = []
        self._selected_entities: list[str] = []
        self._site_id: str | None = None
        self._device_mappings: dict[str, str] = {}
        self._api_url: str = DEFAULT_API_BASE_URL
        # Installation mode - mutually exclusive: "real" or "simulation"
        self._installation_mode: str = INSTALLATION_MODE_REAL
        # Simulation options (only used in simulation mode)
        self._enable_simulation: bool = False
        self._simulation_profile: str = "family"
        self._simulation_wh_type: str = "smart"
        # OAuth tokens (set after successful OAuth)
        self._oauth_token: str | None = None
        self._oauth_refresh_token: str | None = None
        # API key (for API key auth method)
        self._api_key: str | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data to include in the authorize URL."""
        return {"scope": "ha:full"}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step - choose OAuth or API key."""
        if user_input is not None:
            auth_method = user_input.get(CONF_AUTH_METHOD, AUTH_METHOD_OAUTH)

            if auth_method == AUTH_METHOD_OAUTH:
                # Register our built-in OAuth implementation
                # This must be done before pick_implementation for fresh installs
                async_register_implementation(
                    self.hass,
                    DOMAIN,
                    AmperaOAuth2Implementation(self.hass),
                )
                # Start OAuth2 flow using HA's built-in handler
                return await self.async_step_pick_implementation()
            else:
                # Go to API key entry
                return await self.async_step_api_key()

        # Build auth method options
        auth_options = [SelectOptionDict(value=code, label=name) for code, name in AUTH_METHODS]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_METHOD, default=AUTH_METHOD_OAUTH): SelectSelector(
                        SelectSelectorConfig(
                            options=auth_options,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create entry from successful OAuth.

        This is called by AbstractOAuth2FlowHandler after successful OAuth.
        We continue to mode selection.
        """
        # Store OAuth tokens
        self._oauth_token = data.get("token", {}).get("access_token")
        self._oauth_refresh_token = data.get("token", {}).get("refresh_token")

        _LOGGER.info("OAuth authentication successful, proceeding to mode selection")

        # Continue to installation mode selection
        return await self.async_step_mode()

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle API key entry step (fallback authentication)."""
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
                    # Store for later use
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
            step_id="api_key",
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

    async def async_step_mode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle installation mode selection.

        Users must choose between:
        - Real Devices: For production use with actual physical devices
        - Simulation: For demos and testing with simulated devices

        These modes are mutually exclusive to prevent mixing simulated
        and real devices in the same installation.
        """
        if user_input is not None:
            self._installation_mode = user_input.get(CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL)
            # Move to location configuration
            return await self.async_step_location()

        # Build mode options
        mode_options = [
            SelectOptionDict(value=code, label=name) for code, name in INSTALLATION_MODES
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
        region_options = [SelectOptionDict(value=code, label=name) for code, name in GRID_REGIONS]

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
            raw_selection = user_input.get(CONF_SELECTED_ENTITIES, [])
            # Expand any group IDs back to member device IDs before we
            # persist the selection — downstream code (device sync, API
            # registration) only understands raw ha_device_id values.
            self._selected_entities = expand_group_selections(
                raw_selection, getattr(self, "_device_groups", [])
            )
            # Allow continuing with 0 devices - user can add devices later
            # In real mode, go directly to registration (no simulation)
            self._enable_simulation = False
            return await self._async_register_and_complete()

        # Discover devices
        discovery = DiscoveryOrchestrator(self.hass)
        self._discovered_devices, _ = discovery.discover()

        if not self._discovered_devices:
            # No devices found - show informational message but allow continuing
            # User can add devices later via options flow or by adding HA integrations
            _LOGGER.info("No compatible devices found - user can continue without devices")
            return self.async_show_form(
                step_id="devices",
                data_schema=vol.Schema(
                    {
                        # Empty multi-select - user just clicks submit to continue
                        vol.Optional(CONF_SELECTED_ENTITIES, default=[]): SelectSelector(
                            SelectSelectorConfig(
                                options=[],
                                multiple=True,
                                mode=SelectSelectorMode.LIST,
                            )
                        ),
                    }
                ),
                description_placeholders={"device_count": "0"},
            )

        # Build filtered, sorted device options with smart pre-selection.
        # During initial setup we hide non-energy devices by default —
        # users with many smart-home devices (cameras, switches) get a
        # focused list. They can opt in to the full list later via the
        # "Manage devices" options flow.
        device_options, default_selection, device_groups = _build_device_picker_options(
            self._discovered_devices,
            show_all=False,
        )
        self._device_groups = device_groups
        total_count = len(self._discovered_devices)
        energy_count = sum(1 for d in self._discovered_devices if d.is_energy_relevant)
        hidden_count = total_count - energy_count
        group_count = len(device_groups)
        grouped_device_count = sum(g.count for g in device_groups)
        shown_option_count = len(device_options)

        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SELECTED_ENTITIES, default=default_selection): SelectSelector(
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
                "device_count": str(shown_option_count),
                "total_count": str(total_count),
                "hidden_count": str(hidden_count),
                "group_count": str(group_count),
                "grouped_device_count": str(grouped_device_count),
                "energy_count": str(energy_count),
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
            self._simulation_profile = user_input.get(CONF_SIMULATION_HOUSEHOLD_PROFILE, "family")
            self._simulation_wh_type = user_input.get(CONF_SIMULATION_WATER_HEATER_TYPE, "smart")

            # No devices selected in simulation mode - simulation creates them
            self._selected_entities = []

            # Proceed to registration
            return await self._async_register_and_complete()

        # Build profile options
        profile_options = [
            SelectOptionDict(value=code, label=name) for code, name in SIMULATION_PROFILES
        ]

        # Build water heater type options
        wh_type_options = [
            SelectOptionDict(value=code, label=name) for code, name in SIMULATION_WH_TYPES
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

        # Determine auth method and create API client
        if self._oauth_token:
            auth_method = AUTH_METHOD_OAUTH
            client = AmperaApiClient(self._oauth_token, base_url=self._api_url)
        else:
            auth_method = AUTH_METHOD_API_KEY
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
                discovery = DiscoveryOrchestrator(self.hass)
                all_devices, _ = discovery.discover()
                selected_ids = set(self._selected_entities)
                devices_to_register = [
                    d for d in all_devices if d.ha_device_id in selected_ids
                ]
                device_data = [d.to_dict() for d in devices_to_register]
            else:
                device_data = []

            # Register devices (skip if empty - simulation mode creates devices later)
            if device_data:
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
                _LOGGER.info("Registered %d devices", devices_response["registered"])
            else:
                _LOGGER.info(
                    "No devices to register (mode: %s) - skipping device registration",
                    self._installation_mode,
                )
                self._device_mappings = {}

            # Check if already configured (by HA instance ID)
            await self.async_set_unique_id(self._ha_instance_id)
            self._abort_if_unique_id_configured()

            # Create the config entry
            # Include installation mode badge in title for clarity
            title_suffix = (
                " (Simulation)" if self._installation_mode == INSTALLATION_MODE_SIMULATION else ""
            )

            # Build config data based on auth method
            config_data = {
                CONF_AUTH_METHOD: auth_method,
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
            }

            # Store credentials based on auth method
            if auth_method == AUTH_METHOD_OAUTH:
                config_data[CONF_OAUTH_TOKEN] = self._oauth_token
                config_data[CONF_OAUTH_REFRESH_TOKEN] = self._oauth_refresh_token
            else:
                config_data[CONF_API_KEY] = self._api_key

            return self.async_create_entry(
                title=f"{self._site_name}{title_suffix}",
                data=config_data,
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

            # Use the stored API URL from the failing config entry
            reauth_entry = self._get_reauth_entry()
            api_url = reauth_entry.data.get(CONF_API_URL, DEFAULT_API_BASE_URL)
            _LOGGER.info("Reauth: validating new API key against %s", api_url)

            client = AmperaApiClient(api_key, base_url=api_url)
            try:
                valid = await client.async_validate_token()
                if not valid:
                    _LOGGER.warning("Reauth: token validation returned False")
                    errors["base"] = "invalid_auth"
                else:
                    # Update the existing entry, writing to the correct token field
                    # based on the original auth method used during setup
                    auth_method = reauth_entry.data.get(CONF_AUTH_METHOD, AUTH_METHOD_API_KEY)
                    if auth_method == AUTH_METHOD_OAUTH:
                        token_update = {CONF_OAUTH_TOKEN: api_key}
                    else:
                        token_update = {CONF_API_KEY: api_key}
                    _LOGGER.info(
                        "Reauth successful, updating %s field and reloading",
                        "oauth_token" if auth_method == AUTH_METHOD_OAUTH else "api_key",
                    )
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data={**reauth_entry.data, **token_update},
                    )

            except AmperaAuthError as err:
                _LOGGER.warning("Reauth: auth error - %s", err)
                errors["base"] = "invalid_auth"
            except AmperaConnectionError as err:
                _LOGGER.warning("Reauth: connection error - %s", err)
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


# Alias for backward compatibility - HA uses domain lookup
AmperaConfigFlow = AmperaOAuth2FlowHandler


class AmperaOptionsFlow(OptionsFlow):
    """Handle options flow for Ampæra Energy.

    Provides a menu-based interface with:
    - Connection status checking
    - Re-authentication capability
    - Device management (add/remove synced devices)
    - Settings configuration

    Options available depend on installation mode:
    - Real Device Mode: Polling intervals, voltage sensors, dev mode
    - Simulation Mode: Household profile, water heater type

    Installation mode cannot be changed after setup - users must
    reconfigure the integration to switch modes.
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._discovered_devices: list[Any] = []
        self._manage_device_groups: list[DeviceGroup] = []

    @property
    def config_entry(self) -> ConfigEntry:
        """Return the config entry for this flow."""
        return self._config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Show main options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "check_connection",
                "reauth",
                "manage_devices",
                "regenerate_dashboard",
                "entity_browser",
                "sensor_streams",
                "settings",
            ],
        )

    async def async_step_check_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Test connection to Ampæra and show status."""
        if user_input is not None:
            # User acknowledged result, return to menu
            return await self.async_step_init()

        # Get credentials from config entry
        entry_data = self.config_entry.data
        auth_method = entry_data.get(CONF_AUTH_METHOD)
        api_url = entry_data.get(CONF_API_URL, DEFAULT_API_BASE_URL)

        # Get token based on auth method
        if auth_method == AUTH_METHOD_OAUTH:
            token = entry_data.get(CONF_OAUTH_TOKEN)
        else:
            token = entry_data.get(CONF_API_KEY)

        # Test connection
        status = "unknown"
        description = ""

        if not token:
            status = "no_credentials"
            description = "No credentials found"
        else:
            api = AmperaApiClient(token, base_url=api_url)
            try:
                is_valid = await api.async_validate_token()
                if is_valid:
                    status = "connected"
                    site_name = entry_data.get(CONF_SITE_NAME, "Unknown")
                    description = f"Site: {site_name}"
                else:
                    status = "auth_failed"
                    description = "Token is invalid or expired"
            except AmperaConnectionError as e:
                status = "connection_failed"
                description = str(e)
            except Exception as e:
                _LOGGER.exception("Unexpected error checking connection: %s", e)
                status = "error"
                description = str(e)
            finally:
                await api.close()

        return self.async_show_form(
            step_id="check_connection",
            description_placeholders={"status": status, "description": description},
            data_schema=vol.Schema({}),  # Just OK button
        )

    async def async_step_reauth(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle re-authentication - show API key form regardless of original auth method."""
        return await self.async_step_reauth_api_key()

    async def async_step_reauth_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-enter API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY, "")
            api_url = self.config_entry.data.get(CONF_API_URL, DEFAULT_API_BASE_URL)

            if not api_key:
                return self.async_show_form(
                    step_id="reauth_api_key",
                    data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
                    errors={"base": "invalid_auth"},
                )

            # Validate new API key
            api = AmperaApiClient(api_key, base_url=api_url)
            try:
                if await api.async_validate_token():
                    # Update the correct token field based on the original auth method
                    auth_method = self.config_entry.data.get(CONF_AUTH_METHOD, AUTH_METHOD_API_KEY)
                    token_field = CONF_OAUTH_TOKEN if auth_method == AUTH_METHOD_OAUTH else CONF_API_KEY
                    new_data = {**self.config_entry.data, token_field: api_key}
                    self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
                    # Reload so the running API client picks up the new token.
                    # Without this, async_setup_entry is never re-run and the
                    # integration keeps using the old expired token in memory.
                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(self.config_entry.entry_id)
                    )
                    return self.async_create_entry(title="", data=self.config_entry.options)
                else:
                    errors["base"] = "invalid_auth"
            except AmperaConnectionError:
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.exception("Unexpected error during reauth: %s", e)
                errors["base"] = "unknown"
            finally:
                await api.close()

        return self.async_show_form(
            step_id="reauth_api_key",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    async def async_step_manage_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage which devices are synced to Ampæra.

        Real mode: respects the per-entry ``CONF_SHOW_ALL_DEVICES`` toggle
        to either hide or show non-energy devices (cameras, etc.). Toggling
        the checkbox and submitting persists the preference and re-renders
        the form with the new filter applied.
        """
        entry_data = self.config_entry.data
        installation_mode = entry_data.get(CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL)
        is_simulation = installation_mode == INSTALLATION_MODE_SIMULATION
        current_show_all = bool(entry_data.get(CONF_SHOW_ALL_DEVICES, False))

        if user_input is not None:
            # User submitted new device selection (and possibly toggled show_all).
            raw_new_selected = user_input.get(CONF_SELECTED_ENTITIES, [])
            new_show_all = bool(user_input.get(CONF_SHOW_ALL_DEVICES, False))

            # If only the toggle changed, persist it and re-render the form
            # so the new filter takes effect immediately.
            if not is_simulation and new_show_all != current_show_all:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**entry_data, CONF_SHOW_ALL_DEVICES: new_show_all},
                )
                return await self.async_step_manage_devices()

            # Expand any group IDs back to member device IDs before storing.
            new_selected = expand_group_selections(
                raw_new_selected, self._manage_device_groups
            )

            # Update config entry data with new selection
            new_data = {
                **entry_data,
                CONF_SELECTED_ENTITIES: new_selected,
                CONF_SHOW_ALL_DEVICES: new_show_all,
            }
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

            # The coordinator will pick up the change on next sync
            _LOGGER.info("Updated device selection: %d devices", len(new_selected))

            return self.async_create_entry(title="", data=self.config_entry.options)

        # Discover all available devices (only in real mode)
        device_options: list[SelectOptionDict] = []
        total_count = 0
        energy_count = 0
        hidden_count = 0
        group_count = 0
        grouped_device_count = 0
        self._manage_device_groups: list[DeviceGroup] = []

        if not is_simulation:
            discovery = DiscoveryOrchestrator(self.hass)
            self._discovered_devices, _ = discovery.discover()
            total_count = len(self._discovered_devices)
            energy_count = sum(
                1 for d in self._discovered_devices if d.is_energy_relevant
            )

            device_options, _, self._manage_device_groups = _build_device_picker_options(
                self._discovered_devices,
                show_all=current_show_all,
            )
            hidden_count = total_count - energy_count
            group_count = len(self._manage_device_groups)
            grouped_device_count = sum(g.count for g in self._manage_device_groups)

        # Get currently selected devices, collapsing fully-selected groups
        # so the form shows one pre-checked group option instead of leaving
        # its members invisible and unchecked. Then filter to options the
        # picker actually exposes — voluptuous validates the default list
        # against the option set and crashes the form on the first stale
        # ID (e.g. a device the user removed from HA, or a v2.1.0 picker
        # selection that we now expect to be a group ID).
        stored_selected = list(entry_data.get(CONF_SELECTED_ENTITIES, []))
        valid_option_values = {opt["value"] for opt in device_options}
        current_selected = [
            value
            for value in collapse_to_group_ids(
                stored_selected, self._manage_device_groups
            )
            if value in valid_option_values
        ]

        # For simulation mode, add simulated device options
        if is_simulation:
            device_options = [
                SelectOptionDict(value="sim_ams_meter", label="Simulated AMS Meter"),
                SelectOptionDict(value="sim_water_heater", label="Simulated Water Heater"),
                SelectOptionDict(value="sim_ev_charger", label="Simulated EV Charger"),
                SelectOptionDict(value="sim_heat_pump", label="Simulated Heat Pump"),
            ]
            total_count = len(device_options)

        if not device_options:
            # No devices available - show empty form with message
            return self.async_show_form(
                step_id="manage_devices",
                data_schema=vol.Schema(
                    {
                        vol.Optional(CONF_SELECTED_ENTITIES, default=[]): SelectSelector(
                            SelectSelectorConfig(
                                options=[],
                                multiple=True,
                                mode=SelectSelectorMode.LIST,
                            )
                        ),
                        vol.Optional(
                            CONF_SHOW_ALL_DEVICES, default=current_show_all
                        ): bool,
                    }
                ),
                description_placeholders={
                    "device_count": "0",
                    "total_count": "0",
                    "hidden_count": "0",
                    "group_count": "0",
                    "grouped_device_count": "0",
                    "energy_count": "0",
                },
            )

        schema_dict: dict[Any, Any] = {
            vol.Optional(
                CONF_SELECTED_ENTITIES, default=current_selected
            ): SelectSelector(
                SelectSelectorConfig(
                    options=device_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        }
        # Only show the toggle in real mode — there's nothing to hide in
        # simulation mode.
        if not is_simulation:
            schema_dict[
                vol.Optional(CONF_SHOW_ALL_DEVICES, default=current_show_all)
            ] = bool

        return self.async_show_form(
            step_id="manage_devices",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "device_count": str(len(device_options)),
                "total_count": str(total_count),
                "hidden_count": str(hidden_count),
                "energy_count": str(energy_count),
                "group_count": str(group_count),
                "grouped_device_count": str(grouped_device_count),
            },
        )

    async def async_step_regenerate_dashboard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Regenerate the Ampæra dashboard with correct entity IDs."""
        if user_input is not None:
            # User confirmed - regenerate dashboard
            from . import _async_create_or_update_dashboard

            entry_data = self.config_entry.data
            site_id = entry_data.get(CONF_SITE_ID, "unknown")
            site_name = entry_data.get(CONF_SITE_NAME, "Ampæra")
            installation_mode = entry_data.get(CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL)

            # Get entity_mappings from running device sync service (for real mode)
            entity_mappings = None
            domain_data = self.hass.data.get(DOMAIN, {})
            entry_runtime = domain_data.get(self.config_entry.entry_id)
            if isinstance(entry_runtime, dict):
                sync_svc = entry_runtime.get("device_sync_service")
                if sync_svc:
                    entity_mappings = sync_svc.entity_mappings

            # Force regeneration by passing force=True
            await _async_create_or_update_dashboard(
                self.hass,
                site_id,
                site_name,
                installation_mode,
                force=True,
                entry=self.config_entry,
                entity_mappings=entity_mappings,
            )

            _LOGGER.info("Dashboard regenerated for site %s", site_name)

            # Return with success message
            return self.async_abort(reason="dashboard_regenerated")

        # Show confirmation form
        return self.async_show_form(
            step_id="regenerate_dashboard",
            data_schema=vol.Schema({}),  # Just confirm button
            description_placeholders={},
        )

    async def async_step_entity_browser(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show entity browser: all synced entities with current values and usage."""
        if user_input is not None:
            return await self.async_step_init()

        # Get entity_mappings from running device sync service
        entity_mappings = {}
        domain_data = self.hass.data.get(DOMAIN, {})
        entry_runtime = domain_data.get(self.config_entry.entry_id)
        if isinstance(entry_runtime, dict):
            sync_svc = entry_runtime.get("device_sync_service")
            if sync_svc:
                entity_mappings = sync_svc.entity_mappings

        if not entity_mappings:
            return self.async_show_form(
                step_id="entity_browser",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "entity_table": "Ingen entiteter synkronisert ennå."
                },
            )

        # Build markdown table of all synced entities
        lines = [
            "| HA-entitet | Verdi | Brukes til |",
            "|------------|-------|-----------|",
        ]

        for entity_id, mapping in sorted(entity_mappings.items()):
            state = self.hass.states.get(entity_id)
            if state:
                value = state.state
                unit = state.attributes.get("unit_of_measurement", "")
                display_value = f"{value} {unit}".strip() if unit else value
            else:
                display_value = "utilgjengelig"

            usage_list = CAPABILITY_USAGE.get(mapping.capability, ["Ukjent"])
            usage = ", ".join(usage_list)

            lines.append(f"| `{entity_id}` | {display_value} | {usage} |")

        table_md = "\n".join(lines)

        return self.async_show_form(
            step_id="entity_browser",
            data_schema=vol.Schema({}),
            description_placeholders={"entity_table": table_md},
        )

    async def async_step_sensor_streams(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure which HA sensor entities to forward to the Data Lab."""
        if user_input is not None:
            new_options = dict(self.config_entry.options)
            new_options[CONF_SENSOR_STREAM_ENTITIES] = user_input.get(
                CONF_SENSOR_STREAM_ENTITIES, []
            )
            new_options[CONF_SENSOR_STREAM_INTERVAL] = user_input.get(
                CONF_SENSOR_STREAM_INTERVAL, DEFAULT_SENSOR_STREAM_INTERVAL
            )
            return self.async_create_entry(title="", data=new_options)

        current_entities = self.config_entry.options.get(CONF_SENSOR_STREAM_ENTITIES, [])
        current_interval = self.config_entry.options.get(
            CONF_SENSOR_STREAM_INTERVAL, DEFAULT_SENSOR_STREAM_INTERVAL
        )

        return self.async_show_form(
            step_id="sensor_streams",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SENSOR_STREAM_ENTITIES,
                        default=current_entities,
                    ): EntitySelector(
                        EntitySelectorConfig(
                            domain="sensor",
                            multiple=True,
                        )
                    ),
                    vol.Optional(
                        CONF_SENSOR_STREAM_INTERVAL,
                        default=current_interval,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=30,
                            max=3600,
                            step=30,
                            unit_of_measurement="seconds",
                        )
                    ),
                }
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure integration settings."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current options with defaults (check both options and data)
        current_options = self.config_entry.options
        entry_data = self.config_entry.data

        # Check installation mode
        installation_mode = entry_data.get(CONF_INSTALLATION_MODE, INSTALLATION_MODE_REAL)
        is_simulation_mode = installation_mode == INSTALLATION_MODE_SIMULATION

        # Build common schema fields (available in both modes)
        schema_fields: dict[vol.Marker, Any] = {
            vol.Optional(
                CONF_POLLING_INTERVAL,
                default=current_options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL),
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
                SelectOptionDict(value=code, label=name) for code, name in SIMULATION_PROFILES
            ]
            wh_type_options = [
                SelectOptionDict(value=code, label=name) for code, name in SIMULATION_WH_TYPES
            ]

            schema_fields[
                vol.Optional(
                    CONF_SIMULATION_HOUSEHOLD_PROFILE,
                    default=current_options.get(
                        CONF_SIMULATION_HOUSEHOLD_PROFILE,
                        entry_data.get(CONF_SIMULATION_HOUSEHOLD_PROFILE, "family"),
                    ),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=profile_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
            schema_fields[
                vol.Optional(
                    CONF_SIMULATION_WATER_HEATER_TYPE,
                    default=current_options.get(
                        CONF_SIMULATION_WATER_HEATER_TYPE,
                        entry_data.get(CONF_SIMULATION_WATER_HEATER_TYPE, "smart"),
                    ),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=wh_type_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        else:
            # Real device mode: show voltage sensor option
            schema_fields[
                vol.Optional(
                    CONF_ENABLE_VOLTAGE_SENSORS,
                    default=current_options.get(CONF_ENABLE_VOLTAGE_SENSORS, False),
                )
            ] = bool

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(schema_fields),
        )
