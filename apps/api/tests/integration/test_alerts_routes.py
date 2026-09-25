"""Integration tests for the Phase 14 Alert Center API surface -- through
the real FastAPI app, same dependency-override pattern as
test_decisions_routes.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertEvent, AlertOrigin, AlertSeverity, AlertType
from app.database.session import get_db
from app.main import app

NOW = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_env():
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
    yield session_factory
    app.dependency_overrides.clear()


def _seed_event(session_factory, *, alert_id="alert-1", dedup_key="dedup-1", symbol="SPY", **overrides):
    session = session_factory()
    repo = SqlAlchemyAlertRepository(session)
    fields = dict(
        alert_id=alert_id,
        symbol=symbol,
        alert_type=AlertType.THESIS_WEAKENING,
        severity=AlertSeverity.IMPORTANT,
        title="Thesis weakening",
        summary="A tracked condition flipped to FAILED.",
        occurred_at=NOW,
        evaluated_at=NOW,
        dedup_key=dedup_key,
        origin=AlertOrigin.LIVE_PROSPECTIVE,
        pipeline_version="test",
        created_at=NOW,
    )
    fields.update(overrides)
    repo.record_event(AlertEvent(**fields))
    session.close()


def test_list_alerts_returns_seeded_event(db_env):
    _seed_event(db_env)
    client = TestClient(app)

    response = client.get("/api/alerts")

    assert response.status_code == 200
    alerts = response.json()
    assert len(alerts) == 1
    assert alerts[0]["alert_id"] == "alert-1"


def test_list_alerts_filters_by_symbol(db_env):
    _seed_event(db_env, alert_id="a1", dedup_key="k1", symbol="SPY")
    _seed_event(db_env, alert_id="a2", dedup_key="k2", symbol="QQQ")
    client = TestClient(app)

    response = client.get("/api/alerts", params={"symbol": "QQQ"})

    alerts = response.json()
    assert [a["alert_id"] for a in alerts] == ["a2"]


def test_unread_count_reflects_seeded_events(db_env):
    _seed_event(db_env, alert_id="a1", dedup_key="k1")
    _seed_event(db_env, alert_id="a2", dedup_key="k2")
    client = TestClient(app)

    response = client.get("/api/alerts/unread-count")

    assert response.status_code == 200
    assert response.json() == {"count": 2}


def test_acknowledge_reduces_unread_count(db_env):
    _seed_event(db_env, alert_id="a1", dedup_key="k1")
    client = TestClient(app)

    ack_response = client.post("/api/alerts/a1/acknowledge")
    count_response = client.get("/api/alerts/unread-count")

    assert ack_response.status_code == 204
    assert count_response.json() == {"count": 0}


def test_acknowledge_unknown_alert_returns_404(db_env):
    client = TestClient(app)

    response = client.post("/api/alerts/does-not-exist/acknowledge")

    assert response.status_code == 404


def test_acknowledge_all_marks_every_unread(db_env):
    _seed_event(db_env, alert_id="a1", dedup_key="k1")
    _seed_event(db_env, alert_id="a2", dedup_key="k2")
    client = TestClient(app)

    response = client.post("/api/alerts/acknowledge-all")

    assert response.status_code == 200
    assert response.json() == {"acknowledged": 2}
    assert client.get("/api/alerts/unread-count").json() == {"count": 0}


def test_get_preferences_returns_every_alert_type_with_defaults(db_env):
    client = TestClient(app)

    response = client.get("/api/alerts/preferences")

    assert response.status_code == 200
    prefs = {p["alert_type"]: p["enabled"] for p in response.json()}
    assert prefs["invalidated"] is True
    assert prefs["watching"] is False
    assert set(prefs.keys()) == {t.value for t in AlertType}


def test_set_preference_overrides_default(db_env):
    client = TestClient(app)

    put_response = client.put("/api/alerts/preferences/watching", json={"enabled": True})
    get_response = client.get("/api/alerts/preferences")

    assert put_response.status_code == 200
    prefs = {p["alert_type"]: p["enabled"] for p in get_response.json()}
    assert prefs["watching"] is True


def test_set_preference_unknown_type_returns_404(db_env):
    client = TestClient(app)

    response = client.put("/api/alerts/preferences/not-a-real-type", json={"enabled": True})

    assert response.status_code == 404
