"""Engine integration tests, with heavy emphasis on the anti-lookahead
invariants required by this phase — this is the highest-stakes correctness
property in the whole package, since the backtester will depend on it.
"""

from datetime import timedelta

from app.market_structure.common import candle_complete_at
from app.market_structure.config import MarketStructureConfig
from app.market_structure.engine import compute_market_structure_snapshot
from app.market_structure.schemas import SwingType, TrendClass
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, make_candle

CONFIG = MarketStructureConfig(left_bars=2, right_bars=2)


def _hourly(hour_offset, high, low, close=None, base=None):
    base = base or et(2026, 8, 17, 9, 30)
    mid = close if close is not None else (high + low) / 2
    return make_candle(
        symbol="TEST",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=base + timedelta(hours=hour_offset),
        session=MarketSession.REGULAR,
        open=mid,
        high=high,
        low=low,
        close=mid,
        volume=1000,
    )


def _single_peak_series(peak_index: int, length: int, peak_height: float = 20.0):
    """A clean series with exactly one swing high, at `peak_index`, and
    nothing else ambiguous nearby."""
    candles = []
    for i in range(length):
        if i == peak_index:
            candles.append(_hourly(i, peak_height, peak_height - 5))
        else:
            distance = abs(i - peak_index)
            height = peak_height - 2 - distance  # strictly declining away from the peak
            candles.append(_hourly(i, height, height - 5))
    return candles


# ---- Basic snapshot sanity ----------------------------------------------


def test_full_snapshot_is_internally_consistent():
    candles = _single_peak_series(peak_index=10, length=20)
    as_of = candles[-1].timestamp + timedelta(hours=2)

    snapshot = compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, candles, as_of, CONFIG)

    assert snapshot.symbol == "TEST"
    assert snapshot.data_quality.candle_count == 20
    assert snapshot.latest_swing_high is not None
    assert snapshot.latest_swing_high.pivot_timestamp == candles[10].timestamp


def test_insufficient_data_with_too_few_candles():
    candles = _single_peak_series(peak_index=1, length=3)
    as_of = candles[-1].timestamp + timedelta(hours=2)

    snapshot = compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, candles, as_of, CONFIG)

    assert snapshot.trend.trend == TrendClass.INSUFFICIENT_DATA
    assert snapshot.swings == []
    assert any("Fewer than" in w for w in snapshot.data_quality.warnings)


# ---- Anti-lookahead invariants (mandatory per spec) -----------------------


def test_invariant_1_swing_unavailable_before_confirmation():
    # Peak at index 10; through index 10 only (no right-side bars at all).
    candles = _single_peak_series(peak_index=10, length=11)
    as_of = candles[-1].timestamp + timedelta(hours=1)

    snapshot = compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, candles, as_of, CONFIG)

    assert snapshot.latest_swing_high is None
    assert all(s.pivot_timestamp != candles[10].timestamp for s in snapshot.swings)


def test_invariant_2_and_3_pivot_and_confirmed_at_are_correct_once_confirmed():
    # Peak at index 10; through index 12 (exactly enough right-side bars).
    candles = _single_peak_series(peak_index=10, length=13)
    as_of = candle_complete_at(candles[12]) + timedelta(minutes=1)

    snapshot = compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, candles, as_of, CONFIG)

    swing = snapshot.latest_swing_high
    assert swing is not None
    assert swing.pivot_timestamp == candles[10].timestamp  # unchanged: still the pivot candle
    assert swing.confirmed_at == candle_complete_at(candles[12])  # first legally-knowable instant
    assert swing.confirmed_at > swing.pivot_timestamp


def test_invariant_4_appending_future_candles_does_not_change_earlier_snapshot():
    short_series = _single_peak_series(peak_index=10, length=13)
    long_series = _single_peak_series(peak_index=10, length=50)
    # long_series and short_series share identical values for indices 0..12
    # by construction (both are generated the same deterministic way).
    as_of = candle_complete_at(short_series[12]) + timedelta(minutes=1)

    snap_short = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, short_series, as_of, CONFIG
    )
    snap_long = compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, long_series, as_of, CONFIG)

    # `candle_count`/`latest_candle_timestamp` legitimately differ:
    # long_series has one extra still-forming candle whose timestamp
    # happens to fall <= as_of (it exists in the raw fetch and is honestly
    # reported as data quality info, but is excluded from every actual
    # calculation) -- everything that's actually computed must match.
    volatile = {
        "data_quality": {
            "warnings",
            "candle_count",
            "latest_candle_timestamp",
            "future_candles_dropped",
        }
    }
    assert snap_short.model_dump(exclude=volatile) == snap_long.model_dump(exclude=volatile)


def test_invariant_5_bos_cannot_be_recognized_before_the_break_candle_closes():
    # Build: peak at 2 (confirms once bars 3,4 exist), then a bar at index 7
    # whose close breaks above it.
    candles = [
        _hourly(0, 10, 5),
        _hourly(1, 11, 6),
        _hourly(2, 20, 15),  # the swing high
        _hourly(3, 11, 6),
        _hourly(4, 10, 5),
        _hourly(5, 10, 5),
        _hourly(6, 10, 5),
        _hourly(7, 25, 18, close=22),  # breaks above 20
    ]

    just_before_break_completes = candle_complete_at(candles[7]) - timedelta(minutes=1)
    right_after_break_completes = candle_complete_at(candles[7]) + timedelta(minutes=1)

    snap_before = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, candles, just_before_break_completes, CONFIG
    )
    snap_after = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, candles, right_after_break_completes, CONFIG
    )

    assert snap_before.breaks_of_structure == []
    assert len(snap_after.breaks_of_structure) == 1


def test_invariant_7_break_timestamp_is_never_backdated_to_the_pivot():
    candles = [
        _hourly(0, 10, 5),
        _hourly(1, 11, 6),
        _hourly(2, 20, 15),
        _hourly(3, 11, 6),
        _hourly(4, 10, 5),
        _hourly(5, 10, 5),
        _hourly(6, 10, 5),
        _hourly(7, 25, 18, close=22),
    ]
    as_of = candles[-1].timestamp + timedelta(hours=2)

    snapshot = compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, candles, as_of, CONFIG)

    event = snapshot.breaks_of_structure[0]
    assert event.break_timestamp == candles[7].timestamp
    assert event.broken_swing_timestamp == candles[2].timestamp
    assert event.break_timestamp > event.broken_swing_timestamp


def test_swing_break_state_is_reflected_on_the_swing_itself():
    candles = [
        _hourly(0, 10, 5),
        _hourly(1, 11, 6),
        _hourly(2, 20, 15),
        _hourly(3, 11, 6),
        _hourly(4, 10, 5),
        _hourly(5, 10, 5),
        _hourly(6, 10, 5),
        _hourly(7, 25, 18, close=22),
    ]
    as_of = candles[-1].timestamp + timedelta(hours=2)

    snapshot = compute_market_structure_snapshot("TEST", Timeframe.ONE_HOUR, candles, as_of, CONFIG)

    swing = next(s for s in snapshot.swings if s.type == SwingType.HIGH)
    assert swing.is_broken is True
    assert swing.first_broken_at == candles[7].timestamp
