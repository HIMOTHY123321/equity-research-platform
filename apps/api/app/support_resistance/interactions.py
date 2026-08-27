"""Per-candle classification of price interaction with a zone.

Precedence (a candle gets exactly one classification): close_break is
handled entirely by breaks.py and excluded here (callers pass `stop_at` to
exclude candles at/after a confirmed break) -- among what's left, rejection
outranks wick_breach outranks touch, since a candle that pokes through the
zone AND closes back below the representative price is a clearer, more
informative signal than a plain wick poke that doesn't fully reject.

Independence: consecutive interactions within
`minimum_bars_between_independent_touches` bars of the prior one are folded
into the same event -- still recorded (for later research), but flagged
`is_independent=False` -- so a five-candle consolidation at one price
doesn't silently become five confirmations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.schemas.market_data import Candle
from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.rejection import is_resistance_rejection, is_support_rejection
from app.support_resistance.schemas import InteractionType, LevelKind, ZoneInteraction


def _classify(
    candle: Candle,
    kind: LevelKind,
    lower_bound: float,
    upper_bound: float,
    representative_price: float,
    tolerance: float,
) -> Optional[InteractionType]:
    overlaps = candle.high >= lower_bound - tolerance and candle.low <= upper_bound + tolerance
    if not overlaps:
        return None

    if kind == LevelKind.RESISTANCE:
        if is_resistance_rejection(candle, representative_price):
            return InteractionType.REJECTION
        if candle.high > upper_bound:
            return InteractionType.WICK_BREACH
        return InteractionType.TOUCH

    if is_support_rejection(candle, representative_price):
        return InteractionType.REJECTION
    if candle.low < lower_bound:
        return InteractionType.WICK_BREACH
    return InteractionType.TOUCH


def detect_interactions(
    candles: list[Candle],
    kind: LevelKind,
    lower_bound: float,
    upper_bound: float,
    representative_price: float,
    config: SupportResistanceConfig,
    stop_at: Optional[datetime] = None,
) -> list[ZoneInteraction]:
    tolerance = representative_price * (config.touch_tolerance_percent / 100)
    interactions: list[ZoneInteraction] = []
    last_independent_index: Optional[int] = None

    for idx, candle in enumerate(candles):
        if stop_at is not None and candle.timestamp >= stop_at:
            continue

        interaction_type = _classify(candle, kind, lower_bound, upper_bound, representative_price, tolerance)
        if interaction_type is None:
            continue

        is_independent = (
            last_independent_index is None
            or (idx - last_independent_index) >= config.minimum_bars_between_independent_touches
        )
        if is_independent:
            last_independent_index = idx

        interactions.append(
            ZoneInteraction(
                timestamp=candle.timestamp,
                interaction_type=interaction_type,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                distance=abs(candle.close - representative_price),
                is_independent=is_independent,
            )
        )

    return interactions
