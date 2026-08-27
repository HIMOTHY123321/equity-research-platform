from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_market_data_provider
from app.main import app
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import make_candle

# Hand-verified zigzag (left_bars=right_bars=2): LOW(90) -> HIGH(118) ->
# LOW(96, HL) -> HIGH(128, HH) -> bullish. Same fixture used in
# tests/unit/market_structure/test_multi_timeframe.py.
_POINTS = [
    (102, 97),
    (100, 95),
    (98, 90),
    (105, 95),
    (112, 100),
    (118, 108),
    (110, 100),
    (106, 96),
    (112, 102),
    (116, 106),
    (128, 118),
    (120, 110),
    (116, 106),
]


def _bullish_series():
    # The route always uses the real "now" as as_of, so this series must end
    # safely in the past relative to whenever the test actually runs.
    end = datetime.now(timezone.utc).replace(minute=30, second=0, microsecond=0) - timedelta(hours=2)
    base = end - timedelta(hours=len(_POINTS) - 1)
    candles = []
    for i, (high, low) in enumerate(_POINTS):
        candles.append(
            make_candle(
                symbol="NVDA",
                timeframe=Timeframe.ONE_HOUR,
                timestamp=base + timedelta(hours=i),
                session=MarketSession.REGULAR,
                open=(high + low) / 2,
                high=high,
                low=low,
                close=(high + low) / 2,
                volume=1000,
            )
        )
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


def test_structure_endpoint_returns_full_snapshot(client_with_candles):
    client = client_with_candles(_bullish_series())
    response = client.get("/api/market/NVDA/structure?timeframe=1h")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NVDA"
    assert body["trend"]["trend"] == "bullish"
    assert body["latest_swing_high"] is not None


def test_structure_endpoint_reports_insufficient_data_without_erroring(client_with_candles):
    client = client_with_candles(_bullish_series()[:2])
    response = client.get("/api/market/NVDA/structure?timeframe=1h")

    assert response.status_code == 200
    body = response.json()
    assert body["trend"]["trend"] == "insufficient_data"
    assert body["swings"] == []


def test_structure_endpoint_invalid_timeframe_is_422(client_with_candles):
    client = client_with_candles(_bullish_series())
    response = client.get("/api/market/NVDA/structure?timeframe=bogus")
    assert response.status_code == 422


def test_structure_endpoint_invalid_symbol_is_422(client_with_candles):
    client = client_with_candles(_bullish_series())
    response = client.get("/api/market/123/structure")
    assert response.status_code == 422
