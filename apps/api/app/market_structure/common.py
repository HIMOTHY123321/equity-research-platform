"""As-of/no-lookahead policy for this package.

Deliberately self-contained rather than importing app.features.common:
Phase 4 is required to stay independent of the feature engine (see the ADR),
even though both packages need identical "is this candle complete" logic.

Structure detection additionally needs something the feature engine never
did: the exact instant a candle *becomes* complete, not just a yes/no
answer. That instant is `pivot_timestamp` vs `confirmed_at`'s dividing
line — see swings.py.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum

from app.market_data.sessions import EXCHANGE_TZ, exchange_trading_date
from app.schemas.market_data import Candle, Timeframe

TIMEFRAME_DURATION: dict[Timeframe, timedelta] = {
    Timeframe.ONE_MIN: timedelta(minutes=1),
    Timeframe.FIVE_MIN: timedelta(minutes=5),
    Timeframe.FIFTEEN_MIN: timedelta(minutes=15),
    Timeframe.ONE_HOUR: timedelta(hours=1),
    Timeframe.FOUR_HOUR: timedelta(hours=4),
}


class StructureStatus(str, Enum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"


def candle_complete_at(candle: Candle) -> datetime:
    """The earliest instant at which `candle` could no longer receive new
    data — i.e. the earliest legal `confirmed_at`/`break_timestamp` basis
    for anything derived from it."""
    if candle.timeframe == Timeframe.ONE_DAY:
        next_date: date = exchange_trading_date(candle.timestamp) + timedelta(days=1)
        return datetime.combine(next_date, time.min, tzinfo=EXCHANGE_TZ)

    duration = TIMEFRAME_DURATION.get(candle.timeframe)
    if duration is None:
        raise ValueError(f"No known duration for timeframe {candle.timeframe.value}")
    return candle.timestamp + duration


def is_candle_complete(candle: Candle, as_of: datetime) -> bool:
    return as_of >= candle_complete_at(candle)


def truncate_to_as_of(candles: list[Candle], as_of: datetime) -> tuple[list[Candle], int]:
    """Defensively drop any candle after `as_of`. Returns (kept, dropped_count)."""
    kept = [c for c in candles if c.timestamp <= as_of]
    return kept, len(candles) - len(kept)


def completed_only(candles: list[Candle], as_of: datetime) -> list[Candle]:
    """Drop a trailing still-forming candle, if any. Structure detection never
    evaluates a pivot using a bar whose high/low could still change."""
    return [c for c in candles if is_candle_complete(c, as_of)]
