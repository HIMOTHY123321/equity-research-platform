"""Integration tests for the Phase 14 monitoring universe API surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.session import get_db
from app.main import app
from app.watchlist.repository import DEFAULT_WATCHLIST_SYMBOLS


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
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_monitoring_seeds_from_default_symbols(client):
    # Phase 16 (§9/§97): the monitoring universe now seeds from a fixed
    # global default (DEFAULT_WATCHLIST_SYMBOLS), never from any single
    # user's personal (now per-user, auth-required) Watchlist.
    response = client.get("/api/monitoring")

    assert response.status_code == 200
    symbols = {s["symbol"] for s in response.json()}
    assert symbols == set(DEFAULT_WATCHLIST_SYMBOLS)
    assert all(s["enabled"] for s in response.json())


def test_disable_then_enable_monitoring_round_trips(client):
    client.get("/api/monitoring")  # seed

    disable_response = client.delete("/api/monitoring/SPY")
    after_disable = {s["symbol"]: s["enabled"] for s in client.get("/api/monitoring").json()}

    enable_response = client.post("/api/monitoring/SPY")
    after_enable = {s["symbol"]: s["enabled"] for s in client.get("/api/monitoring").json()}

    assert disable_response.status_code == 204
    assert after_disable["SPY"] is False
    assert enable_response.status_code == 200
    assert after_enable["SPY"] is True


def test_enable_monitoring_for_new_symbol_not_in_default_universe(client):
    assert "IBM" not in DEFAULT_WATCHLIST_SYMBOLS
    response = client.post("/api/monitoring/IBM")

    assert response.status_code == 200
    assert response.json()["symbol"] == "IBM"
    symbols = {s["symbol"] for s in client.get("/api/monitoring").json()}
    assert "IBM" in symbols
