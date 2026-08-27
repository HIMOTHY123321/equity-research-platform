import pytest

from app.features.common import FeatureStatus
from app.features.previous_period import compute_previous_day_levels, compute_previous_week_levels
from tests.conftest import et
from tests.unit.features.conftest import daily

TOLERANCE = 1e-9

# Week 1: Mon Aug 10 - Fri Aug 14, 2026
WEEK1 = [
    daily(10, 100, 105, 95, 101, 1000),
    daily(11, 101, 106, 96, 102, 1100),
    daily(12, 102, 107, 97, 103, 1200),
    daily(13, 103, 108, 98, 104, 1300),
    daily(14, 104, 109, 99, 105, 1400),
]

# Week 2: Mon Aug 17 - Wed Aug 19, 2026 (partial, still in progress)
WEEK2_PARTIAL = [
    daily(17, 110, 115, 109, 111, 2000),
    daily(18, 111, 116, 110, 112, 2100),
    daily(19, 112, 117, 111, 113, 2200),
]


# ---- Previous day -----------------------------------------------------------


def test_normal_weekday_looks_back_one_day():
    candles = WEEK2_PARTIAL  # Mon 17, Tue 18, Wed 19
    result = compute_previous_day_levels(candles, et(2026, 8, 19, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.trading_date.day == 18
    assert result.close == pytest.approx(112, abs=TOLERANCE)
    assert result.open == pytest.approx(111, abs=TOLERANCE)
    assert result.high == pytest.approx(116, abs=TOLERANCE)
    assert result.low == pytest.approx(110, abs=TOLERANCE)
    assert result.volume == pytest.approx(2100, abs=TOLERANCE)
    assert result.range == pytest.approx(6, abs=TOLERANCE)
    assert result.percent_change == pytest.approx((112 - 111) / 111 * 100, abs=TOLERANCE)


def test_monday_uses_friday_not_the_weekend():
    candles = WEEK1  # last bar is Fri Aug 14
    result = compute_previous_day_levels(candles, et(2026, 8, 17, 10, 0))  # Monday

    assert result.status == FeatureStatus.OK
    assert result.trading_date.day == 14
    assert result.close == pytest.approx(105, abs=TOLERANCE)


def test_holiday_gap_uses_latest_available_prior_session():
    # Tuesday Aug 18 missing entirely (simulated holiday)
    candles = [daily(17, 110, 115, 109, 111, 2000), daily(19, 112, 117, 111, 113, 2200)]
    result = compute_previous_day_levels(candles, et(2026, 8, 19, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.trading_date.day == 17
    assert result.close == pytest.approx(111, abs=TOLERANCE)


def test_missing_multi_day_session_gap_still_resolves_correctly():
    # Aug 11-13 all missing from our dataset for whatever reason
    candles = [daily(10, 100, 105, 95, 101, 1000), daily(14, 104, 109, 99, 105, 1400)]
    result = compute_previous_day_levels(candles, et(2026, 8, 14, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.trading_date.day == 10
    assert result.close == pytest.approx(101, abs=TOLERANCE)


def test_current_day_is_never_returned_as_previous_day():
    candles = WEEK2_PARTIAL
    result = compute_previous_day_levels(candles, et(2026, 8, 19, 12, 0))
    assert result.trading_date.day != 19


def test_no_prior_data_is_insufficient_history():
    candles = [daily(17, 110, 115, 109, 111, 2000)]
    result = compute_previous_day_levels(candles, et(2026, 8, 17, 10, 0))

    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY
    assert result.close is None


# ---- Previous week ------------------------------------------------------------


def test_normal_week_aggregates_all_five_days():
    candles = WEEK1 + WEEK2_PARTIAL
    result = compute_previous_week_levels(candles, et(2026, 8, 19, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.week_start_date.day == 10
    assert result.week_end_date.day == 14
    assert result.open == pytest.approx(100, abs=TOLERANCE)
    assert result.close == pytest.approx(105, abs=TOLERANCE)
    assert result.high == pytest.approx(109, abs=TOLERANCE)
    assert result.low == pytest.approx(95, abs=TOLERANCE)
    assert result.volume == pytest.approx(6000, abs=TOLERANCE)
    assert result.range == pytest.approx(14, abs=TOLERANCE)
    assert result.percent_change == pytest.approx(5.0, abs=TOLERANCE)
    assert result.trading_days_counted == 5


def test_monday_previous_week_is_last_full_week_not_this_one():
    candles = WEEK1 + [WEEK2_PARTIAL[0]]  # only Monday of week 2 exists so far
    result = compute_previous_week_levels(candles, et(2026, 8, 17, 9, 45))  # Monday morning

    assert result.status == FeatureStatus.OK
    assert result.week_start_date.day == 10
    assert result.week_end_date.day == 14
    assert result.trading_days_counted == 5


def test_partial_current_week_is_never_returned_as_previous_week():
    candles = WEEK1 + WEEK2_PARTIAL
    result = compute_previous_week_levels(candles, et(2026, 8, 19, 12, 0))
    assert result.week_start_date.day != 17


def test_holiday_shortened_week_uses_only_available_days():
    # Monday Aug 10 missing (simulated holiday) -> week 1 only has Tue-Fri
    shortened_week1 = WEEK1[1:]  # Tue 11 .. Fri 14
    candles = shortened_week1 + WEEK2_PARTIAL
    result = compute_previous_week_levels(candles, et(2026, 8, 19, 12, 0))

    assert result.status == FeatureStatus.OK
    assert result.trading_days_counted == 4
    assert result.week_start_date.day == 11
    assert result.open == pytest.approx(101, abs=TOLERANCE)  # Tuesday's open, not fabricated
    assert result.close == pytest.approx(105, abs=TOLERANCE)
    assert result.high == pytest.approx(109, abs=TOLERANCE)
    assert result.low == pytest.approx(96, abs=TOLERANCE)
    assert result.volume == pytest.approx(1100 + 1200 + 1300 + 1400, abs=TOLERANCE)


def test_no_prior_week_data_is_insufficient_history():
    candles = WEEK2_PARTIAL
    result = compute_previous_week_levels(candles, et(2026, 8, 19, 12, 0))

    assert result.status == FeatureStatus.INSUFFICIENT_HISTORY
    assert result.close is None
