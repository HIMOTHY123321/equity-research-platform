"""Phase 19.2: HybridMarketDataProvider -- Twelve Data for genuine live/
latest quotes, yfinance for ALL historical/research candles, with an
automatic (and never silent) REST fallback for the quote path only."""

from __future__ import annotations

from app.market_data.cache import InMemoryCache
from app.market_data.cached_provider import CachedMarketDataProvider
from app.market_data.exceptions import AuthenticationError, InvalidSymbolError, ProviderError, RateLimitError
from app.market_data.hybrid_provider import HybridMarketDataProvider
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import MarketSession, PreviousClose, Quote, Timeframe
from tests.conftest import make_candle, utc


class _StubProvider(MarketDataProvider):
    """A MarketDataProvider whose behavior per-call is fully scripted by the
    test -- `quote_error` lets a test force RateLimitError/ProviderError/
    AuthenticationError/InvalidSymbolError without any real network."""

    def __init__(self, name: str, quote_error: Exception | None = None):
        self.name = name
        self.quote_error = quote_error
        self.candle_calls = 0
        self.quote_calls = 0
        self.previous_close_calls = 0

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        self.candle_calls += 1
        return [make_candle(symbol=symbol, timeframe=timeframe)]

    def get_latest_quote(self, symbol):
        self.quote_calls += 1
        if self.quote_error is not None:
            raise self.quote_error
        return Quote(
            symbol=symbol,
            timestamp=utc(2026, 8, 17, 14, 30),
            session=MarketSession.REGULAR,
            bid_price=1.0,
            bid_size=1.0,
            ask_price=1.1,
            ask_size=1.0,
            is_approximate=True,
        )

    def get_previous_close(self, symbol):
        self.previous_close_calls += 1
        return PreviousClose(
            symbol=symbol, trading_date=utc(2026, 8, 14, 0, 0).date(), close=100, volume=1000
        )


def test_twelve_data_latest_quote_is_preferred_when_it_succeeds():
    primary = _StubProvider("twelve_data")
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    quote = provider.get_latest_quote("AAPL")

    assert quote.provider == "twelve_data"
    assert primary.quote_calls == 1
    assert historical.quote_calls == 0


def test_yfinance_fallback_on_rate_limit():
    primary = _StubProvider("twelve_data", quote_error=RateLimitError("429"))
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    quote = provider.get_latest_quote("AAPL")

    assert quote.provider == "yfinance"
    assert primary.quote_calls == 1
    assert historical.quote_calls == 1


def test_yfinance_fallback_on_timeout_shaped_provider_error():
    primary = _StubProvider("twelve_data", quote_error=ProviderError("Network error calling Twelve Data"))
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    quote = provider.get_latest_quote("AAPL")

    assert quote.provider == "yfinance"
    assert historical.quote_calls == 1


def test_authentication_failure_is_never_silently_hidden_by_a_fallback():
    primary = _StubProvider("twelve_data", quote_error=AuthenticationError("bad key"))
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    try:
        provider.get_latest_quote("AAPL")
        raised = False
    except AuthenticationError:
        raised = True

    assert raised is True
    assert historical.quote_calls == 0


def test_invalid_symbol_is_never_silently_hidden_by_a_fallback():
    primary = _StubProvider("twelve_data", quote_error=InvalidSymbolError("ZZZZZ"))
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    try:
        provider.get_latest_quote("ZZZZZ")
        raised = False
    except InvalidSymbolError:
        raised = True

    assert raised is True
    assert historical.quote_calls == 0


def test_provenance_is_exact_on_the_primary_path():
    provider = HybridMarketDataProvider(_StubProvider("twelve_data"), _StubProvider("yfinance"))
    assert provider.get_latest_quote("AAPL").provider == "twelve_data"


def test_provenance_is_exact_after_fallback():
    provider = HybridMarketDataProvider(
        _StubProvider("twelve_data", quote_error=RateLimitError("429")), _StubProvider("yfinance")
    )
    assert provider.get_latest_quote("AAPL").provider == "yfinance"


def test_custom_provider_names_are_respected_in_provenance():
    provider = HybridMarketDataProvider(
        _StubProvider("primary"), _StubProvider("hist"), primary_name="primary", historical_name="hist"
    )
    assert provider.get_latest_quote("AAPL").provider == "primary"


def test_historical_candles_always_use_the_historical_provider():
    primary = _StubProvider("twelve_data")
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    provider.get_candles("AAPL", Timeframe.ONE_DAY, limit=10)
    provider.get_candles("AAPL", Timeframe.FIFTEEN_MIN, limit=50)

    assert historical.candle_calls == 2
    assert primary.candle_calls == 0


def test_broad_historical_requests_never_consume_twelve_data_credits():
    primary = _StubProvider("twelve_data")
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    for timeframe in (Timeframe.FIVE_MIN, Timeframe.ONE_HOUR, Timeframe.FOUR_HOUR, Timeframe.ONE_DAY):
        provider.get_candles("AAPL", timeframe, limit=200)

    assert primary.candle_calls == 0
    assert historical.candle_calls == 4


def test_previous_close_always_uses_the_historical_provider():
    primary = _StubProvider("twelve_data")
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    provider.get_previous_close("AAPL")

    assert historical.previous_close_calls == 1
    assert primary.previous_close_calls == 0


def test_capabilities_combine_streaming_from_primary_and_history_from_historical():
    primary = _StubProvider("twelve_data")
    historical = _StubProvider("yfinance")
    provider = HybridMarketDataProvider(primary, historical)

    caps = provider.capabilities()

    # Both stub providers use MarketDataProvider's conservative defaults,
    # so this mainly proves capabilities() doesn't crash and returns the
    # historical provider's `historical_intraday` (the field get_candles
    # actually honors here).
    assert caps.historical_intraday == historical.capabilities().historical_intraday


def test_caching_and_coalescing_prevent_user_count_request_multiplication():
    """Phase 19.1 (§3)/19.2 (§7): N users asking about the same symbol
    within the TTL window must never multiply into N real Twelve Data (or
    yfinance) calls -- CachedMarketDataProvider wraps HybridMarketDataProvider
    the exact same way it wraps every other provider, so this is free, not
    reimplemented here."""
    primary = _StubProvider("twelve_data")
    historical = _StubProvider("yfinance")
    hybrid = HybridMarketDataProvider(primary, historical)
    cached = CachedMarketDataProvider(hybrid, InMemoryCache())

    for _ in range(25):
        cached.get_latest_quote("NVDA")

    assert primary.quote_calls == 1

    for _ in range(25):
        cached.get_candles("NVDA", Timeframe.ONE_DAY)

    assert historical.candle_calls == 1
