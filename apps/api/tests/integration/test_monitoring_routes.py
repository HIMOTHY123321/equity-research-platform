"""Phase 16.1 (§5): /api/monitoring is now auth-required and strictly
per-user -- "which symbols does THIS user want alerted," never the
process-wide SYSTEM RESEARCH UNIVERSE (app.monitoring.universe), which is
no longer directly exposed by any route."""

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


def _signup(client: TestClient, email: str) -> str:
    response = client.post("/api/auth/signup", json={"email": email, "password": "hunter2hunter2"})
    assert response.status_code == 201
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_monitoring_requires_authentication(client):
    assert client.get("/api/monitoring").status_code == 401
    assert client.post("/api/monitoring/SPY").status_code == 401
    assert client.delete("/api/monitoring/SPY").status_code == 401


def test_new_user_starts_with_no_monitoring_subscriptions(client):
    token = _signup(client, "trader@example.com")
    response = client.get("/api/monitoring", headers=_auth(token))
    assert response.status_code == 200
    assert response.json() == []


def test_enable_then_list_then_disable_round_trips(client):
    token = _signup(client, "trader@example.com")

    enable_response = client.post("/api/monitoring/NVDA", headers=_auth(token))
    assert enable_response.status_code == 200
    assert enable_response.json()["symbol"] == "NVDA"
    assert enable_response.json()["enabled"] is True

    listed = client.get("/api/monitoring", headers=_auth(token)).json()
    assert {s["symbol"]: s["enabled"] for s in listed} == {"NVDA": True}

    disable_response = client.delete("/api/monitoring/NVDA", headers=_auth(token))
    assert disable_response.status_code == 204
    assert client.get("/api/monitoring", headers=_auth(token)).json() == []
