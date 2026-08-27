import pytest

from app.features.common import FeatureStatus
from app.features.config import FeatureConfig
from app.features.rolling import compute_rolling_level, compute_rolling_levels, rolling_high, rolling_low
from tests.unit.features.conftest import daily

TOLERANCE = 1e-9

# 5 candles with distinct, easy-to-track highs/lows.
CANDLES = [
    daily(10, 10, 15, 5, 12, 1000),
    daily(11, 11, 20, 6, 13, 1000),
    daily(12, 12, 12, 7, 11, 1000),  # highest low here doesn't matter
    daily(13, 13, 18, 4, 14, 1000),  # lowest low here
    daily(14, 14, 16, 8, 15, 1000),  # most recent (current) bar
]


def test_include_current_uses_last_period_bars():
    # last 3: highs [12,18,16] low=[7,4,8] -> high=18, low=4
    assert rolling_high(CANDLES, 3, include_current=True) == pytest.approx(18, abs=TOLERANCE)
    assert rolling_low(CANDLES, 3, include_current=True) == pytest.approx(4, abs=TOLERANCE)


def test_exclude_current_uses_bars_before_the_last_one():
    # excluding the last bar (index4): prior 3 are indices [1,2,3] -> highs [20,12,18], lows [6,7,4]
    assert rolling_high(CANDLES, 3, include_current=False) == pytest.approx(20, abs=TOLERANCE)
    assert rolling_low(CANDLES, 3, include_current=False) == pytest.approx(4, abs=TOLERANCE)


def test_exclude_current_never_includes_the_most_recent_bars_extreme():
    # bar index4 has high=16 which is NOT the max of the whole series (20 is),
    # so this alone wouldn't prove exclusion. Use a bar whose current values
    # are the extreme, and confirm excluding it changes the result.
    candles = CANDLES + [daily(15, 15, 999, 0.01, 15, 1000)]  # extreme current bar
    included = rolling_high(candles, 3, include_current=True)
    excluded = rolling_high(candles, 3, include_current=False)

    assert included == pytest.approx(999, abs=TOLERANCE)
    assert excluded != pytest.approx(999, abs=TOLERANCE)


def test_insufficient_history_include_current():
    assert rolling_high(CANDLES, 10, include_current=True) is None
    assert rolling_low(CANDLES, 10, include_current=True) is None


def test_insufficient_history_exclude_current_needs_one_extra_bar():
    # exactly `period` candles is NOT enough when excluding the current bar
    assert rolling_high(CANDLES, 5, include_current=False) is None
    assert rolling_high(CANDLES, 4, include_current=False) is not None


def test_compute_rolling_level_status_and_fields():
    level = compute_rolling_level(CANDLES, 3, include_current=True)
    assert level.status == FeatureStatus.OK
    assert level.period == 3
    assert level.include_current is True
    assert level.high == pytest.approx(18, abs=TOLERANCE)
    assert level.low == pytest.approx(4, abs=TOLERANCE)


def test_bundle_produces_both_variants_for_every_configured_window():
    config = FeatureConfig(rolling_windows=(2, 3))
    bundle = compute_rolling_levels(CANDLES, config)

    assert [level.period for level in bundle.including_current] == [2, 3]
    assert [level.period for level in bundle.excluding_current] == [2, 3]
    assert all(level.include_current for level in bundle.including_current)
    assert all(not level.include_current for level in bundle.excluding_current)
