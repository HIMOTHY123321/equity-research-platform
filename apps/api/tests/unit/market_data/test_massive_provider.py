"""Phase 12.2: MassiveMarketDataProvider REST implementation -- same
MockTransport-driven pattern as tests/unit/market_data/test_alpaca_provider.py.
"""

from __future__ import annotations

import httpx
import pytest

from app.market_data.exceptions import AuthenticationError, InvalidSymbolError, ProviderError, RateLimitError
from app.market_data.massive_provider import MassiveMarketDataProvider
from app.schemas.market_data import Timeframe
from tests.conftest import utc


def _provider(handler, sleep_fn=None, now_fn=None, max_retries=3):
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.massive.com")
    kwargs = {"client": client, "sleep_fn": sleep_fn or (lambda _: None), "max_retries": max_retries}
    if now_fn is not None:
        kwargs["now_fn"] = now_fn
    return MassiveMarketDataProvider(**kwargs)


BAR = {"t": 1755440400000, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 1000}  # 2025-08-17T13:00:00Z


def test_capabilities_declare_genuine_streaming():
    provider = _provider(lambda r: httpx.Response(200, json={}))
    caps = provider.capabilities()
    assert caps.streaming_trades is True
    assert caps.streaming_quotes is True
    assert caps.streaming_bars is True


def test_get_candles_normalizes_response():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": [BAR]})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    candles = provider.get_candles("AAPL", Timeframe.ONE_DAY, limit=10)

    assert len(calls) == 1
    assert "/v2/aggs/ticker/AAPL/range/1/day/" in str(calls[0].url)
    assert candles[0].close == 100.5


def test_get_candles_paginates_via_next_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if "next-page" in str(request.url):
            return httpx.Response(200, json={"results": [{**BAR, "t": BAR["t"] + 3_600_000}]})
        return httpx.Response(
            200,
            json={"results": [BAR], "next_url": "https://api.massive.com/next-page"},
        )

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    candles = provider.get_candles("AAPL", Timeframe.ONE_HOUR, limit=10)

    assert len(candles) == 2
    assert candles[0].timestamp < candles[1].timestamp


def test_get_candles_4h_aggregates_from_hourly():
    hourly_bars = [{**BAR, "t": BAR["t"] + h * 3_600_000, "v": 100} for h in range(7)]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/range/1/hour/" in str(request.url)
        return httpx.Response(200, json={"results": hourly_bars})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    candles = provider.get_candles("AAPL", Timeframe.FOUR_HOUR, limit=10)

    assert all(c.timeframe == Timeframe.FOUR_HOUR for c in candles)


def test_get_candles_before_cursor_anchors_range_on_cursor_date():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"results": [BAR]})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    cursor = utc(2025, 8, 17, 13, 0)
    provider.get_candles("AAPL", Timeframe.ONE_DAY, limit=10, before=cursor)

    assert "/range/1/day/" in str(calls[0].url)
    assert "2026-08" not in str(calls[0].url)


def test_get_candles_before_cursor_excludes_boundary_bar():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [BAR]})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    cursor = utc(2025, 8, 17, 13, 0)  # exactly BAR's own timestamp
    candles = provider.get_candles("AAPL", Timeframe.ONE_DAY, limit=10, before=cursor)

    assert all(c.timestamp != cursor for c in candles)


def test_get_candles_before_cursor_returns_ascending_order():
    older_bars = [{**BAR, "t": BAR["t"] - d * 86_400_000} for d in range(5, 0, -1)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": older_bars})

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    candles = provider.get_candles(
        "AAPL", Timeframe.ONE_DAY, limit=10, before=utc(2025, 8, 17, 13, 0)
    )

    timestamps = [c.timestamp for c in candles]
    assert timestamps == sorted(timestamps)


def test_get_latest_quote_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/quotes/AAPL"
        quote = {
            "sip_timestamp": 1755440400000000000,
            "bid_price": 100.0,
            "bid_size": 1,
            "ask_price": 100.2,
            "ask_size": 1,
        }
        return httpx.Response(200, json={"results": [quote]})

    provider = _provider(handler)
    quote = provider.get_latest_quote("AAPL")
    assert quote.bid_price == 100.0
    assert quote.ask_price == 100.2


def test_get_latest_quote_missing_raises_invalid_symbol():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    provider = _provider(handler)
    with pytest.raises(InvalidSymbolError):
        provider.get_latest_quote("ZZZZZ")


def test_get_previous_close():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/aggs/ticker/AAPL/prev"
        return httpx.Response(200, json={"results": [{**BAR, "c": 99.0}]})

    provider = _provider(handler)
    previous_close = provider.get_previous_close("AAPL")
    assert previous_close.close == 99.0


def test_authentication_error_is_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"error": "bad key"})

    provider = _provider(handler)
    with pytest.raises(AuthenticationError):
        provider.get_previous_close("AAPL")
    assert len(calls) == 1


def test_rate_limit_retries_then_raises():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"})

    provider = _provider(handler, max_retries=2)
    with pytest.raises(RateLimitError):
        provider.get_previous_close("AAPL")
    assert len(calls) == 3  # initial + 2 retries


def test_server_error_retries_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 2:
            return httpx.Response(500)
        return httpx.Response(200, json={"results": [BAR]})

    provider = _provider(handler)
    previous_close = provider.get_previous_close("AAPL")
    assert previous_close.close == 100.5
    assert len(calls) == 2


def test_no_previous_close_results_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    provider = _provider(handler)
    with pytest.raises(ProviderError):
        provider.get_previous_close("AAPL")
