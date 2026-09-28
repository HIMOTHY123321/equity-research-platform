"""Phase 19 (Part 15): integration coverage for GET /api/symbols/{symbol}/
thesis -- confirms the route wires app.thesis.service correctly end-to-end
(DI, response_model serialization, as_of validation), not the composition
logic itself (see tests/unit/thesis/test_service.py for that).
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


def test_get_thesis_returns_a_composed_thesis(client):
    as_of = SPY_1H[-1].timestamp.isoformat()
    response = client.get("/api/symbols/SPY/thesis", params={"timeframe": "1h", "as_of": as_of})
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "SPY"
    assert body["ranking_gate_status"].lower() == "fail"
    assert len(body["multi_timeframe_trend"]) == 4
    dumped = response.text.upper()
    for term in ("BUY", "SELL", "STRONG BUY", "STRONG SELL"):
        assert term not in dumped


def test_future_as_of_is_rejected(client):
    response = client.get(
        "/api/symbols/SPY/thesis", params={"timeframe": "1h", "as_of": "2999-01-01T00:00:00Z"}
    )
    assert response.status_code == 400


def test_live_thesis_defaults_to_now_when_as_of_omitted(client):
    response = client.get("/api/symbols/SPY/thesis", params={"timeframe": "1h"})
    assert response.status_code == 200
