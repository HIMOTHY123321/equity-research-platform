"""Drives a DecisionPlan through one evaluation pass, and the live
subscription wiring that calls it whenever a completed candle refreshes a
symbol/timeframe's canonical snapshot (§16 of the Phase 13 spec).

`evaluate_plan` is pure -- given a plan and a fresh MarketSnapshot, it
returns the (possibly unchanged) new plan plus every DecisionTransition and
EvidenceDiffSnapshot produced, with no I/O. `DecisionEngineService` is the
thin, stateful wrapper that persists those results and subscribes to
RecomputationEngine's push-based SnapshotRefreshedEvent queue -- the SAME
completed-bar trigger every other live consumer in this codebase already
uses, so this module adds zero new polling/timer infrastructure and cannot
evaluate on a still-forming candle.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.ai_analysis.market_snapshot import MarketSnapshot, build_market_snapshot
from app.decision_engine.conditions import ConditionContext, evaluate
from app.decision_engine.evidence_diff import compute_evidence_diff
from app.decision_engine.plan_builder import build_activation_snapshot, build_decision_plan
from app.decision_engine.repository import DecisionEngineRepository
from app.decision_engine.schemas import (
    TERMINAL_STATES,
    ConditionStatus,
    DecisionCondition,
    DecisionPlan,
    DecisionState,
    DecisionTransition,
    EvidenceDiffSnapshot,
    ThesisDirectionClass,
)
from app.decision_engine.state_machine import apply_transition, build_transition, is_legal_transition
from app.live.recompute import RecomputationEngine, SnapshotRefreshedEvent
from app.market_data.provider import MarketDataProvider
from app.news.schemas import SetupCatalystContext
from app.schemas.market_data import Timeframe

_THESIS_STATES = (
    DecisionState.ACTIVE_THESIS,
    DecisionState.THESIS_STRENGTHENING,
    DecisionState.THESIS_WEAKENING,
)

_CLASSIFICATION_TO_STATE = {
    ThesisDirectionClass.STRENGTHENING: DecisionState.THESIS_STRENGTHENING,
    ThesisDirectionClass.WEAKENING: DecisionState.THESIS_WEAKENING,
    ThesisDirectionClass.NEUTRAL: DecisionState.ACTIVE_THESIS,
}


@dataclass(frozen=True)
class EvaluationResult:
    plan: DecisionPlan
    transitions: list[DecisionTransition] = field(default_factory=list)
    evaluated_conditions: list[DecisionCondition] = field(default_factory=list)
    evidence_diff: Optional[EvidenceDiffSnapshot] = None


def _evaluate_all(conditions: list[DecisionCondition], ctx: ConditionContext) -> list[DecisionCondition]:
    return [evaluate(c, ctx) for c in conditions]


def _first_passed(conditions: list[DecisionCondition]) -> Optional[DecisionCondition]:
    for c in conditions:
        if c.status == ConditionStatus.PASSED:
            return c
    return None


def _all_passed(conditions: list[DecisionCondition]) -> bool:
    return len(conditions) > 0 and all(c.status == ConditionStatus.PASSED for c in conditions)


def evaluate_plan(
    plan: DecisionPlan,
    market_snapshot: MarketSnapshot,
    as_of: datetime,
    *,
    catalyst_context: Optional[SetupCatalystContext] = None,
    evidence_packet_id: Optional[str] = None,
) -> EvaluationResult:
    """One deterministic evaluation pass. Only uses `market_snapshot`, which
    the caller must have built with `as_of` set to the instant the triggering
    completed candle became known -- never a future instant relative to it
    (see replay.py, which is what makes this reproducible)."""
    if plan.state in TERMINAL_STATES:
        return EvaluationResult(plan=plan)

    ctx = ConditionContext(
        snapshot=market_snapshot,
        as_of=as_of,
        catalyst_context=catalyst_context,
        monitoring_started_at=plan.created_at,
    )
    evaluated: list[DecisionCondition] = []
    transitions: list[DecisionTransition] = []
    working = plan

    if working.state == DecisionState.WATCHING:
        evaluated_invalidation = _evaluate_all(working.invalidation_conditions, ctx)
        evaluated.extend(evaluated_invalidation)
        trigger = _first_passed(evaluated_invalidation)
        if trigger is not None:
            t = build_transition(
                working,
                DecisionState.INVALIDATED,
                reason=f"Invalidation condition met before entry: {trigger.description}",
                as_of=as_of,
                trigger_condition_ids=[trigger.id],
            )
            return EvaluationResult(
                plan=apply_transition(working, t), transitions=[t], evaluated_conditions=evaluated
            )

        evaluated_exit = _evaluate_all(working.exit_conditions, ctx)
        expiration = next(
            (
                c
                for c in evaluated_exit
                if c.status == ConditionStatus.PASSED and c.required_value is not None
            ),
            None,
        )
        evaluated_entry = _evaluate_all(working.entry_conditions, ctx)
        evaluated.extend(evaluated_entry)

        if _all_passed(evaluated_entry):
            t = build_transition(
                working,
                DecisionState.ENTRY_CONDITIONS_MET,
                reason="All predefined entry conditions are now satisfied",
                as_of=as_of,
                trigger_condition_ids=[c.id for c in evaluated_entry],
            )
            working = apply_transition(working, t)
            transitions.append(t)
        elif expiration is not None:
            evaluated.extend(evaluated_exit)
            t = build_transition(
                working,
                DecisionState.EXPIRED,
                reason="Entry conditions were never completed before the monitoring window closed",
                as_of=as_of,
                trigger_condition_ids=[expiration.id],
            )
            return EvaluationResult(
                plan=apply_transition(working, t), transitions=[t], evaluated_conditions=evaluated
            )
        else:
            return EvaluationResult(
                plan=working.model_copy(update={"as_of": as_of}), evaluated_conditions=evaluated
            )

    if working.state == DecisionState.ENTRY_CONDITIONS_MET:
        activation = build_activation_snapshot(market_snapshot, working, as_of, evidence_packet_id)
        t = build_transition(
            working,
            DecisionState.ACTIVE_THESIS,
            reason="Entry conditions occurred; monitoring the predefined scenario prospectively",
            as_of=as_of,
        )
        working = apply_transition(working, t).model_copy(update={"activation_snapshot": activation})
        transitions.append(t)

    if working.state in _THESIS_STATES:
        evaluated_invalidation = _evaluate_all(working.invalidation_conditions, ctx)
        evaluated.extend(evaluated_invalidation)
        trigger = _first_passed(evaluated_invalidation)
        if trigger is not None:
            t = build_transition(
                working,
                DecisionState.INVALIDATED,
                reason=f"Invalidation condition met: {trigger.description}",
                as_of=as_of,
                trigger_condition_ids=[trigger.id],
            )
            return EvaluationResult(
                plan=apply_transition(working, t),
                transitions=[*transitions, t],
                evaluated_conditions=evaluated,
            )

        evaluated_exit = _evaluate_all(working.exit_conditions, ctx)
        evaluated.extend(evaluated_exit)
        exit_trigger = _first_passed(evaluated_exit)
        if exit_trigger is not None:
            t = build_transition(
                working,
                DecisionState.EXIT_CONDITIONS_MET,
                reason=f"Exit condition met: {exit_trigger.description}",
                as_of=as_of,
                trigger_condition_ids=[exit_trigger.id],
            )
            return EvaluationResult(
                plan=apply_transition(working, t),
                transitions=[*transitions, t],
                evaluated_conditions=evaluated,
            )

        diff = None
        if working.activation_snapshot is not None:
            diff = compute_evidence_diff(
                working.decision_plan_id,
                working.direction,
                working.timeframe,
                working.activation_snapshot,
                market_snapshot,
                as_of,
            )
            target_state = _CLASSIFICATION_TO_STATE[diff.classification]
            if target_state != working.state and is_legal_transition(working.state, target_state):
                t = build_transition(
                    working,
                    target_state,
                    reason=(
                        "; ".join(diff.classification_reasons)
                        if diff.classification_reasons
                        else "Evidence diff produced no qualifying reasons"
                    ),
                    as_of=as_of,
                    evidence_refs=[diff.snapshot_id],
                )
                working = apply_transition(working, t)
                transitions.append(t)

        return EvaluationResult(
            plan=working.model_copy(update={"as_of": as_of}),
            transitions=transitions,
            evaluated_conditions=evaluated,
            evidence_diff=diff,
        )

    return EvaluationResult(
        plan=working.model_copy(update={"as_of": as_of}),
        transitions=transitions,
        evaluated_conditions=evaluated,
    )


@dataclass(frozen=True)
class ScanResult:
    plans: list[DecisionPlan]
    """Every plan for this symbol/timeframe, new or pre-existing."""
    new_plans: list[DecisionPlan]
    """Plans created by this scan (fresh setups that had no plan yet) --
    each carries its own DETECTED->EVALUATING(->WATCHING|ABSTAIN)
    transitions in `.transitions`."""
    transitions: list[DecisionTransition]
    """Every transition produced by re-evaluating already-open plans this
    pass (does not include new_plans' own initial transitions -- read those
    off `new_plans[i].transitions` instead, same as plan_builder always
    returns them)."""


def run_symbol_scan(
    symbol: str,
    timeframe: Timeframe,
    market_provider: MarketDataProvider,
    repository: DecisionEngineRepository,
    as_of: datetime,
) -> ScanResult:
    """One full scan for one symbol/timeframe: build a fresh snapshot,
    create a DecisionPlan for every qualified setup that doesn't already
    have one, evaluate every open plan against the same snapshot, and
    persist everything. Extracted from app.api.routes.decisions.scan_symbol
    (§6 of the Phase 14 plan -- the route and the Phase 14 monitoring
    service must never carry two divergent implementations of the same
    scan) with zero behavior change to the route; the route now just calls
    this and returns `.plans`."""
    snapshot = build_market_snapshot(symbol, timeframe, market_provider, as_of, now=as_of)

    existing_setup_ids = {
        p.setup_id for p in repository.list_plans(symbol=symbol, timeframe=timeframe.value, limit=1000)
    }
    new_plans: list[DecisionPlan] = []
    for setup in snapshot.setup_snapshot.qualified_setups:
        if setup.id in existing_setup_ids:
            continue
        plan = build_decision_plan(setup, as_of=as_of)
        repository.save_plan(plan)
        for transition in plan.transitions:
            repository.record_transition(transition)
        new_plans.append(plan)

    open_plans = repository.list_plans(symbol=symbol, timeframe=timeframe.value, open_only=True)
    all_transitions: list[DecisionTransition] = []
    for plan in open_plans:
        result = evaluate_plan(plan, snapshot, as_of)
        repository.save_plan(result.plan)
        for transition in result.transitions:
            repository.record_transition(transition)
        all_transitions.extend(result.transitions)
        if result.evaluated_conditions:
            repository.record_condition_evaluations(plan.decision_plan_id, result.evaluated_conditions)
        if result.evidence_diff is not None:
            repository.record_evidence_diff(result.evidence_diff)

    return ScanResult(
        plans=repository.list_plans(symbol=symbol, timeframe=timeframe.value, limit=1000),
        new_plans=new_plans,
        transitions=all_transitions,
    )


class DecisionEngineService:
    """Subscribes to RecomputationEngine's SnapshotRefreshedEvent queue and
    re-evaluates every open plan for the refreshed (symbol, timeframe) --
    the ONLY trigger for live evaluation, so a plan can never transition on
    a still-forming candle (RecomputationEngine itself only fires on
    CompletedCandleEvent, never on a live tick)."""

    def __init__(
        self,
        repository: DecisionEngineRepository,
        recompute_engine: RecomputationEngine,
        market_provider: MarketDataProvider,
    ) -> None:
        self._repository = repository
        self._recompute_engine = recompute_engine
        self._market_provider = market_provider
        self._queue: Optional["asyncio.Queue[SnapshotRefreshedEvent]"] = None
        self._task: Optional[asyncio.Task] = None

    def evaluate_open_plans_for(
        self, symbol: str, timeframe: Timeframe, as_of: datetime
    ) -> list[EvaluationResult]:
        snapshot = build_market_snapshot(symbol, timeframe, self._market_provider, as_of, now=as_of)
        open_plans = [
            p for p in self._repository.list_plans(symbol=symbol, timeframe=timeframe.value, open_only=True)
        ]
        results = []
        for plan in open_plans:
            result = evaluate_plan(plan, snapshot, as_of)
            self._repository.save_plan(result.plan)
            for t in result.transitions:
                self._repository.record_transition(t)
            if result.evaluated_conditions:
                self._repository.record_condition_evaluations(
                    plan.decision_plan_id, result.evaluated_conditions
                )
            if result.evidence_diff is not None:
                self._repository.record_evidence_diff(result.evidence_diff)
            results.append(result)
        return results

    async def start(self) -> None:
        self._queue = self._recompute_engine.add_listener()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        if self._queue is not None:
            self._recompute_engine.remove_listener(self._queue)

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            self.evaluate_open_plans_for(event.symbol, event.timeframe, event.refreshed_at)
