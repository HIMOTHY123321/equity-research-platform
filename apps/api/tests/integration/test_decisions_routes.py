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
