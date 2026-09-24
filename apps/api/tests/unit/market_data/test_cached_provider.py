from app.market_data.cache import InMemoryCache
from app.market_data.cached_provider import CachedMarketDataProvider
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import MarketSession, PreviousClose, Quote, Timeframe
from tests.conftest import make_candle, utc


class CountingProvider(MarketDataProvider):
    def __init__(self):
        self.candle_calls = 0
        self.quote_calls = 0
        self.previous_close_calls = 0

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        self.candle_calls += 1
        self.last_before = before
        return [make_candle(symbol=symbol, timeframe=timeframe)]

    def get_latest_quote(self, symbol):
        self.quote_calls += 1
        return Quote(
            symbol=symbol,
            timestamp=utc(2026, 8, 17, 14, 30),
            session=MarketSession.REGULAR,
            bid_price=1,
            bid_size=1,
            ask_price=1.1,
            ask_size=1,
        )

    def get_previous_close(self, symbol):
        self.previous_close_calls += 1
        return PreviousClose(
            symbol=symbol, trading_date=utc(2026, 8, 14, 0, 0).date(), close=100, volume=1000
        )


def test_candles_are_cached_between_calls():
    inner = CountingProvider()
    provider = CachedMarketDataProvider(inner, InMemoryCache())

    provider.get_candles("AAPL", Timeframe.ONE_DAY)
    provider.get_candles("AAPL", Timeframe.ONE_DAY)

    assert inner.candle_calls == 1


def test_different_symbols_are_cached_independently():
    inner = CountingProvider()
    provider = CachedMarketDataProvider(inner, InMemoryCache())

    provider.get_candles("AAPL", Timeframe.ONE_DAY)
    provider.get_candles("MSFT", Timeframe.ONE_DAY)

    assert inner.candle_calls == 2


def test_different_timeframes_are_cached_independently():
    inner = CountingProvider()
    provider = CachedMarketDataProvider(inner, InMemoryCache())

    provider.get_candles("AAPL", Timeframe.ONE_DAY)
    provider.get_candles("AAPL", Timeframe.ONE_HOUR)

    assert inner.candle_calls == 2


def test_quote_and_candles_use_independent_cache_entries():
    inner = CountingProvider()
    provider = CachedMarketDataProvider(inner, InMemoryCache())

    provider.get_candles("AAPL", Timeframe.ONE_DAY)
    provider.get_latest_quote("AAPL")

    assert inner.candle_calls == 1
    assert inner.quote_calls == 1


def test_before_cursor_is_accepted_and_forwarded_to_inner_provider():
    # Regression: CachedMarketDataProvider.get_candles previously had no
    # `before` parameter at all -- every call from the route (which always
    # passes `before=` as a keyword, even when None) raised TypeError.
    inner = CountingProvider()
    provider = CachedMarketDataProvider(inner, InMemoryCache())
    cursor = utc(2026, 1, 1, 0, 0)

    provider.get_candles("AAPL", Timeframe.ONE_DAY, before=cursor)

    assert inner.candle_calls == 1
    assert inner.last_before == cursor


def test_before_cursor_pages_are_cached_independently_of_the_base_page():
    inner = CountingProvider()
    provider = CachedMarketDataProvider(inner, InMemoryCache())

    provider.get_candles("AAPL", Timeframe.ONE_DAY)
    provider.get_candles("AAPL", Timeframe.ONE_DAY, before=utc(2026, 1, 1, 0, 0))

    assert inner.candle_calls == 2


def test_different_before_cursors_are_cached_independently():
    inner = CountingProvider()
    provider = CachedMarketDataProvider(inner, InMemoryCache())

    provider.get_candles("AAPL", Timeframe.ONE_DAY, before=utc(2026, 1, 1, 0, 0))
    provider.get_candles("AAPL", Timeframe.ONE_DAY, before=utc(2025, 1, 1, 0, 0))

    assert inner.candle_calls == 2


def test_repeated_calls_with_the_same_before_cursor_are_cached():
    inner = CountingProvider()
    provider = CachedMarketDataProvider(inner, InMemoryCache())
    cursor = utc(2026, 1, 1, 0, 0)

    provider.get_candles("AAPL", Timeframe.ONE_DAY, before=cursor)
    provider.get_candles("AAPL", Timeframe.ONE_DAY, before=cursor)

    assert inner.candle_calls == 1


def test_cache_expiry_triggers_fresh_fetch():
    now = [0.0]
    inner = CountingProvider()
    provider = CachedMarketDataProvider(
        inner, InMemoryCache(clock=lambda: now[0]), candles_ttl=10.0
    )

    provider.get_candles("AAPL", Timeframe.ONE_DAY)
    now[0] = 11.0
    provider.get_candles("AAPL", Timeframe.ONE_DAY)

    assert inner.candle_calls == 2
