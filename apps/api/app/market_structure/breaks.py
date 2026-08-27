"""Break of Structure (BOS): a candle's close moving decisively beyond the
most recently confirmed swing high (bullish) or swing low (bearish).

This is a sequential, chronological simulation rather than a "look at the
final snapshot and compare" calculation, and that distinction matters for
lookahead safety: at each candle, a swing only becomes eligible as the
"active" reference level once that swing's own `confirmed_at` has already
passed, and a break is only ever recognized using a candle that has itself
fully completed. See the ADR for the full worked example and for why only
the single most-recently-confirmed, unbroken swing of each type is tracked
(not every historical swing high/low independently).

Default confirmation is `close` (a wick through the level is never enough on
its own) with a configurable percentage tolerance beyond the level —
0% tolerance means a strictly-beyond close counts and exact equality never
does, since the comparison is `close > level`, not `>=`.
"""

from __future__ import annotations

from app.market_structure.common import candle_complete_at
from app.market_structure.config import MarketStructureConfig
from app.market_structure.schemas import BreakOfStructureEvent, Direction, SwingPoint, SwingType
from app.schemas.market_data import Candle


def detect_breaks_of_structure(
    completed_candles: list[Candle],
    confirmed_swings: list[SwingPoint],
    config: MarketStructureConfig,
) -> list[BreakOfStructureEvent]:
    highs = sorted(
        (s for s in confirmed_swings if s.type == SwingType.HIGH), key=lambda s: s.confirmed_at
    )
    lows = sorted((s for s in confirmed_swings if s.type == SwingType.LOW), key=lambda s: s.confirmed_at)
    candles = sorted(completed_candles, key=lambda c: c.timestamp)

    events: list[BreakOfStructureEvent] = []
    active_high: SwingPoint | None = None
    active_low: SwingPoint | None = None
    broken_high_pivots: set = set()
    broken_low_pivots: set = set()
    hi_idx = 0
    lo_idx = 0

    for candle in candles:
        known_at = candle_complete_at(candle)

        while hi_idx < len(highs) and highs[hi_idx].confirmed_at <= known_at:
            active_high = highs[hi_idx]
            hi_idx += 1
        while lo_idx < len(lows) and lows[lo_idx].confirmed_at <= known_at:
            active_low = lows[lo_idx]
            lo_idx += 1

        if active_high is not None and active_high.pivot_timestamp not in broken_high_pivots:
            threshold = active_high.price * (1 + config.bos_tolerance_percent / 100)
            if candle.close > threshold:
                events.append(
                    BreakOfStructureEvent(
                        direction=Direction.BULLISH,
                        broken_level=active_high.price,
                        broken_swing_timestamp=active_high.pivot_timestamp,
                        break_timestamp=candle.timestamp,
                        confirmation="close",
                        distance_beyond_level=candle.close - active_high.price,
                    )
                )
                broken_high_pivots.add(active_high.pivot_timestamp)

        if active_low is not None and active_low.pivot_timestamp not in broken_low_pivots:
            threshold = active_low.price * (1 - config.bos_tolerance_percent / 100)
            if candle.close < threshold:
                events.append(
                    BreakOfStructureEvent(
                        direction=Direction.BEARISH,
                        broken_level=active_low.price,
                        broken_swing_timestamp=active_low.pivot_timestamp,
                        break_timestamp=candle.timestamp,
                        confirmation="close",
                        distance_beyond_level=active_low.price - candle.close,
                    )
                )
                broken_low_pivots.add(active_low.pivot_timestamp)

    events.sort(key=lambda e: e.break_timestamp)
    return events


def apply_break_state(
    swings: list[SwingPoint], bos_events: list[BreakOfStructureEvent]
) -> list[SwingPoint]:
    """Annotate each swing with is_broken/first_broken_at/break_direction,
    deterministically re-derived from the event list rather than mutated
    global state — a historical snapshot must be reconstructable from data
    alone.

    Keyed by (swing_type, pivot_timestamp), not pivot_timestamp alone: a
    single candle can legitimately be both a swing high and a swing low
    pivot at once (e.g. an unusually wide-range bar whose neighbors sit
    entirely inside its range on both sides). Keying by timestamp only was
    a real bug, found via real-data validation on 2026-08-24 SPY 1H data —
    a bearish break of the swing LOW at that timestamp was incorrectly
    also applied to the unrelated swing HIGH sharing the same timestamp.
    A bullish BOS event only ever describes a broken swing high; a bearish
    one only ever describes a broken swing low (see
    detect_breaks_of_structure above), so the expected type is derivable
    from the event's direction.
    """
    broken_by_pivot: dict[tuple[SwingType, object], BreakOfStructureEvent] = {}
    for event in bos_events:
        swing_type = SwingType.HIGH if event.direction == Direction.BULLISH else SwingType.LOW
        broken_by_pivot[(swing_type, event.broken_swing_timestamp)] = event

    result = []
    for swing in swings:
        event = broken_by_pivot.get((swing.type, swing.pivot_timestamp))
        if event is None:
            result.append(swing)
            continue
        result.append(
            swing.model_copy(
                update={
                    "is_broken": True,
                    "first_broken_at": event.break_timestamp,
                    "break_direction": event.direction,
                }
            )
        )
    return result
