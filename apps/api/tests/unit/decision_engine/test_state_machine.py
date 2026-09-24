from datetime import datetime, timezone

import pytest

from app.decision_engine.schemas import DecisionPlan, DecisionState
from app.decision_engine.state_machine import (
    TRANSITION_TABLE,
    IllegalTransitionError,
    apply_transition,
    build_transition,
    is_legal_transition,
)
from app.market_structure.schemas import Direction
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupType


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def make_plan(state: DecisionState = DecisionState.DETECTED) -> DecisionPlan:
    return DecisionPlan(
        decision_plan_id="plan-1",
        symbol="AAPL",
        timeframe=Timeframe.FIVE_MIN,
        setup_id="setup-1",
        setup_type=SetupType.BREAKOUT_RETEST,
        direction=Direction.BULLISH,
        created_at=utc(2026, 1, 1),
        as_of=utc(2026, 1, 1),
        state=state,
        entry_conditions=[],
        invalidation_conditions=[],
        exit_conditions=[],
        monitoring_conditions=[],
        transitions=[],
        pipeline_version="decision-engine-1.0",
    )


LEGAL_EDGES = [
    (DecisionState.DETECTED, DecisionState.EVALUATING),
    (DecisionState.EVALUATING, DecisionState.ABSTAIN),
    (DecisionState.EVALUATING, DecisionState.WATCHING),
    (DecisionState.WATCHING, DecisionState.ENTRY_CONDITIONS_MET),
    (DecisionState.WATCHING, DecisionState.INVALIDATED),
    (DecisionState.WATCHING, DecisionState.EXPIRED),
    (DecisionState.ENTRY_CONDITIONS_MET, DecisionState.ACTIVE_THESIS),
    (DecisionState.ENTRY_CONDITIONS_MET, DecisionState.INVALIDATED),
    (DecisionState.ACTIVE_THESIS, DecisionState.THESIS_STRENGTHENING),
    (DecisionState.ACTIVE_THESIS, DecisionState.THESIS_WEAKENING),
    (DecisionState.ACTIVE_THESIS, DecisionState.INVALIDATED),
    (DecisionState.ACTIVE_THESIS, DecisionState.EXIT_CONDITIONS_MET),
    (DecisionState.ACTIVE_THESIS, DecisionState.EXPIRED),
    (DecisionState.THESIS_STRENGTHENING, DecisionState.ACTIVE_THESIS),
    (DecisionState.THESIS_STRENGTHENING, DecisionState.THESIS_WEAKENING),
    (DecisionState.THESIS_STRENGTHENING, DecisionState.INVALIDATED),
    (DecisionState.THESIS_STRENGTHENING, DecisionState.EXIT_CONDITIONS_MET),
    (DecisionState.THESIS_STRENGTHENING, DecisionState.EXPIRED),
    (DecisionState.THESIS_WEAKENING, DecisionState.ACTIVE_THESIS),
    (DecisionState.THESIS_WEAKENING, DecisionState.THESIS_STRENGTHENING),
    (DecisionState.THESIS_WEAKENING, DecisionState.INVALIDATED),
    (DecisionState.THESIS_WEAKENING, DecisionState.EXIT_CONDITIONS_MET),
    (DecisionState.THESIS_WEAKENING, DecisionState.EXPIRED),
]


@pytest.mark.parametrize("from_state,to_state", LEGAL_EDGES)
def test_legal_transitions_are_accepted(from_state, to_state):
    plan = make_plan(from_state)
    transition = build_transition(plan, to_state, reason="test", as_of=utc(2026, 1, 2))
    assert transition.from_state == from_state
    assert transition.to_state == to_state

    new_plan = apply_transition(plan, transition)
    assert new_plan.state == to_state
    assert new_plan.transitions == [transition]
    # The input plan is never mutated.
    assert plan.state == from_state
    assert plan.transitions == []


ALL_STATES = list(DecisionState)
ILLEGAL_EDGES = [(f, t) for f in ALL_STATES for t in ALL_STATES if not is_legal_transition(f, t) and f != t]


@pytest.mark.parametrize("from_state,to_state", ILLEGAL_EDGES[:40])
def test_illegal_transitions_are_rejected(from_state, to_state):
    plan = make_plan(from_state)
    with pytest.raises(IllegalTransitionError):
        build_transition(plan, to_state, reason="test", as_of=utc(2026, 1, 2))


def test_terminal_states_have_no_outgoing_edges():
    for state in (
        DecisionState.ABSTAIN,
        DecisionState.INVALIDATED,
        DecisionState.EXIT_CONDITIONS_MET,
        DecisionState.EXPIRED,
    ):
        assert TRANSITION_TABLE[state] == set()


def test_direct_watching_to_exit_conditions_met_is_illegal():
    # A plan must pass through ENTRY_CONDITIONS_MET / ACTIVE_THESIS first --
    # skipping straight from WATCHING to EXIT_CONDITIONS_MET would imply a
    # thesis exited before it was ever activated.
    plan = make_plan(DecisionState.WATCHING)
    with pytest.raises(IllegalTransitionError):
        build_transition(plan, DecisionState.EXIT_CONDITIONS_MET, reason="test", as_of=utc(2026, 1, 2))


def test_transition_records_trigger_conditions_and_evidence_refs():
    plan = make_plan(DecisionState.WATCHING)
    transition = build_transition(
        plan,
        DecisionState.ENTRY_CONDITIONS_MET,
        reason="All entry conditions satisfied",
        as_of=utc(2026, 1, 2),
        trigger_condition_ids=["cond-1", "cond-2"],
        evidence_refs=["evidence-1"],
    )
    assert transition.trigger_condition_ids == ["cond-1", "cond-2"]
    assert transition.evidence_refs == ["evidence-1"]
    assert transition.decision_plan_id == "plan-1"
