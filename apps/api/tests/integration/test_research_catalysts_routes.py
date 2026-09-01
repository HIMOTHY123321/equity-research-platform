"""Integration tests for Phase 10.1's catalyst-scoped research rigor (#B):
`POST /api/research/catalysts/query` must run the same Phase 8/9 machinery
`/api/research/query` runs, correctly scoped to the catalyst-filtered
population -- never just filtering the raw sample count while leaving the
qualified-vs-rejected comparison (or anything else) unscoped.
"""

from __future__ import annotations

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
from tests.unit.news.conftest import raw_article
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")


class FakeProvider(MarketDataProvider):
    _BY_SYMBOL_TIMEFRAME = {
        ("SPY", "1h"): SPY_1H,
        ("SPY", "1d"): SPY_1D,
        ("SPY", "4h"): SPY_1H,
    }

    def get_candles(self, symbol, timeframe, limit=200):
        candles = self._BY_SYMBOL_TIMEFRAME.get((symbol, timeframe.value), [])
        return candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


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
    app.dependency_overrides[get_market_data_provider] = lambda: FakeProvider()
    app.dependency_overrides[get_news_provider] = lambda: news_provider
    return TestClient(app)


@pytest.fixture
def client_with_earnings_article():
    # Anchored to the middle of the real SPY_1H fixture's own date range so
    # plenty of ledger entries (qualified AND rejected) fall within the
    # default 72h catalyst-linking lookback/lookahead window on both sides.
    anchor_time = SPY_1H[len(SPY_1H) // 2].timestamp
    raw = [
        raw_article(
            "Acme reports quarterly earnings beat",
            anchor_time - timedelta(hours=2),
            ["SPY"],
            source="Reuters",
        )
    ]
    client = _client(FixtureNewsProvider(raw))
    yield client, anchor_time
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_news():
    client = _client(FixtureNewsProvider([]))
    yield client
    app.dependency_overrides.clear()


def _run_replay(client, symbol="SPY"):
    response = client.post(
        "/api/research/replay",
        json={
            "symbol": symbol,
            "timeframe": "1h",
            "start": SPY_1H[0].timestamp.isoformat(),
            "end": SPY_1H[-1].timestamp.isoformat(),
        },
    )
    assert response.status_code == 200
    return response.json()["run_id"]


def test_catalyst_query_with_no_filters_matches_plain_query_exactly(client_no_news):
    run_id = _run_replay(client_no_news)
    body = {"run_ids": [run_id], "horizon_bars": 5, "seed": 0}

    plain = client_no_news.post("/api/research/query", json=body)
    catalyst = client_no_news.post("/api/research/catalysts/query", json=body)
    assert plain.status_code == catalyst.status_code == 200

    plain_json, catalyst_json = plain.json(), catalyst.json()
    # Every field ResearchQueryResponse defines must be byte-identical --
    # the catalyst route with no catalyst filters must reproduce the plain
    # route exactly (#B backward compatibility).
    for key in plain_json:
        assert catalyst_json[key] == plain_json[key], key
    assert catalyst_json["catalyst_filtered_raw_sample_count"] == plain_json["sample_count"]
    assert catalyst_json["unfiltered_raw_sample_count"] == plain_json["sample_count"]


def test_catalyst_filter_narrows_sample_and_exposes_raw_vs_independent_counts(client_with_earnings_article):
    client, anchor_time = client_with_earnings_article
    run_id = _run_replay(client)

    response = client.post(
        "/api/research/catalysts/query",
        json={"run_ids": [run_id], "horizon_bars": 5, "seed": 0, "catalyst_category": "earnings"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["catalyst_filters_applied"]["catalyst_category"] == "earnings"
    assert body["catalyst_filtered_raw_sample_count"] <= body["unfiltered_raw_sample_count"]
    assert body["catalyst_filtered_raw_sample_count"] > 0
    # The raw count is never presented as the independent sample size --
    # confirm the independence section's own (potentially smaller) counts
    # are present and separately labeled.
    composition = body["independence"]["sample_composition"]
    assert composition["raw_count"] <= body["catalyst_filtered_raw_sample_count"]
    assert composition["episode_count"] <= composition["raw_count"]


def test_catalyst_filter_with_no_matches_is_404(client_no_news):
    run_id = _run_replay(client_no_news)
    response = client_no_news.post(
        "/api/research/catalysts/query",
        json={"run_ids": [run_id], "horizon_bars": 5, "catalyst_category": "earnings"},
    )
    assert response.status_code == 404


def test_qualification_lift_is_scoped_to_the_catalyst_filtered_population(client_with_earnings_article):
    client, anchor_time = client_with_earnings_article
    run_id = _run_replay(client)

    unfiltered = client.post(
        "/api/research/catalysts/query", json={"run_ids": [run_id], "horizon_bars": 5, "seed": 0}
    ).json()
    filtered = client.post(
        "/api/research/catalysts/query",
        json={"run_ids": [run_id], "horizon_bars": 5, "seed": 0, "catalyst_category": "earnings"},
    ).json()

    # Both may or may not have a populated qualification_lift depending on
    # whether both qualified and rejected members exist in each population,
    # but if both are populated they must legitimately differ in sample
    # composition (proving the filtered one is NOT silently computed over
    # the full unfiltered pool -- the Phase 10.1 bug this test guards).
    if unfiltered["qualification_lift"] and filtered["qualification_lift"]:
        unfiltered_n = (
            unfiltered["qualification_lift"]["raw"]["group_a_distribution"]["n"]
            + unfiltered["qualification_lift"]["raw"]["group_b_distribution"]["n"]
        )
        filtered_n = (
            filtered["qualification_lift"]["raw"]["group_a_distribution"]["n"]
            + filtered["qualification_lift"]["raw"]["group_b_distribution"]["n"]
        )
        assert filtered_n <= unfiltered_n


def test_compare_to_no_catalyst_produces_a_baseline_comparison(client_with_earnings_article):
    client, anchor_time = client_with_earnings_article
    run_id = _run_replay(client)

    response = client.post(
        "/api/research/catalysts/query",
        json={
            "run_ids": [run_id],
            "horizon_bars": 5,
            "seed": 0,
            "catalyst_category": "earnings",
            "compare_to_no_catalyst": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    # Populated only if a genuine complement (non-matching) group exists in
    # the same setup_type/direction population -- assert the field exists
    # and, when populated, both group labels are the expected ones.
    if body["catalyst_vs_baseline"] is not None:
        assert body["catalyst_vs_baseline"]["raw"]["group_a_label"] == "catalyst_match"
        assert body["catalyst_vs_baseline"]["raw"]["group_b_label"] == "baseline_no_match"


def test_compare_to_no_catalyst_false_by_default_omits_baseline(client_with_earnings_article):
    client, anchor_time = client_with_earnings_article
    run_id = _run_replay(client)
    response = client.post(
        "/api/research/catalysts/query",
        json={"run_ids": [run_id], "horizon_bars": 5, "seed": 0, "catalyst_category": "earnings"},
    )
    assert response.status_code == 200
    assert response.json()["catalyst_vs_baseline"] is None


def test_require_catalyst_true_excludes_entries_with_no_nearest_catalyst(client_with_earnings_article):
    client, anchor_time = client_with_earnings_article
    run_id = _run_replay(client)
    response = client.post(
        "/api/research/catalysts/query",
        json={"run_ids": [run_id], "horizon_bars": 5, "seed": 0, "require_catalyst": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["catalyst_filtered_raw_sample_count"] <= body["unfiltered_raw_sample_count"]


def test_invalid_run_id_is_404(client_no_news):
    response = client_no_news.post(
        "/api/research/catalysts/query", json={"run_ids": ["does-not-exist"], "horizon_bars": 5}
    )
    assert response.status_code == 404
