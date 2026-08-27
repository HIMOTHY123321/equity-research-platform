"""Setup Episode engine (Phase 9 #3-#4, #8). Groups ledger entries that
likely depend on substantially the same underlying market event, so
dependent observations stop looking like independent evidence.

Deterministic rule (explicitly NOT "blindly group everything within N
bars"): within each (symbol, timeframe, setup_type, direction) group,
sorted chronologically by `candidate_candle_timestamp`, each entry after
the first either joins the immediately preceding entry's episode or starts
a new one:

- STRUCTURAL_REFERENCE: both entries have the same non-null
  (reference_source, reference_timestamp) -- they are anchored to the
  literal same swing/level/zone, the strongest possible evidence they are
  the same event.
- TEMPORAL_PROXIMITY (fallback, eligible only when at least one of the two
  entries has no reference info at all -- several detectors don't set
  reference_timestamp; if BOTH entries have a reference and it differs,
  that is a genuine "different event" signal and is never overridden by
  time proximity): the entries are within that specific setup type's own
  `candidate_expiration_bars` window of each other. This is not an
  arbitrary constant -- it is the exact bar count production code already
  uses to decide how long this setup type's own opportunity window stays
  open (`app.setup_detection.config.get_expiration_bars`), so it is
  detector-native, not invented for this analysis.

Raw `SetupLedgerEntry` rows are never modified, merged, or deleted --
episodes are read-only research output computed from them.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.schemas import EpisodeMembership, SetupEpisode
from app.schemas.market_data import Timeframe
from app.setup_detection.config import (
    DEFAULT_SETUP_DETECTION_CONFIG,
    SetupDetectionConfig,
    get_expiration_bars,
)
from app.setup_detection.detectors._common import bar_duration_seconds
from app.setup_detection.schemas import SetupType

JOIN_ANCHOR = "anchor"
JOIN_STRUCTURAL = "structural_reference"
JOIN_TEMPORAL = "temporal_proximity"


def episode_id(symbol: str, setup_type: str, direction: str, timeframe: str, anchor_setup_id: str) -> str:
    """Deterministic, content-derived -- never a random UUID. Two runs
    grouping the same ledger entries always produce the same episode ID
    for the same anchor member."""
    raw = "|".join([symbol, setup_type, direction, timeframe, anchor_setup_id])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"episode:{setup_type}:{digest}"


def _group_key(entry: SetupLedgerEntry) -> tuple:
    return (entry.symbol, entry.timeframe, entry.setup_type, entry.direction)


def _has_reference(entry: SetupLedgerEntry) -> bool:
    return entry.detection.reference_source is not None and entry.detection.reference_timestamp is not None


def _structural_match(a: SetupLedgerEntry, b: SetupLedgerEntry) -> bool:
    if not (_has_reference(a) and _has_reference(b)):
        return False
    ref_a = a.detection.reference_source, a.detection.reference_timestamp
    ref_b = b.detection.reference_source, b.detection.reference_timestamp
    return ref_a == ref_b


def _temporal_match(prev: SetupLedgerEntry, curr: SetupLedgerEntry, config: SetupDetectionConfig) -> bool:
    try:
        timeframe = Timeframe(curr.timeframe)
        setup_type = SetupType(curr.setup_type)
    except ValueError:
        return False
    window_bars = get_expiration_bars(setup_type.value, config)
    window = timedelta(seconds=bar_duration_seconds(timeframe) * window_bars)
    return curr.candidate_candle_timestamp - prev.candidate_candle_timestamp <= window


def build_episode_memberships(
    entries: list[SetupLedgerEntry], config: SetupDetectionConfig = DEFAULT_SETUP_DETECTION_CONFIG
) -> list[EpisodeMembership]:
    """One membership row per entry, in no particular order. Entries in
    different (symbol, timeframe, setup_type, direction) groups can never
    share an episode."""
    by_group: dict[tuple, list[SetupLedgerEntry]] = {}
    for entry in entries:
        by_group.setdefault(_group_key(entry), []).append(entry)

    memberships: list[EpisodeMembership] = []
    for group_entries in by_group.values():
        ordered = sorted(group_entries, key=lambda e: (e.candidate_candle_timestamp, e.setup_id))
        current_episode_id = None
        for i, entry in enumerate(ordered):
            if i == 0:
                current_episode_id = episode_id(
                    entry.symbol, entry.setup_type, entry.direction, entry.timeframe, entry.setup_id
                )
                memberships.append(
                    EpisodeMembership(
                        setup_id=entry.setup_id, episode_id=current_episode_id, join_basis=JOIN_ANCHOR
                    )
                )
                continue

            prev = ordered[i - 1]
            # The temporal fallback is only eligible when reference info is
            # missing on at least one side -- if both sides HAVE a
            # reference and it differs, that is a genuine "different event"
            # signal and must never be overridden by mere time proximity.
            temporal_eligible = not (_has_reference(prev) and _has_reference(entry))
            if _structural_match(prev, entry):
                memberships.append(
                    EpisodeMembership(
                        setup_id=entry.setup_id, episode_id=current_episode_id, join_basis=JOIN_STRUCTURAL
                    )
                )
            elif temporal_eligible and _temporal_match(prev, entry, config):
                memberships.append(
                    EpisodeMembership(
                        setup_id=entry.setup_id, episode_id=current_episode_id, join_basis=JOIN_TEMPORAL
                    )
                )
            else:
                current_episode_id = episode_id(
                    entry.symbol, entry.setup_type, entry.direction, entry.timeframe, entry.setup_id
                )
                memberships.append(
                    EpisodeMembership(
                        setup_id=entry.setup_id, episode_id=current_episode_id, join_basis=JOIN_ANCHOR
                    )
                )

    return memberships


def _representative_setup_id(members: list[SetupLedgerEntry]) -> str:
    """(Phase 9 #8) Deterministic rule, fixed at detection time: the first
    QUALIFIED member if one exists, else the episode's first (earliest)
    member overall. Never chosen by which member later produced the best
    outcome -- outcomes are not consulted here at all."""
    ordered = sorted(members, key=lambda e: (e.candidate_candle_timestamp, e.setup_id))
    first_qualified = next((e for e in ordered if e.detection.current_state == "qualified"), None)
    return (first_qualified or ordered[0]).setup_id


def build_episodes(
    entries: list[SetupLedgerEntry], config: SetupDetectionConfig = DEFAULT_SETUP_DETECTION_CONFIG
) -> list[SetupEpisode]:
    memberships = build_episode_memberships(entries, config)
    entry_by_id = {e.setup_id: e for e in entries}
    episode_to_setup_ids: dict[str, list[str]] = {}
    for m in memberships:
        episode_to_setup_ids.setdefault(m.episode_id, []).append(m.setup_id)

    episodes: list[SetupEpisode] = []
    for ep_id, setup_ids in episode_to_setup_ids.items():
        members = [entry_by_id[sid] for sid in setup_ids]
        ordered = sorted(members, key=lambda e: (e.candidate_candle_timestamp, e.setup_id))
        anchor = ordered[0]
        episodes.append(
            SetupEpisode(
                episode_id=ep_id,
                setup_type=anchor.setup_type,
                direction=anchor.direction,
                symbol=anchor.symbol,
                timeframe=anchor.timeframe,
                member_setup_ids=[e.setup_id for e in ordered],
                first_detected_at=ordered[0].candidate_candle_timestamp,
                last_member_at=ordered[-1].candidate_candle_timestamp,
                reference_source=anchor.detection.reference_source,
                reference_timestamp=anchor.detection.reference_timestamp,
                qualification_states_represented=sorted({e.detection.current_state for e in ordered}),
                raw_observation_count=len(ordered),
                representative_setup_id=_representative_setup_id(ordered),
            )
        )
    return episodes


def episode_by_setup_id(episodes: list[SetupEpisode]) -> dict[str, SetupEpisode]:
    result: dict[str, SetupEpisode] = {}
    for ep in episodes:
        for sid in ep.member_setup_ids:
            result[sid] = ep
    return result
