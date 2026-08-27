import pytest

from app.features.common import FeatureStatus
from app.features.volume import average_volume, compute_intraday_relative_volume, compute_volume_features
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et
from tests.unit.features.conftest import daily, hourly

TOLERANCE = 1e-9


def _volume_candles(volumes):
    return [daily(10 + i, 100, 101, 99, 100, v) for i, v in enumerate(volumes)]


# ---- Full-period volume / RVOL ----------------------------------------------


def test_average_volume_excludes_current_bar():
    # 5 candles, period=4: average should be of the first 4, not all 5.
    candles = _volume_candles([100, 200, 300, 400, 999999])
    assert average_volume(candles, 4) == pytest.approx((100 + 200 + 300 + 400) / 4, abs=TOLERANCE)


def test_relative_volume_exact_value():
    candles = _volume_candles([100, 100, 100, 100, 200])
    result = compute_volume_features(candles, period=4, as_of=et(2026, 8, 20, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.current_volume == pytest.approx(200, abs=TOLERANCE)
    assert result.average_volume == pytest.approx(100, abs=TOLERANCE)
    assert result.relative_volume == pytest.approx(2.0, abs=TOLERANCE)


def test_zero_average_volume_does_not_raise():
    candles = _volume_candles([0, 0, 0, 0, 500])
    result = compute_volume_features(candles, period=4, as_of=et(2026, 8, 20, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.average_volume == pytest.approx(0.0, abs=TOLERANCE)
    assert result.relative_volume is None


def test_insufficient_history_for_reference_average():
    candles = _volume_candles([100, 200])
    result = compute_volume_features(candles, period=20, as_of=et(2026, 8, 11, 12, 0))

    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY
    assert result.current_volume == pytest.approx(200, abs=TOLERANCE)
    assert result.average_volume is None
    assert result.relative_volume is None


def test_current_bar_partial_flag_reflects_completeness():
    candles = _volume_candles([100, 200, 300, 400, 500])
    forming = compute_volume_features(candles, period=4, as_of=et(2026, 8, 14, 12, 0))
    completed = compute_volume_features(candles, period=4, as_of=et(2026, 8, 15, 9, 0))

    assert forming.current_bar_is_partial is True
    assert completed.current_bar_is_partial is False


def test_empty_candles_is_insufficient_history():
    result = compute_volume_features([], period=20, as_of=et(2026, 8, 20, 12, 0))
    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY
    assert result.current_volume is None


# ---- Intraday (time-of-day) relative volume ----------------------------------


def test_intraday_rvol_not_applicable_for_daily_timeframe():
    candles = _volume_candles([100, 200])
    result = compute_intraday_relative_volume(
        candles, et(2026, 8, 20, 12, 0), Timeframe.ONE_DAY, lookback_days=20
    )
    assert result.status == FeatureStatus.NOT_APPLICABLE


def test_intraday_rvol_compares_same_cutoff_time_across_days():
    # Two prior days each with 10:30 cumulative volume of 300 (100+200),
    # today has cumulative volume of 600 through 10:30 -> intraday RVOL = 2.0
    candles = []
    for day in (17, 18):
        candles.append(hourly(day, 9, 30, 100, 101, 99, 100, 100))
        candles.append(hourly(day, 10, 30, 100, 101, 99, 100, 200))
        candles.append(hourly(day, 11, 30, 100, 101, 99, 100, 9999))  # after today's cutoff time

    today_bars = [
        hourly(19, 9, 30, 100, 101, 99, 100, 250),
        hourly(19, 10, 30, 100, 101, 99, 100, 350),
    ]
    candles += today_bars

    result = compute_intraday_relative_volume(
        candles, et(2026, 8, 19, 10, 45), Timeframe.ONE_HOUR, lookback_days=20
    )

    assert result.status == FeatureStatus.OK
    assert result.cumulative_volume_today == pytest.approx(600, abs=TOLERANCE)
    assert result.cumulative_volume_reference_average == pytest.approx(300, abs=TOLERANCE)
    assert result.intraday_relative_volume == pytest.approx(2.0, abs=TOLERANCE)
    assert result.lookback_days_used == 2


def test_intraday_rvol_excludes_premarket_and_after_hours():
    premarket = hourly(19, 7, 0, 100, 101, 99, 100, 5000, session=MarketSession.PRE_MARKET)
    regular = hourly(19, 9, 30, 100, 101, 99, 100, 100)
    candles = [premarket, regular]

    result = compute_intraday_relative_volume(
        candles, et(2026, 8, 19, 9, 45), Timeframe.ONE_HOUR, lookback_days=20
    )

    assert result.cumulative_volume_today == pytest.approx(100, abs=TOLERANCE)


def test_intraday_rvol_unavailable_before_todays_session():
    candles = [hourly(18, 9, 30, 100, 101, 99, 100, 100)]
    result = compute_intraday_relative_volume(
        candles, et(2026, 8, 19, 8, 0), Timeframe.ONE_HOUR, lookback_days=20
    )
    assert result.status == FeatureStatus.UNAVAILABLE


def test_intraday_rvol_insufficient_history_with_no_prior_days():
    candles = [hourly(19, 9, 30, 100, 101, 99, 100, 100)]
    result = compute_intraday_relative_volume(
        candles, et(2026, 8, 19, 9, 45), Timeframe.ONE_HOUR, lookback_days=20
    )
    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY
    assert result.cumulative_volume_today == pytest.approx(100, abs=TOLERANCE)
