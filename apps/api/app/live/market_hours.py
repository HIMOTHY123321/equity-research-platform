"""Phase 12.1 (#S): live-display session classification. Reuses
app.market_data.sessions' exact boundary constants and timezone (never a
second copy of 04:00/09:30/16:00/20:00 ET) and adds the one concept that
module deliberately doesn't need for candle classification: a weekend/
closed day has no candles to classify, but a live dashboard still needs to
honestly say MARKET_CLOSED instead of implying a quote is merely quiet.

Not a full holiday calendar -- same documented limitation
app.market_data.sessions already carries (Alpaca/yfinance simply return no
bars for closed days; this doesn't fabricate a holiday list either).
"""

from __future__ import annotations

from datetime import datetime

from app.live.config import LiveSessionState
from app.market_data.sessions import EXCHANGE_TZ, classify_timestamp_session


def is_trading_day(timestamp: datetime) -> bool:
    return timestamp.astimezone(EXCHANGE_TZ).weekday() < 5  # Mon-Fri


def current_live_session(timestamp: datetime) -> LiveSessionState:
    if not is_trading_day(timestamp):
        return LiveSessionState.MARKET_CLOSED
    return LiveSessionState(classify_timestamp_session(timestamp).value)
