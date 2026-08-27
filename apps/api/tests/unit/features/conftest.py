from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, make_candle


def daily(day, open, high, low, close, volume, month=8, year=2026):  # noqa: A002
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


def hourly(day, hour, minute, open, high, low, close, volume, session=MarketSession.REGULAR):  # noqa: A002
    return make_candle(
        symbol="TEST",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=et(2026, 8, day, hour, minute),
        session=session,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
