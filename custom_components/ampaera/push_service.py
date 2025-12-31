"""Telemetry push service for Ampæra HA integration.

Listens for Home Assistant state changes and pushes telemetry
to the Ampæra cloud platform.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_track_state_change_event

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

    from .api import AmperaApiClient

_LOGGER = logging.getLogger(__name__)

# Debounce interval for batching state changes
DEFAULT_DEBOUNCE_SECONDS = 2.0

# Maximum batch size before forcing a push
MAX_BATCH_SIZE = 50


class AmperaTelemetryPushService:
    """Push Home Assistant state changes to Ampæra.

    Features:
    - Listens for state changes on tracked entities
    - Debounces rapid changes to reduce API calls
    - Batches multiple readings into single requests
    - Handles connection errors gracefully
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: AmperaApiClient,
        site_id: str,
        device_mappings: dict[str, str],
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    ) -> None:
        """Initialize the push service.

        Args:
            hass: Home Assistant instance
            api_client: Ampæra API client
            site_id: Ampæra site UUID
            device_mappings: Mapping of HA entity_id → Ampæra device_id
            debounce_seconds: Seconds to wait before pushing batched changes
        """
        self._hass = hass
        self._api = api_client
        self._site_id = site_id
        self._device_mappings = device_mappings
        self._debounce_seconds = debounce_seconds

        # Pending readings to push (keyed by device_id to dedupe)
        self._pending_readings: dict[str, dict[str, Any]] = {}
        self._pending_lock = asyncio.Lock()

        # Debounce timer
        self._debounce_task: asyncio.Task | None = None

        # Unsubscribe callback
        self._unsubscribe: callable | None = None

        # Service state
        self._running = False

    @property
    def is_running(self) -> bool:
        """Return whether the service is running."""
        return self._running

    @property
    def tracked_entities(self) -> list[str]:
        """Return list of tracked entity IDs."""
        return list(self._device_mappings.keys())

    async def async_start(self) -> None:
        """Start listening for state changes."""
        if self._running:
            _LOGGER.warning("Push service already running")
            return

        _LOGGER.info(
            "Starting telemetry push service for site %s with %d entities",
            self._site_id,
            len(self._device_mappings),
        )

        # Subscribe to state changes for tracked entities
        self._unsubscribe = async_track_state_change_event(
            self._hass,
            list(self._device_mappings.keys()),
            self._handle_state_change,
        )

        self._running = True

        # Push initial states
        await self._push_initial_states()

    async def async_stop(self) -> None:
        """Stop the push service."""
        if not self._running:
            return

        _LOGGER.info("Stopping telemetry push service")

        # Cancel debounce timer
        if self._debounce_task:
            self._debounce_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._debounce_task
            self._debounce_task = None

        # Unsubscribe from state changes
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

        # Push any pending readings
        await self._flush_pending()

        self._running = False

    async def _push_initial_states(self) -> None:
        """Push current states of all tracked entities."""
        for entity_id in self._device_mappings:
            state = self._hass.states.get(entity_id)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                reading = self._format_reading(entity_id, state)
                if reading:
                    device_id = self._device_mappings[entity_id]
                    async with self._pending_lock:
                        self._pending_readings[device_id] = reading

        # Push immediately
        await self._flush_pending()

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Handle Home Assistant state change event."""
        entity_id = event.data.get("entity_id")
        new_state: State | None = event.data.get("new_state")

        if not entity_id or not new_state:
            return

        if new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug("Ignoring unavailable state for %s", entity_id)
            return

        # Format reading
        reading = self._format_reading(entity_id, new_state)
        if not reading:
            return

        device_id = self._device_mappings.get(entity_id)
        if not device_id:
            _LOGGER.warning("No device mapping for %s", entity_id)
            return

        # Add to pending (async)
        self._hass.async_create_task(
            self._add_pending_reading(device_id, reading)
        )

    async def _add_pending_reading(
        self,
        device_id: str,
        reading: dict[str, Any],
    ) -> None:
        """Add a reading to the pending batch."""
        async with self._pending_lock:
            self._pending_readings[device_id] = reading

            # Force push if batch is full
            if len(self._pending_readings) >= MAX_BATCH_SIZE:
                await self._flush_pending()
                return

        # Schedule debounced push
        self._schedule_push()

    def _schedule_push(self) -> None:
        """Schedule a debounced push."""
        if self._debounce_task and not self._debounce_task.done():
            # Already scheduled
            return

        self._debounce_task = self._hass.async_create_task(
            self._debounced_push()
        )

    async def _debounced_push(self) -> None:
        """Wait for debounce period then push."""
        await asyncio.sleep(self._debounce_seconds)
        await self._flush_pending()

    async def _flush_pending(self) -> None:
        """Push all pending readings to Ampæra."""
        async with self._pending_lock:
            if not self._pending_readings:
                return

            readings = list(self._pending_readings.values())
            self._pending_readings.clear()

        if not readings:
            return

        timestamp = datetime.now(UTC).isoformat()

        try:
            response = await self._api.async_push_telemetry(
                site_id=self._site_id,
                timestamp=timestamp,
                readings=readings,
            )
            _LOGGER.debug(
                "Pushed %d readings to Ampæra: %s",
                len(readings),
                response,
            )
        except Exception as err:
            _LOGGER.error(
                "Failed to push telemetry to Ampæra: %s",
                err,
            )
            # Re-add readings to pending for retry
            async with self._pending_lock:
                for reading in readings:
                    device_id = reading.get("device_id")
                    if device_id:
                        self._pending_readings[device_id] = reading

    def _format_reading(
        self,
        entity_id: str,
        state: State,
    ) -> dict[str, Any] | None:
        """Format a state into a telemetry reading.

        Returns dict with device_id and measurements, or None if invalid.
        """
        device_id = self._device_mappings.get(entity_id)
        if not device_id:
            return None

        reading: dict[str, Any] = {"device_id": device_id}
        domain = entity_id.split(".")[0]
        device_class = state.attributes.get(ATTR_DEVICE_CLASS)

        # Handle based on domain/device_class
        if domain == "sensor":
            reading = self._format_sensor_reading(reading, state, device_class)
        elif domain == "water_heater":
            reading = self._format_water_heater_reading(reading, state)
        elif domain == "switch":
            reading = self._format_switch_reading(reading, state)
        elif domain == "climate":
            reading = self._format_climate_reading(reading, state)

        # Only return if we have actual measurements
        if len(reading) > 1:  # More than just device_id
            return reading
        return None

    def _format_sensor_reading(
        self,
        reading: dict[str, Any],
        state: State,
        device_class: str | None,
    ) -> dict[str, Any]:
        """Format sensor state into reading."""
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return reading

        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")

        if device_class == "power":
            # Convert to watts if needed
            if unit == "kW":
                value *= 1000
            reading["power_w"] = value

        elif device_class == "energy":
            # Convert to kWh if needed
            if unit == "Wh":
                value /= 1000
            elif unit == "MWh":
                value *= 1000
            reading["energy_kwh"] = value

        elif device_class == "voltage":
            reading["voltage_l1"] = value

        elif device_class == "current":
            reading["current_l1"] = value

        elif device_class == "temperature":
            reading["temperature_c"] = value

        return reading

    def _format_water_heater_reading(
        self,
        reading: dict[str, Any],
        state: State,
    ) -> dict[str, Any]:
        """Format water heater state into reading."""
        # Current temperature
        if "current_temperature" in state.attributes:
            reading["temperature_c"] = state.attributes["current_temperature"]

        # Target temperature
        if "temperature" in state.attributes:
            reading["target_temperature_c"] = state.attributes["temperature"]

        # Is on (based on operation mode)
        reading["is_on"] = state.state not in ("off", "idle")

        return reading

    def _format_switch_reading(
        self,
        reading: dict[str, Any],
        state: State,
    ) -> dict[str, Any]:
        """Format switch state into reading."""
        reading["is_on"] = state.state == STATE_ON

        # Check for power monitoring attributes
        if "current_power_w" in state.attributes:
            reading["power_w"] = state.attributes["current_power_w"]

        if "total_energy_kwh" in state.attributes:
            reading["energy_kwh"] = state.attributes["total_energy_kwh"]

        return reading

    def _format_climate_reading(
        self,
        reading: dict[str, Any],
        state: State,
    ) -> dict[str, Any]:
        """Format climate state into reading."""
        # Current temperature
        if "current_temperature" in state.attributes:
            reading["temperature_c"] = state.attributes["current_temperature"]

        # Target temperature
        if "temperature" in state.attributes:
            reading["target_temperature_c"] = state.attributes["temperature"]

        # Is on (based on HVAC mode)
        reading["is_on"] = state.state not in ("off",)

        return reading

    def update_device_mappings(self, mappings: dict[str, str]) -> None:
        """Update device mappings (e.g., after reconfiguration)."""
        old_entities = set(self._device_mappings.keys())
        new_entities = set(mappings.keys())

        self._device_mappings = mappings

        # If tracked entities changed, restart subscription
        if old_entities != new_entities and self._running:
            _LOGGER.info("Device mappings changed, restarting subscription")
            if self._unsubscribe:
                self._unsubscribe()

            self._unsubscribe = async_track_state_change_event(
                self._hass,
                list(mappings.keys()),
                self._handle_state_change,
            )
