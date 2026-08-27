"""Zone lifecycle state and freshness.

Anchored ONLY on the zone-eligible candle slice (candles from the zone's own
`known_at` through `as_of`, completed bars only) -- never on a raw
as-of-truncated series that might incidentally include a still-forming
trailing candle. That inconsistency is exactly the bug Phase 4's freshness
calculation had; see docs/decisions/0004 for the postmortem. Because the
caller already filters `zone_candles` to that exact eligible slice,
`bars_since_created` is simply `len(zone_candles) - 1` -- no special-casing
needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.schemas.market_data import Candle
from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.schemas import (
    BreakEvent,
    InteractionType,
    ZoneFreshness,
    ZoneInteraction,
    ZoneLifecycle,
)


def _bars_since(zone_candles: list[Candle], target_timestamp: Optional[datetime]) -> Optional[int]:
    if target_timestamp is None:
        return None
    for idx in range(len(zone_candles) - 1, -1, -1):
        if zone_candles[idx].timestamp == target_timestamp:
            return (len(zone_candles) - 1) - idx
    return None


def compute_freshness(
    zone_candles: list[Candle],
    interactions: list[ZoneInteraction],
    break_event: Optional[BreakEvent],
) -> ZoneFreshness:
    independent = [i for i in interactions if i.is_independent]
    last_touch = independent[-1].timestamp if independent else None
    rejections = [i for i in independent if i.interaction_type == InteractionType.REJECTION]
    last_rejection = rejections[-1].timestamp if rejections else None

    return ZoneFreshness(
        bars_since_created=(len(zone_candles) - 1) if zone_candles else None,
        bars_since_last_touch=_bars_since(zone_candles, last_touch),
        bars_since_last_rejection=_bars_since(zone_candles, last_rejection),
        bars_since_break=_bars_since(zone_candles, break_event.first_broken_at if break_event else None),
    )


def determine_lifecycle(
    freshness: ZoneFreshness,
    independent_interaction_count: int,
    is_broken: bool,
    config: SupportResistanceConfig,
) -> ZoneLifecycle:
    if is_broken:
        return ZoneLifecycle.BROKEN

    bars_since_last = (
        freshness.bars_since_last_touch
        if freshness.bars_since_last_touch is not None
        else freshness.bars_since_created
    )
    if bars_since_last is not None and bars_since_last > config.stale_after_bars:
        return ZoneLifecycle.STALE

    if independent_interaction_count >= config.weakened_after_independent_interactions:
        return ZoneLifecycle.WEAKENED

    if independent_interaction_count >= 1:
        return ZoneLifecycle.TESTED

    return ZoneLifecycle.ACTIVE
