"""Shared building blocks: the completeness/as-of policy every feature in this
package follows, plus the vocabulary for "we don't have enough data" that
lets consumers tell a real 0 from a missing value.

As-of / no-lookahead policy
----------------------------
Every entry point in this package takes an explicit `as_of: datetime` and a
candle series. Two things follow from that, deliberately:

1. The engine defensively re-filters the series to `timestamp <= as_of`
   itself — it never trusts a caller's claim that a series was already
   truncated. This is what makes it safe to reuse for backtesting: hand it
   the full history plus a historical `as_of` and it cannot see the future,
   even if the caller has a bug.
2. Continuous features (ATR, moving averages, rolling levels, volume) use
   the most recent available candle even if that candle is still forming as
   of `as_of` — a still-forming bar's high/low/volume-so-far genuinely was
   observable at that instant, so using it is not lookahead. Discrete
   pattern features (the latest-candle body/wick classification) instead use
   the latest *completed* candle, since "was this candle bullish?" shouldn't
   flip mid-formation. `DataQuality.latest_candle_is_complete` tells callers
   which situation they're in.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from app.schemas.market_data import Candle, Timeframe

# Nominal bar duration used only to decide whether the most recent bar could
# still be receiving new data. Not used for aggregation (see market_data).
TIMEFRAME_DURATION: dict[Timeframe, timedelta] = {
    Timeframe.ONE_MIN: timedelta(minutes=1),
    Timeframe.FIVE_MIN: timedelta(minutes=5),
    Timeframe.FIFTEEN_MIN: timedelta(minutes=15),
    Timeframe.ONE_HOUR: timedelta(hours=1),
    Timeframe.FOUR_HOUR: timedelta(hours=4),
}


class FeatureStatus(str, Enum):
    OK = "ok"
    INSUFFICIENT_HISTORY = "insufficient_history"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


def truncate_to_as_of(candles: list[Candle], as_of: datetime) -> tuple[list[Candle], int]:
    """Defensively drop any candle after `as_of`. Returns (kept, dropped_count)."""
    kept = [c for c in candles if c.timestamp <= as_of]
    return kept, len(candles) - len(kept)


def is_candle_complete(candle: Candle, as_of: datetime) -> bool:
    """Whether `candle` could no longer receive new data as of `as_of`."""
    if candle.timeframe == Timeframe.ONE_DAY:
        from app.market_data.sessions import exchange_trading_date

        return exchange_trading_date(candle.timestamp) < exchange_trading_date(as_of)
    if candle.timeframe == Timeframe.ONE_WEEK:
        from app.market_data.sessions import exchange_trading_date

        this_week = exchange_trading_date(candle.timestamp).isocalendar()[:2]
        as_of_week = exchange_trading_date(as_of).isocalendar()[:2]
        return this_week < as_of_week

    duration = TIMEFRAME_DURATION.get(candle.timeframe)
    if duration is None:
        raise ValueError(f"No known duration for timeframe {candle.timeframe.value}")
    return as_of >= candle.timestamp + duration


def latest_completed_candle(candles: list[Candle], as_of: datetime) -> Candle | None:
    """The most recent candle in `candles` that is fully complete as of `as_of`."""
    for candle in reversed(candles):
        if is_candle_complete(candle, as_of):
            return candle
    return None
