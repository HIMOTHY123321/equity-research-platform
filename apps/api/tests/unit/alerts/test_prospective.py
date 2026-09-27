from __future__ import annotations

from datetime import datetime, timezone

from app.alerts.prospective import is_prospective_eligible
from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertEvent, AlertOrigin, AlertSeverity, AlertType
from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.decision_engine.schemas import DecisionState
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.decision_engine.test_state_machine import make_plan

NOW = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def _event(
    alert_id: str,
    dedup_key: str,
    alert_type: AlertType,
    origin: AlertOrigin,
    *,
    symbol: str = "AAPL",
    decision_plan_id: str = "plan-1",
) -> AlertEvent:
    return AlertEvent(
        alert_id=alert_id,
        symbol=symbol,
        decision_plan_id=decision_plan_id,
        alert_type=alert_type,
        severity=AlertSeverity.IMPORTANT,
        title="t",
        summary="s",
        occurred_at=NOW,
        evaluated_at=NOW,
        dedup_key=dedup_key,
        origin=origin,
        pipeline_version="test",
        created_at=NOW,
    )


def _decision_repo_with_real_plan():
    """A decision repository with one genuinely-persisted, non-fixture
    plan ("plan-1", symbol AAPL, setup_id "setup-1") -- what every eligible
    event in this file references."""
    repo = SqlAlchemyDecisionEngineRepository(make_session())
    repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    return repo


def test_live_prospective_invalidated_is_eligible():
    decision_repo = _decision_repo_with_real_plan()
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.LIVE_PROSPECTIVE)
    assert is_prospective_eligible(event, decision_repo) is True


def test_dev_fixture_is_never_eligible_even_for_eligible_type():
    decision_repo = _decision_repo_with_real_plan()
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.DEV_FIXTURE)
    assert is_prospective_eligible(event, decision_repo) is False


def test_nothing_is_eligible_while_the_dev_live_simulator_is_enabled(monkeypatch):
    """Phase 17 (§80, CRITICAL): the mock streaming simulator's synthetic
    events flow through the exact same LiveMarketService/RecomputationEngine
    /DecisionEngine pipeline real market data does, so a plan/alert built
    from it is otherwise indistinguishable from a real one (real,
    non-fixture setup_id; real persisted DecisionPlan). The only reliable
    signal is process-wide: whenever this process is configured with the
    simulator on, NOTHING is prospectively eligible -- even an event that
    would otherwise satisfy every other check."""
    import app.alerts.prospective as prospective_module
    from app.config import Settings

    monkeypatch.setattr(
        prospective_module, "get_settings", lambda: Settings(enable_dev_live_simulator=True)
    )
    decision_repo = _decision_repo_with_real_plan()
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.LIVE_PROSPECTIVE)
    assert is_prospective_eligible(event, decision_repo) is False


def test_historical_replay_is_never_eligible_even_for_eligible_type():
    decision_repo = _decision_repo_with_real_plan()
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.HISTORICAL_REPLAY)
    assert is_prospective_eligible(event, decision_repo) is False


def test_watching_is_never_eligible_regardless_of_origin():
    decision_repo = _decision_repo_with_real_plan()
    event = _event("a1", "k1", AlertType.WATCHING, AlertOrigin.LIVE_PROSPECTIVE)
    assert is_prospective_eligible(event, decision_repo) is False


def test_spoofed_origin_on_a_reserved_fixture_symbol_is_never_eligible():
    """§Phase-14.1-4: origin alone is never trusted -- a caller claiming
    live_prospective on one of the structurally-reserved fixture symbols
    must still be rejected."""
    decision_repo = _decision_repo_with_real_plan()
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.LIVE_PROSPECTIVE, symbol="ZFXA")
    assert is_prospective_eligible(event, decision_repo) is False


def test_spoofed_origin_referencing_a_fixture_built_plan_is_never_eligible():
    """A plan whose setup_id carries the "fixture:" prefix (however it got
    that origin claim) is rejected independent of the alert's own origin
    field."""
    decision_repo = SqlAlchemyDecisionEngineRepository(make_session())
    fixture_plan = make_plan(DecisionState.ACTIVE_THESIS).model_copy(
        update={"setup_id": "fixture:strengthen_invalidate"}
    )
    decision_repo.save_plan(fixture_plan)
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.LIVE_PROSPECTIVE)
    assert is_prospective_eligible(event, decision_repo) is False


def test_spoofed_origin_with_no_matching_persisted_plan_is_never_eligible():
    """A synthetic/test-only event referencing a decision_plan_id that was
    never actually persisted (no real DecisionPlan/transition provenance)
    is rejected -- exactly the shape a historical-replay or in-memory-only
    synthetic event would have."""
    decision_repo = SqlAlchemyDecisionEngineRepository(make_session())  # empty -- no plans saved
    event = _event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.LIVE_PROSPECTIVE)
    assert is_prospective_eligible(event, decision_repo) is False


def test_repository_count_only_includes_eligible_live_prospective_events():
    session = make_session()
    alert_repo = SqlAlchemyAlertRepository(session)
    decision_repo = SqlAlchemyDecisionEngineRepository(session)
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))

    alert_repo.record_event(_event("a1", "k1", AlertType.INVALIDATED, AlertOrigin.LIVE_PROSPECTIVE))
    alert_repo.record_event(_event("a2", "k2", AlertType.EXIT_CONDITIONS_MET, AlertOrigin.LIVE_PROSPECTIVE))
    alert_repo.record_event(_event("a3", "k3", AlertType.INVALIDATED, AlertOrigin.DEV_FIXTURE))
    alert_repo.record_event(_event("a4", "k4", AlertType.INVALIDATED, AlertOrigin.HISTORICAL_REPLAY))
    alert_repo.record_event(_event("a5", "k5", AlertType.WATCHING, AlertOrigin.LIVE_PROSPECTIVE))

    assert alert_repo.count_prospective_observations(decision_repo) == 2
