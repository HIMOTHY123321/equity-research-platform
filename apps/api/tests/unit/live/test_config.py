"""Phase 12.1 (#F/#N/#S/#T): deterministic freshness classification, poll
interval resolution, and session/DST handling.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.live.config import (
    DEFAULT_LIVE_CONFIG,
    FreshnessState,
    LiveSessionState,
    SubscriptionPriority,
    classify_freshness,
    resolve_poll_interval,
)
from app.live.market_hours import current_live_session, is_trading_day

# ---------------------------------------------------------------- freshness


def test_fresh_age_is_live():
    assert classify_freshness(0.5, connected=True, session=LiveSessionState.REGULAR) == FreshnessState.LIVE


def test_boundary_age_is_still_live():
    boundary = DEFAULT_LIVE_CONFIG.live_max_age_seconds
    result = classify_freshness(boundary, connected=True, session=LiveSessionState.REGULAR)
    assert result == FreshnessState.LIVE


def test_just_past_live_boundary_is_recent():
    just_over = DEFAULT_LIVE_CONFIG.live_max_age_seconds + 0.01
    result = classify_freshness(just_over, connected=True, session=LiveSessionState.REGULAR)
    assert result == FreshnessState.RECENT


def test_just_past_recent_boundary_is_delayed():
    just_over = DEFAULT_LIVE_CONFIG.recent_max_age_seconds + 0.01
    result = classify_freshness(just_over, connected=True, session=LiveSessionState.REGULAR)
    assert result == FreshnessState.DELAYED


def test_just_past_delayed_boundary_is_stale():
    just_over = DEFAULT_LIVE_CONFIG.delayed_max_age_seconds + 0.01
    result = classify_freshness(just_over, connected=True, session=LiveSessionState.REGULAR)
    assert result == FreshnessState.STALE


def test_disconnected_overrides_everything_else():
    result = classify_freshness(0.1, connected=False, session=LiveSessionState.REGULAR)
    assert result == FreshnessState.DISCONNECTED


def test_market_closed_overrides_a_fresh_looking_age():
    # A stale last-known timestamp from Friday close can look "fresh" in
    # naive seconds-since-epoch math; MARKET_CLOSED must win regardless.
    assert (
        classify_freshness(0.1, connected=True, session=LiveSessionState.MARKET_CLOSED)
        == FreshnessState.MARKET_CLOSED
    )


def test_missing_age_is_unavailable_not_zero():
    result = classify_freshness(None, connected=True, session=LiveSessionState.REGULAR)
    assert result == FreshnessState.UNAVAILABLE


def test_never_left_looking_live_when_actually_stale():
    # A stale-data guard: an old timestamp must never classify as LIVE.
    assert classify_freshness(600.0, connected=True, session=LiveSessionState.REGULAR) != FreshnessState.LIVE


# ------------------------------------------------------------- poll interval


def test_viewed_ticker_polls_at_the_providers_own_floor():
    interval = resolve_poll_interval(3.0, SubscriptionPriority.VIEWED)
    assert interval == 3.0


def test_never_polls_faster_than_the_provider_floor_even_if_target_is_lower():
    # target_interval_seconds defaults to 1.0; a provider floor of 3.0 must win.
    interval = resolve_poll_interval(3.0, SubscriptionPriority.VIEWED)
    assert interval >= 3.0


def test_lower_priority_tiers_back_off_further():
    viewed = resolve_poll_interval(3.0, SubscriptionPriority.VIEWED)
    watchlist = resolve_poll_interval(3.0, SubscriptionPriority.WATCHLIST)
    background = resolve_poll_interval(3.0, SubscriptionPriority.BACKGROUND_BENCHMARK)
    assert viewed < watchlist < background


# --------------------------------------------------------- session / DST


def test_saturday_is_market_closed():
    saturday = datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)
    assert current_live_session(saturday) == LiveSessionState.MARKET_CLOSED
    assert is_trading_day(saturday) is False


def test_sunday_is_market_closed():
    sunday = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
    assert current_live_session(sunday) == LiveSessionState.MARKET_CLOSED


@pytest.mark.parametrize(
    "utc_hour_minute,expected",
    [
        ((14, 37), LiveSessionState.REGULAR),  # 10:37 EDT
        ((9, 0), LiveSessionState.PRE_MARKET),  # 05:00 EDT
        ((21, 0), LiveSessionState.AFTER_HOURS),  # 17:00 EDT
    ],
)
def test_weekday_session_classification_in_edt(utc_hour_minute, expected):
    hour, minute = utc_hour_minute
    # 2026-09-17 is a Thursday, well inside EDT (DST active).
    weekday = datetime(2026, 9, 17, hour, minute, tzinfo=timezone.utc)
    assert current_live_session(weekday) == expected


def test_session_classification_across_the_edt_to_est_dst_boundary():
    # 2026-11-01 is the DST rollback Sunday (America/New_York); use the
    # Monday after (2026-11-02) to get a real EST trading day. 13:00 UTC
    # is 08:00 EST (UTC-5) -- pre-market.
    est_weekday = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
    assert current_live_session(est_weekday) == LiveSessionState.PRE_MARKET
    # The same 13:00 UTC clock time is 09:00 EDT (UTC-4) on a summer date
    # -- also pre-market, so instead prove the DST switch directly: 13:30
    # UTC is 08:30 EST (pre-market) but 09:30 EDT (regular) -- the offset,
    # not just the local clock reading, must actually change across the
    # transition.
    edt_weekday = datetime(2026, 6, 15, 13, 30, tzinfo=timezone.utc)  # summer -> EDT
    est_weekday_2 = datetime(2026, 11, 2, 13, 30, tzinfo=timezone.utc)  # post-rollback -> EST
    assert current_live_session(edt_weekday) == LiveSessionState.REGULAR
    assert current_live_session(est_weekday_2) == LiveSessionState.PRE_MARKET
