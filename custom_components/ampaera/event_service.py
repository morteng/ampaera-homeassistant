"""Ampæra Device Event Service.

Reports device events with source attribution to the Ampæra backend.
Events are discrete state changes (power_on, power_off, shower_event)
with context about what triggered the change.

This supplements telemetry-based state detection with explicit source info,
enabling the backend to distinguish between:
- user_manual: User clicked in HA UI or physical device button
- ha_schedule: Time-based scheduled automation
- ha_physics: Physics-based automation (temperature threshold, charge complete)
- shower_event: Hot water usage event
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api import AmperaApiClient

_LOGGER = logging.getLogger(__name__)


class HAEventSource(str, Enum):
    """Source types for HA-initiated device events.

    These map to different triggering mechanisms in Home Assistant.
    """

    USER_MANUAL = "user_manual"
    HA_SCHEDULE = "ha_schedule"
    HA_PHYSICS = "ha_physics"
    SHOWER_EVENT = "shower_event"
    UNKNOWN = "unknown"


class AmperaEventService:
    """Reports device events with source attribution to Ampæra backend.

    This service is used to report discrete state changes with context
    about what triggered them, enabling better source attribution in
    the backend's device_events table.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: AmperaApiClient,
        site_id: str,
    ) -> None:
        """Initialize the event service.

        Args:
            hass: Home Assistant instance
            api_client: Ampæra API client for sending events
            site_id: Ampæra site UUID
        """
        self._hass = hass
        self._api = api_client
        self._site_id = site_id
        self._pending_events: list[dict[str, Any]] = []

    def classify_source(
        self,
        context: Context | None,
        trigger_info: dict[str, Any] | None = None,
    ) -> HAEventSource:
        """Classify the event source from HA context.

        Args:
            context: HA event context containing user_id and parent_id
            trigger_info: Optional trigger information from automation

        Returns:
            HAEventSource enum value indicating the source type
        """
        if context is None:
            return HAEventSource.UNKNOWN

        # If there's a user_id, it's a user action
        if context.user_id is not None:
            return HAEventSource.USER_MANUAL

        # Check trigger info for automation type hints
        if trigger_info:
            platform = trigger_info.get("platform", "")

            # Time-based triggers
            if platform in ("time", "time_pattern", "sun"):
                return HAEventSource.HA_SCHEDULE

            # Template/state triggers are often physics-based
            if platform in ("template", "numeric_state"):
                return HAEventSource.HA_PHYSICS

        # Default to schedule for automations without user_id
        # (most HA automations are scheduled or rule-based)
        return HAEventSource.HA_SCHEDULE

    async def report_state_change(
        self,
        device_id: str,
        old_state: bool | None,
        new_state: bool,
        ha_source: HAEventSource,
        *,
        power_w: float | None = None,
        automation_id: str | None = None,
        automation_alias: str | None = None,
        user_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Report a device state change event.

        Args:
            device_id: Ampæra device UUID
            old_state: Previous on/off state (True=on, False=off, None=unknown)
            new_state: New on/off state (True=on, False=off)
            ha_source: Source that triggered this event
            power_w: Optional power reading at time of event
            automation_id: Optional HA automation ID if triggered by automation
            automation_alias: Optional human-readable automation name
            user_id: Optional HA user ID if triggered by user action
            timestamp: Optional event timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        # Determine event type from state change
        if new_state and (old_state is None or not old_state):
            event_type = "power_on"
        elif not new_state and (old_state is None or old_state):
            event_type = "power_off"
        else:
            event_type = "state_change"

        event = {
            "device_id": device_id,
            "event_type": event_type,
            "timestamp": timestamp.isoformat(),
            "ha_source": ha_source.value,
            "old_state": "on" if old_state else "off" if old_state is not None else None,
            "new_state": "on" if new_state else "off",
        }

        if power_w is not None:
            event["power_w"] = power_w
        if automation_id:
            event["ha_automation_id"] = automation_id
        if automation_alias:
            event["ha_automation_alias"] = automation_alias
        if user_id:
            event["ha_user_id"] = user_id

        await self._send_event(event)

    async def report_shower_event(
        self,
        device_id: str,
        liters: int,
        temp_drop: float,
        *,
        timestamp: datetime | None = None,
    ) -> None:
        """Report a shower usage event.

        Shower events represent hot water usage that causes temperature
        drop in the water heater. This is tracked separately from power
        on/off events for better analytics.

        Args:
            device_id: Ampæra device UUID (water heater)
            liters: Approximate liters of hot water used
            temp_drop: Temperature drop in degrees Celsius
            timestamp: Optional event timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        event = {
            "device_id": device_id,
            "event_type": "shower_event",
            "timestamp": timestamp.isoformat(),
            "ha_source": HAEventSource.SHOWER_EVENT.value,
            "metadata": {
                "liters": liters,
                "temp_drop_c": temp_drop,
            },
        }

        await self._send_event(event)

    async def _send_event(self, event: dict[str, Any]) -> None:
        """Send a single event to the backend.

        Events are sent individually to ensure timely delivery.
        For batch operations, consider using _send_batch.

        Args:
            event: Event dict to send
        """
        try:
            result = await self._api.async_report_events(
                site_id=self._site_id,
                events=[event],
            )
            ingested = result.get("ingested", 0)
            if ingested > 0:
                _LOGGER.debug(
                    "Reported event %s for device %s (source: %s)",
                    event.get("event_type"),
                    event.get("device_id"),
                    event.get("ha_source"),
                )
            else:
                _LOGGER.warning(
                    "Event not ingested: %s for device %s",
                    event.get("event_type"),
                    event.get("device_id"),
                )
        except Exception as err:
            _LOGGER.warning(
                "Failed to report event %s for device %s: %s",
                event.get("event_type"),
                event.get("device_id"),
                err,
            )
