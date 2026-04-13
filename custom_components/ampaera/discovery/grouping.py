"""Device grouping for the Ampæra picker.

Users with multi-channel energy meters (e.g. em16 with 18 circuits) see
dozens of near-identical devices in the picker. This module collapses
those into a single *device group*, shown as one checkbox in the form.

The grouping is a pure post-processing step over classified devices —
it does not change how devices are discovered, stored, or synced. When
the user selects a group, we expand it back to the underlying member
device IDs before persisting the selection.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .models import AmperaDeviceType, DiscoveredDevice

# Prefix used to distinguish group option values from raw device IDs in
# the HA form payload. Device IDs are HA-generated UUIDs, so "group:" is
# guaranteed not to collide with a real ha_device_id.
GROUP_ID_PREFIX = "group:"

# Minimum number of similar devices required to form a group. Below this
# threshold we show devices individually — grouping two items adds more
# confusion than it saves.
GROUP_MIN_SIZE = 3

# Strip trailing channel/circuit identifiers from a device name so that
# multi-channel meters cluster regardless of how the integration formats
# their per-channel labels. We handle:
#   - parenthetical: "em16 (A1)", "em16 (C6)", "em16 (CH_12)"
#   - dash/underscore phase: "em16-phase-2", "em16_phase_2"
#   - dash/underscore channel: "em16-CH3", "em16_ch_3"
#   - dash/underscore bank+digit: "em16 A1", "em16-A1", "em16_C6"
#   - trailing pure digits: "em16 1", "em16-2"
# Patterns are applied iteratively so a name like "em16_phase_2 (A1)"
# strips to "em16" via two rounds.
_TRAILING_SUFFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\s*\([^)]*\)\s*$"),                  # "(...)"
    re.compile(r"[\s_-]*phase[\s_-]*\d+\s*$", re.I),  # "phase 2", "_phase_2"
    re.compile(r"[\s_-]*ch(annel)?[\s_-]*\d+\s*$", re.I),  # "CH3", "channel 1"
    re.compile(r"[\s_-]+[A-Z]\d{1,2}\s*$"),           # " A1", "_C6"
    re.compile(r"[\s_-]+\d+\s*$"),                    # " 1", "-2"
)


@dataclass
class DeviceGroup:
    """A collapsed set of near-identical devices shown as one picker option."""

    group_id: str  # "group:<stable-key>"
    base_name: str  # human-readable base, e.g. "em16"
    device_type: AmperaDeviceType
    member_ids: list[str]
    is_recommended: bool

    @property
    def count(self) -> int:
        return len(self.member_ids)


def _base_name(display: str) -> str:
    """Strip channel/circuit suffixes from a display name.

    Iteratively applies known suffix patterns so multi-channel meters
    with hybrid naming (parenthetical + suffix, etc.) collapse to the
    same base. Stops when no further substitution shortens the name —
    avoids infinite loops on degenerate inputs.
    """
    cleaned = display.strip()
    for _ in range(4):
        prev = cleaned
        for pattern in _TRAILING_SUFFIX_PATTERNS:
            cleaned = pattern.sub("", cleaned).strip()
        if cleaned == prev or not cleaned:
            break
    return cleaned or display.strip()


def _group_key(device: DiscoveredDevice) -> tuple[str, AmperaDeviceType, str, str]:
    base = _base_name(device.display_name()).lower()
    return (
        base,
        device.device_type,
        (device.manufacturer or "").lower(),
        (device.model or "").lower(),
    )


def group_similar_devices(
    devices: list[DiscoveredDevice],
) -> tuple[list[DeviceGroup], list[DiscoveredDevice]]:
    """Collapse ≥GROUP_MIN_SIZE devices sharing base name+type+model into groups.

    Returns:
        (groups, ungrouped) — ``ungrouped`` contains devices that did not
        meet the group threshold and should be rendered individually. The
        relative order of ungrouped devices matches the input.
    """
    buckets: dict[tuple[str, AmperaDeviceType, str, str], list[DiscoveredDevice]] = (
        defaultdict(list)
    )
    order: dict[tuple[str, AmperaDeviceType, str, str], int] = {}
    for idx, device in enumerate(devices):
        key = _group_key(device)
        if key not in order:
            order[key] = idx
        buckets[key].append(device)

    groups: list[DeviceGroup] = []
    ungrouped: list[DiscoveredDevice] = []
    for key, members in buckets.items():
        base, dtype, mfr, model = key
        if len(members) >= GROUP_MIN_SIZE:
            display_base = _base_name(members[0].display_name()) or base
            stable_key = "|".join((base, dtype.value, mfr, model))
            groups.append(
                DeviceGroup(
                    group_id=f"{GROUP_ID_PREFIX}{stable_key}",
                    base_name=display_base,
                    device_type=dtype,
                    member_ids=[d.ha_device_id for d in members],
                    is_recommended=any(d.is_recommended for d in members),
                )
            )
        else:
            ungrouped.extend(members)

    # Preserve input ordering for ungrouped devices by sorting on first-seen index.
    ungrouped.sort(key=lambda d: order[_group_key(d)])
    return groups, ungrouped


def expand_group_selections(
    selected: list[str],
    groups: list[DeviceGroup],
) -> list[str]:
    """Expand any group IDs in the selection to their member device IDs.

    Raw device IDs in ``selected`` pass through unchanged. Unknown group
    IDs are dropped silently — they usually indicate a stale form submission
    after the grouping changed.
    """
    group_by_id = {g.group_id: g for g in groups}
    out: list[str] = []
    seen: set[str] = set()
    for sel in selected:
        if sel.startswith(GROUP_ID_PREFIX):
            group = group_by_id.get(sel)
            if group is None:
                continue
            for member_id in group.member_ids:
                if member_id not in seen:
                    out.append(member_id)
                    seen.add(member_id)
        elif sel not in seen:
            out.append(sel)
            seen.add(sel)
    return out


def collapse_to_group_ids(
    selected: list[str],
    groups: list[DeviceGroup],
) -> list[str]:
    """Collapse selected group members back to their group ID.

    Used when rendering the form with a pre-existing selection: when any
    member of a group is in ``selected`` we replace **all** member IDs
    with the single group ID. The picker can't show partial selection
    on a group anyway — it's a single checkbox — so partial historical
    selections (e.g. from before grouping existed, when the user had
    cherry-picked 5 of 54 em16 channels) get promoted to "the whole
    group is selected".

    Devices that are not part of any group pass through unchanged. The
    inverse promotion is acceptable because re-saving the form will
    persist the full member list, and toggling *Show all devices*
    afterwards lets the user prune individual channels again.
    """
    selected_set = set(selected)
    consumed: set[str] = set()
    out: list[str] = []
    for group in groups:
        member_ids = group.member_ids or []
        if any(member_id in selected_set for member_id in member_ids):
            out.append(group.group_id)
            consumed.update(member_ids)
    for sel in selected:
        if sel in consumed:
            continue
        out.append(sel)
    return out
