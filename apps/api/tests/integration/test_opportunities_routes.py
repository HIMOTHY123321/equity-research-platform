"""Phase 19 (Part 15): integration coverage for GET /api/opportunities."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_market_data_provider
from app.database.session import get_db
from app.main import app
from app.market_data.provider import MarketDataProvider
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")


class FakeProvider(MarketDataProvider):
    def get_candles(self, symbol, timeframe, limit=200):
        if symbol == "SPY" and timeframe.value in ("1h", "4h", "1d", "15m"):
            return SPY_1H[-limit:]
        return []

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
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_opportunities_returns_candidates_for_the_default_universe(client):
    response = client.get("/api/opportunities", params={"timeframe": "1h"})
    assert response.status_code == 200
    body = response.json()
    assert body["ranking_validation_message"] == "VALIDATED RELATIVE RANKING: UNAVAILABLE"
    assert isinstance(body["candidates"], list)
    assert len(body["candidates"]) > 0
    dumped = response.text.upper()
    for term in ("BUY", "SELL", "STRONG BUY", "STRONG SELL"):
        assert term not in dumped


def test_invalid_sort_is_rejected(client):
    response = client.get("/api/opportunities", params={"sort": "score"})
    assert response.status_code == 422
