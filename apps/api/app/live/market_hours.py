"""Phase 12.1 (#S): live-display session classification. Reuses
app.market_data.sessions' exact boundary constants and timezone (never a
second copy of 04:00/09:30/16:00/20:00 ET) and adds the one concept that
module deliberately doesn't need for candle classification: a weekend/
closed day has no candles to classify, but a live dashboard still needs to
honestly say MARKET_CLOSED instead of implying a quote is merely quiet.

Phase 19.2.1: also closes the overnight gap -- `classify_timestamp_session`
deliberately folds any out-of-range time (including the 20:00-04:00 ET
overnight window) into AFTER_HOURS as a "tail of the prior session"
convenience for CANDLE classification (a candle can only exist for a time
the market was genuinely open, so that fallback is harmless there). A LIVE
display has no such guarantee -- "right now" may genuinely be the middle of
the night -- so this module checks the overnight window explicitly before
ever delegating to that candle-oriented fallback.

Not a full holiday calendar -- same documented limitation
app.market_data.sessions already carries (Alpaca/yfinance simply return no
bars for closed days; this doesn't fabricate a holiday list either).
"""

from __future__ import annotations

from datetime import datetime

from app.live.config import LiveSessionState
from app.market_data.sessions import (
    AFTER_HOURS_CLOSE,
    EXCHANGE_TZ,
    PRE_MARKET_OPEN,
    classify_timestamp_session,
)


def is_trading_day(timestamp: datetime) -> bool:
    return timestamp.astimezone(EXCHANGE_TZ).weekday() < 5  # Mon-Fri


def current_live_session(timestamp: datetime) -> LiveSessionState:
    if not is_trading_day(timestamp):
        return LiveSessionState.MARKET_CLOSED
    local = timestamp.astimezone(EXCHANGE_TZ).time()
    if local < PRE_MARKET_OPEN or local >= AFTER_HOURS_CLOSE:
        # Overnight (20:00-04:00 ET) -- genuinely closed, never the tail of
        # yesterday's after-hours session the candle-oriented classifier
        # below would otherwise report.
        return LiveSessionState.MARKET_CLOSED
    return LiveSessionState(classify_timestamp_session(timestamp).value)
