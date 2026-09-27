"""Phase 16 (§48-§52/§106): entitlements are enforced server-side from the
authenticated user's own DB-stored `plan`/`role` -- never from a client-
supplied claim. TEST-MODE ONLY: no real payment provider is involved."""

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


def _signup(client: TestClient, email: str) -> tuple[str, str]:
    response = client.post("/api/auth/signup", json={"email": email, "password": "hunter2hunter2"})
    body = response.json()
    return body["access_token"], body["user"]["id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_new_signup_defaults_to_the_free_plan(client):
    token, _ = _signup(client, "trader@example.com")
    response = client.get("/api/billing/plan", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["plan"] == "free"
    assert response.json()["entitlements"] == []


def test_free_plan_is_denied_the_premium_example_route(client):
    token, _ = _signup(client, "trader@example.com")
    response = client.get("/api/billing/premium-example", headers=_auth(token))
    assert response.status_code == 403


def test_a_client_supplied_plan_header_is_ignored_server_is_authoritative(client):
    token, _ = _signup(client, "trader@example.com")
    response = client.get(
        "/api/billing/premium-example", headers={**_auth(token), "X-Plan": "pro", "X-Role": "admin"}
    )
    assert response.status_code == 403  # still denied -- server never reads these headers


def test_non_admin_cannot_change_anyones_plan(client):
    token, user_id = _signup(client, "trader@example.com")
    response = client.post(
        f"/api/admin/users/{user_id}/plan", json={"plan": "pro"}, headers=_auth(token)
    )
    assert response.status_code == 403


def test_admin_can_upgrade_a_user_and_the_upgrade_actually_grants_access(client):
    admin_token, admin_id = _signup(client, "admin@example.com")
    user_token, user_id = _signup(client, "trader@example.com")

    # Promote the admin account directly in the DB (no self-service
    # admin-signup route exists by design -- this simulates an operator
    # action, not something reachable over the API).
    from uuid import UUID

    from sqlalchemy.orm import Session as OrmSession

    from app.database.models import User

    db_override = app.dependency_overrides[get_db]
    session: OrmSession = next(db_override())
    admin_user = session.get(User, UUID(admin_id))
    admin_user.role = "admin"
    session.commit()

    before = client.get("/api/billing/premium-example", headers=_auth(user_token))
    assert before.status_code == 403

    upgrade = client.post(
        f"/api/admin/users/{user_id}/plan", json={"plan": "pro"}, headers=_auth(admin_token)
    )
    assert upgrade.status_code == 200
    assert upgrade.json()["plan"] == "pro"

    after = client.get("/api/billing/premium-example", headers=_auth(user_token))
    assert after.status_code == 200


def test_admin_endpoint_rejects_an_unknown_plan_name(client):
    admin_token, admin_id = _signup(client, "admin@example.com")
    from uuid import UUID

    from sqlalchemy.orm import Session as OrmSession

    from app.database.models import User

    db_override = app.dependency_overrides[get_db]
    session: OrmSession = next(db_override())
    admin_user = session.get(User, UUID(admin_id))
    admin_user.role = "admin"
    session.commit()

    _, target_id = _signup(client, "trader@example.com")
    response = client.post(
        f"/api/admin/users/{target_id}/plan",
        json={"plan": "diamond-super-plan"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 422
