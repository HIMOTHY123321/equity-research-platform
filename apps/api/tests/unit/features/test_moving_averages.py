from datetime import timedelta

import pytest

from app.features.common import FeatureStatus
from app.features.config import FeatureConfig
from app.features.moving_averages import compute_moving_average_feature, compute_moving_averages_bundle
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, make_candle

TOLERANCE = 1e-9


def _closes_candles(closes):
    base = et(2026, 1, 1, 9, 30)
    return [
        make_candle(
            timeframe=Timeframe.ONE_DAY,
            timestamp=base + timedelta(days=i),
            session=MarketSession.REGULAR,
            open=c,
            high=c + 1,
            low=c - 1,
            close=c,
            volume=1000,
        )
        for i, c in enumerate(closes)
    ]


def test_sma_known_value_and_distance():
    # closes 1..10, SMA(5) of last 5 = (6+7+8+9+10)/5 = 8.0; latest close = 10
    candles = _closes_candles(range(1, 11))
    result = compute_moving_average_feature(candles, "sma", 5)

    assert result.status == FeatureStatus.OK
    assert result.value == pytest.approx(8.0, abs=TOLERANCE)
    assert result.distance_absolute == pytest.approx(2.0, abs=TOLERANCE)
    assert result.distance_percent == pytest.approx(25.0, abs=TOLERANCE)
    assert result.position == "above"


def test_ema_known_value():
    # Matches the hand-calculated EMA fixture in test_indicators.py.
    candles = _closes_candles(range(1, 11))
    result = compute_moving_average_feature(candles, "ema", 3)

    assert result.status == FeatureStatus.OK
    assert result.value == pytest.approx(9.0, abs=TOLERANCE)


def test_price_below_ma():
    candles = _closes_candles([10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
    result = compute_moving_average_feature(candles, "sma", 5)
    # last 5 closes: 5,4,3,2,1 -> avg=3.0, latest close=1 -> below
    assert result.value == pytest.approx(3.0, abs=TOLERANCE)
    assert result.position == "below"


def test_price_exactly_equal_to_ma():
    candles = _closes_candles([5, 5, 5, 5, 5])
    result = compute_moving_average_feature(candles, "sma", 5)
    assert result.value == pytest.approx(5.0, abs=TOLERANCE)
    assert result.position == "equal"


def test_insufficient_history_returns_no_value():
    candles = _closes_candles([1, 2, 3])
    result = compute_moving_average_feature(candles, "sma", 50)

    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY
    assert result.value is None
    assert result.distance_absolute is None
    assert result.position is None


def test_bundle_uses_configured_periods():
    candles = _closes_candles(range(1, 60))
    bundle = compute_moving_averages_bundle(candles, FeatureConfig())

    assert bundle.ema20.period == 20
    assert bundle.sma50.period == 50
    assert bundle.sma200.period == 200
    assert bundle.ema20.status == FeatureStatus.OK
    assert bundle.sma50.status == FeatureStatus.OK
    assert bundle.sma200.status == FeatureStatus.INSUFFICIENT_HISTORY
