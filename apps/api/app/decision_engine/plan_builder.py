"""Translates a QUALIFIED SetupCandidate into a DecisionPlan -- the
"setup -> explicit prospective conditions" step (§5 of the Phase 13 spec).

Condition thresholds are derived generically from the setup's own
`reference_price`/`direction`/`context` rather than one bespoke rule set per
SetupType (16 types); every generated condition is still a real, typed,
independently-evaluable DecisionCondition (see conditions.py), just built
from a shared template rather than 16 hand-tuned ones. This keeps the
generation logic itself simple and auditable, at the cost of not encoding
setup-type-specific nuance beyond direction/retest-applicability -- a
deliberate, disclosed scope choice (see the Phase 13 final report).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from app.decision_engine.schemas import (
    AbstentionReason,
    ActivationSnapshot,
    BarSemantics,
    ConditionOperator,
    ConditionRole,
    ConditionStatus,
    ConditionType,
    DecisionCondition,
    DecisionPlan,
    DecisionState,
    ResearchStatusLabel,
)
from app.decision_engine.state_machine import PIPELINE_VERSION, build_transition
from app.market_structure.schemas import Direction
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import ConflictSeverity, SetupCandidate, SetupType

# Setup types whose qualifying pattern includes a retest leg -- these get an
# explicit RETEST_CONFIRMED entry condition; other setup types (e.g. a
# straight previous-day-high breakout) do not require a retest to confirm.
_RETEST_SETUP_TYPES = {
    SetupType.BREAKOUT_RETEST,
    SetupType.SUPPORT_RECLAIM,
    SetupType.RESISTANCE_REJECTION,
    SetupType.MOVING_AVERAGE_RECLAIM,
    SetupType.GAP_FILL,
}

# Default invalidation buffer when the setup context has no ATR (%) --
# conservative and clearly labeled as a fallback, never silently applied
# without being visible in the condition's own description.
_DEFAULT_INVALIDATION_BUFFER_PERCENT = 0.5

_DEFAULT_EXIT_HORIZON_MINUTES = 24 * 60.0

_MAJOR_CONFLICT_ABSTAIN_THRESHOLD = 1
_MIN_SOFT_CHECKS_PASSED = 1


def _new_condition(
    *,
    role: ConditionRole,
    type_: ConditionType,
    description: str,
    timeframe: Timeframe,
    bar_semantics: BarSemantics,
    operator: ConditionOperator,
    required_value: Optional[float] = None,
    source_evidence_ref: Optional[str] = None,
) -> DecisionCondition:
    return DecisionCondition(
        id=str(uuid.uuid4()),
        role=role,
        type=type_,
        description=description,
        timeframe=timeframe,
        bar_semantics=bar_semantics,
        operator=operator,
        required_value=required_value,
        actual_value=None,
        status=ConditionStatus.PENDING,
        evaluated_at=None,
        source_evidence_ref=source_evidence_ref,
    )


def _invalidation_buffer(setup: SetupCandidate) -> float:
    if setup.reference_price is None:
        return 0.0
    atr = setup.context.atr if setup.context else None
    if atr:
        return atr
    return abs(setup.reference_price) * (_DEFAULT_INVALIDATION_BUFFER_PERCENT / 100.0)


def build_entry_conditions(setup: SetupCandidate) -> list[DecisionCondition]:
    if setup.reference_price is None:
        return []
    bullish = setup.direction == Direction.BULLISH
    conditions = [
        _new_condition(
            role=ConditionRole.ENTRY,
            type_=ConditionType.CLOSE_ABOVE if bullish else ConditionType.CLOSE_BELOW,
            description=(
                f"{setup.timeframe.value} close "
                f"{'above' if bullish else 'below'} {setup.reference_price:.2f}"
            ),
            timeframe=setup.timeframe,
            bar_semantics=BarSemantics.COMPLETED_BAR,
            operator=ConditionOperator.GTE if bullish else ConditionOperator.LTE,
            required_value=setup.reference_price,
            source_evidence_ref=setup.reference_source,
        )
    ]
    if setup.setup_type in _RETEST_SETUP_TYPES:
        conditions.append(
            _new_condition(
                role=ConditionRole.ENTRY,
                type_=ConditionType.RETEST_CONFIRMED,
                description=f"Retest of {setup.reference_price:.2f} confirmed",
                timeframe=setup.timeframe,
                bar_semantics=BarSemantics.COMPLETED_BAR,
                operator=ConditionOperator.PRESENT,
                required_value=setup.reference_price,
            )
        )
    return conditions


def build_invalidation_conditions(setup: SetupCandidate) -> list[DecisionCondition]:
    if setup.reference_price is None:
        return []
    bullish = setup.direction == Direction.BULLISH
    buffer = _invalidation_buffer(setup)
    invalidation_level = setup.reference_price - buffer if bullish else setup.reference_price + buffer
    return [
        _new_condition(
            role=ConditionRole.INVALIDATION,
            type_=ConditionType.CLOSE_BELOW if bullish else ConditionType.CLOSE_ABOVE,
            description=(
                f"{setup.timeframe.value} close "
                f"{'below' if bullish else 'above'} {invalidation_level:.2f} "
                f"(invalidation buffer {buffer:.2f})"
            ),
            timeframe=setup.timeframe,
            bar_semantics=BarSemantics.COMPLETED_BAR,
            operator=ConditionOperator.LTE if bullish else ConditionOperator.GTE,
            required_value=invalidation_level,
        ),
        _new_condition(
            role=ConditionRole.INVALIDATION,
            type_=ConditionType.STRUCTURE_CHOCH,
            description=f"{setup.timeframe.value} change of character against {setup.direction.value}",
            timeframe=setup.timeframe,
            bar_semantics=BarSemantics.COMPLETED_BAR,
            operator=ConditionOperator.EQ,
            required_value=1.0 if not bullish else 0.0,
        ),
    ]


def build_exit_conditions(setup: SetupCandidate) -> list[DecisionCondition]:
    bullish = setup.direction == Direction.BULLISH
    return [
        _new_condition(
            role=ConditionRole.EXIT,
            type_=ConditionType.STRUCTURE_BOS,
            description=f"{setup.timeframe.value} break of structure against {setup.direction.value}",
            timeframe=setup.timeframe,
            bar_semantics=BarSemantics.COMPLETED_BAR,
            operator=ConditionOperator.EQ,
            required_value=0.0 if bullish else 1.0,
        ),
        _new_condition(
            role=ConditionRole.EXIT,
            type_=ConditionType.TIME_ELAPSED,
            description=(
                f"Monitoring window of {int(_DEFAULT_EXIT_HORIZON_MINUTES)} minutes elapsed "
                "without exit/invalidation"
            ),
            timeframe=setup.timeframe,
            bar_semantics=BarSemantics.TICK,
            operator=ConditionOperator.GTE,
            required_value=_DEFAULT_EXIT_HORIZON_MINUTES,
        ),
    ]


def build_monitoring_conditions(setup: SetupCandidate) -> list[DecisionCondition]:
    return [
        _new_condition(
            role=ConditionRole.MONITORING,
            type_=ConditionType.RVOL_ABOVE,
            description="Relative volume tracked for context",
            timeframe=setup.timeframe,
            bar_semantics=BarSemantics.COMPLETED_BAR,
            operator=ConditionOperator.GTE,
            required_value=1.0,
        )
    ]


def _abstention_reason(setup: SetupCandidate) -> Optional[AbstentionReason]:
    major_conflicts = [c for c in setup.conflicts if c.severity == ConflictSeverity.MAJOR]
    if len(major_conflicts) >= _MAJOR_CONFLICT_ABSTAIN_THRESHOLD:
        return AbstentionReason.CONTRADICTORY_EVIDENCE
    passed_soft = [c for c in setup.soft_checks if c.passed]
    if len(passed_soft) < _MIN_SOFT_CHECKS_PASSED:
        return AbstentionReason.WEAK_EVIDENCE
    if setup.reference_price is None:
        return AbstentionReason.INSUFFICIENT_EVIDENCE
    return None


def build_decision_plan(
    setup: SetupCandidate,
    *,
    as_of: datetime,
    ranking_gate_status: str = "fail",
    source_evidence_packet_id: Optional[str] = None,
) -> DecisionPlan:
    """Creates a new plan in DETECTED state and immediately drives it
    through EVALUATING to either ABSTAIN or WATCHING -- setup qualification
    already happened upstream (setup_detection), so there is no reason for a
    freshly built plan to sit in DETECTED/EVALUATING once created."""
    plan = DecisionPlan(
        decision_plan_id=str(uuid.uuid4()),
        symbol=setup.symbol,
        timeframe=setup.timeframe,
        setup_id=setup.id,
        setup_type=setup.setup_type,
        direction=setup.direction,
        created_at=as_of,
        as_of=as_of,
        state=DecisionState.DETECTED,
        entry_conditions=build_entry_conditions(setup),
        invalidation_conditions=build_invalidation_conditions(setup),
        exit_conditions=build_exit_conditions(setup),
        monitoring_conditions=build_monitoring_conditions(setup),
        transitions=[],
        research_status=[
            ResearchStatusLabel.RESEARCH_MONITORING_ONLY,
            ResearchStatusLabel.INSUFFICIENT_FOR_RANKED_SIGNAL,
        ],
        ranking_gate_status=ranking_gate_status,
        source_setup_snapshot_id=setup.id,
        source_evidence_packet_id=source_evidence_packet_id,
        pipeline_version=PIPELINE_VERSION,
    )

    evaluating_transition = build_transition(
        plan,
        DecisionState.EVALUATING,
        reason="Setup qualified by setup_detection; beginning evaluation",
        as_of=as_of,
    )
    plan = plan.model_copy(update={"state": DecisionState.EVALUATING, "transitions": [evaluating_transition]})

    reason = _abstention_reason(setup)
    if reason is not None:
        transition = build_transition(
            plan, DecisionState.ABSTAIN, reason=f"Abstaining: {reason.value}", as_of=as_of
        )
        return plan.model_copy(
            update={
                "state": DecisionState.ABSTAIN,
                "transitions": [*plan.transitions, transition],
                "abstention_reason": reason,
            }
        )

    transition = build_transition(
        plan,
        DecisionState.WATCHING,
        reason="Entry conditions defined; monitoring for satisfaction",
        as_of=as_of,
    )
    return plan.model_copy(
        update={"state": DecisionState.WATCHING, "transitions": [*plan.transitions, transition]}
    )


def build_activation_snapshot(
    market_snapshot, plan: DecisionPlan, as_of: datetime, evidence_packet_id: Optional[str] = None
) -> ActivationSnapshot:
    structure_labels = {
        tf.value: snap.trend.trend.value for tf, snap in market_snapshot.structure_by_timeframe.items()
    }
    support = market_snapshot.levels_snapshot.nearest_support
    resistance = market_snapshot.levels_snapshot.nearest_resistance
    invalidation_condition = plan.invalidation_conditions[0] if plan.invalidation_conditions else None
    price = market_snapshot.feature_snapshot.latest_candle.close
    invalidation_distance = None
    if (
        price is not None
        and invalidation_condition is not None
        and invalidation_condition.required_value is not None
    ):
        invalidation_distance = abs(price - invalidation_condition.required_value)
    return ActivationSnapshot(
        activated_at=as_of,
        activation_price_reference=price,
        structure_by_timeframe=structure_labels,
        nearest_support_price=support.representative_price if support else None,
        nearest_resistance_price=resistance.representative_price if resistance else None,
        rvol=market_snapshot.feature_snapshot.volume.relative_volume,
        atr=market_snapshot.feature_snapshot.atr.value,
        invalidation_distance=invalidation_distance,
        evidence_packet_id=evidence_packet_id,
    )
