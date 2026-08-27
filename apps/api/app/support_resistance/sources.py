"""Previous trading day / week / session-open raw levels, derived directly
from daily candles rather than from a FeatureSnapshot -- this engine owns
its own minimal previous-period extraction (see the ADR for why), the same
way Phase 4 kept its own completeness helpers independent of Phase 3's.

Reuses the same trick as app.features.previous_period: "most recent
completed period before the current one" skips weekends/holidays for free,
since they never produce a candle in the first place.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.market_data.sessions import EXCHANGE_TZ, exchange_trading_date
from app.market_structure.common import candle_complete_at
from app.schemas.market_data import Candle, MarketSession, Timeframe
from app.support_resistance.ids import raw_level_id
from app.support_resistance.schemas import LevelKind, RawLevel


def _week_start_after(trading_date: date) -> datetime:
    """The instant an ISO week containing `trading_date` is definitely over:
    midnight ET on the following Monday."""
    days_until_next_monday = 7 - trading_date.weekday()
    next_monday = trading_date + timedelta(days=days_until_next_monday)
    return datetime.combine(next_monday, time.min, tzinfo=EXCHANGE_TZ)


def extract_previous_day_levels(daily_candles: list[Candle], as_of: datetime) -> list[RawLevel]:
    today = exchange_trading_date(as_of)
    completed = [c for c in daily_candles if exchange_trading_date(c.timestamp) < today]
    if not completed:
        return []

    previous_day = max(completed, key=lambda c: c.timestamp)
    known_at = candle_complete_at(previous_day)

    return [
        RawLevel(
            id=raw_level_id("previous_day_high", Timeframe.ONE_DAY, previous_day.timestamp),
            price=previous_day.high,
            kind=LevelKind.RESISTANCE,
            source="previous_day_high",
            source_timeframe=Timeframe.ONE_DAY,
            origin_timestamp=previous_day.timestamp,
            known_at=known_at,
        ),
        RawLevel(
            id=raw_level_id("previous_day_low", Timeframe.ONE_DAY, previous_day.timestamp),
            price=previous_day.low,
            kind=LevelKind.SUPPORT,
            source="previous_day_low",
            source_timeframe=Timeframe.ONE_DAY,
            origin_timestamp=previous_day.timestamp,
            known_at=known_at,
        ),
        RawLevel(
            id=raw_level_id("previous_day_close", Timeframe.ONE_DAY, previous_day.timestamp),
            price=previous_day.close,
            kind=LevelKind.REFERENCE,
            source="previous_day_close",
            source_timeframe=Timeframe.ONE_DAY,
            origin_timestamp=previous_day.timestamp,
            known_at=known_at,
        ),
    ]


def extract_previous_week_levels(daily_candles: list[Candle], as_of: datetime) -> list[RawLevel]:
    current_week = exchange_trading_date(as_of).isocalendar()[:2]

    by_week: dict[tuple, list[Candle]] = {}
    for candle in daily_candles:
        week_key = exchange_trading_date(candle.timestamp).isocalendar()[:2]
        if week_key < current_week:
            by_week.setdefault(week_key, []).append(candle)

    if not by_week:
        return []

    previous_week_key = max(by_week.keys())
    week_candles = sorted(by_week[previous_week_key], key=lambda c: c.timestamp)

    high_candle = max(week_candles, key=lambda c: c.high)
    low_candle = min(week_candles, key=lambda c: c.low)
    close_candle = week_candles[-1]
    known_at = _week_start_after(exchange_trading_date(week_candles[-1].timestamp))

    return [
        RawLevel(
            id=raw_level_id("previous_week_high", Timeframe.ONE_DAY, high_candle.timestamp),
            price=high_candle.high,
            kind=LevelKind.RESISTANCE,
            source="previous_week_high",
            source_timeframe=Timeframe.ONE_DAY,
            origin_timestamp=high_candle.timestamp,
            known_at=known_at,
        ),
        RawLevel(
            id=raw_level_id("previous_week_low", Timeframe.ONE_DAY, low_candle.timestamp),
            price=low_candle.low,
            kind=LevelKind.SUPPORT,
            source="previous_week_low",
            source_timeframe=Timeframe.ONE_DAY,
            origin_timestamp=low_candle.timestamp,
            known_at=known_at,
        ),
        RawLevel(
            id=raw_level_id("previous_week_close", Timeframe.ONE_DAY, close_candle.timestamp),
            price=close_candle.close,
            kind=LevelKind.REFERENCE,
            source="previous_week_close",
            source_timeframe=Timeframe.ONE_DAY,
            origin_timestamp=close_candle.timestamp,
            known_at=known_at,
        ),
    ]


def extract_session_open_level(daily_candles: list[Candle], as_of: datetime) -> list[RawLevel]:
    """Today's regular-session open. Known immediately -- a daily bar's open
    is fixed the instant the session starts and never revised (same
    reasoning as the Phase 3 gap feature)."""
    today = exchange_trading_date(as_of)
    todays_bar = next(
        (
            c
            for c in daily_candles
            if exchange_trading_date(c.timestamp) == today and c.session == MarketSession.REGULAR
        ),
        None,
    )
    if todays_bar is None:
        return []

    return [
        RawLevel(
            id=raw_level_id("session_open", Timeframe.ONE_DAY, todays_bar.timestamp),
            price=todays_bar.open,
            kind=LevelKind.REFERENCE,
            source="session_open",
            source_timeframe=Timeframe.ONE_DAY,
            origin_timestamp=todays_bar.timestamp,
            known_at=todays_bar.timestamp,
        )
    ]
