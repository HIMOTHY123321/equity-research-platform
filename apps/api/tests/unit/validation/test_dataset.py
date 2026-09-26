"""Phase 15 §1/§71: the prospective dataset must include only genuine,
provenance-verified LIVE_PROSPECTIVE observations -- dev fixtures,
historical replay, synthetic events, and spoofed origins must all be
excluded, exactly like app.alerts.prospective.is_prospective_eligible
already enforces for Forward Validation counting."""

from __future__ import annotations

from datetime import timedelta

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertEvent, AlertHorizonOutcome, AlertOrigin, AlertSeverity, AlertType
from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.decision_engine.schemas import DecisionState
from app.validation.dataset import build_prospective_dataset
from app.validation.schemas import ResolutionQuality
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.decision_engine.test_state_machine import make_plan, utc

_START = utc(2026, 1, 1)


def _repos():
    session = make_session()
    return SqlAlchemyAlertRepository(session), SqlAlchemyDecisionEngineRepository(session)


def _alert(**overrides) -> AlertEvent:
    fields = dict(
        alert_id="alert-1",
        symbol="AAPL",
        decision_plan_id="plan-1",
        setup_id="setup-1",
        alert_type=AlertType.ENTRY_CONDITIONS_MET,
        severity=AlertSeverity.IMPORTANT,
        title="Entry conditions met",
        summary="All predefined entry conditions are now satisfied",
        occurred_at=_START + timedelta(minutes=5),
        evaluated_at=_START + timedelta(minutes=5),
        timeframe="5m",
        setup_type="breakout_retest",
        direction="bullish",
        dedup_key="dedup-1",
        origin=AlertOrigin.LIVE_PROSPECTIVE,
        pipeline_version="test",
        created_at=_START + timedelta(minutes=5),
    )
    fields.update(overrides)
    return AlertEvent(**fields)


def test_genuine_prospective_alert_is_included():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(_alert())

    observations = build_prospective_dataset(alert_repo, decision_repo)

    assert len(observations) == 1
    assert observations[0].symbol == "AAPL"
    assert observations[0].origin.value == "prospective"
    assert observations[0].resolved is False  # no AlertOutcome saved yet


def test_dev_fixture_alert_is_excluded():
    alert_repo, decision_repo = _repos()
    fixture_plan = make_plan(DecisionState.ACTIVE_THESIS).model_copy(
        update={"symbol": "ZFXA", "setup_id": "fixture:strengthen_invalidate"}
    )
    decision_repo.save_plan(fixture_plan)
    alert_repo.record_event(_alert(alert_id="alert-fixture", symbol="ZFXA", dedup_key="dedup-fixture"))

    observations = build_prospective_dataset(alert_repo, decision_repo)

    assert observations == []


def test_historical_replay_origin_alert_is_excluded():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(
        _alert(alert_id="alert-replay", dedup_key="dedup-replay", origin=AlertOrigin.HISTORICAL_REPLAY)
    )

    # HISTORICAL_REPLAY-origin alerts are never even fetched by
    # build_prospective_dataset (it only lists origin=LIVE_PROSPECTIVE),
    # so this must be an empty result, not merely filtered post-hoc.
    observations = build_prospective_dataset(alert_repo, decision_repo)

    assert observations == []


def test_spoofed_origin_on_a_fixture_built_plan_is_excluded():
    """A caller could set origin=LIVE_PROSPECTIVE on an alert that
    actually references a fixture-built plan -- is_prospective_eligible
    must catch this via the plan's own persisted setup_id, not trust the
    alert's self-reported origin alone."""
    alert_repo, decision_repo = _repos()
    fixture_plan = make_plan(DecisionState.ACTIVE_THESIS).model_copy(
        update={"setup_id": "fixture:strengthen_invalidate"}
    )
    decision_repo.save_plan(fixture_plan)
    alert_repo.record_event(_alert(origin=AlertOrigin.LIVE_PROSPECTIVE))

    observations = build_prospective_dataset(alert_repo, decision_repo)

    assert observations == []


def test_resolved_only_excludes_unresolved_observations():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(_alert())

    all_observations = build_prospective_dataset(alert_repo, decision_repo, resolved_only=False)
    resolved_observations = build_prospective_dataset(alert_repo, decision_repo, resolved_only=True)

    assert len(all_observations) == 1
    assert resolved_observations == []


def _horizon_outcome(alert_id: str, horizon_bars: int, return_percent: float) -> AlertHorizonOutcome:
    return AlertHorizonOutcome(
        outcome_id=f"{alert_id}-{horizon_bars}",
        alert_id=alert_id,
        symbol="AAPL",
        decision_plan_id="plan-1",
        horizon_bars=horizon_bars,
        resolved_at=_START + timedelta(hours=1),
        resolution_as_of=_START + timedelta(minutes=5 + horizon_bars * 5),
        return_percent=return_percent,
        pipeline_version="test",
    )


def test_partially_resolved_horizons_produce_partial_quality_with_the_resolved_returns_populated():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(_alert())
    alert_repo.save_horizon_outcome(_horizon_outcome("alert-1", 1, 0.5))
    alert_repo.save_horizon_outcome(_horizon_outcome("alert-1", 3, 1.2))

    observations = build_prospective_dataset(alert_repo, decision_repo)

    assert len(observations) == 1
    obs = observations[0]
    assert obs.resolved is False
    assert obs.resolution_quality == ResolutionQuality.PARTIAL
    assert obs.return_1 == 0.5
    assert obs.return_3 == 1.2
    assert obs.return_5 is None
    assert obs.return_10 is None
    assert obs.return_20 is None


def test_all_five_horizons_resolved_produces_valid_quality():
    alert_repo, decision_repo = _repos()
    decision_repo.save_plan(make_plan(DecisionState.ACTIVE_THESIS))
    alert_repo.record_event(_alert())
    for horizon_bars in (1, 3, 5, 10, 20):
        alert_repo.save_horizon_outcome(_horizon_outcome("alert-1", horizon_bars, 1.0))

    observations = build_prospective_dataset(alert_repo, decision_repo)

    assert len(observations) == 1
    assert observations[0].resolved is True
    assert observations[0].resolution_quality == ResolutionQuality.VALID
