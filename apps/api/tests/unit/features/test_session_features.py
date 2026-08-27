import pytest

from app.features.common import FeatureStatus
from app.features.session_features import compute_session_features
from app.schemas.market_data import MarketSession
from tests.conftest import et
from tests.unit.features.conftest import hourly

TOLERANCE = 1e-9


def test_regular_session_only_aggregation():
    candles = [
        hourly(19, 9, 30, 100, 102, 99, 101, 1000),
        hourly(19, 10, 30, 101, 105, 100, 104, 1000),
        hourly(19, 11, 30, 104, 106, 103, 105, 1000),
    ]
    result = compute_session_features(candles, et(2026, 8, 19, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.session_open == pytest.approx(100, abs=TOLERANCE)
    assert result.session_high_so_far == pytest.approx(106, abs=TOLERANCE)
    assert result.session_low_so_far == pytest.approx(99, abs=TOLERANCE)
    assert result.session_range == pytest.approx(7, abs=TOLERANCE)
    assert result.latest_price == pytest.approx(105, abs=TOLERANCE)
    assert result.distance_from_high_absolute == pytest.approx(1, abs=TOLERANCE)
    assert result.distance_from_low_absolute == pytest.approx(6, abs=TOLERANCE)


def test_premarket_bars_excluded():
    candles = [
        hourly(19, 7, 0, 50, 999, 1, 50, 1000, session=MarketSession.PRE_MARKET),
        hourly(19, 9, 30, 100, 102, 99, 101, 1000),
    ]
    result = compute_session_features(candles, et(2026, 8, 19, 10, 0))

    assert result.session_open == pytest.approx(100, abs=TOLERANCE)
    assert result.session_high_so_far == pytest.approx(102, abs=TOLERANCE)
    assert result.session_low_so_far == pytest.approx(99, abs=TOLERANCE)


def test_after_hours_bars_excluded():
    candles = [
        hourly(19, 9, 30, 100, 102, 99, 101, 1000),
        hourly(19, 16, 30, 105, 999, 1, 105, 1000, session=MarketSession.AFTER_HOURS),
    ]
    result = compute_session_features(candles, et(2026, 8, 19, 17, 0))

    assert result.session_high_so_far == pytest.approx(102, abs=TOLERANCE)
    assert result.session_low_so_far == pytest.approx(99, abs=TOLERANCE)
    assert result.latest_price == pytest.approx(101, abs=TOLERANCE)


def test_only_prior_days_data_is_unavailable():
    candles = [hourly(18, 9, 30, 100, 102, 99, 101, 1000)]
    result = compute_session_features(candles, et(2026, 8, 19, 10, 0))
    assert result.status == FeatureStatus.UNAVAILABLE


def test_incomplete_session_uses_only_bars_so_far():
    candles = [hourly(19, 9, 30, 100, 102, 99, 101, 1000)]
    result = compute_session_features(candles, et(2026, 8, 19, 9, 45))

    assert result.status == FeatureStatus.OK
    assert result.session_high_so_far == pytest.approx(102, abs=TOLERANCE)
    assert result.latest_price == pytest.approx(101, abs=TOLERANCE)
