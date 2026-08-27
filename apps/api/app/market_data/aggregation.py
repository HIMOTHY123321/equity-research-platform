"""Deterministic, session-aware construction of 4H candles from 1H candles.

Alpaca does not offer a native 4-hour timeframe, so we build it ourselves.
Blindly grouping "every four 1H bars" would silently merge bars across
trading-day boundaries (and across holiday-shortened sessions), producing a
4H bar that mixes two unrelated sessions. Instead: extended-hours bars are
excluded (4H structure is regular-session structure), bars are grouped by
exchange trading date first, and only then bucketed within a single day by
elapsed time since the regular session open (09:30 ET) — so a bucket can
never span two calendar trading days.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type

from app.market_data.sessions import EXCHANGE_TZ, REGULAR_OPEN, exchange_trading_date
from app.schemas.market_data import Candle, MarketSession, Timeframe

FOUR_HOURS_SECONDS = 4 * 3600
_REGULAR_OPEN_SECONDS = REGULAR_OPEN.hour * 3600 + REGULAR_OPEN.minute * 60


def aggregate_hourly_to_4h(hourly_candles: list[Candle]) -> list[Candle]:
    for candle in hourly_candles:
        if candle.timeframe != Timeframe.ONE_HOUR:
            raise ValueError(f"aggregate_hourly_to_4h expects 1h candles, got {candle.timeframe}")

    regular = sorted(
        (c for c in hourly_candles if c.session == MarketSession.REGULAR),
        key=lambda c: c.timestamp,
    )

    by_day: dict[date_type, list[Candle]] = defaultdict(list)
    for candle in regular:
        by_day[exchange_trading_date(candle.timestamp)].append(candle)

    result: list[Candle] = []
    for _, day_candles in sorted(by_day.items()):
        buckets: dict[int, list[Candle]] = defaultdict(list)
        for candle in day_candles:
            local = candle.timestamp.astimezone(EXCHANGE_TZ)
            elapsed_seconds = (
                local.hour * 3600 + local.minute * 60 + local.second
            ) - _REGULAR_OPEN_SECONDS
            bucket_index = max(elapsed_seconds, 0) // FOUR_HOURS_SECONDS
            buckets[bucket_index].append(candle)

        for _, bucket_candles in sorted(buckets.items()):
            bucket_candles.sort(key=lambda c: c.timestamp)
            result.append(
                Candle(
                    symbol=bucket_candles[0].symbol,
                    timeframe=Timeframe.FOUR_HOUR,
                    timestamp=bucket_candles[0].timestamp,
                    session=MarketSession.REGULAR,
                    open=bucket_candles[0].open,
                    high=max(c.high for c in bucket_candles),
                    low=min(c.low for c in bucket_candles),
                    close=bucket_candles[-1].close,
                    volume=sum(c.volume for c in bucket_candles),
                )
            )

    return result
