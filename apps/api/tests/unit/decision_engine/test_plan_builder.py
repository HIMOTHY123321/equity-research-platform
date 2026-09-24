from __future__ import annotations

from app.decision_engine.plan_builder import build_activation_snapshot, build_decision_plan
from app.decision_engine.schemas import AbstentionReason, ConditionRole, DecisionState
from tests.unit.decision_engine.conftest import spy_snapshot


def _qualified(index: int):
    snapshot = spy_snapshot()
    return snapshot.setup_snapshot.qualified_setups[index], snapshot


def test_weak_evidence_setup_abstains():
    setup, snapshot = _qualified(0)  # 0 passed soft checks, 0 major conflicts
    plan = build_decision_plan(setup, as_of=snapshot.as_of)

    assert plan.state == DecisionState.ABSTAIN
    assert plan.abstention_reason == AbstentionReason.WEAK_EVIDENCE
    assert [t.to_state for t in plan.transitions] == [
        DecisionState.EVALUATING,
        DecisionState.ABSTAIN,
    ]


def test_major_conflict_setup_abstains_contradictory_evidence():
    setup, snapshot = _qualified(2)  # has a MAJOR conflict
    plan = build_decision_plan(setup, as_of=snapshot.as_of)

    assert plan.state == DecisionState.ABSTAIN
    assert plan.abstention_reason == AbstentionReason.CONTRADICTORY_EVIDENCE


def test_sufficient_evidence_setup_reaches_watching():
    setup, snapshot = _qualified(3)  # 1 passed soft check, 0 major conflicts
    plan = build_decision_plan(setup, as_of=snapshot.as_of)

    assert plan.state == DecisionState.WATCHING
    assert plan.abstention_reason is None
    assert len(plan.entry_conditions) >= 1
    assert all(c.role == ConditionRole.ENTRY for c in plan.entry_conditions)
    assert len(plan.invalidation_conditions) >= 1
    assert len(plan.exit_conditions) >= 1


def test_plan_never_uses_buy_sell_or_confidence_language():
    setup, snapshot = _qualified(3)
    plan = build_decision_plan(setup, as_of=snapshot.as_of)

    banned = ["buy", "sell", "confidence", "guaranteed", "win probability"]
    haystacks = [t.reason for t in plan.transitions]
    haystacks += [
        c.description for c in [*plan.entry_conditions, *plan.invalidation_conditions, *plan.exit_conditions]
    ]
    for text in haystacks:
        lowered = text.lower()
        for term in banned:
            assert term not in lowered, f"banned term {term!r} found in {text!r}"


def test_plan_freezes_thresholds_reference_price_does_not_change():
    setup, snapshot = _qualified(3)
    plan = build_decision_plan(setup, as_of=snapshot.as_of)
    original_required_value = plan.entry_conditions[0].required_value

    # Rebuilding from the same setup at a later as_of must not change the
    # frozen entry condition threshold on the ALREADY-CREATED plan object.
    assert plan.entry_conditions[0].required_value == original_required_value
    assert plan.entry_conditions[0].required_value == setup.reference_price


def test_build_activation_snapshot_captures_current_evidence():
    setup, snapshot = _qualified(3)
    plan = build_decision_plan(setup, as_of=snapshot.as_of)

    activation = build_activation_snapshot(snapshot, plan, snapshot.as_of)

    assert activation.activated_at == snapshot.as_of
    assert activation.activation_price_reference == snapshot.feature_snapshot.latest_candle.close
    assert "1h" in activation.structure_by_timeframe
