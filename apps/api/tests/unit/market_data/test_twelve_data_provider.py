"""Phase 19.1: TwelveDataMarketDataProvider REST implementation -- same
MockTransport-driven pattern as tests/unit/market_data/test_massive_provider.py.
"""

from __future__ import annotations

import httpx
import pytest

from app.market_data.exceptions import AuthenticationError, InvalidSymbolError, ProviderError, RateLimitError
from app.market_data.twelve_data_provider import TwelveDataMarketDataProvider
from app.schemas.market_data import Timeframe
from tests.conftest import utc

BAR = {"datetime": "2026-08-17 13:00:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}


def _provider(handler, sleep_fn=None, now_fn=None, max_retries=2):
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.twelvedata.com")
    kwargs = {"client": client, "sleep_fn": sleep_fn or (lambda _: None), "max_retries": max_retries}
    if now_fn is not None:
        kwargs["now_fn"] = now_fn
    return TwelveDataMarketDataProvider(**kwargs)


def test_capabilities_declare_honest_trade_only_streaming():
    provider = _provider(lambda r: httpx.Response(200, json={}))
    caps = provider.capabilities()
    assert caps.streaming_trades is True
    assert caps.streaming_quotes is False
    assert caps.streaming_bars is False


def test_get_candles_maps_time_series_response():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"values": [BAR], "status": "ok"})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    candles = provider.get_candles("AAPL", Timeframe.ONE_DAY, limit=10)

    assert len(calls) == 1
    assert "/time_series" in str(calls[0].url)
    assert "interval=1day" in str(calls[0].url)
    assert candles[0].close == 100.5
    assert candles[0].timestamp.tzinfo is not None


def test_get_candles_4h_aggregates_from_hourly():
    hourly_bars = [
        {**BAR, "datetime": f"2026-08-17 {h:02d}:00:00"} for h in range(7)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "interval=1h" in str(request.url)
        return httpx.Response(200, json={"values": hourly_bars, "status": "ok"})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    candles = provider.get_candles("AAPL", Timeframe.FOUR_HOUR, limit=10)

    assert all(c.timeframe == Timeframe.FOUR_HOUR for c in candles)


def test_get_candles_before_cursor_excludes_boundary_bar():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"values": [BAR], "status": "ok"})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    cursor = utc(2026, 8, 17, 13, 0)  # exactly BAR's own timestamp
    candles = provider.get_candles("AAPL", Timeframe.ONE_DAY, limit=10, before=cursor)

    assert all(c.timestamp != cursor for c in candles)


def test_get_candles_missing_volume_is_zero_not_fabricated():
    bar_no_volume = {**BAR}
    del bar_no_volume["volume"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"values": [bar_no_volume], "status": "ok"})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    candles = provider.get_candles("SPX", Timeframe.ONE_DAY, limit=10)
    assert candles[0].volume == 0.0


def test_get_candles_malformed_bar_is_rejected_not_raised():
    malformed = {"datetime": "2026-08-17 13:00:00", "open": "not-a-number", "high": 1, "low": 1, "close": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"values": [malformed, BAR], "status": "ok"})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    candles = provider.get_candles("AAPL", Timeframe.ONE_DAY, limit=10)
    assert len(candles) == 1
    assert candles[0].close == 100.5


def test_get_latest_quote_is_approximate_bid_equals_ask():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/quote"
        return httpx.Response(200, json={"close": "123.45", "timestamp": 1755440400})

    provider = _provider(handler)
    quote = provider.get_latest_quote("AAPL")
    assert quote.bid_price == quote.ask_price == 123.45
    assert quote.is_approximate is True


def test_get_latest_quote_missing_close_raises_invalid_symbol():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "error", "code": 400, "message": "symbol not found"})

    provider = _provider(handler)
    with pytest.raises(InvalidSymbolError):
        provider.get_latest_quote("ZZZZZ")


def test_get_previous_close_filters_to_completed_day():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"values": [BAR], "status": "ok"})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 18, 18, 0))
    previous_close = provider.get_previous_close("AAPL")
    assert previous_close.close == 100.5


def test_authentication_error_via_http_status_is_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"code": 401, "message": "bad key"})

    provider = _provider(handler)
    with pytest.raises(AuthenticationError):
        provider.get_previous_close("AAPL")
    assert len(calls) == 1


def test_authentication_error_via_embedded_error_body_is_not_retried():
    """Twelve Data has historically returned HTTP 200 with an embedded
    error body for some failure modes -- this must be treated identically
    to a real 401 status, never mistaken for successful data."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "error", "code": 401, "message": "invalid apikey"})

    provider = _provider(handler)
    with pytest.raises(AuthenticationError):
        provider.get_previous_close("AAPL")
    assert len(calls) == 1


def test_rate_limit_via_http_429_retries_then_raises():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"})

    provider = _provider(handler, max_retries=2)
    with pytest.raises(RateLimitError):
        provider.get_previous_close("AAPL")
    assert len(calls) == 3  # initial + 2 retries


def test_rate_limit_via_embedded_error_body_retries_then_raises():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "error", "code": 429, "message": "credits exceeded"})

    provider = _provider(handler, max_retries=1)
    with pytest.raises(RateLimitError):
        provider.get_previous_close("AAPL")
    assert len(calls) == 2  # initial + 1 retry


def test_network_timeout_retries_then_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    provider = _provider(handler, max_retries=1)
    with pytest.raises(ProviderError):
        provider.get_previous_close("AAPL")


def test_provenance_uses_the_configured_authorization_header():
    """(§1) REST requests use the documented `Authorization: apikey <key>`
    header form, never a query-string credential that could end up in a
    proxy/access log."""
    from app.config import Settings

    settings = Settings(_env_file=None, twelve_data_api_key="test-secret-key-do-not-leak")
    provider = TwelveDataMarketDataProvider(settings=settings)
    try:
        auth_header = provider._client.headers.get("authorization")
        assert auth_header == "apikey test-secret-key-do-not-leak"
        # Never placed in the URL/query string.
        assert "test-secret-key-do-not-leak" not in str(provider._client.base_url)
    finally:
        provider.close()
