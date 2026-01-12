"""Telemetry push service for Ampæra HA integration.

Listens for Home Assistant state changes and pushes telemetry
to the Ampæra cloud platform.

Supports entity-to-device mapping where multiple HA entities
(sensors) are grouped under a single parent device.

Works with both real hardware integrations (e.g., Tibber, Easee, Shelly)
and simulated/demo devices (e.g., template sensors, input helpers) to
support development and demo environments.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
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
    from .event_service import AmperaEventService

_LOGGER = logging.getLogger(__name__)

# Debounce interval for batching state changes
DEFAULT_DEBOUNCE_SECONDS = 2.0

# Maximum batch size before forcing a push
MAX_BATCH_SIZE = 50

# Heartbeat interval for periodic push (ensures data flows even without state changes)
DEFAULT_HEARTBEAT_SECONDS = 30.0


@dataclass
class EntityMapping:
    """Mapping info for a single HA entity.

    Maps an HA entity_id to its parent Ampæra device and capability.
    """

    device_id: str  # Ampæra device UUID
    capability: str  # Capability this entity provides (power, voltage_l1, etc.)
    ha_device_id: str  # HA device registry ID (parent device)


class AmperaTelemetryPushService:
    """Push Home Assistant state changes to Ampæra.

    Features:
    - Listens for state changes on tracked entities
    - Maps entities to their parent devices and capabilities
    - Debounces rapid changes to reduce API calls
    - Batches multiple readings into single requests
    - Handles connection errors gracefully
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: AmperaApiClient,
        site_id: str,
        entity_mappings: dict[str, EntityMapping],
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        event_service: AmperaEventService | None = None,
    ) -> None:
        """Initialize the push service.

        Args:
            hass: Home Assistant instance
            api_client: Ampæra API client
            site_id: Ampæra site UUID
            entity_mappings: Mapping of HA entity_id → EntityMapping
            debounce_seconds: Seconds to wait before pushing batched changes
            heartbeat_seconds: Seconds between periodic heartbeat pushes
            event_service: Optional event service for state change reporting
        """
        self._hass = hass
        self._api = api_client
        self._site_id = site_id
        self._entity_mappings = entity_mappings
        self._debounce_seconds = debounce_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._event_service = event_service

        # Pending readings to push (keyed by device_id to dedupe)
        # Each device accumulates readings from multiple entities
        self._pending_readings: dict[str, dict[str, Any]] = {}
        self._pending_lock = asyncio.Lock()

        # Debounce timer
        self._debounce_task: asyncio.Task | None = None

        # Heartbeat timer for periodic push
        self._heartbeat_task: asyncio.Task | None = None

        # Unsubscribe callback
        self._unsubscribe: callable | None = None

        # Service state
        self._running = False

        # Track previous on/off states for state change detection
        self._previous_is_on: dict[str, bool | None] = {}

        # Build device → on_off entity mapping for including is_on in sensor readings
        self._device_on_off_entities: dict[str, str] = self._build_device_on_off_map()

    def _build_device_on_off_map(self) -> dict[str, str]:
        """Build mapping of device_id → on_off entity_id.

        This enables sensor readings to include is_on state from the
        associated switch/control entity, which is essential for devices
        where sensors and switches are separate HA entities (e.g., template
        sensors + template switches in simulation).
        """
        device_on_off: dict[str, str] = {}
        for entity_id, mapping in self._entity_mappings.items():
            if mapping.capability == "on_off":
                device_on_off[mapping.device_id] = entity_id
        return device_on_off

    @property
    def is_running(self) -> bool:
        """Return whether the service is running."""
        return self._running

    @property
    def tracked_entities(self) -> list[str]:
        """Return list of tracked entity IDs."""
        return list(self._entity_mappings.keys())

    @classmethod
    def from_device_mappings(
        cls,
        hass: HomeAssistant,
        api_client: AmperaApiClient,
        site_id: str,
        device_mappings: dict[str, dict],
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    ) -> AmperaTelemetryPushService:
        """Create push service from device mappings response.

        Args:
            hass: Home Assistant instance
            api_client: Ampæra API client
            site_id: Ampæra site UUID
            device_mappings: Dict of ha_device_id → {
                "device_id": ampera_device_id,
                "entity_mapping": {capability: entity_id}
            }
            debounce_seconds: Seconds to wait before pushing batched changes

        Returns:
            Configured push service instance
        """
        entity_mappings: dict[str, EntityMapping] = {}

        for ha_device_id, device_info in device_mappings.items():
            ampera_device_id = device_info.get("device_id", "")
            entity_mapping = device_info.get("entity_mapping", {})

            # Create EntityMapping for each entity in the device
            for capability, entity_id in entity_mapping.items():
                entity_mappings[entity_id] = EntityMapping(
                    device_id=ampera_device_id,
                    capability=capability,
                    ha_device_id=ha_device_id,
                )

        return cls(
            hass=hass,
            api_client=api_client,
            site_id=site_id,
            entity_mappings=entity_mappings,
            debounce_seconds=debounce_seconds,
        )

    async def async_start(self) -> None:
        """Start listening for state changes."""
        if self._running:
            _LOGGER.warning("Push service already running")
            return

        _LOGGER.info(
            "Starting telemetry push service for site %s with %d entities (heartbeat: %.0fs)",
            self._site_id,
            len(self._entity_mappings),
            self._heartbeat_seconds,
        )

        # Subscribe to state changes for tracked entities
        self._unsubscribe = async_track_state_change_event(
            self._hass,
            list(self._entity_mappings.keys()),
            self._handle_state_change,
        )

        self._running = True

        # Push initial states
        await self._push_initial_states()

        # Start heartbeat for periodic pushes (ensures data flows even without changes)
        # Use background task so it doesn't block HA startup completion
        self._heartbeat_task = self._hass.async_create_background_task(
            self._run_heartbeat(), "ampaera_telemetry_heartbeat"
        )

    async def async_stop(self) -> None:
        """Stop the push service."""
        if not self._running:
            return

        _LOGGER.info("Stopping telemetry push service")

        # Cancel heartbeat timer
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

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

    async def async_push_now(self) -> None:
        """Trigger an immediate telemetry push (for service call).

        Collects current states from all tracked entities and pushes immediately.
        """
        _LOGGER.info("Manual telemetry push triggered")

        if not self._entity_mappings:
            _LOGGER.warning("No entities to push")
            return

        # Collect current states
        for entity_id, mapping in self._entity_mappings.items():
            state = self._hass.states.get(entity_id)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                reading = self._format_reading(entity_id, state, mapping)
                if reading:
                    async with self._pending_lock:
                        if mapping.device_id not in self._pending_readings:
                            self._pending_readings[mapping.device_id] = {
                                "device_id": mapping.device_id
                            }
                        self._pending_readings[mapping.device_id].update(reading)

        # Push immediately
        await self._flush_pending()

    async def _push_initial_states(self) -> None:
        """Push current states of all tracked entities."""
        for entity_id, mapping in self._entity_mappings.items():
            state = self._hass.states.get(entity_id)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                reading = self._format_reading(entity_id, state, mapping)
                if reading:
                    # Merge reading into device's pending readings
                    async with self._pending_lock:
                        if mapping.device_id not in self._pending_readings:
                            self._pending_readings[mapping.device_id] = {
                                "device_id": mapping.device_id
                            }
                        self._pending_readings[mapping.device_id].update(reading)

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

        mapping = self._entity_mappings.get(entity_id)
        if not mapping:
            _LOGGER.warning("No entity mapping for %s", entity_id)
            return

        # Format reading with capability info
        reading = self._format_reading(entity_id, new_state, mapping)
        if not reading:
            return

        # Detect on/off state changes for event reporting
        if self._event_service and "is_on" in reading:
            new_is_on = reading["is_on"]
            device_id = mapping.device_id

            # Get previous state from our tracking
            old_is_on = self._previous_is_on.get(device_id)

            # Update our tracking
            self._previous_is_on[device_id] = new_is_on

            # Report state change if it actually changed
            if old_is_on is not None and old_is_on != new_is_on:
                # Extract power if available
                power_w = reading.get("power_w")

                # Classify the source from HA event context
                ha_source = self._event_service.classify_source(event.context)

                # Get user_id if present
                user_id = event.context.user_id if event.context else None

                # Report the state change event asynchronously
                self._hass.async_create_task(
                    self._event_service.report_state_change(
                        device_id=device_id,
                        old_state=old_is_on,
                        new_state=new_is_on,
                        ha_source=ha_source,
                        power_w=power_w,
                        user_id=user_id,
                    )
                )

        # Add to pending (async)
        self._hass.async_create_task(self._add_pending_reading(mapping.device_id, reading))

    async def _add_pending_reading(
        self,
        device_id: str,
        reading: dict[str, Any],
    ) -> None:
        """Add a reading to the pending batch.

        Readings for the same device are merged (multiple entities
        contribute to a single device's state).
        """
        async with self._pending_lock:
            if device_id not in self._pending_readings:
                self._pending_readings[device_id] = {"device_id": device_id}
            # Merge new reading into existing
            self._pending_readings[device_id].update(reading)

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

        self._debounce_task = self._hass.async_create_background_task(
            self._debounced_push(), "ampaera_telemetry_debounce"
        )

    async def _debounced_push(self) -> None:
        """Wait for debounce period then push."""
        await asyncio.sleep(self._debounce_seconds)
        await self._flush_pending()

    async def _run_heartbeat(self) -> None:
        """Periodically push current states regardless of changes.

        This ensures telemetry data flows continuously even when sensor
        values don't change (common in simulated/demo environments).
        """
        while self._running:
            await asyncio.sleep(self._heartbeat_seconds)
            if not self._running:
                break

            _LOGGER.debug("Heartbeat: pushing current states")
            await self.async_push_now()

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
        mapping: EntityMapping,
    ) -> dict[str, Any] | None:
        """Format a state into a telemetry reading.

        Uses the capability from the mapping to determine which
        field to populate. Returns dict with measurements, or None if invalid.
        """
        reading: dict[str, Any] = {
            "ha_entity_id": entity_id,
            "capability": mapping.capability,
        }
        domain = entity_id.split(".")[0]

        # Handle based on domain - capability determines the field to update
        if domain == "sensor":
            reading = self._format_sensor_reading(reading, state, mapping)
        elif domain == "water_heater":
            reading = self._format_water_heater_reading(reading, state)
        elif domain == "switch":
            reading = self._format_switch_reading(reading, state)
        elif domain == "climate":
            reading = self._format_climate_reading(reading, state)

        # Only return if we have actual measurements (more than just metadata)
        if len(reading) > 2:  # More than just ha_entity_id and capability
            return reading
        return None

    def _format_sensor_reading(
        self,
        reading: dict[str, Any],
        state: State,
        mapping: EntityMapping,
    ) -> dict[str, Any]:
        """Format sensor state into reading.

        Uses the capability to determine which field to populate,
        supporting phase-specific readings (voltage_l1, l2, l3, etc.).

        Also includes is_on state from associated on_off entity if available,
        which is essential for devices where sensors and switches are separate
        HA entities (e.g., template sensors + template switches in simulation).
        """
        capability = mapping.capability

        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return reading

        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")

        # Include is_on from associated switch entity if available
        # This enables state change detection for sensor-based readings
        on_off_entity_id = self._device_on_off_entities.get(mapping.device_id)
        if on_off_entity_id:
            on_off_state = self._hass.states.get(on_off_entity_id)
            if on_off_state and on_off_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                reading["is_on"] = on_off_state.state == STATE_ON

        # Map capability to the correct reading field
        if capability == "power":
            # Convert to watts if needed
            if unit == "kW":
                value *= 1000
            reading["power_w"] = value

        elif capability == "power_l1":
            # Phase-specific power (L1)
            if unit == "kW":
                value *= 1000
            reading["power_l1_w"] = value

        elif capability == "power_l2":
            # Phase-specific power (L2)
            if unit == "kW":
                value *= 1000
            reading["power_l2_w"] = value

        elif capability == "power_l3":
            # Phase-specific power (L3)
            if unit == "kW":
                value *= 1000
            reading["power_l3_w"] = value

        elif capability == "energy":
            # Convert to kWh if needed
            if unit == "Wh":
                value /= 1000
            elif unit == "MWh":
                value *= 1000
            reading["energy_kwh"] = value

        elif capability == "energy_import":
            if unit == "Wh":
                value /= 1000
            elif unit == "MWh":
                value *= 1000
            reading["energy_import_kwh"] = value

        elif capability == "energy_export":
            if unit == "Wh":
                value /= 1000
            elif unit == "MWh":
                value *= 1000
            reading["energy_export_kwh"] = value

        elif capability in ("voltage", "voltage_l1"):
            reading["voltage_l1"] = value
        elif capability == "voltage_l2":
            reading["voltage_l2"] = value
        elif capability == "voltage_l3":
            reading["voltage_l3"] = value

        elif capability in ("current", "current_l1"):
            reading["current_l1"] = value
        elif capability == "current_l2":
            reading["current_l2"] = value
        elif capability == "current_l3":
            reading["current_l3"] = value

        elif capability == "temperature":
            reading["temperature_c"] = value

        elif capability == "session_energy":
            if unit == "Wh":
                value /= 1000
            elif unit == "MWh":
                value *= 1000
            reading["session_energy_kwh"] = value

        elif capability == "charge_limit":
            reading["charge_limit_a"] = int(value)

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

    def update_entity_mappings(self, entity_mappings: dict[str, EntityMapping]) -> None:
        """Update entity mappings (e.g., after reconfiguration)."""
        old_entities = set(self._entity_mappings.keys())
        new_entities = set(entity_mappings.keys())

        self._entity_mappings = entity_mappings

        # Rebuild device → on_off entity map
        self._device_on_off_entities = self._build_device_on_off_map()

        # If tracked entities changed, restart subscription
        if old_entities != new_entities and self._running:
            _LOGGER.info("Entity mappings changed, restarting subscription")
            if self._unsubscribe:
                self._unsubscribe()

            self._unsubscribe = async_track_state_change_event(
                self._hass,
                list(entity_mappings.keys()),
                self._handle_state_change,
            )
