"""Engine integration tests, with heavy emphasis on the anti-lookahead
invariants mandated by this phase.
"""

from datetime import timedelta

import pytest

from app.market_structure.common import candle_complete_at
from app.market_structure.config import MarketStructureConfig
from app.market_structure.engine import compute_market_structure_snapshot
from app.schemas.market_data import MarketSession, Timeframe
from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.engine import compute_support_resistance_snapshot
from app.support_resistance.schemas import ZoneLifecycle
from tests.conftest import et, make_candle
from tests.unit.support_resistance.conftest import daily

STRUCTURE_CONFIG = MarketStructureConfig(left_bars=2, right_bars=2)
SR_CONFIG = SupportResistanceConfig()

VOLATILE = {"data_quality"}


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
    candles = []
    for i in range(length):
        if i == peak_index:
            candles.append(_hourly(i, peak_height, peak_height - 5))
        else:
            distance = abs(i - peak_index)
            height = peak_height - 2 - distance
            candles.append(_hourly(i, height, height - 5))
    return candles


def _confirmed_zone_snapshot():
    """A daily-free snapshot with exactly one confirmed resistance zone,
    sourced from a single confirmed 1H swing high."""
    candles = _single_peak_series(peak_index=10, length=13)
    as_of = candle_complete_at(candles[12]) + timedelta(minutes=1)
    structure = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, candles, as_of, STRUCTURE_CONFIG
    )
    snapshot = compute_support_resistance_snapshot(
        "TEST", Timeframe.ONE_HOUR, candles, [], {Timeframe.ONE_HOUR: structure}, as_of, SR_CONFIG
    )
    return candles, as_of, structure, snapshot


# ---- Basic sanity -----------------------------------------------------------


def test_full_snapshot_is_internally_consistent():
    candles, as_of, _, snapshot = _confirmed_zone_snapshot()

    assert snapshot.symbol == "TEST"
    assert len(snapshot.active_resistance_zones) == 1
    zone = snapshot.active_resistance_zones[0]
    assert zone.lower_bound == pytest.approx(20.0, abs=1e-9)
    assert zone.member_levels[0].source == "confirmed_swing_high"
    assert zone.lifecycle in (ZoneLifecycle.ACTIVE, ZoneLifecycle.TESTED, ZoneLifecycle.WEAKENED)


# ---- Mandatory anti-lookahead invariants ------------------------------------


def test_invariant_1_appending_future_candles_does_not_change_snapshot():
    short_series = _single_peak_series(peak_index=10, length=13)
    long_series = _single_peak_series(peak_index=10, length=50)
    as_of = candle_complete_at(short_series[12]) + timedelta(minutes=1)

    structure_short = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, short_series, as_of, STRUCTURE_CONFIG
    )
    structure_long = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, long_series, as_of, STRUCTURE_CONFIG
    )

    snap_short = compute_support_resistance_snapshot(
        "TEST", Timeframe.ONE_HOUR, short_series, [], {Timeframe.ONE_HOUR: structure_short}, as_of, SR_CONFIG
    )
    snap_long = compute_support_resistance_snapshot(
        "TEST", Timeframe.ONE_HOUR, long_series, [], {Timeframe.ONE_HOUR: structure_long}, as_of, SR_CONFIG
    )

    # `price_relationship` legitimately differs: long_series has one extra
    # candle whose timestamp happens to fall <= as_of (contiguous hourly
    # bars mean candle 13 starts exactly when candle 12 completes, so there
    # is no as_of that both confirms the swing and excludes it) -- it's real,
    # non-future data, so "current price" correctly reflects it. Every piece
    # of zone EVIDENCE (the actual thing this invariant protects) must still
    # match exactly.
    zone_fields = {"price_relationship"}
    volatile = {
        "data_quality": True,
        "active_resistance_zones": {"__all__": zone_fields},
        "active_support_zones": {"__all__": zone_fields},
        "nearest_resistance": zone_fields,
        "nearest_support": zone_fields,
    }
    assert snap_short.model_dump(exclude=volatile) == snap_long.model_dump(exclude=volatile)


def test_invariant_2_unconfirmed_swing_produces_no_level():
    candles = _single_peak_series(peak_index=10, length=11)  # no right-side bars yet
    as_of = candles[-1].timestamp + timedelta(hours=1)

    structure = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, candles, as_of, STRUCTURE_CONFIG
    )
    assert structure.swings == []

    snapshot = compute_support_resistance_snapshot(
        "TEST", Timeframe.ONE_HOUR, candles, [], {Timeframe.ONE_HOUR: structure}, as_of, SR_CONFIG
    )
    assert snapshot.active_resistance_zones == []


def test_invariant_3_origin_and_known_at_correct_once_confirmed():
    candles, as_of, _, snapshot = _confirmed_zone_snapshot()

    member = snapshot.active_resistance_zones[0].member_levels[0]
    assert member.origin_timestamp == candles[10].timestamp
    assert member.known_at == candle_complete_at(candles[12])
    assert member.known_at > member.origin_timestamp


def test_invariant_4_future_rejection_cannot_increase_historical_strength():
    candles, as_of, _, snap_before = _confirmed_zone_snapshot()
    zone_before = snap_before.active_resistance_zones[0]

    future_rejection = _hourly(20, 25, 5, close=5)  # deep rejection, timestamped after as_of
    extended = candles + [future_rejection]
    structure_extended = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, extended, as_of, STRUCTURE_CONFIG
    )
    snap_after = compute_support_resistance_snapshot(
        "TEST", Timeframe.ONE_HOUR, extended, [], {Timeframe.ONE_HOUR: structure_extended}, as_of, SR_CONFIG
    )
    zone_after = snap_after.active_resistance_zones[0]

    assert zone_after.strength.total == pytest.approx(zone_before.strength.total, abs=1e-9)
    assert zone_after.interaction_summary == zone_before.interaction_summary


def test_invariant_5_future_touch_cannot_increase_historical_touch_count():
    candles, as_of, _, snap_before = _confirmed_zone_snapshot()
    zone_before = snap_before.active_resistance_zones[0]

    future_touch = _hourly(20, 19.5, 19.0, close=19.4)  # a plain future touch, not even a rejection
    extended = candles + [future_touch]
    structure_extended = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, extended, as_of, STRUCTURE_CONFIG
    )
    snap_after = compute_support_resistance_snapshot(
        "TEST", Timeframe.ONE_HOUR, extended, [], {Timeframe.ONE_HOUR: structure_extended}, as_of, SR_CONFIG
    )
    zone_after = snap_after.active_resistance_zones[0]

    assert (
        zone_after.interaction_summary.independent_touches
        == zone_before.interaction_summary.independent_touches
    )


def test_invariant_6_future_break_does_not_retroactively_break_zone():
    candles, as_of, _, snap_before = _confirmed_zone_snapshot()
    zone_before = snap_before.active_resistance_zones[0]
    assert zone_before.lifecycle != ZoneLifecycle.BROKEN

    future_break = _hourly(20, 30, 25, close=30)  # closes well above the zone, but after as_of
    extended = candles + [future_break]
    structure_extended = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, extended, as_of, STRUCTURE_CONFIG
    )
    snap_after = compute_support_resistance_snapshot(
        "TEST", Timeframe.ONE_HOUR, extended, [], {Timeframe.ONE_HOUR: structure_extended}, as_of, SR_CONFIG
    )
    zone_after = snap_after.active_resistance_zones[0]

    assert zone_after.lifecycle != ZoneLifecycle.BROKEN
    assert zone_after.break_event is None


def test_invariant_7_defensively_ignores_swings_confirmed_after_as_of():
    candles = _single_peak_series(peak_index=10, length=13)
    early_as_of = candles[10].timestamp + timedelta(hours=1)  # before any right-side bar completes

    early_structure = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, candles, early_as_of, STRUCTURE_CONFIG
    )
    assert early_structure.swings == []

    # Simulate a caller mistake: pass a structure snapshot that was computed
    # with a LATER as_of (so it already contains the confirmed swing) into
    # an S/R query that itself still uses the earlier as_of.
    later_as_of = candle_complete_at(candles[12]) + timedelta(minutes=1)
    structure_from_later = compute_market_structure_snapshot(
        "TEST", Timeframe.ONE_HOUR, candles, later_as_of, STRUCTURE_CONFIG
    )
    assert structure_from_later.swings != []

    snapshot = compute_support_resistance_snapshot(
        "TEST",
        Timeframe.ONE_HOUR,
        candles,
        [],
        {Timeframe.ONE_HOUR: structure_from_later},
        early_as_of,
        SR_CONFIG,
    )
    assert snapshot.active_resistance_zones == []


def test_invariant_8_previous_week_levels_obey_phase_3_semantics():
    # Monday uses the prior Friday-ending week -- same rule proven
    # exhaustively in test_sources.py; this confirms it holds end-to-end
    # through the full engine, not just the sources module in isolation.
    week1 = [
        daily(10, 100, 105, 95, 101),
        daily(11, 101, 106, 96, 102),
        daily(12, 102, 107, 97, 103),
        daily(13, 103, 108, 98, 104),
        daily(14, 104, 109, 99, 105),
    ]
    monday_bar = [daily(17, 109, 111, 108, 110)]
    as_of = et(2026, 8, 17, 10, 0)

    snapshot = compute_support_resistance_snapshot(
        "TEST", Timeframe.ONE_DAY, week1 + monday_bar, week1 + monday_bar, {}, as_of, SR_CONFIG
    )

    sources_seen = {lvl.source for lvl in snapshot.reference_levels}
    assert "previous_week_close" in sources_seen
    pwc = next(lvl for lvl in snapshot.reference_levels if lvl.source == "previous_week_close")
    assert pwc.price == pytest.approx(105, abs=1e-9)  # Friday's close, not Monday's
