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
