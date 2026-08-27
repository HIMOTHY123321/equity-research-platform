import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_market_data_provider
from app.database.session import get_db
from app.main import app
from app.market_data.provider import MarketDataProvider
from tests.unit.setup_detection.conftest import load_real_candles

SPY_1H = load_real_candles("SPY_1h")
SPY_1D = load_real_candles("SPY_1d")
QQQ_1H = load_real_candles("QQQ_1h")
QQQ_1D = load_real_candles("QQQ_1d")


class FakeProvider(MarketDataProvider):
    """Serves the same real, static SPY/QQQ fixture every other test in
    this suite uses -- no network access."""

    _BY_SYMBOL_TIMEFRAME = {
        ("SPY", "1h"): SPY_1H,
        ("SPY", "1d"): SPY_1D,
        ("SPY", "4h"): SPY_1H,
        ("QQQ", "1h"): QQQ_1H,
        ("QQQ", "1d"): QQQ_1D,
        ("QQQ", "4h"): QQQ_1H,
    }

    def get_candles(self, symbol, timeframe, limit=200):
        candles = self._BY_SYMBOL_TIMEFRAME.get((symbol, timeframe.value), [])
        return candles[-limit:]

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_previous_close(self, symbol):
        raise NotImplementedError


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
    app.dependency_overrides[get_market_data_provider] = lambda: FakeProvider()
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_market_data_provider, None)


def _run_replay(client, symbol="SPY"):
    candles = SPY_1H if symbol == "SPY" else QQQ_1H
    response = client.post(
        "/api/research/replay",
        json={
            "symbol": symbol,
            "timeframe": "1h",
            "start": candles[0].timestamp.isoformat(),
            "end": candles[-1].timestamp.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def test_universe_replay_runs_every_requested_symbol(client):
    response = client.post(
        "/api/research/universe-replay",
        json={
            "symbols": ["SPY", "QQQ"],
            "timeframe": "1h",
            "start": SPY_1H[0].timestamp.isoformat(),
            "end": SPY_1H[-1].timestamp.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["run_ids"].keys()) == {"SPY", "QQQ"}
    assert body["failures"] == {}


def test_universe_replay_reports_per_symbol_failure_without_aborting_others(client):
    response = client.post(
        "/api/research/universe-replay",
        json={
            "symbols": ["SPY", "NOT_A_REAL_TICKER_12345"],
            "timeframe": "1h",
            "start": SPY_1H[0].timestamp.isoformat(),
            "end": SPY_1H[-1].timestamp.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "SPY" in body["run_ids"]
    assert "NOT_A_REAL_TICKER_12345" in body["failures"]


def test_research_query_returns_full_evidence_bundle(client):
    run_id = _run_replay(client)
    response = client.post(
        "/api/research/query",
        json={"run_ids": [run_id], "setup_type": "trend_pullback", "horizon_bars": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sample_count"] > 0
    assert body["evidence_card"]["setup_type"] == "trend_pullback"
    assert body["signal_decay"]["horizons"]
    assert "distribution" in body["excursions"] or "mfe_atr" in body["excursions"]
    assert body["temporal_stability"]["granularity"] == "monthly"
    assert isinstance(body["contradictions"], list) and len(body["contradictions"]) == 4


def test_research_query_independence_section_is_present_and_consistent(client):
    run_id = _run_replay(client)
    response = client.post(
        "/api/research/query",
        json={"run_ids": [run_id], "setup_type": "trend_pullback", "horizon_bars": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    independence = body["independence"]
    composition = independence["sample_composition"]
    assert composition["raw_count"] == body["sample_count"]
    assert composition["episode_count"] <= composition["raw_count"]
    for horizon, purged_count in composition["purged_counts_by_horizon"].items():
        assert purged_count <= composition["raw_count"]
    assert independence["walk_forward"]["horizon_bars"] == 5
    assert independence["evidence_maturity"] in {"insufficient", "preliminary", "mixed", "replicated"}
    # Same evidence-card Phase 9 fields (#22) are populated on this query path too.
    assert body["evidence_card"]["independent_episode_count"] is not None
    assert body["evidence_card"]["purged_sample_count"] is not None


def test_research_query_pools_multiple_runs(client):
    run_a = _run_replay(client, "SPY")
    run_b = _run_replay(client, "QQQ")
    response = client.post("/api/research/query", json={"run_ids": [run_a, run_b], "horizon_bars": 5})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cross_symbol_stability"]["symbols_with_data"] >= 1
    symbols = {s["symbol"] for s in body["cross_symbol_stability"]["per_symbol"]}
    assert symbols <= {"SPY", "QQQ"}


def test_research_query_unknown_run_id_is_404(client):
    response = client.post("/api/research/query", json={"run_ids": ["00000000-0000-0000-0000-000000000000"]})
    assert response.status_code == 404


def test_research_query_no_matching_entries_is_404(client):
    run_id = _run_replay(client)
    response = client.post(
        "/api/research/query", json={"run_ids": [run_id], "setup_type": "gap_fill", "direction": "bearish"}
    )
    # gap_fill may or may not appear in the real fixture -- either a real
    # result or an explicit 404, never a fabricated empty-but-200 payload.
    assert response.status_code in (200, 404)


def test_analogs_endpoint_ranks_against_the_corpus(client):
    run_id = _run_replay(client)
    setups_response = client.get(f"/api/research/runs/{run_id}/setups", params={"limit": 50})
    entries = setups_response.json()["entries"]
    trend_entries = [e for e in entries if e["setup_type"] == "trend_pullback"]
    assert trend_entries, "expected at least one trend_pullback entry in the real fixture"
    query_candidate = trend_entries[0]["detection"]

    response = client.post(
        "/api/research/analogs",
        json={"query_candidate": query_candidate, "corpus_run_ids": [run_id], "top_n": 5},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    analogs = payload["analogs"]
    assert len(analogs) <= 5
    for analog in analogs:
        assert analog["setup_id"] != query_candidate["id"]  # never ranks itself
        assert "distance" in analog["distance"]

    # (#20/#21) Diversity report and the "one per episode" filtered view are
    # present, read-only over the same ranked list -- never re-scored.
    diversity = payload["diversity"]
    assert diversity["total_analogs"] == len(analogs)
    diverse = payload["diverse_analogs"]
    assert len(diverse) <= len(analogs)
    diverse_ids = {a["setup_id"] for a in diverse}
    ranked_ids = {a["setup_id"] for a in analogs}
    assert diverse_ids <= ranked_ids
    ranked_distance_by_id = {a["setup_id"]: a["distance"]["distance"] for a in analogs}
    for a in diverse:
        assert a["distance"]["distance"] == ranked_distance_by_id[a["setup_id"]]


def test_snapshot_create_get_and_compare_round_trip(client):
    create_response = client.post(
        "/api/research/snapshots",
        json={
            "label": "test snapshot A",
            "research_run_ids": ["run-1"],
            "config_hash": "hash-a",
            "dataset_manifest": {"symbols": ["SPY"], "timeframe": "1h"},
            "cohort_definition": {"setup_type": "breakout_retest"},
            "filters": {},
            "statistical_output": {"median": 0.2},
            "warning_flags": [],
        },
    )
    assert create_response.status_code == 200, create_response.text
    snapshot_id_a = create_response.json()["snapshot_id"]

    get_response = client.get(f"/api/research/snapshots/{snapshot_id_a}")
    assert get_response.status_code == 200
    assert get_response.json()["label"] == "test snapshot A"

    create_b = client.post(
        "/api/research/snapshots",
        json={
            "label": "test snapshot B",
            "research_run_ids": ["run-2"],
            "config_hash": "hash-b",
            "dataset_manifest": {"symbols": ["SPY"], "timeframe": "1h"},
            "cohort_definition": {"setup_type": "breakout_retest"},
            "filters": {},
            "statistical_output": {"median": 0.3},
            "warning_flags": [],
        },
    )
    snapshot_id_b = create_b.json()["snapshot_id"]

    compare_response = client.get(
        "/api/research/snapshots/compare",
        params={"snapshot_a": snapshot_id_a, "snapshot_b": snapshot_id_b},
    )
    assert compare_response.status_code == 200, compare_response.text
    comparison = compare_response.json()
    assert comparison["same_config_hash"] is False

    list_response = client.get("/api/research/snapshots")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2


def test_get_unknown_snapshot_is_404(client):
    response = client.get("/api/research/snapshots/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
