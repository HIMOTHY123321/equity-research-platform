import pytest

from app.schemas.market_data import Timeframe
from app.support_resistance.clustering import cluster_levels
from app.support_resistance.config import SupportResistanceConfig
from app.support_resistance.ids import raw_level_id
from app.support_resistance.schemas import LevelKind, RawLevel
from tests.conftest import et

TOLERANCE = 1e-9
CONFIG = SupportResistanceConfig(cluster_tolerance_percent=0.25)


def level(source, price, kind, timeframe=Timeframe.ONE_DAY, hour=9):
    ts = et(2026, 8, 17, hour, 30)
    return RawLevel(
        id=raw_level_id(source, timeframe, ts),
        price=price,
        kind=kind,
        source=source,
        source_timeframe=timeframe,
        origin_timestamp=ts,
        known_at=ts,
    )


def test_two_levels_inside_tolerance_merge():
    # 0.25% of 190.00 = 0.475; 190.20 is within that.
    levels = [
        level("previous_week_high", 190.00, LevelKind.RESISTANCE),
        level("confirmed_swing_high", 190.20, LevelKind.RESISTANCE, Timeframe.ONE_HOUR),
    ]
    zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)

    assert len(zones) == 1
    assert len(zones[0].member_levels) == 2


def test_two_levels_outside_tolerance_do_not_merge():
    levels = [
        level("previous_week_high", 190.00, LevelKind.RESISTANCE),
        level("confirmed_swing_high", 195.00, LevelKind.RESISTANCE, Timeframe.ONE_HOUR),
    ]
    zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)

    assert len(zones) == 2


def test_three_level_cluster():
    levels = [
        level("previous_week_high", 190.18, LevelKind.RESISTANCE),
        level("confirmed_swing_high", 190.07, LevelKind.RESISTANCE, Timeframe.ONE_DAY),
        level("confirmed_swing_high", 189.98, LevelKind.RESISTANCE, Timeframe.FOUR_HOUR),
    ]
    zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)

    assert len(zones) == 1
    zone = zones[0]
    assert len(zone.member_levels) == 3
    assert zone.lower_bound == pytest.approx(189.98, abs=TOLERANCE)
    assert zone.upper_bound == pytest.approx(190.18, abs=TOLERANCE)


def test_multi_timeframe_cluster_has_correct_confluence():
    levels = [
        level("previous_week_high", 190.18, LevelKind.RESISTANCE, Timeframe.ONE_DAY),
        level("confirmed_swing_high", 190.07, LevelKind.RESISTANCE, Timeframe.ONE_DAY),
        level("confirmed_swing_high", 189.98, LevelKind.RESISTANCE, Timeframe.FOUR_HOUR),
    ]
    zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)

    confluence = zones[0].confluence
    assert confluence.source_count == 3
    assert confluence.timeframe_count == 2  # 1d and 4h
    assert set(confluence.timeframes) == {Timeframe.ONE_DAY, Timeframe.FOUR_HOUR}


def test_weekly_and_daily_cluster_together_when_close():
    levels = [
        level("previous_week_high", 190.00, LevelKind.RESISTANCE),
        level("confirmed_swing_high", 190.10, LevelKind.RESISTANCE, Timeframe.ONE_DAY),
    ]
    zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)
    assert len(zones) == 1
    assert {e.source for e in zones[0].evidence} == {"previous_week_high", "confirmed_swing_high"}


def test_support_and_resistance_are_never_merged():
    levels = [
        level("previous_week_high", 190.00, LevelKind.RESISTANCE),
        level("previous_week_low", 190.00, LevelKind.SUPPORT),  # identical price, opposite polarity
    ]
    resistance_zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)
    support_zones = cluster_levels(levels, LevelKind.SUPPORT, CONFIG)

    assert len(resistance_zones) == 1
    assert len(support_zones) == 1
    assert resistance_zones[0].member_levels[0].kind == LevelKind.RESISTANCE
    assert support_zones[0].member_levels[0].kind == LevelKind.SUPPORT


def test_representative_price_is_source_weighted():
    # previous_week_high weight=25, confirmed_swing_high@1h weight=6 (per default config)
    levels = [
        level("previous_week_high", 200.00, LevelKind.RESISTANCE),
        level("confirmed_swing_high", 200.10, LevelKind.RESISTANCE, Timeframe.ONE_HOUR),
    ]
    zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)
    zone = zones[0]

    expected = (200.00 * 25 + 200.10 * 6) / (25 + 6)
    assert zone.representative_price == pytest.approx(expected, abs=TOLERANCE)


def test_deterministic_ordering_by_price():
    levels = [
        level("previous_week_high", 205.00, LevelKind.RESISTANCE),
        level("confirmed_swing_high", 190.00, LevelKind.RESISTANCE, Timeframe.ONE_DAY, hour=10),
    ]
    zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)
    assert [z.lower_bound for z in zones] == sorted(z.lower_bound for z in zones)


def test_stable_ids_across_recomputation():
    levels = [
        level("previous_week_high", 190.18, LevelKind.RESISTANCE),
        level("confirmed_swing_high", 190.07, LevelKind.RESISTANCE, Timeframe.ONE_DAY),
    ]
    zones_a = cluster_levels(list(levels), LevelKind.RESISTANCE, CONFIG)
    zones_b = cluster_levels(list(reversed(levels)), LevelKind.RESISTANCE, CONFIG)

    assert zones_a[0].id == zones_b[0].id


def test_provenance_is_fully_preserved():
    levels = [
        level("previous_week_high", 190.18, LevelKind.RESISTANCE),
        level("confirmed_swing_high", 190.07, LevelKind.RESISTANCE, Timeframe.ONE_DAY),
    ]
    zones = cluster_levels(levels, LevelKind.RESISTANCE, CONFIG)
    zone = zones[0]

    assert {lvl.price for lvl in zone.member_levels} == {190.18, 190.07}
    assert {lvl.id for lvl in zone.member_levels} == {lvl.id for lvl in levels}
    assert len(zone.evidence) == 2
