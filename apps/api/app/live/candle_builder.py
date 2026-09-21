"""Phase 12.1 (#G): forming-candle bucketing and OHLCV folding. Purely a
*display* projection -- nothing here ever writes to the candle cache/DB or
is handed to build_market_snapshot/get_candles. Bucket boundaries during the
regular session reuse the exact session-open-relative convention
app.market_data.aggregation already uses for 4H bars (never a second,
diverging alignment rule), so a forming bar reconciles with whatever
get_candles() authoritatively reports once it actually completes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.live.schemas import CandleState, LiveCandle
from app.market_data.sessions import EXCHANGE_TZ, REGULAR_OPEN, classify_timestamp_session
from app.market_structure.common import TIMEFRAME_DURATION
from app.schemas.market_data import Timeframe

_REGULAR_OPEN_SECONDS = REGULAR_OPEN.hour * 3600 + REGULAR_OPEN.minute * 60


def bucket_start(now: datetime, timeframe: Timeframe) -> datetime:
    """The open timestamp of the bar containing `now`."""
    if timeframe == Timeframe.ONE_DAY:
        local_midnight = now.astimezone(EXCHANGE_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight

    duration = TIMEFRAME_DURATION.get(timeframe)
    if duration is None:
        raise ValueError(f"No known live bucketing for timeframe {timeframe.value}")
    duration_seconds = int(duration.total_seconds())

    local = now.astimezone(EXCHANGE_TZ)
    seconds_since_midnight = local.hour * 3600 + local.minute * 60 + local.second

    if classify_timestamp_session(now).value == "regular":
        elapsed = max(seconds_since_midnight - _REGULAR_OPEN_SECONDS, 0)
        bucket_offset = (elapsed // duration_seconds) * duration_seconds
        bucket_seconds = _REGULAR_OPEN_SECONDS + bucket_offset
    else:
        bucket_seconds = (seconds_since_midnight // duration_seconds) * duration_seconds

    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight + timedelta(seconds=bucket_seconds)


def fold_price_into_candle(
    existing: LiveCandle | None,
    *,
    symbol: str,
    timeframe: Timeframe,
    bucket_open: datetime,
    price: float,
    volume: float,
    freshness,
) -> LiveCandle:
    """Fold one more observed price/volume sample into the forming bar for
    `bucket_open`. If `existing` belongs to a different (now-past) bucket,
    a brand-new forming candle starts -- the old one is the caller's
    responsibility to have already emitted as COMPLETED before calling this
    (see LiveMarketService._ingest_quote)."""
    if existing is None or existing.timestamp != bucket_open:
        return LiveCandle(
            symbol=symbol,
            timeframe=timeframe.value,
            timestamp=bucket_open,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=volume,
            state=CandleState.FORMING,
            freshness=freshness,
        )
    return LiveCandle(
        symbol=symbol,
        timeframe=timeframe.value,
        timestamp=bucket_open,
        open=existing.open,
        high=max(existing.high, price),
        low=min(existing.low, price),
        close=price,
        volume=existing.volume + volume,
        state=CandleState.FORMING,
        freshness=freshness,
    )


def fold_aggregate_into_candle(
    existing: LiveCandle | None,
    *,
    symbol: str,
    timeframe: Timeframe,
    bucket_open: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    freshness,
) -> LiveCandle:
    """Phase 12.2 (#H): fold one real per-second OHLCV aggregate into the
    forming bar for `bucket_open` -- unlike fold_price_into_candle (a single
    quote sample with volume=0.0), this carries genuine trade volume and a
    genuine O/H/L/C for the second just observed. Still purely a display
    projection: only a real higher-timeframe boundary crossing (the caller's
    responsibility, exactly as in fold_price_into_candle) ever marks a bar
    COMPLETED."""
    if existing is None or existing.timestamp != bucket_open:
        return LiveCandle(
            symbol=symbol,
            timeframe=timeframe.value,
            timestamp=bucket_open,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            state=CandleState.FORMING,
            freshness=freshness,
        )
    return LiveCandle(
        symbol=symbol,
        timeframe=timeframe.value,
        timestamp=bucket_open,
        open=existing.open,
        high=max(existing.high, high),
        low=min(existing.low, low),
        close=close,
        volume=existing.volume + volume,
        state=CandleState.FORMING,
        freshness=freshness,
    )
