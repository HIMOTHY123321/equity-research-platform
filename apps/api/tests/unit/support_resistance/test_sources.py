import pytest

from app.market_structure.common import candle_complete_at
from app.schemas.market_data import MarketSession, Timeframe
from app.support_resistance.schemas import LevelKind
from app.support_resistance.sources import (
    extract_previous_day_levels,
    extract_previous_week_levels,
    extract_session_open_level,
)
from tests.conftest import et
from tests.unit.support_resistance.conftest import daily

TOLERANCE = 1e-9

# Week 1: Mon Aug 10 - Fri Aug 14, 2026
WEEK1 = [
    daily(10, 100, 105, 95, 101),
    daily(11, 101, 106, 96, 102),
    daily(12, 102, 107, 97, 103),
    daily(13, 103, 108, 98, 104),
    daily(14, 104, 109, 99, 105),
]
# Week 2: Mon Aug 17 - Wed Aug 19 (partial)
WEEK2_PARTIAL = [
    daily(17, 110, 115, 109, 111),
    daily(18, 111, 116, 110, 112),
    daily(19, 112, 117, 111, 113),
]


def test_previous_day_high_low_close():
    candles = WEEK2_PARTIAL
    levels = extract_previous_day_levels(candles, et(2026, 8, 19, 12, 0))

    by_source = {lvl.source: lvl for lvl in levels}
    pdh = by_source["previous_day_high"]
    pdl = by_source["previous_day_low"]
    pdc = by_source["previous_day_close"]

    assert pdh.price == pytest.approx(116, abs=TOLERANCE)
    assert pdh.kind == LevelKind.RESISTANCE
    assert pdl.price == pytest.approx(110, abs=TOLERANCE)
    assert pdl.kind == LevelKind.SUPPORT
    assert pdc.price == pytest.approx(112, abs=TOLERANCE)
    assert pdc.kind == LevelKind.REFERENCE

    for lvl in levels:
        assert lvl.source_timeframe == Timeframe.ONE_DAY
        assert lvl.origin_timestamp == candles[1].timestamp  # Aug 18
        assert lvl.known_at == candle_complete_at(candles[1])


def test_previous_day_levels_empty_with_no_prior_day():
    levels = extract_previous_day_levels([WEEK2_PARTIAL[0]], et(2026, 8, 17, 10, 0))
    assert levels == []


def test_previous_week_high_low_close():
    candles = WEEK1 + WEEK2_PARTIAL
    levels = extract_previous_week_levels(candles, et(2026, 8, 19, 12, 0))

    by_source = {lvl.source: lvl for lvl in levels}
    pwh = by_source["previous_week_high"]
    pwl = by_source["previous_week_low"]
    pwc = by_source["previous_week_close"]

    assert pwh.price == pytest.approx(109, abs=TOLERANCE)  # Friday's high
    assert pwh.kind == LevelKind.RESISTANCE
    assert pwh.origin_timestamp == WEEK1[4].timestamp  # the specific day it occurred

    assert pwl.price == pytest.approx(95, abs=TOLERANCE)  # Monday's low
    assert pwl.kind == LevelKind.SUPPORT
    assert pwl.origin_timestamp == WEEK1[0].timestamp

    assert pwc.price == pytest.approx(105, abs=TOLERANCE)  # Friday's close
    assert pwc.kind == LevelKind.REFERENCE

    # known_at must be the same for all three: the week isn't "final" until
    # it's fully over, regardless of which specific day produced the extreme.
    expected_known_at = et(2026, 8, 17, 0, 0)  # Monday after the week ends
    assert pwh.known_at == expected_known_at
    assert pwl.known_at == expected_known_at
    assert pwc.known_at == expected_known_at


def test_previous_week_levels_empty_with_no_prior_week():
    levels = extract_previous_week_levels(WEEK2_PARTIAL, et(2026, 8, 19, 12, 0))
    assert levels == []


def test_session_open_level():
    todays_bar = daily(19, 112, 117, 111, 113)
    levels = extract_session_open_level(WEEK1 + [todays_bar], et(2026, 8, 19, 12, 0))

    assert len(levels) == 1
    level = levels[0]
    assert level.price == pytest.approx(112, abs=TOLERANCE)
    assert level.kind == LevelKind.REFERENCE
    assert level.source == "session_open"
    assert level.origin_timestamp == todays_bar.timestamp
    assert level.known_at == todays_bar.timestamp  # known immediately, no delay


def test_session_open_unavailable_before_todays_bar_exists():
    levels = extract_session_open_level(WEEK1, et(2026, 8, 19, 8, 0))
    assert levels == []


def test_session_open_ignores_premarket():
    from tests.conftest import make_candle

    premarket = make_candle(
        symbol="TEST",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=et(2026, 8, 19, 7, 0),
        session=MarketSession.PRE_MARKET,
        open=999,
        high=999,
        low=999,
        close=999,
        volume=1,
    )
    levels = extract_session_open_level(WEEK1 + [premarket], et(2026, 8, 19, 8, 0))
    assert levels == []
