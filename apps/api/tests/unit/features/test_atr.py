import pytest

from app.features.atr import compute_atr_feature
from app.features.common import FeatureStatus
from tests.unit.features.conftest import daily

TOLERANCE = 1e-9


def _candle_with_hlc(day, high, low, close):
    return daily(day, close, high, low, close, 1000)


def test_atr_matches_hand_calculated_wilder_fixture():
    # Same H/L/C fixture as test_indicators.py's wilder ATR test:
    # TR = [2, 2, 5, 8] -> ATR(2) series = [None, 2.0, 3.5, 5.75]
    candles = [
        _candle_with_hlc(10, 10, 8, 9),
        _candle_with_hlc(11, 11, 9, 10),
        _candle_with_hlc(12, 15, 11, 14),
        _candle_with_hlc(13, 13, 6, 7),
    ]

    result = compute_atr_feature(candles, period=2)

    assert result.status == FeatureStatus.OK
    assert result.method == "wilder"
    assert result.value == pytest.approx(5.75, abs=TOLERANCE)


def test_atr_insufficient_history():
    candles = [_candle_with_hlc(10, 10, 8, 9)]
    result = compute_atr_feature(candles, period=14)

    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY
    assert result.value is None
    assert result.period == 14


def test_atr_exactly_enough_history():
    candles = [_candle_with_hlc(10 + i, 10, 8, 9) for i in range(5)]
    result = compute_atr_feature(candles, period=5)
    assert result.status == FeatureStatus.OK
    assert result.value == pytest.approx(2.0, abs=TOLERANCE)  # constant TR of 2
