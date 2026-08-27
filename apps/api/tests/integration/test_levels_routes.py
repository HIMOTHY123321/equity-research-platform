from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_market_data_provider
from app.main import app
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import MarketSession, Timeframe
from tests.conftest import make_candle

# Same hand-verified zigzag used across market_structure tests.
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


def _series(timeframe: Timeframe):
    end = datetime.now(timezone.utc).replace(minute=30, second=0, microsecond=0) - timedelta(hours=2)
    base = end - timedelta(hours=len(_POINTS) - 1)
    candles = []
    for i, (high, low) in enumerate(_POINTS):
        candles.append(
            make_candle(
                symbol="NVDA",
                timeframe=timeframe,
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
    """Serves the same zigzag shape at whatever timeframe is requested --
    good enough to exercise routing/orchestration without needing to
    simulate a realistic multi-timeframe relationship."""

    def get_candles(self, symbol, timeframe, limit=200):
        return _series(timeframe)[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


@pytest.fixture
def client():
    app.dependency_overrides[get_market_data_provider] = lambda: StubProvider()
    yield TestClient(app)
    app.dependency_overrides.pop(get_market_data_provider, None)


def test_levels_endpoint_returns_full_snapshot(client):
    response = client.get("/api/market/NVDA/levels?timeframe=1h")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NVDA"
    assert "active_resistance_zones" in body
    assert "active_support_zones" in body
    assert "data_quality" in body


def test_levels_endpoint_zones_carry_evidence(client):
    response = client.get("/api/market/NVDA/levels?timeframe=1h")
    body = response.json()

    all_zones = body["active_resistance_zones"] + body["active_support_zones"]
    assert len(all_zones) > 0
    for zone in all_zones:
        assert len(zone["evidence"]) > 0
        assert zone["strength"]["total"] >= 0
        assert "lifecycle" in zone


def test_levels_endpoint_invalid_timeframe_is_422(client):
    response = client.get("/api/market/NVDA/levels?timeframe=bogus")
    assert response.status_code == 422


def test_levels_endpoint_invalid_symbol_is_422(client):
    response = client.get("/api/market/123/levels")
    assert response.status_code == 422
