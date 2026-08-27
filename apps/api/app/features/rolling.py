"""Rolling N-bar high/low, with the include/exclude-current-bar distinction
made structurally explicit rather than left to a boolean callers can
misread: `rolling_high`/`rolling_low` take `include_current` positionally
required-by-keyword-in-practice, and the bundle output carries two separate
lists (`including_current` / `excluding_current`) rather than one list with
a flag buried in each row.
"""

from __future__ import annotations

from typing import Optional

from app.features.common import FeatureStatus
from app.features.config import FeatureConfig
from app.features.schemas import RollingLevel, RollingLevels
from app.schemas.market_data import Candle


def _window(candles: list[Candle], period: int, include_current: bool) -> Optional[list[Candle]]:
    if include_current:
        if len(candles) < period:
            return None
        return candles[-period:]
    if len(candles) < period + 1:
        return None
    return candles[-period - 1 : -1]


def rolling_high(candles: list[Candle], period: int, include_current: bool) -> Optional[float]:
    window = _window(candles, period, include_current)
    return max(c.high for c in window) if window else None


def rolling_low(candles: list[Candle], period: int, include_current: bool) -> Optional[float]:
    window = _window(candles, period, include_current)
    return min(c.low for c in window) if window else None


def compute_rolling_level(candles: list[Candle], period: int, include_current: bool) -> RollingLevel:
    window = _window(candles, period, include_current)
    if window is None:
        return RollingLevel(
            status=FeatureStatus.INSUFFICIENT_HISTORY, period=period, include_current=include_current
        )
    return RollingLevel(
        status=FeatureStatus.OK,
        period=period,
        include_current=include_current,
        high=max(c.high for c in window),
        low=min(c.low for c in window),
    )


def compute_rolling_levels(candles: list[Candle], config: FeatureConfig) -> RollingLevels:
    return RollingLevels(
        including_current=[
            compute_rolling_level(candles, period, True) for period in config.rolling_windows
        ],
        excluding_current=[
            compute_rolling_level(candles, period, False) for period in config.rolling_windows
        ],
    )
