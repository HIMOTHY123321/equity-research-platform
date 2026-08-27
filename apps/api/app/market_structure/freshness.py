"""How recent are the important structural events, in bars. Descriptive
only -- never turned into a trading recommendation here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.market_structure.schemas import (
    BreakOfStructureEvent,
    ChangeOfCharacterEvent,
    Freshness,
    SwingPoint,
)
from app.schemas.market_data import Candle


def _bars_since(candles: list[Candle], target_timestamp: Optional[datetime]) -> Optional[int]:
    if target_timestamp is None:
        return None
    for idx in range(len(candles) - 1, -1, -1):
        if candles[idx].timestamp == target_timestamp:
            return (len(candles) - 1) - idx
    return None


def compute_freshness(
    candles: list[Candle],
    latest_swing_high: Optional[SwingPoint],
    latest_swing_low: Optional[SwingPoint],
    latest_bullish_bos: Optional[BreakOfStructureEvent],
    latest_bearish_bos: Optional[BreakOfStructureEvent],
    latest_choch: Optional[ChangeOfCharacterEvent],
) -> Freshness:
    return Freshness(
        bars_since_last_swing_high=_bars_since(
            candles, latest_swing_high.pivot_timestamp if latest_swing_high else None
        ),
        bars_since_last_swing_low=_bars_since(
            candles, latest_swing_low.pivot_timestamp if latest_swing_low else None
        ),
        bars_since_last_bullish_bos=_bars_since(
            candles, latest_bullish_bos.break_timestamp if latest_bullish_bos else None
        ),
        bars_since_last_bearish_bos=_bars_since(
            candles, latest_bearish_bos.break_timestamp if latest_bearish_bos else None
        ),
        bars_since_last_choch=_bars_since(candles, latest_choch.break_timestamp if latest_choch else None),
    )
