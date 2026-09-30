"""Phase 12.1 (#C/#D): provider capability discovery must never claim
streaming/real-time behavior a provider implementation doesn't actually
have, and the base ABC default must be safe for the many test-only fake
providers across the suite that never override it.
"""

from __future__ import annotations

from app.market_data.alpaca_provider import AlpacaMarketDataProvider
from app.market_data.cache import InMemoryCache
from app.market_data.cached_provider import CachedMarketDataProvider
from app.market_data.capabilities import ALPACA_CAPABILITIES, TWELVE_DATA_CAPABILITIES, YFINANCE_CAPABILITIES
from app.market_data.provider import MarketDataProvider
from app.market_data.twelve_data_provider import TwelveDataMarketDataProvider
from app.market_data.yfinance_provider import YFinanceMarketDataProvider


class _MinimalFakeProvider(MarketDataProvider):
    """Deliberately does not override capabilities() -- proves the ABC
    default is usable without forcing every test fake to implement it."""

    def get_candles(self, symbol, timeframe, limit=200):
        return []

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


def test_default_capabilities_never_claim_streaming_or_real_time():
    caps = _MinimalFakeProvider().capabilities()
    assert caps.real_time_quotes is False
    assert caps.streaming_quotes is False
    assert caps.streaming_trades is False
    assert caps.streaming_bars is False
    assert caps.streaming_news is False
    assert caps.quote_delay_seconds is None


def test_yfinance_declares_no_streaming():
    caps = YFinanceMarketDataProvider().capabilities()
    assert caps == YFINANCE_CAPABILITIES
    assert caps.streaming_quotes is False
    assert caps.real_time_quotes is False


def test_alpaca_declares_no_streaming_for_this_rest_only_implementation():
    provider = AlpacaMarketDataProvider()
    assert provider.capabilities() == ALPACA_CAPABILITIES
    provider.close()


def test_twelve_data_declares_trade_only_streaming_never_quotes_or_bars():
    """Phase 19.1: the /v1/quotes/price feed carries price ticks only --
    streaming_quotes/streaming_bars must stay False so nothing downstream
    ever expects a bid/ask or pre-aggregated bar from this provider."""
    provider = TwelveDataMarketDataProvider()
    try:
        caps = provider.capabilities()
        assert caps == TWELVE_DATA_CAPABILITIES
        assert caps.streaming_trades is True
        assert caps.streaming_quotes is False
        assert caps.streaming_bars is False
    finally:
        provider.close()


def test_cached_provider_passes_through_inner_capabilities():
    inner = YFinanceMarketDataProvider()
    cached = CachedMarketDataProvider(inner, InMemoryCache())
    assert cached.capabilities() == inner.capabilities()
