"""Stage 4: Split multi-channel devices into per-channel devices.

Multi-channel devices (e.g., Refoss EM16 with A1/B1 channels) expose
multiple entities for the same capability.  This stage detects such
devices and splits them into separate ``DiscoveredDevice`` instances,
one per channel.
"""

from __future__ import annotations

import logging

from .models import (
    DiscoveredDevice,
    DiscoveredEntity,
    DiscoveryReport,
    SplitDetail,
)

_LOGGER = logging.getLogger(__name__)


class ChannelSplitter:
    """Stage 4: Split multi-channel devices into per-channel devices."""

    def split(
        self,
        devices: list[DiscoveredDevice],
        report: DiscoveryReport,
    ) -> list[DiscoveredDevice]:
        """Split multi-channel devices.  Returns expanded device list.

        Safeguards:
        - Requires at least 2 capabilities with duplicate entities
        - Entity names must show a clear channel naming pattern
          (a1/b1, 1/2, ch1/ch2)
        - Single accidental duplicates do not trigger splitting

        Updates *report* with split statistics.
        """
        result: list[DiscoveredDevice] = []

        for device in devices:
            channel_groups = self._split_into_channels(device, report)

            if len(channel_groups) <= 1:
                # Single-channel device — pass through unchanged.
                result.append(device)
                continue

            # Create one DiscoveredDevice per channel.
            for ch_id, ch_entities in channel_groups:
                caps = list({e.capability for e in ch_entities if e.capability})
                mapping: dict[str, str] = {}
                for e in ch_entities:
                    if e.capability and e.capability.value not in mapping:
                        mapping[e.capability.value] = e.entity_id

                synthetic_id = f"{device.ha_device_id}__ch_{ch_id}"
                channel_name = f"{device.name} ({ch_id.upper()})"

                result.append(
                    DiscoveredDevice(
                        ha_device_id=synthetic_id,
                        name=channel_name,
                        device_type=device.device_type,
                        manufacturer=device.manufacturer,
                        model=device.model,
                        entities=ch_entities,
                        capabilities=caps,
                        entity_mapping=mapping,
                        primary_entity_id=(ch_entities[0].entity_id if ch_entities else ""),
                        classification_reason=device.classification_reason,
                        channel_id=ch_id,
                    )
                )

            report.channel_splits_performed += 1

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_into_channels(
        self,
        device: DiscoveredDevice,
        report: DiscoveryReport,
    ) -> list[tuple[str, list[DiscoveredEntity]]]:
        """Detect and split a device's entities into per-channel groups.

        Returns a list of ``(channel_id, entities)`` tuples.  If the
        device is single-channel, returns a single-element list with a
        ``None``-ish channel id (the caller checks length).
        """
        entities = device.entities

        # Step 1: Group entities by capability.
        capability_entities: dict[str, list[DiscoveredEntity]] = {}
        for entity in entities:
            if entity.capability:
                cap_key = entity.capability.value
                capability_entities.setdefault(cap_key, []).append(entity)

        # Step 2: Find capabilities with multiple entities (duplicates).
        multi_cap = {cap: ents for cap, ents in capability_entities.items() if len(ents) > 1}

        if not multi_cap:
            return [("_single", entities)]

        # Step 3: Safeguard — require >= 2 capabilities with duplicates.
        if len(multi_cap) < 2:
            _LOGGER.debug(
                "Only %d capability with duplicates — not enough evidence "
                "for channel split (capabilities: %s)",
                len(multi_cap),
                list(multi_cap.keys()),
            )
            report.channel_splits_skipped += 1
            report.split_details.append(
                SplitDetail(
                    device_id=device.ha_device_id,
                    action="skipped",
                    reason=(f"Only {len(multi_cap)} capability with duplicates"),
                )
            )
            return [("_single", entities)]

        # Step 4: Safeguard — verify channel naming pattern.
        has_pattern = any(
            self._has_channel_pattern([e.entity_id for e in ents]) for ents in multi_cap.values()
        )
        if not has_pattern:
            _LOGGER.debug(
                "Duplicate capabilities found but no channel naming "
                "pattern detected — treating as single device "
                "(capabilities: %s)",
                list(multi_cap.keys()),
            )
            report.channel_splits_skipped += 1
            report.split_details.append(
                SplitDetail(
                    device_id=device.ha_device_id,
                    action="skipped",
                    reason="No channel naming pattern detected",
                )
            )
            return [("_single", entities)]

        # Step 5: Build direct entity_id → channel_id map from all
        # multi-cap sets.
        direct_map: dict[str, str] = {}
        for _cap, ents in multi_cap.items():
            cap_ids = [e.entity_id for e in ents]
            cap_channels = self._extract_channel_ids(cap_ids)
            direct_map.update(cap_channels)

        channels: dict[str, list[DiscoveredEntity]] = {
            ch_id: [] for ch_id in set(direct_map.values())
        }
        shared_entities: list[DiscoveredEntity] = []

        for entity in entities:
            if entity.entity_id in direct_map:
                channels[direct_map[entity.entity_id]].append(entity)
            else:
                # Unique-capability entity — try token matching.
                entity_name = (
                    entity.entity_id.split(".", 1)[1]
                    if "." in entity.entity_id
                    else entity.entity_id
                )
                entity_name_lower = entity_name.lower()

                matched_channel: str | None = None
                for ch_id in channels:
                    token = ch_id.lower()
                    if (
                        f"_{token}_" in entity_name_lower
                        or entity_name_lower.startswith(f"{token}_")
                        or entity_name_lower.endswith(f"_{token}")
                        or entity_name_lower == token
                    ):
                        matched_channel = ch_id
                        break

                if matched_channel:
                    channels[matched_channel].append(entity)
                else:
                    shared_entities.append(entity)

        # Shared entities go into every channel.
        for ch_id in channels:
            channels[ch_id].extend(shared_entities)

        # Record split detail.
        channel_ids_sorted = sorted(channels.keys())
        report.split_details.append(
            SplitDetail(
                device_id=device.ha_device_id,
                action="split",
                reason=f"Split into {len(channel_ids_sorted)} channels",
                channels=channel_ids_sorted,
            )
        )

        return [(ch_id, ch_entities) for ch_id, ch_entities in sorted(channels.items())]

    # ------------------------------------------------------------------
    # Static helpers (ported from DeviceDiscovery)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_channel_ids(entity_ids: list[str]) -> dict[str, str]:
        """Extract channel identifiers from entity IDs sharing a capability.

        Given ``["sensor.em16_a1_power", "sensor.em16_b1_power"]``,
        identifies the differing underscore-delimited segment(s)
        (``a1``, ``b1``).

        Returns a mapping of ``entity_id -> channel_id``.  Falls back
        to index-based naming (``ch_1``, ``ch_2``) when extraction fails.
        """
        if len(entity_ids) < 2:
            return {entity_ids[0]: "ch_1"} if entity_ids else {}

        # Strip domain prefix.
        names = [eid.split(".", 1)[1] if "." in eid else eid for eid in entity_ids]

        # Split into underscore-delimited segments.
        segmented = [name.split("_") for name in names]

        # Asymmetric naming → fallback.
        if len({len(s) for s in segmented}) > 1:
            return {eid: f"ch_{i + 1}" for i, eid in enumerate(entity_ids)}

        num_segs = len(segmented[0])

        # Positions where segments differ across entities.
        differing_positions = [i for i in range(num_segs) if len({s[i] for s in segmented}) > 1]

        if not differing_positions:
            return {eid: f"ch_{i + 1}" for i, eid in enumerate(entity_ids)}

        # Build channel ID from differing segment positions.
        channel_ids: dict[str, str] = {}
        for eid, segs in zip(entity_ids, segmented, strict=True):
            parts = [segs[pos] for pos in differing_positions]
            cid = "_".join(parts).lower()
            channel_ids[eid] = cid

        if any(not cid for cid in channel_ids.values()):
            return {eid: f"ch_{i + 1}" for i, eid in enumerate(entity_ids)}

        return channel_ids

    @staticmethod
    def _has_channel_pattern(entity_ids: list[str]) -> bool:
        """Check if entity IDs show a clear multi-channel naming pattern.

        Requires that the differing segments are short (<=4 chars) and
        contain a digit — e.g., ``a1``/``b1``, ``1``/``2``,
        ``ch1``/``ch2``.
        """
        if len(entity_ids) < 2:
            return False

        names = [eid.split(".", 1)[1] if "." in eid else eid for eid in entity_ids]
        segmented = [name.split("_") for name in names]

        if len({len(s) for s in segmented}) > 1:
            return False

        num_segs = len(segmented[0])
        differing_positions = [i for i in range(num_segs) if len({s[i] for s in segmented}) > 1]

        if not differing_positions:
            return False

        for pos in differing_positions:
            for segs in segmented:
                token = segs[pos]
                if len(token) > 4 or not any(c.isdigit() for c in token):
                    return False

        return True

    @staticmethod
    def _resolve_base_device_id(device_id: str) -> str:
        """Resolve a (possibly synthetic) device ID to its base device ID.

        Synthetic IDs look like ``"real_device_id__ch_a1"``.  Returns
        the portion before ``__ch_`` if present, otherwise the original.
        """
        marker = "__ch_"
        idx = device_id.find(marker)
        if idx != -1:
            return device_id[:idx]
        return device_id
