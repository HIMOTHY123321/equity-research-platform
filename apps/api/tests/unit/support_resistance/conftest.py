from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, make_candle


def daily(day, open, high, low, close, volume=1000, month=8, year=2026):  # noqa: A002
    return make_candle(
        symbol="TEST",
        timeframe=Timeframe.ONE_DAY,
        timestamp=et(year, month, day, 9, 30),
        session=MarketSession.REGULAR,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def hourly(day, hour, open, high, low, close, volume=1000, month=8, year=2026, session=MarketSession.REGULAR):  # noqa: A002
    return make_candle(
        symbol="TEST",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=et(year, month, day, hour, 30),
        session=session,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
