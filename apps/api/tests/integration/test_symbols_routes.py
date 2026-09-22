from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_search_returns_ranked_matches():
    resp = client.get("/api/symbols/search", params={"q": "NV"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "NV"
    tickers = [r["ticker"] for r in body["results"]]
    assert "NVDA" in tickers


def test_search_by_company_name():
    resp = client.get("/api/symbols/search", params={"q": "NVIDIA"})
    assert resp.status_code == 200
    tickers = [r["ticker"] for r in resp.json()["results"]]
    assert "NVDA" in tickers


def test_search_requires_nonempty_query():
    resp = client.get("/api/symbols/search", params={"q": ""})
    assert resp.status_code == 422


def test_search_gibberish_returns_empty_results_not_an_error():
    resp = client.get("/api/symbols/search", params={"q": "XYZNOTREAL"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_get_known_ticker():
    resp = client.get("/api/symbols/SPY")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "SPY"


def test_get_unknown_ticker_is_404():
    resp = client.get("/api/symbols/XYZNOTREAL")
    assert resp.status_code == 404
