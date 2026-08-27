import pytest

from app.features.candle_features import compute_candle_features
from app.features.common import FeatureStatus
from app.features.config import FeatureConfig
from tests.conftest import et
from tests.unit.features.conftest import daily

TOLERANCE = 1e-9


def test_bullish_candle():
    candles = [daily(17, 100, 108, 98, 106, 1000)]
    result = compute_candle_features(candles, et(2026, 8, 18, 9, 30), FeatureConfig())

    assert result.status == FeatureStatus.OK
    assert result.classification == "bullish"
    assert result.body_size == pytest.approx(6, abs=TOLERANCE)
    assert result.full_range == pytest.approx(10, abs=TOLERANCE)
    assert result.upper_wick == pytest.approx(2, abs=TOLERANCE)  # 108 - 106
    assert result.lower_wick == pytest.approx(2, abs=TOLERANCE)  # 100 - 98
    assert result.body_percent_of_range == pytest.approx(60.0, abs=TOLERANCE)


def test_bearish_candle():
    candles = [daily(17, 106, 108, 98, 100, 1000)]
    result = compute_candle_features(candles, et(2026, 8, 18, 9, 30), FeatureConfig())

    assert result.classification == "bearish"
    assert result.body_size == pytest.approx(6, abs=TOLERANCE)
    assert result.upper_wick == pytest.approx(2, abs=TOLERANCE)  # 108 - 106
    assert result.lower_wick == pytest.approx(2, abs=TOLERANCE)  # 100 - 98


def test_doji_within_configured_tolerance():
    # body=1, range=100 -> body% = 1% <= default 10% threshold -> doji
    candles = [daily(17, 100, 150, 50, 101, 1000)]
    result = compute_candle_features(candles, et(2026, 8, 18, 9, 30), FeatureConfig())

    assert result.classification == "doji"
    assert result.body_percent_of_range == pytest.approx(1.0, abs=TOLERANCE)


def test_doji_threshold_is_configurable():
    # body=10, range=100 -> body%=10%, exactly at a 10% threshold -> doji;
    # with a stricter 5% threshold the same candle should NOT be a doji.
    candles = [daily(17, 100, 150, 50, 110, 1000)]

    lenient = compute_candle_features(
        candles, et(2026, 8, 18, 9, 30), FeatureConfig(doji_body_ratio_threshold=0.10)
    )
    strict = compute_candle_features(
        candles, et(2026, 8, 18, 9, 30), FeatureConfig(doji_body_ratio_threshold=0.05)
    )

    assert lenient.classification == "doji"
    assert strict.classification == "bullish"


def test_zero_range_candle_is_doji_without_dividing_by_zero():
    candles = [daily(17, 100, 100, 100, 100, 1000)]
    result = compute_candle_features(candles, et(2026, 8, 18, 9, 30), FeatureConfig())

    assert result.classification == "doji"
    assert result.full_range == pytest.approx(0.0, abs=TOLERANCE)
    assert result.body_percent_of_range is None


def test_uses_latest_completed_candle_not_the_forming_one():
    completed = daily(17, 100, 108, 98, 106, 1000)  # bullish
    forming = daily(18, 106, 107, 90, 91, 1000)  # would be bearish, but still forming
    candles = [completed, forming]

    result = compute_candle_features(candles, et(2026, 8, 18, 12, 0), FeatureConfig())

    assert result.classification == "bullish"
    assert result.timestamp == completed.timestamp


def test_insufficient_history_when_nothing_is_complete_yet():
    candles = [daily(18, 100, 101, 99, 100.5, 1000)]
    result = compute_candle_features(candles, et(2026, 8, 18, 12, 0), FeatureConfig())
    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY
