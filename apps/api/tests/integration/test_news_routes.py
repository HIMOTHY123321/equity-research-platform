from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_market_data_provider, get_news_provider
from app.database.session import get_db
from app.main import app
from app.market_data.provider import MarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from app.news.provider import NewsProvider
from tests.unit.news.conftest import et, raw_article
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")


class FakeMarketDataProvider(MarketDataProvider):
    def get_candles(self, symbol, timeframe, limit=200):
        if symbol == "SPY" and timeframe.value == "1h":
            return SPY_1H[-limit:]
        return []

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


class FailingNewsProvider(NewsProvider):
    def fetch_symbol_news(self, symbol, start, end, as_of):
        raise RuntimeError("simulated provider outage")

    def fetch_market_news(self, start, end, as_of):
        raise RuntimeError("simulated provider outage")


def _client(news_provider):
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
    app.dependency_overrides[get_news_provider] = lambda: news_provider
    app.dependency_overrides[get_market_data_provider] = lambda: FakeMarketDataProvider()
    return TestClient(app)


@pytest.fixture
def empty_client():
    client = _client(FixtureNewsProvider([]))
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_client():
    now = et(2026, 8, 20, 12, 0)
    raw = [
        raw_article(
            "Acme reports quarterly earnings beat", now - timedelta(hours=2), ["SPY"], source="Reuters"
        ),
        raw_article(
            "Acme Q2 earnings per share top estimates",
            now - timedelta(hours=1, minutes=55),
            ["SPY"],
            source="Bloomberg",
        ),
    ]
    client = _client(FixtureNewsProvider(raw))
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def failing_client():
    client = _client(FailingNewsProvider())
    yield client
    app.dependency_overrides.clear()


# ---- /api/news/{symbol} -----------------------------------------------------


def test_get_symbol_news_empty_list_when_no_articles(empty_client):
    response = empty_client.get("/api/news/SPY")
    assert response.status_code == 200
    assert response.json() == []


def test_get_symbol_news_returns_articles(seeded_client):
    response = seeded_client.get("/api/news/SPY")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["headline"]
    assert "article_id" in body[0]


def test_get_symbol_news_invalid_ticker_is_422(empty_client):
    response = empty_client.get("/api/news/123")
    assert response.status_code == 422


def test_get_symbol_news_provider_failure_degrades_to_empty_not_500(failing_client):
    response = failing_client.get("/api/news/SPY")
    assert response.status_code == 200
    assert response.json() == []


def test_article_has_source_link_fields_never_embeds_full_body(seeded_client):
    response = seeded_client.get("/api/news/SPY")
    body = response.json()[0]
    assert "headline" in body
    assert "source" in body
    assert "published_at" in body
    assert "url" in body
    assert "body" not in body
    assert "content" not in body
    assert "full_text" not in body


# ---- /api/news/market/whats-moving ------------------------------------------


def test_whats_moving_aggregates_across_symbols(seeded_client):
    as_of = et(2026, 8, 20, 12, 0).isoformat()
    response = seeded_client.get(
        "/api/news/market/whats-moving", params={"symbols": "SPY,QQQ", "as_of": as_of, "days": 1}
    )
    assert response.status_code == 200
    body = response.json()
    assert "SPY" in body["symbols_covered"]
    assert "QQQ" in body["symbols_covered"]
    assert len(body["events"]) == 1  # SPY's two articles group into one earnings event


def test_whats_moving_one_symbol_failure_does_not_abort_the_rest(seeded_client):
    response = seeded_client.get("/api/news/market/whats-moving", params={"symbols": "SPY,not-a-ticker"})
    assert response.status_code == 200
    body = response.json()
    assert "SPY" in body["symbols_covered"]
    assert "not-a-ticker" in body["symbols_failed"]


def test_whats_moving_empty_when_no_events(empty_client):
    response = empty_client.get("/api/news/market/whats-moving", params={"symbols": "SPY"})
    assert response.status_code == 200
    assert response.json()["events"] == []


# ---- /api/catalysts/{symbol} -------------------------------------------------


def test_get_symbol_catalysts_empty_list(empty_client):
    response = empty_client.get("/api/catalysts/SPY")
    assert response.status_code == 200
    assert response.json() == []


def test_get_symbol_catalysts_groups_into_events(seeded_client):
    response = seeded_client.get("/api/catalysts/SPY")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["source_count"] == 2
    assert events[0]["category"] == "earnings"


def test_get_symbol_catalysts_provider_failure_degrades_gracefully(failing_client):
    response = failing_client.get("/api/catalysts/SPY")
    assert response.status_code == 200
    assert response.json() == []


# ---- /api/catalysts/event/{event_id} -----------------------------------------


def test_get_catalyst_event_not_found_is_404(empty_client):
    response = empty_client.get("/api/catalysts/event/does-not-exist")
    assert response.status_code == 404


def test_get_catalyst_event_detail_includes_articles(seeded_client):
    events = seeded_client.get("/api/catalysts/SPY").json()
    event_id = events[0]["event_id"]
    response = seeded_client.get(f"/api/catalysts/event/{event_id}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["event"]["event_id"] == event_id
    assert len(detail["articles"]) == 2


def test_get_catalyst_reaction_not_found_event_is_404(empty_client):
    response = empty_client.get(
        "/api/catalysts/event/does-not-exist/reaction", params={"symbol": "SPY", "timeframe": "1h"}
    )
    assert response.status_code == 404


def test_get_catalyst_reaction_computes_and_returns(seeded_client):
    events = seeded_client.get("/api/catalysts/SPY").json()
    event_id = events[0]["event_id"]
    response = seeded_client.get(
        f"/api/catalysts/event/{event_id}/reaction", params={"symbol": "SPY", "timeframe": "1h"}
    )
    assert response.status_code == 200
    reaction = response.json()
    assert reaction["event_id"] == event_id
    assert reaction["symbol"] == "SPY"
    assert "session_at_event" in reaction


# ---- /api/catalysts/setup-context --------------------------------------------


def _candidate_payload(symbol="SPY", timestamp=None):
    ts = (timestamp or SPY_1H[100].timestamp).isoformat()
    return {
        "id": "test-setup-1",
        "symbol": symbol,
        "timeframe": "1h",
        "setup_type": "breakout_retest",
        "direction": "bullish",
        "candidate_candle_timestamp": ts,
        "created_at": ts,
        "current_state": "qualified",
        "transitions": [],
        "hard_checks": [],
        "soft_checks": [],
        "conflicts": [],
    }


def test_setup_context_no_recent_catalyst(empty_client):
    response = empty_client.post("/api/catalysts/setup-context", json={"candidate": _candidate_payload()})
    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "no_recent_catalyst_found"


def test_setup_context_with_recent_catalyst(seeded_client):
    detection_time = et(2026, 8, 20, 12, 0)
    response = seeded_client.post(
        "/api/catalysts/setup-context",
        json={"candidate": _candidate_payload(timestamp=detection_time)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["nearest_catalyst"] is not None
    assert body["nearest_catalyst"]["category"] == "earnings"


def test_setup_context_invalid_candidate_is_422(empty_client):
    response = empty_client.post("/api/catalysts/setup-context", json={"candidate": {"symbol": "SPY"}})
    assert response.status_code == 422
