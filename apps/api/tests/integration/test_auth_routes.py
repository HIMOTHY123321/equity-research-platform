"""Integration tests for Phase 16's signup/login/me routes, through the
real FastAPI app -- same dependency-override pattern
tests/integration/test_validation_routes.py already uses."""

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


def test_signup_returns_a_token_and_user(client):
    response = client.post(
        "/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "trader@example.com"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]
    assert body["access_token"]


def test_signup_rejects_duplicate_email(client):
    client.post("/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"})
    response = client.post(
        "/api/auth/signup", json={"email": "trader@example.com", "password": "anotherpassword"}
    )
    assert response.status_code == 409


def test_signup_rejects_short_password(client):
    response = client.post("/api/auth/signup", json={"email": "trader@example.com", "password": "short"})
    assert response.status_code == 422


def test_login_succeeds_with_correct_credentials(client):
    client.post("/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"})
    response = client.post(
        "/api/auth/login", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_rejects_wrong_password(client):
    client.post("/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"})
    response = client.post(
        "/api/auth/login", json={"email": "trader@example.com", "password": "wrongpassword"}
    )
    assert response.status_code == 401


def test_login_rejects_unknown_email(client):
    response = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever12345"}
    )
    assert response.status_code == 401


def test_me_requires_authentication(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_rejects_garbage_token(client):
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_me_returns_the_authenticated_user(client):
    signup_response = client.post(
        "/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    )
    token = signup_response.json()["access_token"]

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "trader@example.com"


def test_a_second_users_token_does_not_authenticate_as_the_first_user(client):
    token_a = client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": "hunter2hunter2"}
    ).json()["access_token"]
    token_b = client.post(
        "/api/auth/signup", json={"email": "b@example.com", "password": "hunter2hunter2"}
    ).json()["access_token"]

    me_a = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_a}"}).json()
    me_b = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_b}"}).json()

    assert me_a["email"] == "a@example.com"
    assert me_b["email"] == "b@example.com"
    assert me_a["id"] != me_b["id"]


# --------------------------------------------------------------- Phase 16.1
# Session lifecycle: cookie transport, logout revocation, disabled-user and
# expired-session rejection -- see app.auth.sessions/app.auth.cookies.


def test_signup_sets_an_httponly_session_cookie(client):
    response = client.post(
        "/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    )
    cookie = next((c for c in response.cookies.jar if c.name == "amd_session"), None)
    assert cookie is not None
    # http.cookiejar records boolean-only attributes as a present key with
    # value None -- "HttpOnly" in the rest dict IS the flag being set.
    assert "HttpOnly" in cookie._rest


def test_cookie_alone_authenticates_me_without_an_authorization_header(client):
    client.post("/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"})
    # TestClient persists cookies across requests on the same client by
    # default -- this call sends NO Authorization header at all.
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "trader@example.com"


def test_login_then_authenticated_then_logout_then_session_rejected(client):
    client.post("/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"})
    login_response = client.post(
        "/api/auth/login", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/auth/me", headers=headers).status_code == 200

    logout_response = client.post("/api/auth/logout", headers=headers)
    assert logout_response.status_code == 204

    # The exact same token, presented again, is now rejected -- proves
    # revocation is server-verifiable, not merely "the client forgot it."
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_clears_the_session_cookie(client):
    client.post("/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"})
    client.post("/api/auth/logout")
    # Cookie-based session is gone -- a follow-up request with no override
    # header is unauthenticated.
    assert client.get("/api/auth/me").status_code == 401


def test_logging_out_one_session_does_not_revoke_a_second_login_session(client):
    client.post("/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"})
    session_one = client.post(
        "/api/auth/login", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    ).json()["access_token"]
    session_two = client.post(
        "/api/auth/login", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    ).json()["access_token"]

    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {session_one}"})

    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {session_one}"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {session_two}"}).status_code == 200


def test_disabled_user_cannot_continue_using_an_existing_valid_session(client):
    from app.auth.repository import SqlAlchemyUserRepository
    from app.database.session import get_db

    token = client.post(
        "/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    # Directly disable the user through the same DB the app's own
    # dependency override points at -- simulates an admin action, no new
    # session/token issued.
    db = next(app.dependency_overrides[get_db]())
    user = SqlAlchemyUserRepository(db).get_by_email("trader@example.com")
    user.status = "disabled"
    db.commit()
    db.close()

    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_expired_session_is_rejected_with_401(client):
    from datetime import datetime, timedelta, timezone

    from app.auth.security import create_access_token
    from app.config import get_settings

    signup_response = client.post(
        "/api/auth/signup", json={"email": "trader@example.com", "password": "hunter2hunter2"}
    )
    user_id = signup_response.json()["user"]["id"]

    from uuid import UUID

    issued = create_access_token(
        UUID(user_id), settings=get_settings(), now=datetime.now(timezone.utc) - timedelta(hours=48)
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {issued.token}"})
    assert response.status_code == 401
