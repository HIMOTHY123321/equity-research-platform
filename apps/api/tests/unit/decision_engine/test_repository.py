from __future__ import annotations

from datetime import datetime, timezone

from app.decision_engine.repository import SqlAlchemyDecisionEngineRepository
from app.decision_engine.schemas import DecisionState
from app.decision_engine.state_machine import build_transition
from tests.unit.ai_analysis.conftest import make_session
from tests.unit.decision_engine.test_state_machine import make_plan


def _repo() -> SqlAlchemyDecisionEngineRepository:
    return SqlAlchemyDecisionEngineRepository(make_session())


def test_save_and_get_plan_round_trips():
    repo = _repo()
    plan = make_plan(DecisionState.WATCHING)

    repo.save_plan(plan)
    fetched = repo.get_plan(plan.decision_plan_id)

    assert fetched is not None
    assert fetched.decision_plan_id == plan.decision_plan_id
    assert fetched.state == DecisionState.WATCHING


def test_save_plan_upserts_by_business_key_not_duplicate_rows():
    repo = _repo()
    plan = make_plan(DecisionState.WATCHING)
    repo.save_plan(plan)

    advanced = plan.model_copy(update={"state": DecisionState.INVALIDATED})
    repo.save_plan(advanced)

    plans = repo.list_plans(symbol=plan.symbol)
    assert len(plans) == 1
    assert plans[0].state == DecisionState.INVALIDATED


def test_list_plans_open_only_excludes_terminal_states():
    repo = _repo()
    watching = make_plan(DecisionState.WATCHING)
    invalidated = make_plan(DecisionState.INVALIDATED).model_copy(update={"decision_plan_id": "plan-2"})
    repo.save_plan(watching)
    repo.save_plan(invalidated)

    open_plans = repo.list_plans(open_only=True)
    assert [p.decision_plan_id for p in open_plans] == ["plan-1"]


def test_transitions_are_append_only_and_ordered():
    repo = _repo()
    plan = make_plan(DecisionState.WATCHING)
    as_of = datetime(2026, 1, 2, tzinfo=timezone.utc)
    transition = build_transition(plan, DecisionState.INVALIDATED, reason="test", as_of=as_of)

    repo.record_transition(transition)
    transitions = repo.list_transitions(plan.decision_plan_id)

    assert len(transitions) == 1
    assert transitions[0].transition_id == transition.transition_id
    assert not hasattr(repo, "update_transition")
    assert not hasattr(repo, "delete_transition")
