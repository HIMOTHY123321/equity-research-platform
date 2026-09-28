"""Phase 19 (Part 2): composes the Opportunity Intelligence read-model over
the SYSTEM RESEARCH UNIVERSE (app.monitoring.universe.MonitoringUniverse --
the exact same universe Phase 19's always-on streaming now subscribes to).
Deliberately cheap per symbol: an existing, already-persisted DecisionPlan
is read directly (no recomputation); only symbols with no open plan yet get
one lightweight `build_market_snapshot` call (structure + setup detection,
no catalyst/analog work -- see app.thesis.service for the expensive,
single-symbol composition that belongs on the Stock Thesis endpoint
instead, never here). This keeps a request over the whole universe bounded
regardless of universe size (Part 11).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from app.ai_analysis.market_snapshot import build_market_snapshot
from app.ai_analysis.schemas import RANKING_GATE_STATUS
from app.decision_engine.repository import DecisionEngineRepository
from app.decision_engine.schemas import DecisionPlan, DecisionState
from app.monitoring.universe import MonitoringUniverse
from app.schemas.market_data import Timeframe
from app.thesis.opportunity_schemas import (
    AttentionCategory,
    OpportunityCandidate,
    OpportunityListResponse,
)
from app.thesis.service import _history_sufficiency
from app.validation.gate import SIGNAL_GATE_VERSION
from app.validation.repository import SignalGateRepository

if TYPE_CHECKING:
    from app.market_data.provider import MarketDataProvider

_EXCLUDED_STATES = frozenset(
    {DecisionState.INVALIDATED, DecisionState.EXIT_CONDITIONS_MET, DecisionState.EXPIRED}
)

_PLAN_STATE_TO_CATEGORY = {
    DecisionState.DETECTED: AttentionCategory.WATCHING,
    DecisionState.EVALUATING: AttentionCategory.WATCHING,
    DecisionState.WATCHING: AttentionCategory.WATCHING,
    DecisionState.ENTRY_CONDITIONS_MET: AttentionCategory.ENTRY_CONDITIONS_MET,
    DecisionState.ACTIVE_THESIS: AttentionCategory.ACTIVE_THESIS,
    DecisionState.THESIS_STRENGTHENING: AttentionCategory.THESIS_STRENGTHENING,
    DecisionState.THESIS_WEAKENING: AttentionCategory.MIXED,
    DecisionState.ABSTAIN: AttentionCategory.ABSTAIN,
}

# Factual ordering (Part 2: "never labeled predictive ranking") -- purely a
# stable, documented tiebreaker for the `sort=state` view, describing how
# far along the Decision Engine's own lifecycle a symbol is, never an
# implied "better than" ranking.
_CATEGORY_ORDER = {
    AttentionCategory.ENTRY_CONDITIONS_MET: 0,
    AttentionCategory.ACTIVE_THESIS: 1,
    AttentionCategory.THESIS_STRENGTHENING: 2,
    AttentionCategory.NEAR_SETUP: 3,
    AttentionCategory.WATCHING: 4,
    AttentionCategory.MIXED: 5,
    AttentionCategory.ABSTAIN: 6,
    AttentionCategory.INSUFFICIENT_DATA: 7,
}


def _latest_open_plan_by_symbol(
    decision_repository: DecisionEngineRepository, timeframe: Timeframe
) -> dict[str, DecisionPlan]:
    plans = decision_repository.list_plans(timeframe=timeframe.value, limit=1000)
    latest: dict[str, DecisionPlan] = {}
    for plan in plans:
        if plan.state in _EXCLUDED_STATES:
            continue
        current = latest.get(plan.symbol)
        if current is None or plan.as_of > current.as_of:
            latest[plan.symbol] = plan
    return latest


def _why_for_plan(plan: DecisionPlan, category: AttentionCategory) -> str:
    label = category.value.replace("_", " ").upper()
    if plan.research_status:
        statuses = ", ".join(s.value.replace("_", " ") for s in plan.research_status)
        return f"{label}: {plan.setup_type.value} {plan.direction.value} setup ({statuses})."
    return f"{label}: {plan.setup_type.value} {plan.direction.value} setup."


def _candidate_from_plan(plan: DecisionPlan, signal_decision: str) -> OpportunityCandidate:
    category = _PLAN_STATE_TO_CATEGORY.get(plan.state, AttentionCategory.WATCHING)
    return OpportunityCandidate(
        symbol=plan.symbol,
        as_of=plan.as_of,
        timeframe=plan.timeframe,
        category=category,
        decision_state=plan.state,
        why=_why_for_plan(plan, category),
        setup_type=plan.setup_type,
        direction=plan.direction,
        structure_trend=None,
        contradictions_present=plan.state == DecisionState.THESIS_WEAKENING,
        signal_validation_decision=signal_decision,
        ranking_gate_status=plan.ranking_gate_status,
        market_data_provider="",
        history_sufficiency=None,  # filled in by caller once market_data_provider is known
        decision_plan_id=plan.decision_plan_id,
    )


def _candidate_from_snapshot(
    symbol: str,
    timeframe: Timeframe,
    market_provider: "MarketDataProvider",
    resolved_as_of: datetime,
    signal_decision: str,
    provider_name: str,
) -> OpportunityCandidate:
    market_snapshot = build_market_snapshot(symbol, timeframe, market_provider, resolved_as_of)
    setup_snapshot = market_snapshot.setup_snapshot
    structure = market_snapshot.structure_by_timeframe.get(timeframe)
    trend = structure.trend.trend if structure is not None else None
    history_sufficiency, _reason = _history_sufficiency(setup_snapshot, timeframe)

    if setup_snapshot.qualified_setups:
        candidate = setup_snapshot.qualified_setups[0]
        category = AttentionCategory.NEAR_SETUP
        why = (
            f"NEAR SETUP: a qualified {candidate.setup_type.value} {candidate.direction.value} setup "
            "exists but no DecisionPlan has been created for it yet."
        )
        return OpportunityCandidate(
            symbol=symbol,
            as_of=resolved_as_of,
            timeframe=timeframe,
            category=category,
            why=why,
            setup_type=candidate.setup_type,
            direction=candidate.direction,
            structure_trend=trend,
            signal_validation_decision=signal_decision,
            ranking_gate_status=RANKING_GATE_STATUS.lower(),
            market_data_provider=provider_name,
            history_sufficiency=history_sufficiency,
        )

    near_misses = list(setup_snapshot.candidates)
    if near_misses:
        candidate = near_misses[0]
        why = (
            f"NEAR SETUP: a {candidate.setup_type.value} {candidate.direction.value} candidate "
            "is being evaluated but has not qualified."
        )
        return OpportunityCandidate(
            symbol=symbol,
            as_of=resolved_as_of,
            timeframe=timeframe,
            category=AttentionCategory.NEAR_SETUP,
            why=why,
            setup_type=candidate.setup_type,
            direction=candidate.direction,
            structure_trend=trend,
            signal_validation_decision=signal_decision,
            ranking_gate_status=RANKING_GATE_STATUS.lower(),
            market_data_provider=provider_name,
            history_sufficiency=history_sufficiency,
        )

    if setup_snapshot.data_quality.status.value == "unavailable":
        return OpportunityCandidate(
            symbol=symbol,
            as_of=resolved_as_of,
            timeframe=timeframe,
            category=AttentionCategory.INSUFFICIENT_DATA,
            why="INSUFFICIENT DATA: not enough market history to detect a setup for this symbol/timeframe.",
            structure_trend=trend,
            signal_validation_decision=signal_decision,
            ranking_gate_status=RANKING_GATE_STATUS.lower(),
            market_data_provider=provider_name,
            history_sufficiency=history_sufficiency,
        )

    return OpportunityCandidate(
        symbol=symbol,
        as_of=resolved_as_of,
        timeframe=timeframe,
        category=AttentionCategory.WATCHING,
        why="WATCHING: no qualified or near-miss setup detected yet.",
        structure_trend=trend,
        signal_validation_decision=signal_decision,
        ranking_gate_status=RANKING_GATE_STATUS.lower(),
        market_data_provider=provider_name,
        history_sufficiency=history_sufficiency,
    )


def build_opportunities(
    *,
    timeframe: Timeframe,
    market_provider: "MarketDataProvider",
    universe: MonitoringUniverse,
    decision_repository: DecisionEngineRepository,
    gate_repository: SignalGateRepository,
    provider_name: str,
    category: Optional[AttentionCategory] = None,
    setup_type: Optional[str] = None,
    sort: str = "state",
    as_of: Optional[datetime] = None,
) -> OpportunityListResponse:
    resolved_as_of = as_of or datetime.now(timezone.utc)
    if resolved_as_of.tzinfo is None:
        resolved_as_of = resolved_as_of.replace(tzinfo=timezone.utc)

    gate_payload = gate_repository.get_latest_gate_result(gate_version=SIGNAL_GATE_VERSION)
    signal_decision = gate_payload.get("decision", "not_enough_data") if gate_payload else "not_enough_data"

    symbols = universe.list_enabled_symbols()
    plans_by_symbol = _latest_open_plan_by_symbol(decision_repository, timeframe)

    candidates: list[OpportunityCandidate] = []
    for symbol in symbols:
        plan = plans_by_symbol.get(symbol)
        if plan is not None:
            candidate = _candidate_from_plan(plan, signal_decision)
            candidate = candidate.model_copy(update={"market_data_provider": provider_name})
        else:
            try:
                candidate = _candidate_from_snapshot(
                    symbol, timeframe, market_provider, resolved_as_of, signal_decision, provider_name
                )
            except Exception:  # noqa: BLE001 -- one bad symbol must not break the whole list (§ scan_once precedent)
                continue
        candidates.append(candidate)

    if category is not None:
        candidates = [c for c in candidates if c.category == category]
    if setup_type is not None:
        candidates = [c for c in candidates if c.setup_type is not None and c.setup_type.value == setup_type]

    if sort == "symbol":
        candidates.sort(key=lambda c: c.symbol)
    elif sort == "recency":
        candidates.sort(key=lambda c: c.as_of, reverse=True)
    else:
        candidates.sort(key=lambda c: (_CATEGORY_ORDER.get(c.category, 99), c.symbol))

    ranking_message = "VALIDATED RELATIVE RANKING: UNAVAILABLE"

    return OpportunityListResponse(
        as_of=resolved_as_of,
        timeframe=timeframe,
        candidates=candidates,
        ranking_validation_message=ranking_message,
    )
