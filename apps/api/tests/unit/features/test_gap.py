import pytest

from app.features.common import FeatureStatus
from app.features.gap import compute_gap
from app.schemas.market_data import MarketSession
from tests.conftest import et
from tests.unit.features.conftest import daily, hourly

TOLERANCE = 1e-9


def test_gap_up():
    candles = [daily(17, 100, 102, 99, 100, 1000), daily(18, 103, 105, 102, 104, 1200)]
    result = compute_gap(candles, et(2026, 8, 18, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.previous_close == pytest.approx(100, abs=TOLERANCE)
    assert result.session_open == pytest.approx(103, abs=TOLERANCE)
    assert result.gap_absolute == pytest.approx(3, abs=TOLERANCE)
    assert result.gap_percent == pytest.approx(3.0, abs=TOLERANCE)
    assert result.direction == "up"


def test_gap_down():
    candles = [daily(17, 100, 102, 99, 100, 1000), daily(18, 97, 98, 95, 97.5, 1200)]
    result = compute_gap(candles, et(2026, 8, 18, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.gap_absolute == pytest.approx(-3, abs=TOLERANCE)
    assert result.gap_percent == pytest.approx(-3.0, abs=TOLERANCE)
    assert result.direction == "down"


def test_flat_open_has_zero_gap():
    candles = [daily(17, 100, 102, 99, 100, 1000), daily(18, 100, 101, 99, 100.5, 1200)]
    result = compute_gap(candles, et(2026, 8, 18, 12, 0))

    assert result.gap_absolute == pytest.approx(0.0, abs=TOLERANCE)
    assert result.direction == "flat"


def test_gap_unavailable_before_todays_session_opens():
    candles = [daily(17, 100, 102, 99, 100, 1000)]  # no bar for the 18th yet
    result = compute_gap(candles, et(2026, 8, 18, 8, 0))

    assert result.status == FeatureStatus.UNAVAILABLE
    assert result.previous_close == pytest.approx(100, abs=TOLERANCE)
    assert result.session_open is None


def test_gap_insufficient_history_with_no_previous_day():
    candles = [daily(17, 100, 102, 99, 100, 1000)]
    result = compute_gap(candles, et(2026, 8, 17, 10, 0))
    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY


def test_gap_ignores_premarket_bars_and_uses_regular_session_open():
    premarket = hourly(18, 7, 0, 999, 999, 999, 999, 500, session=MarketSession.PRE_MARKET)
    todays_daily = daily(18, 103, 105, 102, 104, 1200)
    candles = [daily(17, 100, 102, 99, 100, 1000), premarket, todays_daily]

    result = compute_gap(candles, et(2026, 8, 18, 12, 0))

    # session_open must come from the regular-session daily bar (103), never
    # the premarket price (999), even though the premarket bar sorts earlier.
    assert result.session_open == pytest.approx(103, abs=TOLERANCE)
