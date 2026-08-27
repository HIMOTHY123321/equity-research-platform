"""US equity market session classification (regular / pre-market / after-hours).

All boundaries are in exchange local time (America/New_York) and follow the
standard NYSE/Nasdaq convention: pre-market 04:00-09:30, regular 09:30-16:00,
after-hours 16:00-20:00. This is intentionally not a full holiday calendar —
Alpaca simply returns no bars for closed days, and we never fabricate bars to
fill that gap (see normalization.py).
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.schemas.market_data import MarketSession, Timeframe

EXCHANGE_TZ = ZoneInfo("America/New_York")

PRE_MARKET_OPEN = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
AFTER_HOURS_CLOSE = time(20, 0)

# Bars at or after this timeframe represent the whole session and are always REGULAR.
SESSION_AGGREGATE_TIMEFRAMES = {Timeframe.ONE_DAY, Timeframe.ONE_WEEK}


def classify_session(timestamp: datetime, timeframe: Timeframe) -> MarketSession:
    """Classify a bar timestamp for a given candle timeframe (any input timezone)."""
    if timeframe in SESSION_AGGREGATE_TIMEFRAMES:
        return MarketSession.REGULAR
    return classify_timestamp_session(timestamp)


def classify_timestamp_session(timestamp: datetime) -> MarketSession:
    """Classify any intraday timestamp (quote, trade, bar) by time of day."""
    local = timestamp.astimezone(EXCHANGE_TZ).time()

    if REGULAR_OPEN <= local < REGULAR_CLOSE:
        return MarketSession.REGULAR
    if PRE_MARKET_OPEN <= local < REGULAR_OPEN:
        return MarketSession.PRE_MARKET
    if REGULAR_CLOSE <= local < AFTER_HOURS_CLOSE:
        return MarketSession.AFTER_HOURS
    # Outside 04:00-20:00 ET: equities don't trade here under Alpaca's extended
    # hours feed; treat as the tail of the prior after-hours session rather
    # than fabricate a fourth session bucket.
    return MarketSession.AFTER_HOURS


def exchange_trading_date(timestamp: datetime):
    """The calendar date (in exchange time) this timestamp falls on."""
    return timestamp.astimezone(EXCHANGE_TZ).date()
