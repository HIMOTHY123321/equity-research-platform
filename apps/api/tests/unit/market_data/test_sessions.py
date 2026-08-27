from datetime import date

from app.market_data.sessions import classify_session, classify_timestamp_session, exchange_trading_date
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, utc


def test_classify_regular_session_open():
    assert classify_timestamp_session(et(2026, 8, 17, 9, 30)) == MarketSession.REGULAR


def test_classify_regular_session_just_before_close():
    assert classify_timestamp_session(et(2026, 8, 17, 15, 59)) == MarketSession.REGULAR


def test_classify_pre_market():
    assert classify_timestamp_session(et(2026, 8, 17, 7, 0)) == MarketSession.PRE_MARKET


def test_classify_after_hours():
    assert classify_timestamp_session(et(2026, 8, 17, 17, 0)) == MarketSession.AFTER_HOURS


def test_classify_at_session_close_boundary_is_after_hours():
    assert classify_timestamp_session(et(2026, 8, 17, 16, 0)) == MarketSession.AFTER_HOURS


def test_classify_daily_timeframe_is_always_regular_regardless_of_time():
    midnight = et(2026, 8, 17, 0, 0)
    assert classify_session(midnight, Timeframe.ONE_DAY) == MarketSession.REGULAR


def test_classify_intraday_timeframe_uses_time_of_day():
    morning = et(2026, 8, 17, 10, 0)
    assert classify_session(morning, Timeframe.ONE_HOUR) == MarketSession.REGULAR


def test_exchange_trading_date_converts_utc_to_exchange_calendar_day():
    # 03:00 UTC on Aug 18 is 23:00 ET on Aug 17 (EDT, UTC-4) -> previous day
    late_utc = utc(2026, 8, 18, 3, 0)
    assert exchange_trading_date(late_utc) == date(2026, 8, 17)
