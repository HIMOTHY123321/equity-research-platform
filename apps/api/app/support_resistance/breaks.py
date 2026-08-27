"""Zone break detection: a CLOSE beyond the zone boundary (+ configurable
tolerance) confirms a break. A wick poking through without the close
confirming is a `wick_breach` interaction (see interactions.py), never a
break. Exact boundary equality never counts (strict inequality). A zone
breaks at most once -- the first qualifying close is recorded and nothing
after it matters for break purposes.
"""

from __future__ import annotations

from typing import Optional

from app.schemas.market_data import Candle
from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.schemas import BreakEvent, LevelKind


def detect_zone_break(
    candles: list[Candle],
    kind: LevelKind,
    lower_bound: float,
    upper_bound: float,
    config: SupportResistanceConfig,
) -> Optional[BreakEvent]:
    if kind == LevelKind.RESISTANCE:
        threshold = upper_bound * (1 + config.break_tolerance_percent / 100)
        for candle in candles:
            if candle.close > threshold:
                return BreakEvent(
                    direction=LevelKind.RESISTANCE,
                    break_price=candle.close,
                    first_broken_at=candle.timestamp,
                    zone_lower_bound=lower_bound,
                    zone_upper_bound=upper_bound,
                )
        return None

    if kind == LevelKind.SUPPORT:
        threshold = lower_bound * (1 - config.break_tolerance_percent / 100)
        for candle in candles:
            if candle.close < threshold:
                return BreakEvent(
                    direction=LevelKind.SUPPORT,
                    break_price=candle.close,
                    first_broken_at=candle.timestamp,
                    zone_lower_bound=lower_bound,
                    zone_upper_bound=upper_bound,
                )
        return None

    return None
