from __future__ import annotations

from datetime import timedelta

from app.decision_engine.plan_builder import build_decision_plan
from app.decision_engine.schemas import ConditionOperator, ConditionStatus, DecisionState
from app.decision_engine.service import evaluate_plan
from tests.unit.decision_engine.conftest import spy_snapshot


def _watching_plan():
    snapshot = spy_snapshot()
    setup = next(
        s
        for s in snapshot.setup_snapshot.qualified_setups
        if len([c for c in s.soft_checks if c.passed]) >= 1
        and not any(c.severity.value == "major" for c in s.conflicts)
    )
    plan = build_decision_plan(setup, as_of=snapshot.as_of)
    assert plan.state == DecisionState.WATCHING
    return plan, snapshot, setup


def test_watching_plan_unchanged_when_conditions_still_pending():
    plan, snapshot, setup = _watching_plan()
    # Force the entry level far away so it cannot possibly have been hit yet,
    # and clear invalidation/exit conditions so this test isolates entry
    # behavior from whatever those real conditions happen to already read
    # against real historical data.
    far_entry = plan.entry_conditions[0].model_copy(
        update={
            "required_value": plan.entry_conditions[0].required_value + 1000.0,
            "operator": ConditionOperator.GTE,
        }
    )
    plan = plan.model_copy(
        update={"entry_conditions": [far_entry], "invalidation_conditions": [], "exit_conditions": []}
    )

    result = evaluate_plan(plan, snapshot, snapshot.as_of)

    assert result.plan.state == DecisionState.WATCHING
    assert result.transitions == []


def test_watching_plan_advances_to_entry_conditions_met_when_all_entry_conditions_pass():
    plan, snapshot, setup = _watching_plan()
    close = snapshot.feature_snapshot.latest_candle.close
    trivially_true_entry = plan.entry_conditions[0].model_copy(
        update={
            "required_value": close - 1000.0,
            "operator": ConditionOperator.GTE,
            "type": plan.entry_conditions[0].type,
        }
    )
    # Clear invalidation/exit so this test isolates the WATCHING ->
    # ENTRY_CONDITIONS_MET edge from any further auto-advance this same
    # evaluation pass would otherwise cascade into.
    plan = plan.model_copy(
        update={
            "entry_conditions": [trivially_true_entry],
            "invalidation_conditions": [],
            "exit_conditions": [],
        }
    )

    result = evaluate_plan(plan, snapshot, snapshot.as_of)

    assert result.plan.state == DecisionState.ACTIVE_THESIS or result.plan.state in (
        DecisionState.THESIS_STRENGTHENING,
        DecisionState.THESIS_WEAKENING,
    )
    assert DecisionState.ENTRY_CONDITIONS_MET in [t.to_state for t in result.transitions]


def test_entry_conditions_met_auto_advances_to_active_thesis_with_snapshot():
    plan, snapshot, setup = _watching_plan()
    entry_met_plan = plan.model_copy(
        update={
            "state": DecisionState.ENTRY_CONDITIONS_MET,
            "invalidation_conditions": [],
            "exit_conditions": [],
        }
    )
    as_of = snapshot.as_of + timedelta(minutes=1)

    result = evaluate_plan(entry_met_plan, snapshot, as_of)

    assert result.plan.state in (
        DecisionState.ACTIVE_THESIS,
        DecisionState.THESIS_STRENGTHENING,
        DecisionState.THESIS_WEAKENING,
    )
    assert result.plan.activation_snapshot is not None
    assert result.plan.activation_snapshot.activated_at == as_of
    assert DecisionState.ACTIVE_THESIS in [t.to_state for t in result.transitions]


def test_watching_plan_invalidates_when_invalidation_condition_passes():
    plan, snapshot, setup = _watching_plan()
    close = snapshot.feature_snapshot.latest_candle.close
    # Guaranteed to fire (close is always <= close+1000).
    trivially_true_invalidation = plan.invalidation_conditions[0].model_copy(
        update={
            "type": plan.invalidation_conditions[0].type,
            "operator": ConditionOperator.LTE,
            "required_value": close + 1000.0,
        }
    )
    plan = plan.model_copy(update={"invalidation_conditions": [trivially_true_invalidation]})

    result = evaluate_plan(plan, snapshot, snapshot.as_of)

    assert result.plan.state == DecisionState.INVALIDATED
    assert result.transitions[-1].to_state == DecisionState.INVALIDATED


def test_terminal_state_plans_are_never_re_evaluated():
    plan, snapshot, setup = _watching_plan()
    invalidated = plan.model_copy(update={"state": DecisionState.INVALIDATED})

    result = evaluate_plan(invalidated, snapshot, snapshot.as_of)

    assert result.plan == invalidated
    assert result.transitions == []


def test_evaluation_records_condition_evaluations_with_timestamps():
    plan, snapshot, setup = _watching_plan()

    result = evaluate_plan(plan, snapshot, snapshot.as_of)

    assert len(result.evaluated_conditions) > 0
    for condition in result.evaluated_conditions:
        assert condition.status in (
            ConditionStatus.PASSED,
            ConditionStatus.FAILED,
            ConditionStatus.UNAVAILABLE,
        )
        assert condition.evaluated_at == snapshot.as_of
