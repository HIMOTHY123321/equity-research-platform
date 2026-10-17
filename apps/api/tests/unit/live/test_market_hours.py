"""Phase 19.2.1: US equity live-session classification -- weekends must
classify as MARKET_CLOSED, never AFTER_HOURS, regardless of what time of
day it happens to be. Uses America/New_York via ZoneInfo (proper DST),
never a hard-coded EST/EDT offset."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.live.config import LiveSessionState
from app.live.market_hours import current_live_session

_ET = ZoneInfo("America/New_York")


def _et(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=_ET)


def test_saturday_afternoon_is_closed():
    # 2026-10-17 is a Saturday.
    assert current_live_session(_et(2026, 10, 17, 14, 0)) == LiveSessionState.MARKET_CLOSED


def test_sunday_is_closed():
    # 2026-10-18 is a Sunday.
    assert current_live_session(_et(2026, 10, 18, 11, 0)) == LiveSessionState.MARKET_CLOSED
    assert current_live_session(_et(2026, 10, 18, 20, 0)) == LiveSessionState.MARKET_CLOSED


def test_monday_10am_is_regular():
    # 2026-10-19 is a Monday.
    assert current_live_session(_et(2026, 10, 19, 10, 0)) == LiveSessionState.REGULAR


def test_monday_6pm_is_after_hours():
    assert current_live_session(_et(2026, 10, 19, 18, 0)) == LiveSessionState.AFTER_HOURS


def test_monday_late_night_is_closed():
    assert current_live_session(_et(2026, 10, 19, 23, 30)) == LiveSessionState.MARKET_CLOSED


def test_monday_premarket_window_is_pre_market():
    assert current_live_session(_et(2026, 10, 19, 5, 0)) == LiveSessionState.PRE_MARKET


def test_friday_evening_does_not_leak_after_hours_into_saturday():
    """The exact regression this test file exists for: a Friday-evening
    timestamp is genuinely AFTER_HOURS for Friday, but the CURRENT session
    (what the UI must show right now) must be evaluated at the CURRENT
    instant, never frozen from an old event's own timestamp -- see
    app.live.service's ingest_quote/ingest_trade/ingest_nbbo/
    ingest_second_aggregate, which all pass received_at (now), not the
    event's own source timestamp, into current_live_session()."""
    friday_evening = _et(2026, 10, 16, 19, 55)
    assert current_live_session(friday_evening) == LiveSessionState.AFTER_HOURS

    saturday_afternoon = _et(2026, 10, 17, 14, 0)
    assert current_live_session(saturday_afternoon) == LiveSessionState.MARKET_CLOSED


def test_dst_spring_forward_regular_session_boundary():
    # 2026-03-08 is the Sunday DST transition in the US -- the following
    # Monday (2026-03-09) must still classify 9:30am ET as REGULAR using
    # EDT, with no hard-coded UTC offset.
    assert current_live_session(_et(2026, 3, 9, 9, 30)) == LiveSessionState.REGULAR
    assert current_live_session(_et(2026, 3, 9, 9, 29)) == LiveSessionState.PRE_MARKET


def test_dst_fall_back_regular_session_boundary():
    # 2026-11-01 is the Sunday DST transition back to standard time -- the
    # following Monday (2026-11-02) must still classify 9:30am ET as
    # REGULAR using EST, with no hard-coded UTC offset.
    assert current_live_session(_et(2026, 11, 2, 9, 30)) == LiveSessionState.REGULAR
    assert current_live_session(_et(2026, 11, 2, 16, 0)) == LiveSessionState.AFTER_HOURS
