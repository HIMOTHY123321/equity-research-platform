"""The internal normalized candle contract used everywhere downstream of market-data.

Every market data source (Alpaca today, anything else later) must be adapted into
this shape before it touches the feature engine or anything above it.
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Timeframe(str, Enum):
    ONE_MIN = "1m"
    FIVE_MIN = "5m"
    FIFTEEN_MIN = "15m"
    ONE_HOUR = "1h"
    FOUR_HOUR = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"


class MarketSession(str, Enum):
    """Which session a bar/quote belongs to. Regular-hours data must never be
    silently mixed with extended-hours data — callers that care about the
    regular session (structure, levels, most setups) filter on this."""

    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    session: MarketSession = MarketSession.REGULAR
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return v

    @model_validator(mode="after")
    def ohlc_is_internally_consistent(self) -> "Candle":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be >= open, low, and close")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be <= open, high, and close")
        return self

    @field_validator("volume")
    @classmethod
    def volume_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("volume cannot be negative")
        return v


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timestamp: datetime
    session: MarketSession
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float
    # True when a provider has no real bid/ask (e.g. yfinance) and this is a
    # last-price stand-in rather than an actual quoted spread. Always False
    # for providers with a real NBBO feed.
    is_approximate: bool = False

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return v


class PreviousClose(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    trading_date: date
    close: float
    volume: float
