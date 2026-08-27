"""Previous completed trading day / week.

Both use the same trick to handle Mondays, holidays, and missing sessions
uniformly with no special-casing: rather than looking at "yesterday" by the
calendar, we take the most recent *available* daily candle strictly before
the current trading date (day) or current ISO week (week). Weekends and
holidays never produce a candle in the first place, so "most recent available
before today" already skips straight past them to Friday, or past a holiday
to the prior session — no calendar-of-holidays lookup needed.
"""

from __future__ import annotations

from datetime import datetime

from app.features.common import FeatureStatus
from app.features.schemas import PreviousDayLevels, PreviousWeekLevels
from app.market_data.sessions import exchange_trading_date
from app.schemas.market_data import Candle


def compute_previous_day_levels(daily_candles: list[Candle], as_of: datetime) -> PreviousDayLevels:
    today = exchange_trading_date(as_of)
    completed = [c for c in daily_candles if exchange_trading_date(c.timestamp) < today]
    if not completed:
        return PreviousDayLevels(status=FeatureStatus.INSUFFICIENT_HISTORY)

    last = max(completed, key=lambda c: c.timestamp)
    percent_change = (last.close - last.open) / last.open * 100 if last.open else None

    return PreviousDayLevels(
        status=FeatureStatus.OK,
        trading_date=exchange_trading_date(last.timestamp),
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        volume=last.volume,
        range=last.high - last.low,
        percent_change=percent_change,
    )


def compute_previous_week_levels(daily_candles: list[Candle], as_of: datetime) -> PreviousWeekLevels:
    current_week = exchange_trading_date(as_of).isocalendar()[:2]

    by_week: dict[tuple, list[Candle]] = {}
    for candle in daily_candles:
        week_key = exchange_trading_date(candle.timestamp).isocalendar()[:2]
        if week_key < current_week:
            by_week.setdefault(week_key, []).append(candle)

    if not by_week:
        return PreviousWeekLevels(status=FeatureStatus.INSUFFICIENT_HISTORY)

    previous_week_key = max(by_week.keys())
    week_candles = sorted(by_week[previous_week_key], key=lambda c: c.timestamp)

    week_open = week_candles[0].open
    week_close = week_candles[-1].close
    week_high = max(c.high for c in week_candles)
    week_low = min(c.low for c in week_candles)
    percent_change = (week_close - week_open) / week_open * 100 if week_open else None

    return PreviousWeekLevels(
        status=FeatureStatus.OK,
        week_start_date=exchange_trading_date(week_candles[0].timestamp),
        week_end_date=exchange_trading_date(week_candles[-1].timestamp),
        open=week_open,
        high=week_high,
        low=week_low,
        close=week_close,
        volume=sum(c.volume for c in week_candles),
        range=week_high - week_low,
        percent_change=percent_change,
        trading_days_counted=len(week_candles),
    )
