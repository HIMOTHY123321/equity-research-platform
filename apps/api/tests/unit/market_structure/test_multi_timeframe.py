from datetime import timedelta

from app.market_structure.config import MarketStructureConfig
from app.market_structure.multi_timeframe import summarize_multi_timeframe_structure
from app.market_structure.schemas import TrendClass
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, make_candle

CONFIG = MarketStructureConfig(left_bars=2, right_bars=2)


# A hand-verified zigzag (see test_swings.py-style fixtures): with
# left_bars=right_bars=2 this produces confirmed LOW(90) -> HIGH(118) ->
# LOW(96, a Higher Low) -> HIGH(128, a Higher High) -> clear "bullish" trend.
_BULLISH_POINTS = [
    (0, 102, 97),
    (1, 100, 95),
    (2, 98, 90),
    (3, 105, 95),
    (4, 112, 100),
    (5, 118, 108),
    (6, 110, 100),
    (7, 106, 96),
    (8, 112, 102),
    (9, 116, 106),
    (10, 128, 118),
    (11, 120, 110),
    (12, 116, 106),
]


def _points_to_candles(points, timeframe, base):
    return [
        make_candle(
            timeframe=timeframe,
            timestamp=base + timedelta(hours=i),
            session=MarketSession.REGULAR,
            open=(high + low) / 2,
            high=high,
            low=low,
            close=(high + low) / 2,
            volume=1000,
        )
        for i, high, low in points
    ]


def _bullish_series(timeframe, count=13, base=None):
    base = base or et(2026, 8, 17, 9, 30)
    return _points_to_candles(_BULLISH_POINTS[:count], timeframe, base)


def _bearish_series(timeframe, count=13, base=None):
    base = base or et(2026, 8, 17, 9, 30)
    # Mirror the bullish zigzag around 150 -> a declining LH/LL structure.
    mirrored = [(i, 300 - low, 300 - high) for i, high, low in _BULLISH_POINTS[:count]]
    return _points_to_candles(mirrored, timeframe, base)


def test_each_timeframe_reported_independently():
    candles_by_timeframe = {
        Timeframe.ONE_DAY: _bullish_series(Timeframe.ONE_DAY),
        Timeframe.ONE_HOUR: _bearish_series(Timeframe.ONE_HOUR),
    }
    as_of = et(2026, 8, 20, 12, 0)

    summary = summarize_multi_timeframe_structure("TEST", candles_by_timeframe, as_of, CONFIG)

    assert summary.by_timeframe["1d"].trend == TrendClass.BULLISH
    assert summary.by_timeframe["1h"].trend == TrendClass.BEARISH


def test_alignment_when_daily_and_4h_agree():
    candles_by_timeframe = {
        Timeframe.ONE_DAY: _bullish_series(Timeframe.ONE_DAY),
        Timeframe.FOUR_HOUR: _bullish_series(Timeframe.FOUR_HOUR),
    }
    as_of = et(2026, 8, 20, 12, 0)

    summary = summarize_multi_timeframe_structure("TEST", candles_by_timeframe, as_of, CONFIG)
    assert summary.higher_timeframe_alignment == "aligned"


def test_mixed_when_daily_and_4h_disagree():
    candles_by_timeframe = {
        Timeframe.ONE_DAY: _bullish_series(Timeframe.ONE_DAY),
        Timeframe.FOUR_HOUR: _bearish_series(Timeframe.FOUR_HOUR),
    }
    as_of = et(2026, 8, 20, 12, 0)

    summary = summarize_multi_timeframe_structure("TEST", candles_by_timeframe, as_of, CONFIG)
    assert summary.higher_timeframe_alignment == "mixed"


def test_alignment_unavailable_when_a_timeframe_is_missing():
    candles_by_timeframe = {Timeframe.ONE_DAY: _bullish_series(Timeframe.ONE_DAY)}
    as_of = et(2026, 8, 20, 12, 0)

    summary = summarize_multi_timeframe_structure("TEST", candles_by_timeframe, as_of, CONFIG)
    assert summary.higher_timeframe_alignment is None


def test_insufficient_one_timeframe_does_not_affect_another():
    candles_by_timeframe = {
        Timeframe.ONE_DAY: _bullish_series(Timeframe.ONE_DAY),
        Timeframe.ONE_HOUR: _bullish_series(Timeframe.ONE_HOUR, count=2),  # too few for structure
    }
    as_of = et(2026, 8, 20, 12, 0)

    summary = summarize_multi_timeframe_structure("TEST", candles_by_timeframe, as_of, CONFIG)

    assert summary.by_timeframe["1d"].trend == TrendClass.BULLISH
    assert summary.by_timeframe["1h"].trend == TrendClass.INSUFFICIENT_DATA


def test_invariant_8_timeframes_independently_honor_their_own_historical_as_of():
    # Two completely different daily structures (bullish vs bearish), paired
    # with the SAME untouched hourly series. The hourly summary must be
    # byte-identical regardless of what the daily side looks like -- each
    # timeframe's snapshot is a pure function of only its own candles and
    # as_of, never influenced by another timeframe's data.
    hourly = _bullish_series(Timeframe.ONE_HOUR, count=13)
    as_of = et(2026, 8, 20, 12, 0)

    summary_with_bullish_daily = summarize_multi_timeframe_structure(
        "TEST",
        {Timeframe.ONE_DAY: _bullish_series(Timeframe.ONE_DAY, count=13), Timeframe.ONE_HOUR: hourly},
        as_of,
        CONFIG,
    )
    summary_with_bearish_daily = summarize_multi_timeframe_structure(
        "TEST",
        {Timeframe.ONE_DAY: _bearish_series(Timeframe.ONE_DAY, count=13), Timeframe.ONE_HOUR: hourly},
        as_of,
        CONFIG,
    )

    assert summary_with_bullish_daily.by_timeframe["1h"] == summary_with_bearish_daily.by_timeframe["1h"]
    assert summary_with_bullish_daily.by_timeframe["1d"] != summary_with_bearish_daily.by_timeframe["1d"]


def test_invariant_8_extending_one_timeframe_does_not_change_the_others_snapshot():
    # Same idea, but using Phase-3-style prefix/extension: extending the
    # DAILY series into the future (using real day-spaced timestamps, since
    # ONE_DAY completeness is calendar-date-based) must not retroactively
    # change an earlier daily snapshot, and must never touch the hourly one.
    daily_base = et(2026, 8, 3, 9, 30)  # a Monday
    daily_points = [(i, 100 + i, 95 + i) for i in range(20)]  # simple uptrend, 1 candle/day
    daily_short = [
        make_candle(
            timeframe=Timeframe.ONE_DAY,
            timestamp=daily_base + timedelta(days=i),
            session=MarketSession.REGULAR,
            open=(h + lo) / 2,
            high=h,
            low=lo,
            close=(h + lo) / 2,
            volume=1000,
        )
        for i, h, lo in daily_points[:10]
    ]
    daily_long = [
        make_candle(
            timeframe=Timeframe.ONE_DAY,
            timestamp=daily_base + timedelta(days=i),
            session=MarketSession.REGULAR,
            open=(h + lo) / 2,
            high=h,
            low=lo,
            close=(h + lo) / 2,
            volume=1000,
        )
        for i, h, lo in daily_points
    ]
    hourly = _bullish_series(Timeframe.ONE_HOUR, count=13)
    as_of = daily_short[-1].timestamp + timedelta(hours=12)

    summary_short = summarize_multi_timeframe_structure(
        "TEST", {Timeframe.ONE_DAY: daily_short, Timeframe.ONE_HOUR: hourly}, as_of, CONFIG
    )
    summary_long = summarize_multi_timeframe_structure(
        "TEST", {Timeframe.ONE_DAY: daily_long, Timeframe.ONE_HOUR: hourly}, as_of, CONFIG
    )

    assert summary_short.by_timeframe["1d"] == summary_long.by_timeframe["1d"]
    assert summary_short.by_timeframe["1h"] == summary_long.by_timeframe["1h"]
