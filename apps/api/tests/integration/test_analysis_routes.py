"""Integration tests for Phase 11's /api/analysis/* surface (#L). Same
in-memory-SQLite + dependency_overrides pattern as
tests/integration/test_research_catalysts_routes.py.
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


def test_get_evidence_packet_symbol_level(client):
    response = client.get("/api/analysis/SPY/evidence", params={"timeframe": "1h"})
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "SPY"
    assert body["timeframe"] == "1h"
    assert body["setup"] is None
    assert body["ranking_gate_status"] == "FAIL"
    assert "packet_id" in body


def test_get_evidence_packet_unknown_setup_id_is_404(client):
    response = client.get(
        "/api/analysis/SPY/evidence", params={"timeframe": "1h", "setup_id": "does-not-exist"}
    )
    assert response.status_code == 404


def test_create_brief_defaults_to_mock_provider_and_is_grounded(client):
    response = client.post("/api/analysis/SPY/brief", params={"timeframe": "1h", "mode": "full"})
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] in ("mock", "deterministic-fallback")
    assert body["grounding_rejected"] is False
    assert body["mode"] == "full"

    fetched = client.get(f"/api/analysis/SPY/brief/{body['brief_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["brief_id"] == body["brief_id"]


def test_get_unknown_brief_id_is_404(client):
    response = client.get("/api/analysis/SPY/brief/does-not-exist")
    assert response.status_code == 404


def test_list_recent_briefs_returns_the_saved_report_with_symbol_and_setup_metadata(client):
    created = client.post("/api/analysis/SPY/brief", params={"timeframe": "1h", "mode": "quick"}).json()

    listing = client.get("/api/analysis/briefs")
    assert listing.status_code == 200
    items = listing.json()
    assert any(item["brief_id"] == created["brief_id"] for item in items)
    row = next(item for item in items if item["brief_id"] == created["brief_id"])
    assert row["symbol"] == "SPY"
    assert row["timeframe"] == "1h"
    assert row["evidence_packet_id"] == created["evidence_packet_id"]
    assert row["mode"] == "quick"


def test_get_saved_evidence_packet_returns_the_frozen_packet_never_regenerated(client):
    created = client.post("/api/analysis/SPY/brief", params={"timeframe": "1h", "mode": "quick"}).json()

    packet = client.get(f"/api/analysis/SPY/evidence/{created['evidence_packet_id']}")
    assert packet.status_code == 200
    assert packet.json()["packet_id"] == created["evidence_packet_id"]


def test_get_unknown_evidence_packet_id_is_404(client):
    response = client.get("/api/analysis/SPY/evidence/does-not-exist")
    assert response.status_code == 404


@pytest.mark.parametrize("mode", ["quick", "full", "why_this_setup", "why_not", "catalyst", "analogs"])
def test_every_mode_produces_a_valid_brief(client, mode):
    response = client.post("/api/analysis/SPY/brief", params={"timeframe": "1h", "mode": mode})
    assert response.status_code == 200
    assert response.json()["mode"] == mode


def test_evidence_endpoint_never_exposes_buy_sell_language(client):
    response = client.get("/api/analysis/SPY/evidence", params={"timeframe": "1h"})
    assert response.status_code == 200
    body_text = response.text.lower()
    for banned in ('"buy"', '"sell"', "strong buy", "strong sell"):
        assert banned not in body_text
