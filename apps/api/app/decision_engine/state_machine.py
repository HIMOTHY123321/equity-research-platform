"""The only place a DecisionPlan's state is permitted to change.

No AI/LLM code may call `transition()` directly with an arbitrary target
state -- an AI provider may only *explain* a transition the deterministic
engine already produced (see ai_brief.py). Every transition is validated
against TRANSITION_TABLE and rejected with IllegalTransitionError otherwise,
so an invalid lifecycle jump (e.g. WATCHING straight to EXIT_CONDITIONS_MET)
can never be persisted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from app.decision_engine.schemas import DecisionPlan, DecisionState, DecisionTransition

PIPELINE_VERSION = "decision-engine-1.0"

# Legal edges per §35 of the Phase 13 spec. THESIS_STRENGTHENING and
# THESIS_WEAKENING are sub-states of ACTIVE_THESIS reachable from each other
# and from ACTIVE_THESIS itself, and both can terminate the same way
# ACTIVE_THESIS can.
_ACTIVE_THESIS_EXITS = {
    DecisionState.INVALIDATED,
    DecisionState.EXIT_CONDITIONS_MET,
    DecisionState.EXPIRED,
}

TRANSITION_TABLE: dict[DecisionState, set[DecisionState]] = {
    DecisionState.DETECTED: {DecisionState.EVALUATING},
    DecisionState.EVALUATING: {DecisionState.ABSTAIN, DecisionState.WATCHING},
    DecisionState.WATCHING: {
        DecisionState.ENTRY_CONDITIONS_MET,
        DecisionState.INVALIDATED,
        DecisionState.EXPIRED,
    },
    DecisionState.ENTRY_CONDITIONS_MET: {DecisionState.ACTIVE_THESIS, DecisionState.INVALIDATED},
    DecisionState.ACTIVE_THESIS: {
        DecisionState.THESIS_STRENGTHENING,
        DecisionState.THESIS_WEAKENING,
        *_ACTIVE_THESIS_EXITS,
    },
    DecisionState.THESIS_STRENGTHENING: {
        DecisionState.ACTIVE_THESIS,
        DecisionState.THESIS_WEAKENING,
        *_ACTIVE_THESIS_EXITS,
    },
    DecisionState.THESIS_WEAKENING: {
        DecisionState.ACTIVE_THESIS,
        DecisionState.THESIS_STRENGTHENING,
        *_ACTIVE_THESIS_EXITS,
    },
    DecisionState.ABSTAIN: set(),
    DecisionState.INVALIDATED: set(),
    DecisionState.EXIT_CONDITIONS_MET: set(),
    DecisionState.EXPIRED: set(),
}


class IllegalTransitionError(ValueError):
    def __init__(self, from_state: DecisionState, to_state: DecisionState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Illegal decision-state transition: {from_state.value} -> {to_state.value}")


def is_legal_transition(from_state: DecisionState, to_state: DecisionState) -> bool:
    return to_state in TRANSITION_TABLE.get(from_state, set())


def build_transition(
    plan: DecisionPlan,
    to_state: DecisionState,
    *,
    reason: str,
    as_of: datetime,
    occurred_at: Optional[datetime] = None,
    trigger_condition_ids: Optional[list[str]] = None,
    evidence_refs: Optional[list[str]] = None,
) -> DecisionTransition:
    """Validates legality and returns the immutable transition record. Does
    NOT mutate or persist `plan` -- callers (service.py / repository.py)
    apply the returned transition and persist the resulting new DecisionPlan
    state explicitly, keeping this function free of I/O."""
    if not is_legal_transition(plan.state, to_state):
        raise IllegalTransitionError(plan.state, to_state)

    return DecisionTransition(
        transition_id=str(uuid.uuid4()),
        decision_plan_id=plan.decision_plan_id,
        from_state=plan.state,
        to_state=to_state,
        occurred_at=occurred_at or as_of,
        as_of=as_of,
        reason=reason,
        trigger_condition_ids=trigger_condition_ids or [],
        evidence_refs=evidence_refs or [],
        pipeline_version=PIPELINE_VERSION,
    )


def apply_transition(plan: DecisionPlan, transition: DecisionTransition) -> DecisionPlan:
    """Returns a NEW DecisionPlan with the transition appended and `state`
    advanced -- the input `plan` is never mutated (it is frozen)."""
    return plan.model_copy(
        update={
            "state": transition.to_state,
            "transitions": [*plan.transitions, transition],
        }
    )
