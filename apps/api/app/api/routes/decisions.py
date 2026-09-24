"""Phase 13: Trader Decision Engine API. Thin orchestration only -- all
lifecycle logic lives in app.decision_engine (plan_builder/service/
ai_brief), same "no logic lives in a route" convention every other route
module in this codebase follows.

`POST /{symbol}/scan` is the only way a new DecisionPlan gets created: it
builds the canonical live snapshot, creates a plan for every qualified
setup that doesn't already have an open plan, evaluates every open plan for
the symbol/timeframe against the same fresh snapshot, and persists the
result -- deliberately synchronous/on-demand rather than only relying on
the background live-event subscription, so the Decision Monitor UI can
always force a fresh look.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai_analysis.market_snapshot import build_market_snapshot
from app.api.deps import get_market_data_provider
from app.api.routes.market import _validated_symbol, _validated_timeframe
from app.config import get_settings
from app.database.session import get_db
from app.decision_engine.ai_brief import (
    DecisionEvidencePacket,
    build_decision_evidence_packet,
    what_would_change_state,
    why_not_yet,
    why_now,
)
from app.decision_engine.fixtures import FIXTURE_SCENARIOS, run_fixture_scenario
from app.decision_engine.plan_builder import build_decision_plan
from app.decision_engine.repository import DecisionEngineRepository, SqlAlchemyDecisionEngineRepository
from app.decision_engine.schemas import TERMINAL_STATES, DecisionPlan, DecisionTransition
from app.decision_engine.service import evaluate_plan
from app.market_data.provider import MarketDataProvider

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


def _decision_repository(db: Session = Depends(get_db)) -> DecisionEngineRepository:
    return SqlAlchemyDecisionEngineRepository(db)


def _get_plan_or_404(decision_plan_id: str, repository: DecisionEngineRepository) -> DecisionPlan:
    plan = repository.get_plan(decision_plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"DecisionPlan {decision_plan_id!r} not found")
    return plan


@router.post("/_dev/fixtures/{scenario}/replay", response_model=DecisionPlan)
def replay_fixture_scenario(
    scenario: str, repository: DecisionEngineRepository = Depends(_decision_repository)
) -> DecisionPlan:
    """Dev/QA-only: drives one of the deterministic Phase 13.1 lifecycle
    fixtures (app.decision_engine.fixtures) through the REAL, unmodified
    evaluate_plan and persists every step, so the existing Decision Monitor
    UI can display the full WATCHING/ACTIVE_THESIS/STRENGTHENING/WEAKENING/
    INVALIDATED/EXIT_CONDITIONS_MET/EXPIRED lifecycle on demand -- without
    waiting for real market data to happen to produce every state, and
    without any engine or UI code changing to support it. Fixture symbols
    (ZFXA/ZFXB/ZFXC) can never collide with a real ticker. Declared before
    `/{decision_plan_id}` so it is never shadowed by that path.

    Gated on `settings.environment == "development"` (404, not 403 -- the
    route doesn't even acknowledge it exists outside dev) so this can never
    be reached in a production deployment and no fixture data can ever enter
    a production database."""
    if get_settings().environment != "development":
        raise HTTPException(status_code=404, detail="Not Found")
    if scenario not in FIXTURE_SCENARIOS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown fixture scenario {scenario!r}. Known: {sorted(FIXTURE_SCENARIOS)}",
        )
    history = run_fixture_scenario(scenario, repository)
    return history[-1]


@router.post("/{symbol}/scan", response_model=list[DecisionPlan])
def scan_symbol(
    symbol: str,
    timeframe: str = Query("1h"),
    market_provider: MarketDataProvider = Depends(get_market_data_provider),
    repository: DecisionEngineRepository = Depends(_decision_repository),
) -> list[DecisionPlan]:
    validated_symbol = _validated_symbol(symbol)
    validated_timeframe = _validated_timeframe(timeframe)
    as_of = datetime.now(timezone.utc)

    snapshot = build_market_snapshot(validated_symbol, validated_timeframe, market_provider, as_of, now=as_of)

    existing_setup_ids = {
        p.setup_id
        for p in repository.list_plans(
            symbol=validated_symbol, timeframe=validated_timeframe.value, limit=1000
        )
    }
    for setup in snapshot.setup_snapshot.qualified_setups:
        if setup.id in existing_setup_ids:
            continue
        plan = build_decision_plan(setup, as_of=as_of)
        repository.save_plan(plan)
        for transition in plan.transitions:
            repository.record_transition(transition)

    open_plans = repository.list_plans(
        symbol=validated_symbol, timeframe=validated_timeframe.value, open_only=True
    )
    for plan in open_plans:
        result = evaluate_plan(plan, snapshot, as_of)
        repository.save_plan(result.plan)
        for transition in result.transitions:
            repository.record_transition(transition)
        if result.evaluated_conditions:
            repository.record_condition_evaluations(plan.decision_plan_id, result.evaluated_conditions)
        if result.evidence_diff is not None:
            repository.record_evidence_diff(result.evidence_diff)

    return repository.list_plans(symbol=validated_symbol, timeframe=validated_timeframe.value, limit=1000)


@router.get("", response_model=list[DecisionPlan])
def list_decisions(
    symbol: str | None = Query(None),
    timeframe: str | None = Query(None),
    state: str | None = Query(None),
    open_only: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    repository: DecisionEngineRepository = Depends(_decision_repository),
) -> list[DecisionPlan]:
    return repository.list_plans(
        symbol=symbol, timeframe=timeframe, state=state, open_only=open_only, limit=limit
    )


@router.get("/{decision_plan_id}", response_model=DecisionPlan)
def get_decision(
    decision_plan_id: str, repository: DecisionEngineRepository = Depends(_decision_repository)
) -> DecisionPlan:
    return _get_plan_or_404(decision_plan_id, repository)


@router.get("/{decision_plan_id}/transitions", response_model=list[DecisionTransition])
def get_decision_transitions(
    decision_plan_id: str, repository: DecisionEngineRepository = Depends(_decision_repository)
) -> list[DecisionTransition]:
    _get_plan_or_404(decision_plan_id, repository)
    return repository.list_transitions(decision_plan_id)


@router.get("/{decision_plan_id}/evidence", response_model=DecisionEvidencePacket)
def get_decision_evidence(
    decision_plan_id: str, repository: DecisionEngineRepository = Depends(_decision_repository)
) -> DecisionEvidencePacket:
    plan = _get_plan_or_404(decision_plan_id, repository)
    return build_decision_evidence_packet(plan)


@router.get("/{decision_plan_id}/explanations")
def get_decision_explanations(
    decision_plan_id: str, repository: DecisionEngineRepository = Depends(_decision_repository)
) -> dict:
    plan = _get_plan_or_404(decision_plan_id, repository)
    packet = build_decision_evidence_packet(plan)
    return {
        "why_now": why_now(packet),
        "why_not_yet": why_not_yet(packet),
        "what_would_change_state": what_would_change_state(packet),
        "is_terminal": plan.state in TERMINAL_STATES,
    }
