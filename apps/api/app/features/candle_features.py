"""Body/wick/classification of the latest *completed* candle — deliberately
not the latest available one, since a still-forming bar's body and wicks are
still changing and a "bullish"/"doji" call on it could flip before the bar
closes. Continuous features (ATR, MAs) use the forming bar; this one waits.
"""

from __future__ import annotations

from datetime import datetime

from app.features.common import FeatureStatus, latest_completed_candle
from app.features.config import FeatureConfig
from app.features.schemas import CandleFeatures
from app.schemas.market_data import Candle


def compute_candle_features(
    candles: list[Candle], as_of: datetime, config: FeatureConfig
) -> CandleFeatures:
    candle = latest_completed_candle(candles, as_of)
    if candle is None:
        return CandleFeatures(status=FeatureStatus.INSUFFICIENT_HISTORY)

    body_size = abs(candle.close - candle.open)
    full_range = candle.high - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    body_percent_of_range = (body_size / full_range * 100) if full_range > 0 else None

    doji_threshold_percent = config.doji_body_ratio_threshold * 100
    if full_range == 0 or (
        body_percent_of_range is not None and body_percent_of_range <= doji_threshold_percent
    ):
        classification = "doji"
    elif candle.close > candle.open:
        classification = "bullish"
    else:
        classification = "bearish"

    return CandleFeatures(
        status=FeatureStatus.OK,
        timestamp=candle.timestamp,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        body_size=body_size,
        full_range=full_range,
        upper_wick=upper_wick,
        lower_wick=lower_wick,
        body_percent_of_range=body_percent_of_range,
        classification=classification,
    )
