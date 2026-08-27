import pytest

from app.features.indicators import ema, ema_series, sma, true_range_series, wilder_atr_series

TOLERANCE = 1e-9


def test_sma_exact_value():
    assert sma([1, 2, 3, 4, 5], 3) == pytest.approx(4.0, abs=TOLERANCE)


def test_sma_insufficient_history_returns_none():
    assert sma([1, 2], 3) is None


def test_sma_uses_only_the_last_period_values():
    assert sma([100, 100, 1, 2, 3], 3) == pytest.approx(2.0, abs=TOLERANCE)


def test_ema_hand_calculated_fixture():
    # period=3, multiplier=0.5, SMA-seeded: seed=avg(1,2,3)=2.0, then each
    # step is (value - prev) * 0.5 + prev.
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    series = ema_series(values, 3)

    assert series[:2] == [None, None]
    assert series[2:] == pytest.approx([2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0], abs=TOLERANCE)
    assert ema(values, 3) == pytest.approx(9.0, abs=TOLERANCE)


def test_ema_insufficient_history_returns_none():
    assert ema([1, 2], 5) is None


def test_true_range_first_bar_is_just_high_minus_low():
    trs = true_range_series([10], [8], [9])
    assert trs == pytest.approx([2.0], abs=TOLERANCE)


def test_true_range_gap_up_and_gap_down_fixture():
    highs = [10, 11, 15, 13]
    lows = [8, 9, 11, 6]
    closes = [9, 10, 14, 7]

    trs = true_range_series(highs, lows, closes)

    # bar0: no prior close -> high-low
    # bar1: normal bar, range dominates
    # bar2: gap up from prior close 10 -> |high-prev_close| dominates (5)
    # bar3: gap down from prior close 14 -> |low-prev_close| dominates (8)
    assert trs == pytest.approx([2.0, 2.0, 5.0, 8.0], abs=TOLERANCE)


def test_true_range_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        true_range_series([1, 2], [1], [1, 2])


def test_wilder_atr_hand_calculated_fixture():
    # TR = [2, 2, 5, 8], period=2
    # seed (index1) = avg(2,2) = 2.0
    # index2: (2.0*1 + 5)/2 = 3.5
    # index3: (3.5*1 + 8)/2 = 5.75
    true_ranges = [2.0, 2.0, 5.0, 8.0]
    series = wilder_atr_series(true_ranges, 2)

    assert series[0] is None
    assert series[1:] == pytest.approx([2.0, 3.5, 5.75], abs=TOLERANCE)


def test_wilder_atr_constant_true_range_converges_immediately():
    series = wilder_atr_series([5.0] * 20, 14)
    assert all(v == pytest.approx(5.0, abs=TOLERANCE) for v in series[13:])


def test_wilder_atr_insufficient_history_returns_all_none():
    series = wilder_atr_series([1.0, 2.0], 14)
    assert series == [None, None]
