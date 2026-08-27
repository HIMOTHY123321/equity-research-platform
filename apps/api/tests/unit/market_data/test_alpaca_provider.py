import httpx
import pytest

from app.market_data.alpaca_provider import AlpacaMarketDataProvider
from app.market_data.exceptions import (
    AuthenticationError,
    InvalidSymbolError,
    ProviderError,
    RateLimitError,
)
from app.schemas.market_data import Timeframe
from tests.conftest import utc


def _provider(handler, sleep_fn=None, now_fn=None, max_retries=3):
    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://data.alpaca.markets"
    )
    kwargs = {"client": client, "sleep_fn": sleep_fn or (lambda _: None), "max_retries": max_retries}
    if now_fn is not None:
        kwargs["now_fn"] = now_fn
    return AlpacaMarketDataProvider(**kwargs)


def _bars_response(bars, next_page_token=None):
    return httpx.Response(
        200, json={"bars": bars, "symbol": "AAPL", "next_page_token": next_page_token}
    )


BAR = {"t": "2026-08-17T14:30:00Z", "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 1000}


def test_get_candles_normalizes_response():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _bars_response([BAR])

    provider = _provider(handler)
    candles = provider.get_candles("AAPL", Timeframe.ONE_DAY, limit=10)

    assert len(calls) == 1
    assert calls[0].url.path == "/v2/stocks/AAPL/bars"
    assert candles[0].close == 100.5


def test_get_candles_paginates_until_no_next_token():
    def handler(request: httpx.Request) -> httpx.Response:
        if "page_token" in request.url.params:
            return _bars_response([{**BAR, "t": "2026-08-17T15:30:00Z"}], next_page_token=None)
        return _bars_response([BAR], next_page_token="page-2")

    provider = _provider(handler)
    candles = provider.get_candles("AAPL", Timeframe.ONE_HOUR, limit=10)

    assert len(candles) == 2
    assert candles[0].timestamp < candles[1].timestamp


def test_get_candles_4h_aggregates_from_hourly():
    hourly_bars = [
        {**BAR, "t": f"2026-08-17T{h:02d}:30:00Z", "v": 100} for h in (13, 14, 15, 16, 17, 18, 19)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["timeframe"] == "1Hour"
        return _bars_response(hourly_bars)

    provider = _provider(handler)
    candles = provider.get_candles("AAPL", Timeframe.FOUR_HOUR, limit=10)

    assert all(c.timeframe == Timeframe.FOUR_HOUR for c in candles)
    assert len(candles) == 2


def test_get_latest_quote_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/stocks/AAPL/quotes/latest"
        return httpx.Response(
            200,
            json={
                "quote": {"t": "2026-08-17T14:30:00Z", "bp": 100.0, "bs": 1, "ap": 100.2, "as": 1}
            },
        )

    provider = _provider(handler)
    quote = provider.get_latest_quote("AAPL")

    assert quote.bid_price == 100.0
    assert quote.ask_price == 100.2


def test_get_latest_quote_missing_raises_invalid_symbol():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"quote": None})

    provider = _provider(handler)
    with pytest.raises(InvalidSymbolError):
        provider.get_latest_quote("ZZZZZ")


def test_get_previous_close_skips_todays_incomplete_bar():
    daily_bars = [
        {**BAR, "t": "2026-08-13T04:00:00Z", "c": 98.0},
        {**BAR, "t": "2026-08-14T04:00:00Z", "c": 99.0},
        {**BAR, "t": "2026-08-17T04:00:00Z", "c": 105.0},  # today, still forming
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return _bars_response(daily_bars)

    provider = _provider(handler, now_fn=lambda: utc(2026, 8, 17, 18, 0))
    previous_close = provider.get_previous_close("AAPL")

    assert previous_close.close == 99.0


def test_authentication_error_is_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"message": "unauthorized"})

    provider = _provider(handler)
    with pytest.raises(AuthenticationError):
        provider.get_candles("AAPL", Timeframe.ONE_DAY)

    assert len(calls) == 1


def test_rate_limit_retries_then_succeeds():
    calls = []
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return _bars_response([BAR])

    provider = _provider(handler, sleep_fn=sleeps.append)
    candles = provider.get_candles("AAPL", Timeframe.ONE_DAY)

    assert len(calls) == 3
    assert len(sleeps) == 2
    assert len(candles) == 1


def test_rate_limit_raises_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1.5"}, json={})

    provider = _provider(handler, max_retries=2)
    with pytest.raises(RateLimitError) as exc_info:
        provider.get_candles("AAPL", Timeframe.ONE_DAY)

    assert exc_info.value.retry_after == 1.5


def test_server_error_retries_then_raises_provider_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, text="upstream down")

    provider = _provider(handler, max_retries=2)
    with pytest.raises(ProviderError):
        provider.get_candles("AAPL", Timeframe.ONE_DAY)

    assert len(calls) == 3  # initial attempt + 2 retries


def test_network_error_retries_then_raises_provider_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    provider = _provider(handler, max_retries=1)
    with pytest.raises(ProviderError):
        provider.get_candles("AAPL", Timeframe.ONE_DAY)

    assert len(calls) == 2


def test_404_raises_invalid_symbol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    provider = _provider(handler)
    with pytest.raises(InvalidSymbolError):
        provider.get_candles("NOTASYMBOL", Timeframe.ONE_DAY)


def test_empty_bars_response_returns_empty_list_without_fabricating():
    def handler(request: httpx.Request) -> httpx.Response:
        return _bars_response([])

    provider = _provider(handler)
    candles = provider.get_candles("AAPL", Timeframe.ONE_DAY)

    assert candles == []
