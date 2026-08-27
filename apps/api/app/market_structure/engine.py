"""The single entry point: Candle[] -> MarketStructureSnapshot.

Same as-of/no-lookahead discipline as the Phase 3 feature engine, enforced
independently here (see common.py) — this package intentionally does not
import from app.features, per the "keep the two engines separate" scope
rule for this phase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.market_structure.breaks import apply_break_state, detect_breaks_of_structure
from app.market_structure.choch import detect_changes_of_character
from app.market_structure.classification import classify_swings, classify_trend
from app.market_structure.common import completed_only, truncate_to_as_of
from app.market_structure.config import DEFAULT_MARKET_STRUCTURE_CONFIG, MarketStructureConfig
from app.market_structure.freshness import compute_freshness
from app.market_structure.ranges import compute_active_range
from app.market_structure.schemas import (
    BreakOfStructureEvent,
    Direction,
    MarketStructureSnapshot,
    StructureDataQuality,
    SwingPoint,
    SwingType,
)
from app.market_structure.swings import detect_swings
from app.schemas.market_data import Candle, Timeframe


def compute_market_structure_snapshot(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    as_of: datetime,
    config: MarketStructureConfig = DEFAULT_MARKET_STRUCTURE_CONFIG,
) -> MarketStructureSnapshot:
    truncated, future_dropped = truncate_to_as_of(candles, as_of)
    completed = completed_only(truncated, as_of)

    warnings: list[str] = []
    if future_dropped:
        warnings.append(f"Dropped {future_dropped} candle(s) timestamped after as_of")

    swing_result = detect_swings(completed, config)
    classified = classify_swings(swing_result.confirmed, config)

    bos_events = detect_breaks_of_structure(completed, classified, config)
    classified = apply_break_state(classified, bos_events)
    choch_events = detect_changes_of_character(completed, classified, config)

    trend = classify_trend(sorted(classified, key=lambda s: s.pivot_timestamp), config)

    latest_price = truncated[-1].close if truncated else None
    active_range = compute_active_range(classified, latest_price)

    latest_swing_high = _latest_swing(classified, SwingType.HIGH)
    latest_swing_low = _latest_swing(classified, SwingType.LOW)
    latest_hh = _latest_classified(classified, "higher_high")
    latest_hl = _latest_classified(classified, "higher_low")
    latest_lh = _latest_classified(classified, "lower_high")
    latest_ll = _latest_classified(classified, "lower_low")

    latest_bullish_bos = _latest_bos(bos_events, Direction.BULLISH)
    latest_bearish_bos = _latest_bos(bos_events, Direction.BEARISH)
    latest_choch = choch_events[-1] if choch_events else None

    # Anchored on `completed`, not `truncated`: a still-forming trailing
    # candle may or may not be present in the raw fetch depending on
    # incidental data availability, and freshness must not depend on that --
    # only on as_of and the stable completed-candle series everything else
    # in this snapshot is computed from.
    freshness = compute_freshness(
        completed,
        latest_swing_high,
        latest_swing_low,
        latest_bullish_bos,
        latest_bearish_bos,
        latest_choch,
    )

    if not completed:
        warnings.append("No completed candles available")
    min_required = config.left_bars + config.right_bars + 1
    if 0 < len(completed) < min_required:
        warnings.append(f"Fewer than {min_required} completed candles available for swing detection")

    data_quality = StructureDataQuality(
        source_timeframe=timeframe,
        candle_count=len(truncated),
        completed_candle_count=len(completed),
        earliest_candle_timestamp=truncated[0].timestamp if truncated else None,
        latest_candle_timestamp=truncated[-1].timestamp if truncated else None,
        confirmed_swing_count=len(classified),
        candidate_swing_count=len(swing_result.candidates),
        future_candles_dropped=future_dropped,
        warnings=warnings,
    )

    recent_swings = sorted(classified, key=lambda s: s.pivot_timestamp)[-config.max_swings_in_snapshot :]
    recent_bos = bos_events[-config.max_events_in_snapshot :]
    recent_choch = choch_events[-config.max_events_in_snapshot :]

    return MarketStructureSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        as_of=as_of,
        trend=trend,
        swings=recent_swings,
        candidate_swings=swing_result.candidates,
        latest_swing_high=latest_swing_high,
        latest_swing_low=latest_swing_low,
        latest_higher_high=latest_hh,
        latest_higher_low=latest_hl,
        latest_lower_high=latest_lh,
        latest_lower_low=latest_ll,
        breaks_of_structure=recent_bos,
        changes_of_character=recent_choch,
        active_range=active_range,
        freshness=freshness,
        data_quality=data_quality,
    )


def _latest_swing(swings: list[SwingPoint], swing_type: SwingType) -> Optional[SwingPoint]:
    candidates = [s for s in swings if s.type == swing_type]
    return max(candidates, key=lambda s: s.pivot_timestamp) if candidates else None


def _latest_classified(swings: list[SwingPoint], classification: str) -> Optional[SwingPoint]:
    candidates = [
        s for s in swings if s.classification is not None and s.classification.value == classification
    ]
    return max(candidates, key=lambda s: s.pivot_timestamp) if candidates else None


def _latest_bos(
    events: list[BreakOfStructureEvent], direction: Direction
) -> Optional[BreakOfStructureEvent]:
    candidates = [e for e in events if e.direction == direction]
    return max(candidates, key=lambda e: e.break_timestamp) if candidates else None
