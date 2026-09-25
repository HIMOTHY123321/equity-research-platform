from __future__ import annotations

import pytest

from app.alerts.repository import SqlAlchemyAlertRepository
from app.alerts.schemas import AlertOrigin, AlertType
from app.alerts.service import AlertService, transition_alert_type
from app.decision_engine.schemas import DecisionState
from app.decision_engine.state_machine import build_transition
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.decision_engine.test_state_machine import make_plan


def _service() -> AlertService:
    return AlertService(SqlAlchemyAlertRepository(make_session()))


def test_transition_alert_type_maps_invalidated():
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(plan, DecisionState.INVALIDATED, reason="broke support", as_of=plan.as_of)
    assert transition_alert_type(transition) == AlertType.INVALIDATED


def test_transition_alert_type_returns_none_for_abstain():
    plan = make_plan(DecisionState.EVALUATING)
    transition = build_transition(plan, DecisionState.ABSTAIN, reason="no evidence", as_of=plan.as_of)
    assert transition_alert_type(transition) is None


def test_emit_transition_alert_creates_event_with_deterministic_reason():
    service = _service()
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(
        plan, DecisionState.INVALIDATED, reason="Invalidation condition met: broke support", as_of=plan.as_of
    )

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is not None
    assert event.alert_type == AlertType.INVALIDATED
    assert event.summary == transition.reason
    assert event.decision_plan_id == plan.decision_plan_id
    assert event.origin == AlertOrigin.LIVE_PROSPECTIVE


def test_emit_transition_alert_is_idempotent_for_same_transition():
    service = _service()
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(plan, DecisionState.INVALIDATED, reason="broke support", as_of=plan.as_of)

    first = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)
    second = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert first is not None and second is not None
    assert first.alert_id == second.alert_id


def test_emit_transition_alert_respects_disabled_preference():
    repo = SqlAlchemyAlertRepository(make_session())
    repo.set_preference(AlertType.INVALIDATED, False)
    service = AlertService(repo)
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(plan, DecisionState.INVALIDATED, reason="broke support", as_of=plan.as_of)

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is None
    assert repo.unread_count() == 0


def test_emit_transition_alert_returns_none_for_abstain():
    service = _service()
    plan = make_plan(DecisionState.EVALUATING)
    transition = build_transition(plan, DecisionState.ABSTAIN, reason="no evidence", as_of=plan.as_of)

    event = service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)

    assert event is None


def test_emit_transition_alert_rejects_banned_language():
    service = _service()
    plan = make_plan(DecisionState.ACTIVE_THESIS)
    transition = build_transition(
        plan, DecisionState.INVALIDATED, reason="Strong sell, guaranteed loss", as_of=plan.as_of
    )

    with pytest.raises(ValueError):
        service.emit_transition_alert(plan, transition, origin=AlertOrigin.LIVE_PROSPECTIVE)


def test_emit_condition_alert_dedupes_within_cooldown():
    from datetime import datetime, timezone

    service = _service()
    ts = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    first = service.emit_condition_alert(
        symbol="SPY",
        alert_type=AlertType.DATA_STALE,
        identity="freshness",
        title="Data stale",
        summary="SPY market data has not refreshed within the expected window.",
        source_timestamp=ts,
        origin=AlertOrigin.LIVE_PROSPECTIVE,
    )
    second = service.emit_condition_alert(
        symbol="SPY",
        alert_type=AlertType.DATA_STALE,
        identity="freshness",
        title="Data stale",
        summary="SPY market data has not refreshed within the expected window.",
        source_timestamp=ts,
        origin=AlertOrigin.LIVE_PROSPECTIVE,
    )

    assert first is not None and second is not None
    assert first.alert_id == second.alert_id
