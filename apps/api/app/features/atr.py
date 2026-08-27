"""Average True Range, Wilder-smoothed (the standard/original ATR convention).

TR[0] for the earliest candle in the series is just high-low, since there is
no prior close to compare against — a well-known, accepted limitation of
computing ATR from a fixed window rather than infinite history.
"""

from __future__ import annotations

from app.features.common import FeatureStatus
from app.features.indicators import true_range_series, wilder_atr_series
from app.features.schemas import ATRFeature
from app.schemas.market_data import Candle


def compute_atr_feature(candles: list[Candle], period: int) -> ATRFeature:
    if len(candles) < period:
        return ATRFeature(status=FeatureStatus.INSUFFICIENT_HISTORY, period=period)

    true_ranges = true_range_series(
        [c.high for c in candles], [c.low for c in candles], [c.close for c in candles]
    )
    value = wilder_atr_series(true_ranges, period)[-1]

    if value is None:
        return ATRFeature(status=FeatureStatus.INSUFFICIENT_HISTORY, period=period)
    return ATRFeature(status=FeatureStatus.OK, period=period, value=value)
