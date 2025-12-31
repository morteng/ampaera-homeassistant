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

        # Polling task
        self._poll_task: asyncio.Task | None = None
        self._running = False

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
            else:
                raise ValueError(
                    f"set_mode not supported for domain {domain}"
                )

        else:
            raise ValueError(f"Unknown command type: {command_type}")

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

        elif domain == "sensor":
            # Include the sensor value
            if state.state not in ("unavailable", "unknown"):
                try:
                    device_state["value"] = float(state.state)
                except ValueError:
                    device_state["value"] = state.state

        return device_state

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
