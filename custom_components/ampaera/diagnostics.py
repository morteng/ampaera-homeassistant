"""Diagnostics support for Ampaera Energy integration.

Provides debug information for troubleshooting via Home Assistant's
Developer Tools → Diagnostics. Sensitive data is redacted automatically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY

from .const import (
    CONF_API_URL,
    CONF_DEVICE_MAPPINGS,
    CONF_GRID_REGION,
    CONF_HA_INSTANCE_ID,
    CONF_SELECTED_ENTITIES,
    CONF_SITE_ID,
    CONF_SITE_NAME,
    DOMAIN,
    INTEGRATION_VERSION,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

# Keys to redact from diagnostics output
TO_REDACT = {
    CONF_API_KEY,
    "api_key",
    "token",
    "password",
    "secret",
}

# Keys to partially redact (show first/last chars)
TO_PARTIAL_REDACT = {
    CONF_SITE_ID,
    CONF_HA_INSTANCE_ID,
}


def _partial_redact(value: str, visible_chars: int = 4) -> str:
    """Partially redact a string, showing first and last chars."""
    if len(value) <= visible_chars * 2:
        return "***"
    return f"{value[:visible_chars]}...{value[-visible_chars:]}"


def _redact_device_mappings(mappings: dict[str, str]) -> dict[str, str]:
    """Redact device IDs but preserve structure."""
    return {_partial_redact(k): _partial_redact(v) for k, v in mappings.items()}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    This is called when a user exports diagnostics from the integration page.
    """
    # Get coordinator from hass.data
    coordinator = None
    push_service = None
    command_service = None
    device_sync_service = None

    if DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]:
        entry_data = hass.data[DOMAIN][config_entry.entry_id]
        coordinator = entry_data.get("coordinator")
        push_service = entry_data.get("push_service")
        command_service = entry_data.get("command_service")
        device_sync_service = entry_data.get("device_sync_service")

    # Build diagnostics data
    diagnostics: dict[str, Any] = {
        "integration": {
            "version": INTEGRATION_VERSION,
            "domain": DOMAIN,
        },
        "config_entry": {
            "entry_id": config_entry.entry_id,
            "version": config_entry.version,
            "domain": config_entry.domain,
            "title": config_entry.title,
            "source": config_entry.source,
            "state": config_entry.state.value if config_entry.state else "unknown",
            "data": {
                CONF_API_URL: config_entry.data.get(CONF_API_URL, "default"),
                CONF_SITE_NAME: config_entry.data.get(CONF_SITE_NAME),
                CONF_GRID_REGION: config_entry.data.get(CONF_GRID_REGION),
                CONF_SITE_ID: _partial_redact(config_entry.data.get(CONF_SITE_ID, "")),
                CONF_HA_INSTANCE_ID: _partial_redact(
                    config_entry.data.get(CONF_HA_INSTANCE_ID, "")
                ),
                "selected_entities_count": len(config_entry.data.get(CONF_SELECTED_ENTITIES, [])),
                "device_mappings_count": len(config_entry.data.get(CONF_DEVICE_MAPPINGS, {})),
            },
            "options": async_redact_data(dict(config_entry.options), TO_REDACT),
        },
    }

    # Add coordinator info if available
    if coordinator:
        diagnostics["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "last_update_time": (
                coordinator.last_update_success_time.isoformat()
                if hasattr(coordinator, "last_update_success_time")
                and coordinator.last_update_success_time
                else None
            ),
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds() if coordinator.update_interval else None
            ),
            "site_id": _partial_redact(coordinator.site_id or ""),
            "site_name": coordinator.site_name,
        }

        # Add telemetry sample (redacted)
        if hasattr(coordinator, "data") and coordinator.data:
            telemetry = coordinator.data
            diagnostics["coordinator"]["telemetry_sample"] = {
                "has_power": "power_w" in telemetry or "power" in telemetry,
                "has_energy": "energy_today_kwh" in telemetry or "today_kwh" in telemetry,
                "has_voltage": any(k.startswith("voltage") for k in telemetry),
                "has_current": any(k.startswith("current") for k in telemetry),
                "has_cost": "cost_today" in telemetry,
                "has_spot_price": "spot_price" in telemetry,
                "field_count": len(telemetry),
            }

        # Add devices info
        if hasattr(coordinator, "devices_data") and coordinator.devices_data:
            diagnostics["coordinator"]["devices"] = {
                "count": len(coordinator.devices_data),
                "types": list({d.get("device_type", "unknown") for d in coordinator.devices_data}),
            }

    # Add push service info if available
    if push_service:
        diagnostics["push_service"] = {
            "is_running": getattr(push_service, "_running", False),
            "push_interval_seconds": getattr(push_service, "_push_interval", None),
            "last_push_success": getattr(push_service, "_last_push_success", None),
            "consecutive_failures": getattr(push_service, "_consecutive_failures", 0),
        }

    # Add command service info if available
    if command_service:
        diagnostics["command_service"] = {
            "is_running": getattr(command_service, "_running", False),
            "poll_interval_seconds": getattr(command_service, "_poll_interval", None),
            "commands_executed": getattr(command_service, "_commands_executed", 0),
        }

    # Add device sync service info if available
    if device_sync_service:
        diagnostics["device_sync_service"] = {
            "is_running": getattr(device_sync_service, "_running", False),
            "sync_interval_seconds": getattr(device_sync_service, "_sync_interval", None),
            "last_sync_success": getattr(device_sync_service, "_last_sync_success", None),
            "devices_synced": getattr(device_sync_service, "_devices_synced", 0),
        }

    # Add Home Assistant info
    diagnostics["home_assistant"] = {
        "version": getattr(hass.config, "version", "unknown"),
        "timezone": str(getattr(hass.config, "time_zone", "UTC")),
        "location_name": getattr(hass.config, "location_name", "unknown"),
        "unit_system": (
            getattr(hass.config.units, "name", "metric")
            if hasattr(hass.config, "units")
            else "metric"
        ),
    }

    return diagnostics
