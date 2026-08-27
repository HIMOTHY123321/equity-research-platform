"""Change of Character (CHOCH): a decisive close against the currently
established structure.

Exact rule (not vague ICT/SMC terminology): while the currently-classified
trend (re-evaluated at each swing confirmation, using the same
classify_trend() the snapshot itself uses) is bullish, a close below the
most recently confirmed swing low classified as a Higher Low (HL) is a
bearish CHOCH. While trend is bearish, a close above the most recently
confirmed swing high classified as a Lower High (LH) is a bullish CHOCH.
Any swing not classified HL/LH is irrelevant to CHOCH, even if it's the
most recent swing overall — CHOCH specifically watches the swing that
represents "the structure that would have to break for this trend to be
wrong." If structure never reached bullish/bearish (insufficient_data or
ranging) or no HL/LH exists yet, no CHOCH is emitted rather than guessed.

Same chronological-simulation, close-only-confirmation, and
one-event-per-level rules as breaks.py apply here.
"""

from __future__ import annotations

from app.market_structure.classification import classify_trend
from app.market_structure.common import candle_complete_at
from app.market_structure.config import MarketStructureConfig
from app.market_structure.schemas import (
    ChangeOfCharacterEvent,
    Direction,
    SwingClassification,
    SwingPoint,
    TrendClass,
)
from app.schemas.market_data import Candle


def detect_changes_of_character(
    completed_candles: list[Candle],
    classified_swings: list[SwingPoint],
    config: MarketStructureConfig,
) -> list[ChangeOfCharacterEvent]:
    swings_by_confirmed_at = sorted(classified_swings, key=lambda s: s.confirmed_at)
    candles = sorted(completed_candles, key=lambda c: c.timestamp)

    events: list[ChangeOfCharacterEvent] = []
    known_swings: list[SwingPoint] = []
    active_hl: SwingPoint | None = None
    active_lh: SwingPoint | None = None
    broken_hl_pivots: set = set()
    broken_lh_pivots: set = set()
    current_trend = TrendClass.INSUFFICIENT_DATA
    swing_idx = 0

    for candle in candles:
        known_at = candle_complete_at(candle)

        while (
            swing_idx < len(swings_by_confirmed_at)
            and swings_by_confirmed_at[swing_idx].confirmed_at <= known_at
        ):
            swing = swings_by_confirmed_at[swing_idx]
            known_swings.append(swing)
            if swing.classification == SwingClassification.HIGHER_LOW:
                active_hl = swing
            elif swing.classification == SwingClassification.LOWER_HIGH:
                active_lh = swing
            swing_idx += 1
            current_trend = classify_trend(
                sorted(known_swings, key=lambda s: s.pivot_timestamp), config
            ).trend

        if (
            current_trend == TrendClass.BULLISH
            and active_hl is not None
            and active_hl.pivot_timestamp not in broken_hl_pivots
        ):
            threshold = active_hl.price * (1 - config.choch_tolerance_percent / 100)
            if candle.close < threshold:
                events.append(
                    ChangeOfCharacterEvent(
                        direction=Direction.BEARISH,
                        prior_structure=Direction.BULLISH,
                        broken_level=active_hl.price,
                        break_timestamp=candle.timestamp,
                        reference_swing_timestamp=active_hl.pivot_timestamp,
                    )
                )
                broken_hl_pivots.add(active_hl.pivot_timestamp)

        if (
            current_trend == TrendClass.BEARISH
            and active_lh is not None
            and active_lh.pivot_timestamp not in broken_lh_pivots
        ):
            threshold = active_lh.price * (1 + config.choch_tolerance_percent / 100)
            if candle.close > threshold:
                events.append(
                    ChangeOfCharacterEvent(
                        direction=Direction.BULLISH,
                        prior_structure=Direction.BEARISH,
                        broken_level=active_lh.price,
                        break_timestamp=candle.timestamp,
                        reference_swing_timestamp=active_lh.pivot_timestamp,
                    )
                )
                broken_lh_pivots.add(active_lh.pivot_timestamp)

    events.sort(key=lambda e: e.break_timestamp)
    return events
