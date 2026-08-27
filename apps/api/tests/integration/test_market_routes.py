import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_market_data_provider
from app.main import app
from app.market_data.exceptions import AuthenticationError, InvalidSymbolError, RateLimitError
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import MarketSession, PreviousClose, Quote
from tests.conftest import make_candle, utc


class FakeProvider(MarketDataProvider):
    def __init__(self, candles=None, quote=None, previous_close=None, raise_error=None):
        self._candles = candles if candles is not None else [make_candle()]
        self._quote = quote or Quote(
            symbol="AAPL",
            timestamp=utc(2026, 8, 17, 14, 30),
            session=MarketSession.REGULAR,
            bid_price=100,
            bid_size=1,
            ask_price=100.1,
            ask_size=1,
        )
        self._previous_close = previous_close or PreviousClose(
            symbol="AAPL", trading_date=utc(2026, 8, 14, 0, 0).date(), close=99, volume=1000
        )
        self._raise_error = raise_error

    def get_candles(self, symbol, timeframe, limit=200):
        if self._raise_error:
            raise self._raise_error
        return self._candles

    def get_latest_quote(self, symbol):
        if self._raise_error:
            raise self._raise_error
        return self._quote

    def get_previous_close(self, symbol):
        if self._raise_error:
            raise self._raise_error
        return self._previous_close


@pytest.fixture
def client_with_provider():
    def _make(provider: MarketDataProvider) -> TestClient:
        app.dependency_overrides[get_market_data_provider] = lambda: provider
        return TestClient(app)

    yield _make
    app.dependency_overrides.pop(get_market_data_provider, None)


def test_get_candles_success(client_with_provider):
    client = client_with_provider(FakeProvider())
    response = client.get("/api/market/AAPL/candles?timeframe=1d&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["timeframe"] == "1d"
    assert len(body["candles"]) == 1


def test_get_candles_invalid_symbol_is_422(client_with_provider):
    client = client_with_provider(FakeProvider())
    response = client.get("/api/market/123/candles")
    assert response.status_code == 422


def test_get_candles_invalid_timeframe_is_422(client_with_provider):
    client = client_with_provider(FakeProvider())
    response = client.get("/api/market/AAPL/candles?timeframe=3m")
    assert response.status_code == 422


def test_get_candles_unsupported_timeframe_is_422(client_with_provider):
    client = client_with_provider(FakeProvider())
    response = client.get("/api/market/AAPL/candles?timeframe=1w")
    assert response.status_code == 422


def test_get_candles_limit_out_of_range_is_422(client_with_provider):
    client = client_with_provider(FakeProvider())
    response = client.get("/api/market/AAPL/candles?limit=0")
    assert response.status_code == 422


def test_get_quote_success(client_with_provider):
    client = client_with_provider(FakeProvider())
    response = client.get("/api/market/AAPL/quote")

    assert response.status_code == 200
    body = response.json()
    assert body["quote"]["bid_price"] == 100
    assert body["previous_close"]["close"] == 99


def test_authentication_error_maps_to_502(client_with_provider):
    client = client_with_provider(FakeProvider(raise_error=AuthenticationError("bad creds")))
    response = client.get("/api/market/AAPL/candles")
    assert response.status_code == 502


def test_rate_limit_error_maps_to_503_with_retry_after_header(client_with_provider):
    client = client_with_provider(
        FakeProvider(raise_error=RateLimitError("rate limited", retry_after=2.0))
    )
    response = client.get("/api/market/AAPL/candles")
    assert response.status_code == 503
    assert response.headers.get("retry-after") == "2.0"


def test_invalid_symbol_error_maps_to_404(client_with_provider):
    client = client_with_provider(FakeProvider(raise_error=InvalidSymbolError("ZZZZZ")))
    response = client.get("/api/market/AAPL/quote")
    assert response.status_code == 404
