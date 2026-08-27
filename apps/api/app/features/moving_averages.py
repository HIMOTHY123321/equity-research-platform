"""EMA/SMA distance-from-price features. Uses the latest available close even
if that bar is still forming — see app/features/common.py for why that's the
documented, intentional as-of policy rather than lookahead.
"""

from __future__ import annotations

from app.features.common import FeatureStatus
from app.features.config import FeatureConfig
from app.features.indicators import ema, sma
from app.features.schemas import MovingAverageFeature, MovingAveragesBundle
from app.schemas.market_data import Candle


def _position(price: float, ma_value: float) -> str:
    if price > ma_value:
        return "above"
    if price < ma_value:
        return "below"
    return "equal"


def compute_moving_average_feature(
    candles: list[Candle], ma_type: str, period: int
) -> MovingAverageFeature:
    closes = [c.close for c in candles]
    value = ema(closes, period) if ma_type == "ema" else sma(closes, period)

    if value is None:
        return MovingAverageFeature(
            status=FeatureStatus.INSUFFICIENT_HISTORY, type=ma_type, period=period
        )

    latest_price = closes[-1]
    distance_absolute = latest_price - value
    distance_percent = (distance_absolute / value * 100) if value else None

    return MovingAverageFeature(
        status=FeatureStatus.OK,
        type=ma_type,
        period=period,
        value=value,
        distance_absolute=distance_absolute,
        distance_percent=distance_percent,
        position=_position(latest_price, value),
    )


def compute_moving_averages_bundle(
    candles: list[Candle], config: FeatureConfig
) -> MovingAveragesBundle:
    return MovingAveragesBundle(
        ema20=compute_moving_average_feature(candles, "ema", config.ema_period),
        sma50=compute_moving_average_feature(candles, "sma", config.sma_medium_period),
        sma200=compute_moving_average_feature(candles, "sma", config.sma_long_period),
    )
