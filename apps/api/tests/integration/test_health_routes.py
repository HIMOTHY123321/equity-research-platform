"""Phase 16 (§25/§26/§75/§76): health/readiness and provider-status
honesty."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import health as health_routes
from app.config import Settings
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


def test_health_live_never_touches_the_database(client):
    # No get_db override needed for this one -- confirms it truly never
    # depends on the DB dependency at all.
    app.dependency_overrides.clear()
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_ready_reports_ok_when_the_database_is_reachable(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


def test_system_status_reports_yfinance_as_a_development_fallback_by_default(client, monkeypatch):
    # _env_file=None: this asserts Settings' DEFAULT, which must never
    # depend on whatever MARKET_DATA_PROVIDER happens to be set to in the
    # developer's real local apps/api/.env (e.g. "hybrid").
    monkeypatch.setattr(health_routes, "get_settings", lambda: Settings(_env_file=None))
    response = client.get("/api/system/status")
    assert response.status_code == 200
    body = response.json()
    assert body["market_data"]["provider"] == "yfinance"
    assert body["market_data"]["development_only_fallback_in_use"] is True
    assert body["market_data"]["is_licensed_commercial_feed"] is False


def test_system_status_never_returns_any_api_key(client):
    response = client.get("/api/system/status")
    text = response.text.lower()
    assert "api_key" not in text
    assert "secret" not in text
