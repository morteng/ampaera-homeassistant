"""Command receiver service for Ampæra HA integration.

Polls for pending commands from Ampæra cloud and executes them
in Home Assistant.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api import AmperaApiClient

_LOGGER = logging.getLogger(__name__)

# Default polling interval (seconds)
DEFAULT_POLL_INTERVAL = 10

# Command types we handle
COMMAND_TURN_ON = "turn_on"
COMMAND_TURN_OFF = "turn_off"
COMMAND_SET_TEMPERATURE = "set_temperature"
COMMAND_SET_MODE = "set_mode"
COMMAND_SET_CURRENT_LIMIT = "set_current_limit"  # EV charger current limit
COMMAND_START_CHARGE = "start_charge"  # EV charger start charging
COMMAND_STOP_CHARGE = "stop_charge"  # EV charger stop charging


class AmperaCommandService:
    """Poll for and execute commands from Ampæra.

    Features:
    - Polls Ampæra for pending commands at configurable interval
    - Executes commands via Home Assistant service calls
    - Acknowledges command completion/failure back to Ampæra
    - Graceful error handling and retry logic
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: AmperaApiClient,
        site_id: str,
        device_mappings: dict[str, str],
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> None:
        """Initialize the command service.

        Args:
            hass: Home Assistant instance
            api_client: Ampæra API client
            site_id: Ampæra site UUID
            device_mappings: Mapping of HA entity_id → Ampæra device_id
            poll_interval: Seconds between polls
        """
        self._hass = hass
        self._api = api_client
        self._site_id = site_id
        self._device_mappings = device_mappings
        self._poll_interval = poll_interval

        # Reverse mapping: Ampæra device_id → HA entity_id
        self._reverse_mappings = {v: k for k, v in device_mappings.items()}

        # Entity mapping by device - populated from config entry
        # Maps: device_id → {capability → entity_id}
        self._entity_mappings: dict[str, dict[str, str]] = {}

        # Polling task
        self._poll_task: asyncio.Task | None = None
        self._running = False

    def set_entity_mappings(self, mappings: dict[str, dict[str, str]]) -> None:
        """Set entity mappings for command routing.

        Args:
            mappings: Dict of device_id → {capability → entity_id}
        """
        self._entity_mappings = mappings
        _LOGGER.debug("Updated entity mappings for %d devices", len(mappings))

    def _resolve_entity_for_command(
        self,
        ha_entity_id: str | None,
        device_id: str | None,
        command_type: str,
    ) -> str | None:
        """Resolve the correct HA entity for a command type.

        Different commands target different entities:
        - turn_on/turn_off → on_off capability (switch)
        - set_temperature → temperature or input_number helper
        - set_mode → mode input_select helper
        - set_current_limit → current_limit input_number

        Args:
            ha_entity_id: Entity ID from API (may be sensor)
            device_id: Ampæra device UUID
            command_type: Command type (turn_on, turn_off, etc.)

        Returns:
            Resolved entity ID, or original if no mapping found
        """
        if not device_id:
            return ha_entity_id

        # Check if we have entity mappings for this device
        device_mapping = self._entity_mappings.get(device_id, {})

        # Map command type to capability
        command_to_capability = {
            COMMAND_TURN_ON: "on_off",
            COMMAND_TURN_OFF: "on_off",
            COMMAND_SET_TEMPERATURE: "temperature",
            COMMAND_SET_MODE: "mode",
            COMMAND_SET_CURRENT_LIMIT: "current",
            COMMAND_START_CHARGE: "on_off",  # Start/stop charge uses on_off switch
            COMMAND_STOP_CHARGE: "on_off",
        }

        capability = command_to_capability.get(command_type)
        if capability and capability in device_mapping:
            resolved = device_mapping[capability]
            if resolved != ha_entity_id:
                _LOGGER.debug(
                    "Resolved entity for %s: %s → %s",
                    command_type,
                    ha_entity_id,
                    resolved,
                )
            return resolved

        # Fallback: try to find a switch for on/off commands (including start/stop charge)
        if command_type in (
            COMMAND_TURN_ON,
            COMMAND_TURN_OFF,
            COMMAND_START_CHARGE,
            COMMAND_STOP_CHARGE,
        ):
            # Look for switch in device mapping
            if "on_off" in device_mapping:
                return device_mapping["on_off"]

            # Try to derive switch from sensor entity
            if ha_entity_id and ha_entity_id.startswith("sensor."):
                # sensor.water_heater_power → switch.water_heater_switch
                base_name = ha_entity_id.replace("sensor.", "").replace("_power", "").replace("_temperature", "")
                switch_entity = f"switch.{base_name}_switch"
                if self._hass.states.get(switch_entity):
                    _LOGGER.debug(
                        "Derived switch entity: %s → %s",
                        ha_entity_id,
                        switch_entity,
                    )
                    return switch_entity

        return ha_entity_id

    @property
    def is_running(self) -> bool:
        """Return whether the service is running."""
        return self._running

    @property
    def poll_interval(self) -> int:
        """Return the polling interval in seconds."""
        return self._poll_interval

    async def async_start(self) -> None:
        """Start polling for commands."""
        if self._running:
            _LOGGER.warning("Command service already running")
            return

        _LOGGER.info(
            "Starting command service for site %s (poll interval: %ds)",
            self._site_id,
            self._poll_interval,
        )

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def async_stop(self) -> None:
        """Stop the command service."""
        if not self._running:
            return

        _LOGGER.info("Stopping command service")
        self._running = False

        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_and_execute()
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error in command poll loop: %s", err)

            # Wait for next poll interval
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def _poll_and_execute(self) -> None:
        """Poll for pending commands and execute them."""
        try:
            commands = await self._api.async_get_pending_commands(self._site_id)
        except Exception as err:
            _LOGGER.error("Failed to fetch pending commands: %s", err)
            return

        if not commands:
            return

        _LOGGER.debug("Received %d pending commands", len(commands))

        for command in commands:
            await self._execute_command(command)

    async def _execute_command(self, command: dict[str, Any]) -> None:
        """Execute a single command in Home Assistant.

        Args:
            command: Command dict from Ampæra with:
                - command_id: UUID
                - device_id: Ampæra device UUID
                - ha_entity_id: HA entity ID
                - command_type: turn_on, turn_off, set_temperature, etc.
                - parameters: Additional parameters
        """
        command_id = command.get("command_id")
        device_id = command.get("device_id")
        ha_entity_id = command.get("ha_entity_id")
        command_type = command.get("command_type")
        parameters = command.get("parameters", {})

        _LOGGER.info(
            "Executing command %s: %s on %s",
            command_id,
            command_type,
            ha_entity_id,
        )

        # Resolve entity ID if not provided
        if not ha_entity_id and device_id:
            ha_entity_id = self._reverse_mappings.get(device_id)

        # Resolve correct entity based on command type
        # The API may send the primary entity, but we need the right entity for the command
        ha_entity_id = self._resolve_entity_for_command(
            ha_entity_id, device_id, command_type
        )

        if not ha_entity_id:
            await self._ack_command(
                command_id,
                success=False,
                error_message=f"No HA entity for device {device_id}",
            )
            return

        # Verify entity exists
        state = self._hass.states.get(ha_entity_id)
        if not state:
            await self._ack_command(
                command_id,
                success=False,
                error_message=f"Entity {ha_entity_id} not found",
            )
            return

        # Execute the command
        try:
            await self._execute_service_call(
                ha_entity_id,
                command_type,
                parameters,
            )

            # Get device state after command execution
            device_state = self._get_device_state(ha_entity_id)
            await self._ack_command(
                command_id,
                success=True,
                device_state=device_state,
            )

        except Exception as err:
            _LOGGER.error(
                "Failed to execute command %s: %s",
                command_id,
                err,
            )
            await self._ack_command(
                command_id,
                success=False,
                error_message=str(err),
            )

    async def _execute_service_call(
        self,
        entity_id: str,
        command_type: str,
        parameters: dict[str, Any],
    ) -> None:
        """Execute a Home Assistant service call.

        Args:
            entity_id: Target entity
            command_type: Command type (turn_on, turn_off, etc.)
            parameters: Additional parameters
        """
        domain = entity_id.split(".")[0]

        if command_type == COMMAND_TURN_ON:
            await self._hass.services.async_call(
                domain,
                SERVICE_TURN_ON,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
            )

        elif command_type == COMMAND_TURN_OFF:
            await self._hass.services.async_call(
                domain,
                SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
            )

        elif command_type == COMMAND_SET_TEMPERATURE:
            target_temp = parameters.get("target_temperature_c")
            if target_temp is None:
                raise ValueError("Missing target_temperature_c parameter")

            # Different domains use different services
            if domain == "water_heater":
                await self._hass.services.async_call(
                    "water_heater",
                    "set_temperature",
                    {
                        ATTR_ENTITY_ID: entity_id,
                        ATTR_TEMPERATURE: target_temp,
                    },
                    blocking=True,
                )
            elif domain == "climate":
                await self._hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {
                        ATTR_ENTITY_ID: entity_id,
                        ATTR_TEMPERATURE: target_temp,
                    },
                    blocking=True,
                )
            elif domain == "input_number":
                # Support for simulated devices using input_number helpers
                await self._hass.services.async_call(
                    "input_number",
                    "set_value",
                    {
                        ATTR_ENTITY_ID: entity_id,
                        "value": target_temp,
                    },
                    blocking=True,
                )
            elif domain == "switch":
                # Simulated water heater switch - try to find related input_number
                # Convention: switch.sim_water_heater_switch → input_number.water_heater_target_temp
                temp_entity = await self._find_simulation_helper(
                    entity_id, "input_number", "target_temp"
                )
                if temp_entity:
                    await self._hass.services.async_call(
                        "input_number",
                        "set_value",
                        {
                            ATTR_ENTITY_ID: temp_entity,
                            "value": target_temp,
                        },
                        blocking=True,
                    )
                else:
                    raise ValueError(
                        f"set_temperature not supported for {entity_id} (no helper found)"
                    )
            else:
                raise ValueError(
                    f"set_temperature not supported for domain {domain}"
                )

        elif command_type == COMMAND_SET_MODE:
            mode = parameters.get("mode")
            if mode is None:
                raise ValueError("Missing mode parameter")

            if domain == "water_heater":
                await self._hass.services.async_call(
                    "water_heater",
                    "set_operation_mode",
                    {
                        ATTR_ENTITY_ID: entity_id,
                        "operation_mode": mode,
                    },
                    blocking=True,
                )
            elif domain == "climate":
                await self._hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {
                        ATTR_ENTITY_ID: entity_id,
                        "hvac_mode": mode,
                    },
                    blocking=True,
                )
            elif domain == "input_select":
                # Support for simulated devices using input_select helpers
                await self._hass.services.async_call(
                    "input_select",
                    "select_option",
                    {
                        ATTR_ENTITY_ID: entity_id,
                        "option": mode,
                    },
                    blocking=True,
                )
            elif domain == "switch":
                # Simulated water heater switch - try to find related input_select
                # Convention: switch.sim_water_heater_switch → input_select.water_heater_mode
                mode_entity = await self._find_simulation_helper(
                    entity_id, "input_select", "mode"
                )
                if mode_entity:
                    await self._hass.services.async_call(
                        "input_select",
                        "select_option",
                        {
                            ATTR_ENTITY_ID: mode_entity,
                            "option": mode,
                        },
                        blocking=True,
                    )
                else:
                    raise ValueError(
                        f"set_mode not supported for {entity_id} (no helper found)"
                    )
            else:
                raise ValueError(
                    f"set_mode not supported for domain {domain}"
                )

        elif command_type == COMMAND_SET_CURRENT_LIMIT:
            current_limit = parameters.get("current_limit_a")
            if current_limit is None:
                raise ValueError("Missing current_limit_a parameter")

            # EV chargers - check for native integration service or use input_number
            if domain == "switch":
                # Simulated EV charger - find related input_number
                limit_entity = await self._find_simulation_helper(
                    entity_id, "input_number", "current_limit"
                )
                if limit_entity:
                    await self._hass.services.async_call(
                        "input_number",
                        "set_value",
                        {
                            ATTR_ENTITY_ID: limit_entity,
                            "value": current_limit,
                        },
                        blocking=True,
                    )
                else:
                    raise ValueError(
                        f"set_current_limit not supported for {entity_id} (no helper found)"
                    )
            elif domain == "sensor":
                # Entity mapping points to sensor - try to find corresponding input_number
                # sensor.ev_charger_current_limit → input_number.ev_charger_current_limit
                input_entity = entity_id.replace("sensor.", "input_number.")
                if self._hass.states.get(input_entity):
                    _LOGGER.debug(
                        "Resolved sensor to input_number: %s → %s",
                        entity_id,
                        input_entity,
                    )
                    await self._hass.services.async_call(
                        "input_number",
                        "set_value",
                        {
                            ATTR_ENTITY_ID: input_entity,
                            "value": current_limit,
                        },
                        blocking=True,
                    )
                else:
                    raise ValueError(
                        f"set_current_limit not supported for {entity_id} (no input_number found)"
                    )
            elif domain == "input_number":
                # Direct input_number control
                await self._hass.services.async_call(
                    "input_number",
                    "set_value",
                    {
                        ATTR_ENTITY_ID: entity_id,
                        "value": current_limit,
                    },
                    blocking=True,
                )
            else:
                # Native EV charger integrations may have specific services
                # Try common patterns
                try:
                    await self._hass.services.async_call(
                        domain,
                        "set_charging_current",
                        {
                            ATTR_ENTITY_ID: entity_id,
                            "current": current_limit,
                        },
                        blocking=True,
                    )
                except Exception:
                    raise ValueError(
                        f"set_current_limit not supported for domain {domain}"
                    )

        elif command_type == COMMAND_START_CHARGE:
            # Start charging - turn on the charger switch
            # For simulated EV chargers, this just turns on the switch
            # For real EV chargers with native integrations, may need specific service
            if domain == "switch":
                await self._hass.services.async_call(
                    "switch",
                    SERVICE_TURN_ON,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                )
            elif domain == "input_boolean":
                await self._hass.services.async_call(
                    "input_boolean",
                    SERVICE_TURN_ON,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                )
            else:
                # Try native EV charger service
                try:
                    await self._hass.services.async_call(
                        domain,
                        "start_charging",
                        {ATTR_ENTITY_ID: entity_id},
                        blocking=True,
                    )
                except Exception:
                    raise ValueError(
                        f"start_charge not supported for domain {domain}"
                    )

        elif command_type == COMMAND_STOP_CHARGE:
            # Stop charging - turn off the charger switch
            if domain == "switch":
                await self._hass.services.async_call(
                    "switch",
                    SERVICE_TURN_OFF,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                )
            elif domain == "input_boolean":
                await self._hass.services.async_call(
                    "input_boolean",
                    SERVICE_TURN_OFF,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=True,
                )
            else:
                # Try native EV charger service
                try:
                    await self._hass.services.async_call(
                        domain,
                        "stop_charging",
                        {ATTR_ENTITY_ID: entity_id},
                        blocking=True,
                    )
                except Exception:
                    raise ValueError(
                        f"stop_charge not supported for domain {domain}"
                    )

        else:
            raise ValueError(f"Unknown command type: {command_type}")

    async def _find_simulation_helper(
        self,
        source_entity_id: str,
        target_domain: str,
        suffix_hint: str,
    ) -> str | None:
        """Find a related simulation helper entity.

        Uses naming conventions to find input helpers related to a simulated device.
        For example: switch.sim_water_heater_switch → input_number.water_heater_target_temp

        Args:
            source_entity_id: The entity being controlled (e.g., switch.sim_water_heater_switch)
            target_domain: The domain to search (e.g., input_number, input_select)
            suffix_hint: Hint for what to look for (e.g., "target_temp", "mode")

        Returns:
            Entity ID of the helper, or None if not found
        """
        # Extract base name from source entity
        # switch.sim_water_heater_switch → water_heater
        source_name = source_entity_id.split(".", 1)[1] if "." in source_entity_id else source_entity_id

        # Remove common prefixes/suffixes
        base_name = source_name
        for prefix in ("sim_", "simulated_"):
            if base_name.startswith(prefix):
                base_name = base_name[len(prefix):]
        for suffix in ("_switch", "_sensor", "_entity"):
            if base_name.endswith(suffix):
                base_name = base_name[:-len(suffix)]

        # Try different naming patterns
        candidates = [
            f"{target_domain}.{base_name}_{suffix_hint}",  # input_number.water_heater_target_temp
            f"{target_domain}.{base_name}_{suffix_hint.replace('_', '')}",  # input_number.water_heater_targettemp
            f"{target_domain}.sim_{base_name}_{suffix_hint}",  # input_number.sim_water_heater_target_temp
        ]

        # For mode, also try status (EV chargers use "status" instead of "mode")
        if suffix_hint == "mode":
            candidates.append(f"{target_domain}.{base_name}_mode")  # input_select.water_heater_mode
            candidates.append(f"{target_domain}.{base_name}_status")  # input_select.ev_charger_status

        # For temperature, also try current_temp
        if suffix_hint == "target_temp":
            candidates.append(f"{target_domain}.{base_name}_current_temp")  # input_number.water_heater_current_temp
            # EV chargers might have current_limit instead of temp
            candidates.append(f"{target_domain}.{base_name}_current_limit")  # input_number.ev_charger_current_limit

        for candidate in candidates:
            if self._hass.states.get(candidate):
                _LOGGER.debug(
                    "Found simulation helper %s for %s",
                    candidate,
                    source_entity_id,
                )
                return candidate

        _LOGGER.warning(
            "No simulation helper found for %s (tried: %s)",
            source_entity_id,
            candidates,
        )
        return None

    def _get_device_state(self, entity_id: str) -> dict[str, Any] | None:
        """Get current device state from Home Assistant.

        Args:
            entity_id: Target entity ID

        Returns:
            dict with relevant state attributes, or None if entity not found
        """
        state = self._hass.states.get(entity_id)
        if not state:
            return None

        domain = entity_id.split(".")[0]
        device_state: dict[str, Any] = {
            "power_state": "on" if state.state not in ("off", "unavailable") else "off",
        }

        # Add domain-specific attributes
        if domain in ("water_heater", "climate"):
            if (temp := state.attributes.get("current_temperature")) is not None:
                device_state["temperature"] = temp
            if (target := state.attributes.get("temperature")) is not None:
                device_state["target_temperature"] = target
            if (mode := state.attributes.get("operation_mode")) is not None:
                device_state["operation_mode"] = mode
            elif (hvac := state.attributes.get("hvac_mode")) is not None:
                device_state["hvac_mode"] = hvac

        elif domain == "switch":
            device_state["is_on"] = state.state == "on"
            # For simulated switches, try to get related helper state
            self._enrich_switch_state_from_helpers(entity_id, device_state)

        elif domain == "sensor":
            # Include the sensor value
            if state.state not in ("unavailable", "unknown"):
                try:
                    device_state["value"] = float(state.state)
                except ValueError:
                    device_state["value"] = state.state

        elif domain == "input_number":
            # Input number helper - return value
            if state.state not in ("unavailable", "unknown"):
                try:
                    device_state["value"] = float(state.state)
                except ValueError:
                    pass

        elif domain == "input_select":
            # Input select helper - return current option as mode
            if state.state not in ("unavailable", "unknown"):
                device_state["operation_mode"] = state.state

        elif domain == "input_boolean":
            # Input boolean helper - return on/off state
            device_state["is_on"] = state.state == "on"

        return device_state

    def _enrich_switch_state_from_helpers(
        self, switch_entity_id: str, device_state: dict[str, Any]
    ) -> None:
        """Enrich switch state with data from related simulation helpers.

        For simulated devices, looks up related input helpers and adds their
        values to the device state.

        Args:
            switch_entity_id: The switch entity ID
            device_state: State dict to enrich (modified in place)
        """
        # Extract base name
        source_name = switch_entity_id.split(".", 1)[1] if "." in switch_entity_id else switch_entity_id
        base_name = source_name
        for prefix in ("sim_", "simulated_"):
            if base_name.startswith(prefix):
                base_name = base_name[len(prefix):]
        for suffix in ("_switch", "_sensor", "_entity"):
            if base_name.endswith(suffix):
                base_name = base_name[:-len(suffix)]

        # Try to find related temperature helper
        for temp_suffix in ("_current_temp", "_target_temp", "_temp"):
            temp_entity = f"input_number.{base_name}{temp_suffix}"
            temp_state = self._hass.states.get(temp_entity)
            if temp_state and temp_state.state not in ("unavailable", "unknown"):
                try:
                    if "current" in temp_suffix:
                        device_state["temperature"] = float(temp_state.state)
                    else:
                        device_state["target_temperature"] = float(temp_state.state)
                except ValueError:
                    pass

        # Try to find related mode helper (water heater uses "mode", EV uses "status")
        for mode_suffix in ("_mode", "_status"):
            mode_entity = f"input_select.{base_name}{mode_suffix}"
            mode_state = self._hass.states.get(mode_entity)
            if mode_state and mode_state.state not in ("unavailable", "unknown"):
                device_state["operation_mode"] = mode_state.state
                break

        # Try to find EV charger current limit
        limit_entity = f"input_number.{base_name}_current_limit"
        limit_state = self._hass.states.get(limit_entity)
        if limit_state and limit_state.state not in ("unavailable", "unknown"):
            try:
                device_state["current_limit_a"] = float(limit_state.state)
            except ValueError:
                pass

        # Try to find EV charger session energy
        session_entity = f"input_number.{base_name}_session_energy"
        session_state = self._hass.states.get(session_entity)
        if session_state and session_state.state not in ("unavailable", "unknown"):
            try:
                device_state["session_energy_kwh"] = float(session_state.state)
            except ValueError:
                pass

        # Try to find power helper
        power_entity = f"input_number.{base_name}_power"
        power_state = self._hass.states.get(power_entity)
        if power_state and power_state.state not in ("unavailable", "unknown"):
            try:
                device_state["power_w"] = float(power_state.state)
            except ValueError:
                pass

    async def _ack_command(
        self,
        command_id: str,
        success: bool,
        error_message: str | None = None,
        device_state: dict[str, Any] | None = None,
    ) -> None:
        """Acknowledge command execution to Ampæra."""
        try:
            await self._api.async_acknowledge_command(
                command_id=command_id,
                success=success,
                error_message=error_message,
                device_state=device_state,
            )
            _LOGGER.debug(
                "Acknowledged command %s: success=%s, state=%s",
                command_id,
                success,
                device_state,
            )
        except Exception as err:
            _LOGGER.error(
                "Failed to acknowledge command %s: %s",
                command_id,
                err,
            )

    def update_device_mappings(self, mappings: dict[str, str]) -> None:
        """Update device mappings (e.g., after reconfiguration)."""
        self._device_mappings = mappings
        self._reverse_mappings = {v: k for k, v in mappings.items()}
        _LOGGER.info("Updated command service device mappings")

    def set_poll_interval(self, interval: int) -> None:
        """Update the polling interval."""
        self._poll_interval = max(5, min(60, interval))  # Clamp to 5-60 seconds
        _LOGGER.info("Updated poll interval to %d seconds", self._poll_interval)
