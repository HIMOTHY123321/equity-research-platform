"""Today's regular-session range so far. Strictly filters to
MarketSession.REGULAR — pre-market and after-hours bars never enter this
calculation, per Phase 2's session classification.
"""

from __future__ import annotations

from datetime import datetime

from app.features.common import FeatureStatus
from app.features.schemas import SessionFeatures
from app.market_data.sessions import exchange_trading_date
from app.schemas.market_data import Candle, MarketSession


def compute_session_features(candles: list[Candle], as_of: datetime) -> SessionFeatures:
    today = exchange_trading_date(as_of)
    todays_regular = sorted(
        (
            c
            for c in candles
            if c.session == MarketSession.REGULAR and exchange_trading_date(c.timestamp) == today
        ),
        key=lambda c: c.timestamp,
    )
    if not todays_regular:
        return SessionFeatures(status=FeatureStatus.UNAVAILABLE)

    session_open = todays_regular[0].open
    session_high = max(c.high for c in todays_regular)
    session_low = min(c.low for c in todays_regular)
    latest_price = todays_regular[-1].close

    distance_from_high_absolute = session_high - latest_price
    distance_from_low_absolute = latest_price - session_low

    return SessionFeatures(
        status=FeatureStatus.OK,
        session_open=session_open,
        session_high_so_far=session_high,
        session_low_so_far=session_low,
        session_range=session_high - session_low,
        latest_price=latest_price,
        distance_from_high_absolute=distance_from_high_absolute,
        distance_from_high_percent=(
            distance_from_high_absolute / session_high * 100 if session_high else None
        ),
        distance_from_low_absolute=distance_from_low_absolute,
        distance_from_low_percent=(
            distance_from_low_absolute / session_low * 100 if session_low else None
        ),
    )
