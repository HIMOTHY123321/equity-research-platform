"""Phase 12.1 (#F): typed live-data objects. Every one of these carries its
own freshness envelope (source_timestamp/received_at/age_seconds/provider/
market_session/freshness_state) -- there is no live value in this package
that isn't traceable back to exactly when it was actually observed.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.live.config import FreshnessState, LiveSessionState


class FreshnessInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_timestamp: Optional[datetime]
    received_at: datetime
    age_seconds: Optional[float]
    provider: str
    market_session: LiveSessionState
    freshness_state: FreshnessState


class LiveQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    price: float
    bid: float
    ask: float
    spread: float
    is_approximate: bool
    previous_close: Optional[float] = None
    percent_change: Optional[float] = None
    freshness: FreshnessInfo


class CandleState(str, Enum):
    FORMING = "forming"
    COMPLETED = "completed"


class LiveCandle(BaseModel):
    """A forming candle is purely a *display* projection built from live
    quotes -- it is never written to the candle cache/DB and never handed
    to build_market_snapshot/get_candles (#G). Only once `state ==
    COMPLETED` does app.live.recompute treat the boundary as real."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    timestamp: datetime  # the bar's own open time -- never "now"
    open: float
    high: float
    low: float
    close: float
    volume: float
    state: CandleState
    freshness: FreshnessInfo


class ConnectionState(str, Enum):
    CONNECTED = "connected"
    RESYNCING = "resyncing"
    DISCONNECTED = "disconnected"


class ConnectionStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: ConnectionState
    last_message_at: Optional[datetime]
    reconnect_attempts: int
    subscribed_symbols: list[str]
