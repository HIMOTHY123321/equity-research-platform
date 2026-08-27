from datetime import datetime, timezone

from app.market_data.sessions import EXCHANGE_TZ
from app.schemas.market_data import Candle, MarketSession, Timeframe


def alpaca_bar(t: str, o: float, h: float, l: float, c: float, v: float) -> dict:  # noqa: E741
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


def et(year, month, day, hour, minute=0, second=0) -> datetime:
    """Build a tz-aware datetime in exchange local time (America/New_York)."""
    return datetime(year, month, day, hour, minute, second, tzinfo=EXCHANGE_TZ)


def utc(year, month, day, hour, minute=0, second=0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def make_candle(
    symbol: str = "AAPL",
    timeframe: Timeframe = Timeframe.ONE_HOUR,
    timestamp: datetime = None,
    session: MarketSession = MarketSession.REGULAR,
    open: float = 100.0,  # noqa: A002
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.5,
    volume: float = 1000.0,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp or utc(2026, 8, 17, 14, 30),
        session=session,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
