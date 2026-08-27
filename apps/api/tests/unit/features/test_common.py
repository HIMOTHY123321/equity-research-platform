
from app.features.common import is_candle_complete, latest_completed_candle, truncate_to_as_of
from app.schemas.market_data import Timeframe
from tests.conftest import et, make_candle
from tests.unit.features.conftest import daily, hourly


def test_daily_candle_incomplete_on_same_trading_day():
    candle = daily(17, 100, 101, 99, 100.5, 1000)
    assert is_candle_complete(candle, et(2026, 8, 17, 15, 0)) is False


def test_daily_candle_complete_on_later_trading_day():
    candle = daily(17, 100, 101, 99, 100.5, 1000)
    assert is_candle_complete(candle, et(2026, 8, 18, 9, 30)) is True


def test_hourly_candle_incomplete_before_period_end():
    candle = hourly(17, 10, 30, 100, 101, 99, 100.5, 1000)
    assert is_candle_complete(candle, et(2026, 8, 17, 11, 0)) is False


def test_hourly_candle_complete_at_period_end():
    candle = hourly(17, 10, 30, 100, 101, 99, 100.5, 1000)
    assert is_candle_complete(candle, et(2026, 8, 17, 11, 30)) is True


def test_weekly_candle_uses_iso_week_comparison():
    candle = make_candle(timeframe=Timeframe.ONE_WEEK, timestamp=et(2026, 8, 17, 9, 30))
    assert is_candle_complete(candle, et(2026, 8, 24, 9, 30)) is True
    assert is_candle_complete(candle, et(2026, 8, 19, 9, 30)) is False


def test_truncate_drops_future_candles():
    c1 = daily(17, 100, 101, 99, 100.5, 1000)
    c2 = daily(18, 101, 102, 100, 101.5, 1000)
    c3 = daily(19, 102, 103, 101, 102.5, 1000)

    kept, dropped = truncate_to_as_of([c1, c2, c3], et(2026, 8, 18, 12, 0))

    assert kept == [c1, c2]
    assert dropped == 1


def test_truncate_keeps_everything_when_as_of_is_far_future():
    candles = [daily(17, 100, 101, 99, 100.5, 1000)]
    kept, dropped = truncate_to_as_of(candles, et(2030, 1, 1, 0, 0))
    assert kept == candles
    assert dropped == 0


def test_latest_completed_candle_skips_forming_bar():
    c1 = daily(17, 100, 101, 99, 100.5, 1000)
    c2 = daily(18, 101, 102, 100, 101.5, 1000)  # today, still forming

    result = latest_completed_candle([c1, c2], et(2026, 8, 18, 12, 0))

    assert result == c1


def test_latest_completed_candle_returns_none_when_everything_is_incomplete():
    c1 = daily(17, 100, 101, 99, 100.5, 1000)
    result = latest_completed_candle([c1], et(2026, 8, 17, 12, 0))
    assert result is None


def test_one_minute_candle_uses_its_own_duration():
    candle = make_candle(timeframe=Timeframe.ONE_MIN, timestamp=et(2026, 8, 17, 10, 0))
    assert is_candle_complete(candle, et(2026, 8, 17, 10, 2)) is True
    assert is_candle_complete(candle, et(2026, 8, 17, 10, 0, 30)) is False
