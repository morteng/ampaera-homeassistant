"""HA Repairs integration for Ampæra discovery issues."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .discovery.models import DiscoveryReport

_LOGGER = logging.getLogger(__name__)


async def async_create_repair_issues(
    hass: HomeAssistant,
    report: DiscoveryReport,
) -> None:
    """Create or clear HA Repair issues based on discovery report."""

    # Auto-enabled entities
    if report.auto_enabled_entities:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id="entities_auto_enabled",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="entities_auto_enabled",
            translation_placeholders={
                "count": str(len(report.auto_enabled_entities)),
                "entities": ", ".join(report.auto_enabled_entities[:10]),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "entities_auto_enabled")

    # Unmapped entities
    if report.unmapped_entities:
        ir.async_create_issue(
            hass,
            domain=DOMAIN,
            issue_id="unmapped_entities",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="unmapped_entities",
            translation_placeholders={
                "count": str(len(report.unmapped_entities)),
                "entities": ", ".join(e.entity_id for e in report.unmapped_entities[:10]),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "unmapped_entities")
