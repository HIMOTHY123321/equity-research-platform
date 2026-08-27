import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_watchlist_repository
from app.main import app
from app.watchlist.repository import DEFAULT_WATCHLIST_SYMBOLS, InMemoryWatchlistRepository


@pytest.fixture
def client():
    repo = InMemoryWatchlistRepository()
    app.dependency_overrides[get_watchlist_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.pop(get_watchlist_repository, None)


def test_list_watchlist_returns_default_symbols(client):
    response = client.get("/api/watchlist")
    assert response.status_code == 200
    tickers = {row["ticker"] for row in response.json()}
    assert tickers == set(DEFAULT_WATCHLIST_SYMBOLS)


def test_add_symbol_success(client):
    response = client.post("/api/watchlist/symbols", json={"ticker": "nflx"})
    assert response.status_code == 201
    assert response.json()["ticker"] == "NFLX"

    listing = client.get("/api/watchlist").json()
    assert "NFLX" in {row["ticker"] for row in listing}


def test_add_duplicate_symbol_is_409(client):
    client.post("/api/watchlist/symbols", json={"ticker": "AAPL"})
    response = client.post("/api/watchlist/symbols", json={"ticker": "AAPL"})
    assert response.status_code == 409


def test_add_invalid_ticker_is_422(client):
    response = client.post("/api/watchlist/symbols", json={"ticker": "123"})
    assert response.status_code == 422


def test_remove_symbol_success(client):
    response = client.delete("/api/watchlist/symbols/AAPL")
    assert response.status_code == 204

    listing = client.get("/api/watchlist").json()
    assert "AAPL" not in {row["ticker"] for row in listing}


def test_remove_missing_symbol_is_404(client):
    response = client.delete("/api/watchlist/symbols/GOOG")
    assert response.status_code == 404


def test_remove_invalid_ticker_is_422(client):
    response = client.delete("/api/watchlist/symbols/123")
    assert response.status_code == 422
