"""Telemetry push service for Ampæra HA integration.

Listens for Home Assistant state changes and pushes telemetry
to the Ampæra cloud platform.

Supports entity-to-device mapping where multiple HA entities
(sensors) are grouped under a single parent device.
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

_LOGGER = logging.getLogger(__name__)

# Debounce interval for batching state changes
DEFAULT_DEBOUNCE_SECONDS = 2.0

# Maximum batch size before forcing a push
MAX_BATCH_SIZE = 50


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
    ) -> None:
        """Initialize the push service.

        Args:
            hass: Home Assistant instance
            api_client: Ampæra API client
            site_id: Ampæra site UUID
            entity_mappings: Mapping of HA entity_id → EntityMapping
            debounce_seconds: Seconds to wait before pushing batched changes
        """
        self._hass = hass
        self._api = api_client
        self._site_id = site_id
        self._entity_mappings = entity_mappings
        self._debounce_seconds = debounce_seconds

        # Pending readings to push (keyed by device_id to dedupe)
        # Each device accumulates readings from multiple entities
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
            "Starting telemetry push service for site %s with %d entities",
            self._site_id,
            len(self._entity_mappings),
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

        self._debounce_task = self._hass.async_create_task(self._debounced_push())

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
            reading = self._format_sensor_reading(reading, state, mapping.capability)
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
        capability: str,
    ) -> dict[str, Any]:
        """Format sensor state into reading.

        Uses the capability to determine which field to populate,
        supporting phase-specific readings (voltage_l1, l2, l3, etc.).
        """
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return reading

        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")

        # Map capability to the correct reading field
        if capability == "power":
            # Convert to watts if needed
            if unit == "kW":
                value *= 1000
            reading["power_w"] = value

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
