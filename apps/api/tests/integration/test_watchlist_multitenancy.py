"""Phase 16 (§10/§96/§117): the real, DB-backed, per-user Watchlist must
require authentication and must never let one user read or mutate another
user's watchlist -- through the real FastAPI app, real auth routes, real
SqlAlchemyWatchlistRepository, no dependency overrides for either auth or
the watchlist repository (that would defeat the point of this file)."""

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


def test_watchlist_requires_authentication(client):
    response = client.get("/api/watchlist")
    assert response.status_code == 401


def test_add_symbol_requires_authentication(client):
    response = client.post("/api/watchlist/symbols", json={"ticker": "NVDA"})
    assert response.status_code == 401


def test_two_users_each_get_their_own_default_watchlist(client):
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    watchlist_a = client.get("/api/watchlist", headers=_auth(token_a)).json()
    watchlist_b = client.get("/api/watchlist", headers=_auth(token_b)).json()

    # Both seeded from the same default set -- but they are SEPARATE rows,
    # proven below by mutating one and checking the other is unaffected.
    tickers_a = {row["ticker"] for row in watchlist_a}
    tickers_b = {row["ticker"] for row in watchlist_b}
    assert tickers_a == tickers_b
    assert len(tickers_a) > 0


def test_user_a_adding_a_symbol_is_invisible_to_user_b(client):
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    add_response = client.post(
        "/api/watchlist/symbols", json={"ticker": "COIN"}, headers=_auth(token_a)
    )
    assert add_response.status_code == 201

    tickers_a = {row["ticker"] for row in client.get("/api/watchlist", headers=_auth(token_a)).json()}
    tickers_b = {row["ticker"] for row in client.get("/api/watchlist", headers=_auth(token_b)).json()}

    assert "COIN" in tickers_a
    assert "COIN" not in tickers_b


def test_user_a_removing_a_default_symbol_does_not_affect_user_b(client):
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com")

    default_symbol = client.get("/api/watchlist", headers=_auth(token_a)).json()[0]["ticker"]
    remove_response = client.delete(
        f"/api/watchlist/symbols/{default_symbol}", headers=_auth(token_a)
    )
    assert remove_response.status_code == 204

    tickers_a = {row["ticker"] for row in client.get("/api/watchlist", headers=_auth(token_a)).json()}
    tickers_b = {row["ticker"] for row in client.get("/api/watchlist", headers=_auth(token_b)).json()}

    assert default_symbol not in tickers_a
    assert default_symbol in tickers_b


def test_a_stale_or_forged_token_cannot_access_anyones_watchlist(client):
    response = client.get("/api/watchlist", headers=_auth("forged.token.value"))
    assert response.status_code == 401
