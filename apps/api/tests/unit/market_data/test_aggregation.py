import pytest

from app.market_data.aggregation import aggregate_hourly_to_4h
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, make_candle


def _hourly(day_hours_minutes, **overrides):
    """Build a regular-session 1H candle at the given (hour, minute) on Aug 17 2026 ET."""
    hour, minute = day_hours_minutes
    return make_candle(
        timeframe=Timeframe.ONE_HOUR,
        timestamp=et(2026, 8, 17, hour, minute),
        session=MarketSession.REGULAR,
        **overrides,
    )


def test_full_regular_session_splits_into_two_buckets():
    bars = [
        _hourly((9, 30), open=10, high=12, low=9, close=11, volume=100),
        _hourly((10, 30), open=11, high=13, low=10, close=12, volume=100),
        _hourly((11, 30), open=12, high=14, low=11, close=13, volume=100),
        _hourly((12, 30), open=13, high=15, low=12, close=14, volume=100),
        _hourly((13, 30), open=14, high=16, low=13, close=15, volume=100),
        _hourly((14, 30), open=15, high=17, low=14, close=16, volume=100),
        _hourly((15, 30), open=16, high=18, low=15, close=17, volume=100),
    ]

    result = aggregate_hourly_to_4h(bars)

    assert len(result) == 2
    first, second = result
    assert first.timeframe == Timeframe.FOUR_HOUR
    assert first.timestamp.astimezone(bars[0].timestamp.tzinfo).hour == 9
    assert first.open == 10
    assert first.high == 15  # max of first 4 bars' highs
    assert first.low == 9
    assert first.close == 14  # close of the 4th bar (12:30)
    assert first.volume == 400

    assert second.open == 14
    assert second.high == 18
    assert second.low == 13
    assert second.close == 17  # close of the last (15:30) bar
    assert second.volume == 300


def test_short_session_produces_single_bucket_not_merged_with_next_day():
    early_close_day = [
        _hourly((9, 30)),
        _hourly((10, 30)),
        _hourly((11, 30)),
        _hourly((12, 30)),
    ]
    next_day_open = [
        make_candle(
            timeframe=Timeframe.ONE_HOUR,
            timestamp=et(2026, 8, 18, 9, 30),
            session=MarketSession.REGULAR,
        )
    ]

    result = aggregate_hourly_to_4h(early_close_day + next_day_open)

    assert len(result) == 2
    # the short session's 4 bars stayed in one bucket, not spilling into day 2
    assert result[0].volume == 4 * early_close_day[0].volume
    assert result[1].volume == next_day_open[0].volume


def test_extended_hours_bars_are_excluded_from_aggregation():
    bars = [
        make_candle(
            timeframe=Timeframe.ONE_HOUR,
            timestamp=et(2026, 8, 17, 8, 30),
            session=MarketSession.PRE_MARKET,
            volume=9999,
        ),
        _hourly((9, 30), volume=100),
        _hourly((10, 30), volume=100),
        make_candle(
            timeframe=Timeframe.ONE_HOUR,
            timestamp=et(2026, 8, 17, 16, 30),
            session=MarketSession.AFTER_HOURS,
            volume=9999,
        ),
    ]

    result = aggregate_hourly_to_4h(bars)

    assert len(result) == 1
    assert result[0].volume == 200  # only the two regular-session bars counted


def test_two_trading_days_never_merge_into_one_bucket():
    day1 = [_hourly((15, 30), volume=50)]  # last regular bar of day 1
    day2 = [
        make_candle(
            timeframe=Timeframe.ONE_HOUR,
            timestamp=et(2026, 8, 18, 9, 30),
            session=MarketSession.REGULAR,
            volume=60,
        )
    ]

    result = aggregate_hourly_to_4h(day1 + day2)

    assert len(result) == 2
    assert result[0].volume == 50
    assert result[1].volume == 60


def test_rejects_non_hourly_input():
    daily_candle = make_candle(timeframe=Timeframe.ONE_DAY)
    with pytest.raises(ValueError, match="expects 1h candles"):
        aggregate_hourly_to_4h([daily_candle])


def test_empty_input_returns_empty_output():
    assert aggregate_hourly_to_4h([]) == []
