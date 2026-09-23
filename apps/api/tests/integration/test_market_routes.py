from urllib.parse import quote

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

    def get_candles(self, symbol, timeframe, limit=200, before=None):
        if self._raise_error:
            raise self._raise_error
        candles = self._candles
        if before is not None:
            candles = [c for c in candles if c.timestamp < before]
        return candles[-limit:]

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


def _daily_candles(days=10, start_day=1):
    return [make_candle(timestamp=utc(2026, 1, start_day + i, 0, 0)) for i in range(days)]


def _norm(ts: str) -> str:
    """Normalize a timestamp string to compare a Python isoformat() value
    against pydantic's `Z`-suffixed JSON serialization of the same instant."""
    return ts.replace("Z", "+00:00")


def _qs(dt) -> str:
    """URL-encode a `before` cursor for a query string -- isoformat()'s
    literal `+` in `+00:00` would otherwise decode as a space."""
    return quote(dt.isoformat())


def test_get_candles_before_cursor_only_returns_older_candles(client_with_provider):
    candles = _daily_candles(days=10, start_day=1)
    client = client_with_provider(FakeProvider(candles=candles))
    response = client.get(f"/api/market/AAPL/candles?timeframe=1d&limit=10&before={_qs(utc(2026, 1, 6, 0, 0))}")

    assert response.status_code == 200
    body = response.json()
    returned = [_norm(c["timestamp"]) for c in body["candles"]]
    assert all(ts < utc(2026, 1, 6, 0, 0).isoformat() for ts in returned)
    assert len(body["candles"]) == 5


def test_get_candles_before_cursor_excludes_exact_boundary_candle(client_with_provider):
    boundary = utc(2026, 1, 5, 0, 0)
    candles = _daily_candles(days=10, start_day=1)
    client = client_with_provider(FakeProvider(candles=candles))
    response = client.get(f"/api/market/AAPL/candles?timeframe=1d&limit=10&before={_qs(boundary)}")

    body = response.json()
    returned_timestamps = {_norm(c["timestamp"]) for c in body["candles"]}
    assert boundary.isoformat() not in returned_timestamps


def test_get_candles_pagination_preserves_ascending_order(client_with_provider):
    candles = _daily_candles(days=10, start_day=1)
    client = client_with_provider(FakeProvider(candles=candles))
    response = client.get(f"/api/market/AAPL/candles?timeframe=1d&limit=10&before={_qs(utc(2026, 1, 8, 0, 0))}")

    body = response.json()
    timestamps = [c["timestamp"] for c in body["candles"]]
    assert timestamps == sorted(timestamps)


def test_get_candles_no_page_overlap_across_successive_requests(client_with_provider):
    candles = _daily_candles(days=10, start_day=1)
    client = client_with_provider(FakeProvider(candles=candles))

    first = client.get("/api/market/AAPL/candles?timeframe=1d&limit=5").json()
    oldest_in_first_page = _norm(first["candles"][0]["timestamp"])
    next_before = first["next_before"]
    assert _norm(next_before) == oldest_in_first_page

    second = client.get(f"/api/market/AAPL/candles?timeframe=1d&limit=5&before={quote(next_before)}").json()
    first_timestamps = {c["timestamp"] for c in first["candles"]}
    second_timestamps = {c["timestamp"] for c in second["candles"]}
    assert first_timestamps.isdisjoint(second_timestamps)


def test_get_candles_has_more_true_when_full_chunk_returned(client_with_provider):
    candles = _daily_candles(days=10, start_day=1)
    client = client_with_provider(FakeProvider(candles=candles))
    response = client.get("/api/market/AAPL/candles?timeframe=1d&limit=5")

    body = response.json()
    assert len(body["candles"]) == 5
    assert body["has_more"] is True
    assert body["history_exhausted"] is False
    assert _norm(body["next_before"]) == _norm(body["candles"][0]["timestamp"])


def test_get_candles_history_exhausted_when_chunk_shorter_than_limit(client_with_provider):
    candles = _daily_candles(days=3, start_day=1)
    client = client_with_provider(FakeProvider(candles=candles))
    response = client.get("/api/market/AAPL/candles?timeframe=1d&limit=10")

    body = response.json()
    assert len(body["candles"]) == 3
    assert body["has_more"] is False
    assert body["history_exhausted"] is True
    assert body["next_before"] is None


def test_get_candles_history_exhausted_with_before_at_earliest_data(client_with_provider):
    candles = _daily_candles(days=3, start_day=1)
    client = client_with_provider(FakeProvider(candles=candles))
    response = client.get(f"/api/market/AAPL/candles?timeframe=1d&limit=10&before={_qs(utc(2026, 1, 1, 0, 0))}")

    body = response.json()
    assert body["candles"] == []
    assert body["has_more"] is False
    assert body["history_exhausted"] is True


def test_get_candles_provider_error_with_before_cursor_still_maps_correctly(client_with_provider):
    client = client_with_provider(FakeProvider(raise_error=AuthenticationError("bad creds")))
    response = client.get(f"/api/market/AAPL/candles?timeframe=1d&before={_qs(utc(2026, 1, 1, 0, 0))}")
    assert response.status_code == 502


def test_get_candles_unsupported_timeframe_with_before_is_422(client_with_provider):
    client = client_with_provider(FakeProvider())
    response = client.get(f"/api/market/AAPL/candles?timeframe=1w&before={_qs(utc(2026, 1, 1, 0, 0))}")
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
