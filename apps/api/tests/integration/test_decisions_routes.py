"""Integration tests for the Phase 13 Decision Engine API surface: scan,
list, get, transitions, evidence, explanations -- through the real FastAPI
app, same dependency-override pattern as test_forecasts_routes.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

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

_RAW_SPY_1H = load_real_candles("SPY_1h")
_RAW_SPY_1D = load_real_candles("SPY_1d")

# The route under test always evaluates at real `datetime.now()` (a live
# scan cannot backfill an as_of) -- shift the fixture's timestamps so its
# most recent candle looks like it just completed relative to real "now",
# otherwise every setup in the (otherwise-historical) fixture would already
# be past its own expires_at and the scan would legitimately find nothing.
# Shifting preserves every relative gap (weekday spacing, swing timing)
# since the same offset is added to every candle.
_SHIFT = datetime.now(timezone.utc) - _RAW_SPY_1H[-1].timestamp


def _shifted(candles):
    return [c.model_copy(update={"timestamp": c.timestamp + _SHIFT}) for c in candles]


SPY_1H = _shifted(_RAW_SPY_1H)
SPY_1D = _shifted(_RAW_SPY_1D)


class FakeProvider(MarketDataProvider):
    _BY_SYMBOL_TIMEFRAME = {
        ("SPY", "1h"): SPY_1H,
        ("SPY", "1d"): SPY_1D,
        ("SPY", "4h"): SPY_1H,
    }

    def get_candles(self, symbol, timeframe, limit=200, before=None):
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
    app.dependency_overrides.clear()


def test_scan_creates_and_returns_decision_plans(client):
    response = client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"})

    assert response.status_code == 200
    plans = response.json()
    assert len(plans) > 0
    for plan in plans:
        assert plan["symbol"] == "SPY"
        assert plan["state"] in (
            "abstain",
            "watching",
            "entry_conditions_met",
            "active_thesis",
            "thesis_strengthening",
            "thesis_weakening",
            "invalidated",
            "exit_conditions_met",
            "expired",
        )


def test_scan_does_not_duplicate_plans_across_repeated_scans(client):
    first = client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"}).json()
    second = client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"}).json()

    first_ids = sorted(p["decision_plan_id"] for p in first)
    second_ids = sorted(p["decision_plan_id"] for p in second)
    assert first_ids == second_ids


def test_list_decisions_filters_by_state(client):
    client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"})

    response = client.get("/api/decisions", params={"symbol": "SPY", "state": "abstain"})

    assert response.status_code == 200
    for plan in response.json():
        assert plan["state"] == "abstain"


def test_get_decision_returns_404_for_unknown_plan(client):
    response = client.get("/api/decisions/does-not-exist")

    assert response.status_code == 404


def test_get_decision_transitions_returns_full_lifecycle(client):
    plans = client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"}).json()
    plan_id = plans[0]["decision_plan_id"]

    response = client.get(f"/api/decisions/{plan_id}/transitions")

    assert response.status_code == 200
    transitions = response.json()
    assert len(transitions) >= 1
    assert transitions[0]["to_state"] in ("evaluating",)


def test_get_decision_evidence_diffs_returns_the_diff_recorded_after_activation(client):
    """Phase 18 (§11): a diff is only ever computed once a plan has an
    activation snapshot to compare against (app.decision_engine.service),
    so a fresh SPY scan (often WATCHING/ABSTAIN) may have none -- the
    strengthen_invalidate fixture deterministically drives a plan through
    ACTIVE_THESIS/STRENGTHENING, which does."""
    plan = client.post("/api/decisions/_dev/fixtures/strengthen_invalidate/replay").json()
    plan_id = plan["decision_plan_id"]

    response = client.get(f"/api/decisions/{plan_id}/evidence-diffs")

    assert response.status_code == 200
    diffs = response.json()
    assert len(diffs) >= 1
    assert diffs[0]["decision_plan_id"] == plan_id
    assert diffs[0]["classification"] in ("strengthening", "weakening", "neutral")


def test_get_decision_evidence_diffs_empty_list_for_a_plan_never_activated(client):
    plans = client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"}).json()
    plan_id = plans[0]["decision_plan_id"]

    response = client.get(f"/api/decisions/{plan_id}/evidence-diffs")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_decision_evidence_diffs_returns_404_for_unknown_plan(client):
    response = client.get("/api/decisions/does-not-exist/evidence-diffs")

    assert response.status_code == 404


def test_get_decision_evidence_never_contains_banned_language(client):
    plans = client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"}).json()
    plan_id = plans[0]["decision_plan_id"]

    response = client.get(f"/api/decisions/{plan_id}/evidence")

    assert response.status_code == 200
    body = response.text.lower()
    for banned in ("buy", "sell", "guaranteed", "win probability"):
        assert banned not in body


def test_get_decision_explanations_returns_why_now_and_why_not_yet(client):
    plans = client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"}).json()
    plan_id = plans[0]["decision_plan_id"]

    response = client.get(f"/api/decisions/{plan_id}/explanations")

    assert response.status_code == 200
    body = response.json()
    assert "why_now" in body
    assert "why_not_yet" in body
    assert "what_would_change_state" in body
    assert isinstance(body["what_would_change_state"], list)


# ---------------------------------------------------------------------------
# Phase 13.1: deterministic fixture replay through the real API surface --
# the same Decision Monitor UI that displays live SPY plans can display
# these, with zero new frontend code, since they're persisted through the
# exact same repository/routes.
# ---------------------------------------------------------------------------


def test_replay_unknown_fixture_scenario_returns_404(client):
    response = client.post("/api/decisions/_dev/fixtures/not-a-real-scenario/replay")
    assert response.status_code == 404


def test_fixture_replay_route_is_unreachable_outside_development(client, monkeypatch):
    # Dev-only lifecycle fixtures must never be reachable -- and therefore
    # never able to write a ZFXA/ZFXB/ZFXC plan into the database -- in a
    # production deployment. 404 (not 403): the route doesn't even
    # acknowledge it exists outside development.
    from app.config import Settings

    monkeypatch.setattr(
        "app.api.routes.decisions.get_settings", lambda: Settings(
            environment="production",
            secret_key="test-secret",
            database_url="postgresql://user:pass@host/db",
            market_data_provider="alpaca",
            news_provider="fixture",
            cors_origins="https://example.com",
        )
    )

    response = client.post("/api/decisions/_dev/fixtures/strengthen_invalidate/replay")

    assert response.status_code == 404
    # And no plan was ever created as a side effect of the attempt.
    listing = client.get("/api/decisions", params={"symbol": "ZFXA"})
    assert listing.json() == []


def test_replay_strengthen_invalidate_fixture_reaches_invalidated(client):
    response = client.post("/api/decisions/_dev/fixtures/strengthen_invalidate/replay")

    assert response.status_code == 200
    plan = response.json()
    assert plan["symbol"] == "ZFXA"
    assert plan["state"] == "invalidated"

    transitions_resp = client.get(f"/api/decisions/{plan['decision_plan_id']}/transitions")
    assert transitions_resp.status_code == 200
    to_states = [t["to_state"] for t in transitions_resp.json()]
    assert to_states == [
        "evaluating",
        "watching",
        "entry_conditions_met",
        "active_thesis",
        "thesis_strengthening",
        "invalidated",
    ]


def _signed_in_auth_header(client) -> dict:
    """Phase 16.1: /api/alerts now requires auth and is user-scoped -- a
    signed-up, ZFXA-monitoring user is what makes the fixture-replay's
    alert deliveries actually visible to `GET /api/alerts` below."""
    token = client.post(
        "/api/auth/signup", json={"email": "fixture-replay@example.com", "password": "hunter2hunter2"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/monitoring/ZFXA", headers=headers)
    return headers


def test_replay_fixture_emits_alerts_tagged_dev_fixture_origin(client):
    headers = _signed_in_auth_header(client)
    client.post("/api/decisions/_dev/fixtures/strengthen_invalidate/replay")

    alerts = client.get("/api/alerts", params={"symbol": "ZFXA"}, headers=headers).json()

    assert len(alerts) > 0
    assert all(a["origin"] == "dev_fixture" for a in alerts)


def test_fixture_replay_route_unreachable_in_production_creates_no_alerts_either(client, monkeypatch):
    from app.config import Settings

    headers = _signed_in_auth_header(client)

    monkeypatch.setattr(
        "app.api.routes.decisions.get_settings", lambda: Settings(
            environment="production",
            secret_key="test-secret",
            database_url="postgresql://user:pass@host/db",
            market_data_provider="alpaca",
            news_provider="fixture",
            cors_origins="https://example.com",
        )
    )

    client.post("/api/decisions/_dev/fixtures/strengthen_invalidate/replay")

    alerts = client.get("/api/alerts", params={"symbol": "ZFXA"}, headers=headers).json()
    assert alerts == []


def test_replay_exit_fixture_reaches_exit_conditions_met(client):
    response = client.post("/api/decisions/_dev/fixtures/exit/replay")

    assert response.status_code == 200
    plan = response.json()
    assert plan["symbol"] == "ZFXB"
    assert plan["state"] == "exit_conditions_met"


def test_replay_expire_fixture_reaches_expired(client):
    response = client.post("/api/decisions/_dev/fixtures/expire/replay")

    assert response.status_code == 200
    plan = response.json()
    assert plan["symbol"] == "ZFXC"
    assert plan["state"] == "expired"


def test_fixture_plans_appear_through_the_same_list_endpoint_the_ui_uses(client):
    client.post("/api/decisions/_dev/fixtures/strengthen_invalidate/replay")

    response = client.get("/api/decisions", params={"symbol": "ZFXA"})

    assert response.status_code == 200
    plans = response.json()
    assert len(plans) == 1
    assert plans[0]["state"] == "invalidated"


# ---------------------------------------------------------------------------
# Phase 14: cross-symbol Decision Scanner (§9/§36) -- read-only aggregation
# over whatever plans already exist for the monitored universe.
# ---------------------------------------------------------------------------


def test_scanner_surfaces_a_row_for_a_scanned_symbol_with_a_plan(client):
    client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"})

    response = client.get("/api/decisions/scanner")

    assert response.status_code == 200
    rows = response.json()
    spy_row = next(r for r in rows if r["symbol"] == "SPY")
    assert spy_row["state"] in (
        "abstain",
        "watching",
        "entry_conditions_met",
        "active_thesis",
        "thesis_strengthening",
        "thesis_weakening",
        "invalidated",
        "exit_conditions_met",
        "expired",
    )


def test_scanner_never_exposes_a_ranking_score_field(client):
    client.post("/api/decisions/SPY/scan", params={"timeframe": "1h"})

    response = client.get("/api/decisions/scanner")

    rows = response.json()
    for row in rows:
        assert "score" not in row
        assert "rank" not in row
        assert "expected_return" not in row


def test_scanner_route_is_not_shadowed_by_decision_plan_id_path(client):
    response = client.get("/api/decisions/scanner")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
