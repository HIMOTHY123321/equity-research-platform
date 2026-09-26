"""Integration tests for the Phase 15 Validation Lab API surface -- through
the real FastAPI app, same dependency-override pattern
tests/integration/test_forecasts_routes.py already uses. TestClient(app) is
never entered as a context manager here, so the real app lifespan (and its
background MonitoringService/etc.) never starts -- these routes don't need
it and starting it would reintroduce exactly the risk Phase 14.1's
FileSessionFactory fix was written to eliminate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.session import get_db
from app.main import app


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


def test_status_with_no_data_reports_zero_observations(client):
    response = client.get("/api/validation/status")
    assert response.status_code == 200
    body = response.json()
    assert body == {"total": 0, "resolved": 0, "unresolved": 0}


def test_gate_with_no_data_is_not_enough_data(client):
    response = client.get("/api/validation/gate")
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "not_enough_data"
    assert "criteria" in body
    assert body["reasons"]


def test_gate_history_starts_empty_then_records_each_evaluation(client):
    assert client.get("/api/validation/gate/history").json() == []

    client.get("/api/validation/gate")
    client.get("/api/validation/gate")

    history = client.get("/api/validation/gate/history").json()
    assert len(history) == 2  # every evaluation is a new immutable row, never overwritten


def test_observations_endpoint_returns_empty_list_with_no_data(client):
    response = client.get("/api/validation/observations")
    assert response.status_code == 200
    assert response.json() == []


def test_cohort_endpoint_handles_empty_cohort_gracefully(client):
    response = client.get(
        "/api/validation/cohorts",
        params={"event_type": "entry_conditions_met", "horizon_bars": 5, "timeframe": "1h"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["raw_n"] == 0
    assert body["median"] is None


def test_summary_endpoint_with_no_data_is_not_enough_data_and_has_no_banned_language(client):
    response = client.get("/api/validation/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "not_enough_data"
    assert body["gate_version"] == "v1"
    text_lower = body["text"].lower()
    assert "buy" not in text_lower
    assert "sell" not in text_lower
    assert "probability of" not in text_lower
    assert "recommend" not in text_lower


def test_historical_comparison_with_no_data_reports_zero_n_both_sides(client):
    response = client.get(
        "/api/validation/historical-comparison",
        params={"symbol": "SPY", "setup_type": "breakout_retest", "direction": "bullish", "horizon_bars": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["historical_n"] == 0
    assert body["prospective_n"] == 0
    assert body["note"] is not None
