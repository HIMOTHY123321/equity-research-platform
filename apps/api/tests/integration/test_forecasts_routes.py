"""Integration tests for the Phase 12 (#Q) forecast API surface: create,
list, get, resolve, performance, gate -- through the real FastAPI app, same
dependency-override pattern tests/integration/test_research_catalysts_routes
.py already uses.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_market_data_provider, get_news_provider
from app.database.session import get_db
from app.main import app
from app.market_data.provider import MarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


class FakeProvider(MarketDataProvider):
    _BY_SYMBOL_TIMEFRAME = {
        ("SPY", "1h"): SPY_1H,
        ("SPY", "1d"): SPY_1D,
        ("SPY", "4h"): SPY_1H,
    }

    def get_candles(self, symbol, timeframe, limit=200):
        candles = self._BY_SYMBOL_TIMEFRAME.get((symbol, timeframe.value), [])
        return candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    session_factory = sessionmaker(bind=engine)

    def _get_db_override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_market_data_provider] = lambda: FakeProvider()
    app.dependency_overrides[get_news_provider] = lambda: FixtureNewsProvider([])
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_research(client):
    response = client.post(
        "/api/research/replay",
        json={
            "symbol": "SPY",
            "timeframe": "1h",
            "start": SPY_1H[0].timestamp.isoformat(),
            "end": SPY_1H[len(SPY_1H) // 2].timestamp.isoformat(),
        },
    )
    assert response.status_code == 200
    return response.json()["run_id"]


def _some_setup_id(client, as_of):
    response = client.get("/api/market/SPY/setups", params={"timeframe": "1h", "as_of": as_of.isoformat()})
    assert response.status_code == 200
    body = response.json()
    pool = body["qualified_setups"] + body["candidates"] + body["rejected_candidates"]
    assert pool, "fixture must produce at least one candidate"
    return pool[0]["id"]


def test_post_forecast_creates_a_prospective_forecast(client):
    _seed_research(client)
    response = client.post(
        "/api/forecasts",
        json={"symbol": "SPY", "timeframe": "1h", "forecast_category": "volatility", "horizon_bars": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_mode"] == "prospective"
    assert body["status"] in ("active", "abstained")


def test_post_forecast_with_unknown_setup_id_returns_404(client):
    _seed_research(client)
    response = client.post(
        "/api/forecasts",
        json={
            "symbol": "SPY",
            "timeframe": "1h",
            "forecast_category": "direction",
            "horizon_bars": 5,
            "setup_id": "does-not-exist",
        },
    )
    assert response.status_code == 404


def test_get_forecast_round_trips(client):
    _seed_research(client)
    created = client.post(
        "/api/forecasts",
        json={"symbol": "SPY", "timeframe": "1h", "forecast_category": "volatility", "horizon_bars": 5},
    ).json()
    fetched = client.get(f"/api/forecasts/{created['forecast_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_unknown_forecast_returns_404(client):
    response = client.get("/api/forecasts/does-not-exist")
    assert response.status_code == 404


def test_list_forecasts_filters_by_symbol(client):
    _seed_research(client)
    client.post(
        "/api/forecasts",
        json={"symbol": "SPY", "timeframe": "1h", "forecast_category": "volatility", "horizon_bars": 5},
    )
    listed = client.get("/api/forecasts", params={"symbol": "SPY"})
    assert listed.status_code == 200
    assert all(f["symbol"] == "SPY" for f in listed.json())


def test_performance_and_gate_endpoints_respond_with_no_data(client):
    performance = client.get("/api/forecasts/performance")
    assert performance.status_code == 200
    body = performance.json()
    assert "overall" in body and "baselines" in body

    gate = client.get("/api/forecasts/gate")
    assert gate.status_code == 200
    assert gate.json()["decision"] in ("not_enough_data", "fail", "promising", "pass")


def test_resolve_unknown_forecast_returns_404(client):
    response = client.post("/api/forecasts/does-not-exist/resolve")
    assert response.status_code == 404
