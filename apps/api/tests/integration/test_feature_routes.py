from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_market_data_provider
from app.features.common import FeatureStatus
from app.main import app
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import make_candle


def _daily_series(n: int, start_price: float = 100.0):
    # The route always uses the real "now" as as_of (no as_of override), so
    # this series must end safely in the past relative to whenever the test
    # actually runs -- built backwards from yesterday.
    candles = []
    day = datetime.now(timezone.utc).replace(hour=13, minute=30, second=0, microsecond=0) - timedelta(
        days=1
    )
    price = start_price
    while len(candles) < n:
        if day.weekday() < 5:
            candles.append(
                make_candle(
                    symbol="NVDA",
                    timeframe=Timeframe.ONE_DAY,
                    timestamp=day,
                    session=MarketSession.REGULAR,
                    open=price,
                    high=price + 2,
                    low=price - 2,
                    close=price + 1,
                    volume=1_000_000,
                )
            )
            price += 0.5
        day -= timedelta(days=1)
    candles.reverse()
    return candles


class StubProvider(MarketDataProvider):
    def __init__(self, candles):
        self._candles = candles

    def get_candles(self, symbol, timeframe, limit=200):
        return self._candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


@pytest.fixture
def client_with_candles():
    def _make(candles) -> TestClient:
        app.dependency_overrides[get_market_data_provider] = lambda: StubProvider(candles)
        return TestClient(app)

    yield _make
    app.dependency_overrides.pop(get_market_data_provider, None)


def test_features_endpoint_returns_full_snapshot(client_with_candles):
    client = client_with_candles(_daily_series(260))
    response = client.get("/api/market/NVDA/features?timeframe=1d")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NVDA"
    assert body["moving_averages"]["sma200"]["status"] == "ok"
    assert body["data_quality"]["candle_count"] == 260


def test_features_endpoint_reports_insufficient_history_without_erroring(client_with_candles):
    client = client_with_candles(_daily_series(3))
    response = client.get("/api/market/NVDA/features?timeframe=1d")

    assert response.status_code == 200
    body = response.json()
    assert body["moving_averages"]["sma200"]["status"] == FeatureStatus.INSUFFICIENT_HISTORY.value
    assert body["moving_averages"]["sma200"]["value"] is None


def test_features_endpoint_invalid_timeframe_is_422(client_with_candles):
    client = client_with_candles(_daily_series(5))
    response = client.get("/api/market/NVDA/features?timeframe=bogus")
    assert response.status_code == 422


def test_features_endpoint_invalid_symbol_is_422(client_with_candles):
    client = client_with_candles(_daily_series(5))
    response = client.get("/api/market/123/features")
    assert response.status_code == 422
