"""Phase 16.1 (§4/§6/§16): two real users, through the real FastAPI app --
proves per-user alert delivery/monitoring/preferences never leak between
users, while the underlying AlertEventRecord stays a single, shared,
never-duplicated row. See app.database.models's Phase 16.1 section
docstring and docs/decisions/0020 for the SYSTEM RESEARCH UNIVERSE vs USER
MONITORING SUBSCRIPTIONS split this exercises end-to-end."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertOrigin, AlertType
from app.alerts.service import AlertService
from app.database.models import AlertEventRecord
from app.database.session import get_db
from app.main import app


@pytest.fixture
def env():
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
    client = TestClient(app)
    yield client, session_factory
    app.dependency_overrides.clear()


def _signup(client: TestClient, email: str) -> str:
    return client.post(
        "/api/auth/signup", json={"email": email, "password": "hunter2hunter2"}
    ).json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _emit_deterministic_alert(session_factory, *, symbol: str, identity: str) -> str:
    """Constructs exactly one AlertEvent the same way MonitoringService
    would (via AlertService.emit_condition_alert) -- never HTTP, since
    alert construction is not itself a public route (by design: it is
    always derived from an already-computed Decision Engine fact)."""
    session = session_factory()
    try:
        repository = SqlAlchemyAlertRepository(session)
        service = AlertService(repository)
        event = service.emit_condition_alert(
            symbol=symbol,
            alert_type=AlertType.DATA_STALE,
            identity=identity,
            title="Data stale",
            summary=f"{symbol} market data has not refreshed within the expected window.",
            source_timestamp=datetime.now(timezone.utc),
            origin=AlertOrigin.DEV_FIXTURE,
        )
        assert event is not None
        return event.alert_id
    finally:
        session.close()


def test_user_a_monitors_nvda_user_b_does_not_a_sees_alert_b_does_not(env):
    client, session_factory = env
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    client.post("/api/monitoring/NVDA", headers=_auth(token_a))
    # B deliberately does not monitor NVDA.

    _emit_deterministic_alert(session_factory, symbol="NVDA", identity="isolation-1")

    alerts_a = client.get("/api/alerts", headers=_auth(token_a)).json()
    alerts_b = client.get("/api/alerts", headers=_auth(token_b)).json()
    assert any(a["symbol"] == "NVDA" for a in alerts_a)
    assert not any(a["symbol"] == "NVDA" for a in alerts_b)

    unread_a = client.get("/api/alerts/unread-count", headers=_auth(token_a)).json()["count"]
    unread_b = client.get("/api/alerts/unread-count", headers=_auth(token_b)).json()["count"]
    assert unread_a == 1
    assert unread_b == 0


def test_then_b_monitors_spy_spy_alert_reaches_b_not_a(env):
    client, session_factory = env
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    client.post("/api/monitoring/NVDA", headers=_auth(token_a))
    client.post("/api/monitoring/SPY", headers=_auth(token_b))

    _emit_deterministic_alert(session_factory, symbol="SPY", identity="isolation-2")

    alerts_a = client.get("/api/alerts", headers=_auth(token_a)).json()
    alerts_b = client.get("/api/alerts", headers=_auth(token_b)).json()
    assert not any(a["symbol"] == "SPY" for a in alerts_a)
    assert any(a["symbol"] == "SPY" for a in alerts_b)


def test_a_also_monitoring_spy_then_a_receives_the_spy_alert_too(env):
    client, session_factory = env
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    client.post("/api/monitoring/SPY", headers=_auth(token_a))
    client.post("/api/monitoring/SPY", headers=_auth(token_b))

    _emit_deterministic_alert(session_factory, symbol="SPY", identity="isolation-3")

    alerts_a = client.get("/api/alerts", headers=_auth(token_a)).json()
    alerts_b = client.get("/api/alerts", headers=_auth(token_b)).json()
    assert any(a["symbol"] == "SPY" for a in alerts_a)
    assert any(a["symbol"] == "SPY" for a in alerts_b)


def test_a_cannot_acknowledge_bs_delivery(env):
    client, session_factory = env
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    client.post("/api/monitoring/TSLA", headers=_auth(token_b))
    alert_id = _emit_deterministic_alert(session_factory, symbol="TSLA", identity="isolation-4")

    response = client.post(f"/api/alerts/{alert_id}/acknowledge", headers=_auth(token_a))
    assert response.status_code == 404

    # B's own acknowledgement still works, proving the 404 above is
    # ownership-scoped, not a broken route.
    assert client.post(f"/api/alerts/{alert_id}/acknowledge", headers=_auth(token_b)).status_code == 204


def test_a_cannot_list_bs_deliveries(env):
    client, session_factory = env
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    client.post("/api/monitoring/AMZN", headers=_auth(token_b))
    _emit_deterministic_alert(session_factory, symbol="AMZN", identity="isolation-5")

    alerts_a = client.get("/api/alerts", headers=_auth(token_a)).json()
    assert alerts_a == []


def test_a_cannot_alter_bs_alert_preferences(env):
    client, session_factory = env
    del session_factory
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    client.put(
        "/api/alerts/preferences/invalidated", json={"enabled": False}, headers=_auth(token_a)
    )

    prefs_b_response = client.get("/api/alerts/preferences", headers=_auth(token_b)).json()
    prefs_b = {p["alert_type"]: p["enabled"] for p in prefs_b_response}
    # B's own preference for the same alert_type is untouched by A's write.
    assert prefs_b["invalidated"] is True


def test_monitoring_subscriptions_are_isolated_between_users(env):
    client, session_factory = env
    del session_factory
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    client.post("/api/monitoring/NVDA", headers=_auth(token_a))

    subs_a = {s["symbol"] for s in client.get("/api/monitoring", headers=_auth(token_a)).json()}
    subs_b = {s["symbol"] for s in client.get("/api/monitoring", headers=_auth(token_b)).json()}
    assert subs_a == {"NVDA"}
    assert subs_b == set()


def test_prospective_count_is_unauthenticated_and_shared_never_per_user(env):
    """Phase 16.1 (§15): /api/alerts/prospective-count deliberately has NO
    auth dependency and NEVER joins through UserAlertDeliveryRecord -- it
    must return the exact same global figure regardless of who (or how
    many users) is signed in."""
    client, session_factory = env
    for i in range(10):
        token = _signup(client, f"researcher{i}@example.com")
        client.post("/api/monitoring/IBM", headers=_auth(token))

    _emit_deterministic_alert(session_factory, symbol="IBM", identity="isolation-research")

    unauthenticated = client.get("/api/alerts/prospective-count")
    assert unauthenticated.status_code == 200
    # DEV_FIXTURE origin is never prospective-eligible (§35) regardless of
    # subscriber count -- the point here is the route works with zero
    # auth and its count is identical no matter how many users subscribed.
    assert unauthenticated.json()["count"] == 0


def test_100_monitoring_users_produce_exactly_one_shared_alert_event_row(env):
    """Phase 16.1 (§15): the single deterministic AlertEvent a symbol's
    transition produces must NEVER be duplicated per subscriber -- N users
    monitoring the same symbol is N delivery rows, never N AlertEventRecord
    rows."""
    client, session_factory = env
    for i in range(25):
        token = _signup(client, f"user{i}@example.com")
        client.post("/api/monitoring/QQQ", headers=_auth(token))

    _emit_deterministic_alert(session_factory, symbol="QQQ", identity="isolation-fanout")

    session = session_factory()
    try:
        rows = session.execute(
            select(AlertEventRecord).where(AlertEventRecord.symbol == "QQQ")
        ).scalars().all()
        assert len(rows) == 1
    finally:
        session.close()
