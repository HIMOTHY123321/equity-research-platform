from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import et, make_candle


def bar(hour, high, low, open=None, close=None, volume=1000, day=17, month=8, year=2026):  # noqa: A002
    o = open if open is not None else (high + low) / 2
    c = close if close is not None else (high + low) / 2
    return make_candle(
        symbol="TEST",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=et(year, month, day, hour, 30),
        session=MarketSession.REGULAR,
        open=o,
        high=high,
        low=low,
        close=c,
        volume=volume,
    )


def bars(spec):
    """spec: list of (hour, high, low) tuples, or (hour, high, low, close)."""
    result = []
    for item in spec:
        if len(item) == 3:
            hour, high, low = item
            result.append(bar(hour, high, low))
        else:
            hour, high, low, close = item
            result.append(bar(hour, high, low, close=close))
    return result
