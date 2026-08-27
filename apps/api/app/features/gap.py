"""Gap = today's regular-session open vs. the previous completed trading
day's close. A daily bar's `open` is fixed the instant the regular session
starts and never changes afterward, so it's safe to use as soon as today's
daily candle exists — no lookahead risk. Extended-hours prices never enter
this calculation: today's daily bar only exists once the regular session
opens, and its `open` field is the regular-session print, not a premarket
last trade.
"""

from __future__ import annotations

from datetime import datetime

from app.features.common import FeatureStatus
from app.features.previous_period import compute_previous_day_levels
from app.features.schemas import GapFeature
from app.market_data.sessions import exchange_trading_date
from app.schemas.market_data import Candle, MarketSession


def compute_gap(daily_candles: list[Candle], as_of: datetime) -> GapFeature:
    previous_day = compute_previous_day_levels(daily_candles, as_of)
    if previous_day.status != FeatureStatus.OK or previous_day.close is None:
        return GapFeature(status=FeatureStatus.INSUFFICIENT_HISTORY)

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
        # Today's regular session hasn't opened yet (or we have no data for it).
        return GapFeature(status=FeatureStatus.UNAVAILABLE, previous_close=previous_day.close)

    session_open = todays_bar.open
    gap_absolute = session_open - previous_day.close
    gap_percent = gap_absolute / previous_day.close * 100
    direction = "up" if gap_absolute > 0 else "down" if gap_absolute < 0 else "flat"

    return GapFeature(
        status=FeatureStatus.OK,
        previous_close=previous_day.close,
        session_open=session_open,
        gap_absolute=gap_absolute,
        gap_percent=gap_percent,
        direction=direction,
    )
