"""Phase 19 (Part 3): composes the StockThesis read-model entirely from
already-computed, already-tested engine outputs -- app.ai_analysis.
market_snapshot (structure/levels/setups), app.ai_analysis.evidence_packet
(catalyst/analog/research composition, the identical pipeline "Analyze with
AI" already uses), app.decision_engine.repository (the live DecisionPlan),
and app.validation.repository (the last PERSISTED Signal Validation Gate
result -- deliberately not recomputed per request, since that gate is a
global, cross-symbol evaluation, not something a single thesis request
should trigger; see _signal_validation below).

Nothing here invents a number, a probability, or a BUY/SELL label. Every
list on StockThesis traces back to a concrete field on an already-frozen
schema -- see each helper's docstring for exactly which one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from app.ai_analysis.evidence_packet import build_evidence_packet
from app.ai_analysis.market_snapshot import MarketSnapshot, build_market_snapshot
from app.api.routes.market import CANDLE_LIMIT_BY_TIMEFRAME
from app.decision_engine.repository import DecisionEngineRepository
from app.decision_engine.schemas import ConditionRole, ConditionStatus, DecisionPlan, DecisionState
from app.market_structure.engine import compute_market_structure_snapshot
from app.news.config import DEFAULT_CATALYST_CONFIG
from app.schemas.market_data import Timeframe
from app.setup_detection.qualification import failed_hard_checks
from app.setup_detection.schemas import SetupCandidate, SetupDetectionSnapshot
from app.support_resistance.schemas import SupportResistanceSnapshot
from app.thesis.schemas import (
    HistorySufficiency,
    KeyLevelSummary,
    ResearchLean,
    SignalValidationSummary,
    StockThesis,
    TimeframeTrendSummary,
)
from app.validation.gate import SIGNAL_GATE_VERSION
from app.validation.repository import SignalGateRepository

if TYPE_CHECKING:
    from app.market_data.provider import MarketDataProvider
    from app.news.provider import NewsProvider
    from app.news.repository import NewsRepository
    from app.research.repository import ResearchRepository

# Part 3: "multi-timeframe trend (15m/1H/4H/1D minimum)". build_market_
# snapshot only computes structure for {ONE_DAY, FOUR_HOUR} union the
# requested timeframe (app.api.routes.market.LEVEL_SOURCE_TIMEFRAMES) -- any
# of these four not already covered is fetched once, directly, below.
_MULTI_TIMEFRAME_MINIMUM = (
    Timeframe.FIFTEEN_MIN,
    Timeframe.ONE_HOUR,
    Timeframe.FOUR_HOUR,
    Timeframe.ONE_DAY,
)

_MAX_NEAR_MISSES = 5
_MAX_KEY_LEVELS_PER_SIDE = 3


def _multi_timeframe_trend(
    symbol: str,
    market_snapshot: MarketSnapshot,
    market_provider: "MarketDataProvider",
    resolved_as_of: datetime,
) -> list[TimeframeTrendSummary]:
    rows: list[TimeframeTrendSummary] = []
    for tf in _MULTI_TIMEFRAME_MINIMUM:
        snapshot = market_snapshot.structure_by_timeframe.get(tf)
        if snapshot is None:
            candles = market_provider.get_candles(symbol, tf, limit=CANDLE_LIMIT_BY_TIMEFRAME[tf])
            snapshot = compute_market_structure_snapshot(symbol, tf, candles, resolved_as_of)
        rows.append(
            TimeframeTrendSummary(
                timeframe=tf,
                trend=snapshot.trend.trend,
                strength=snapshot.trend.strength,
                explanation=snapshot.trend.evidence,
                candle_count=snapshot.data_quality.candle_count,
            )
        )
    return rows


def _key_levels(levels_snapshot: SupportResistanceSnapshot) -> list[KeyLevelSummary]:
    """(Part 6) Nearest support/resistance first, then the next-strongest
    active zones on each side, each carrying its own real confluence
    provenance -- never a freshly invented strength number."""
    rows: list[KeyLevelSummary] = []
    nearest_ids = set()
    for zone in (levels_snapshot.nearest_support, levels_snapshot.nearest_resistance):
        if zone is None:
            continue
        nearest_ids.add(zone.id)
        rows.append(
            KeyLevelSummary(
                kind=zone.kind,
                price=zone.representative_price,
                is_nearest=True,
                source_count=zone.confluence.source_count,
                timeframe_count=zone.confluence.timeframe_count,
                timeframes=zone.confluence.timeframes,
            )
        )
    for pool in (levels_snapshot.active_support_zones, levels_snapshot.active_resistance_zones):
        ranked = sorted((z for z in pool if z.id not in nearest_ids), key=lambda z: -z.strength.total)
        for zone in ranked[:_MAX_KEY_LEVELS_PER_SIDE]:
            rows.append(
                KeyLevelSummary(
                    kind=zone.kind,
                    price=zone.representative_price,
                    is_nearest=False,
                    source_count=zone.confluence.source_count,
                    timeframe_count=zone.confluence.timeframe_count,
                    timeframes=zone.confluence.timeframes,
                )
            )
    return rows


def _near_misses(setup_snapshot: SetupDetectionSnapshot) -> list[SetupCandidate]:
    """A near miss is a non-qualified candidate that failed at most one hard
    requirement -- reuses SetupCandidate.hard_checks verbatim (Phase 6),
    never a separately invented "closeness" score."""
    qualified_ids = {c.id for c in setup_snapshot.qualified_setups}
    near: list[SetupCandidate] = []
    for candidate in setup_snapshot.candidates:
        if candidate.id in qualified_ids:
            continue
        if len(failed_hard_checks(candidate.hard_checks)) <= 1:
            near.append(candidate)
    return near[:_MAX_NEAR_MISSES]


def _select_setup_id(
    decision_plan: Optional[DecisionPlan], setup_snapshot: SetupDetectionSnapshot
) -> Optional[str]:
    if decision_plan is not None:
        return decision_plan.setup_id
    if setup_snapshot.qualified_setups:
        return setup_snapshot.qualified_setups[0].id
    return None


def _history_sufficiency(
    setup_snapshot: SetupDetectionSnapshot, timeframe: Timeframe
) -> tuple[HistorySufficiency, str]:
    """(Part 5) Deterministic thresholds over the genuine candle_count the
    detection engine actually consumed -- never a days-since-IPO estimate
    (no such concept exists anywhere in this codebase; see the Phase 19
    implementation-map investigation). `full_limit` is the same trailing
    context CANDLE_LIMIT_BY_TIMEFRAME already defines as "what every engine
    wants" for this timeframe."""
    quality = setup_snapshot.data_quality
    count = quality.candles_consumed
    full_limit = CANDLE_LIMIT_BY_TIMEFRAME[timeframe]
    if quality.status.value == "unavailable" or count == 0:
        return (
            HistorySufficiency.INSUFFICIENT,
            "No usable market data could be reconstructed for this symbol/timeframe.",
        )
    if count < 30:
        return (
            HistorySufficiency.VERY_LIMITED,
            f"Only {count} candles of history are available -- LIMITED TRADING HISTORY. "
            "Structure/setup/analog evidence built from this window should be treated with caution.",
        )
    if count < 100:
        return (
            HistorySufficiency.LIMITED,
            f"Only {count} candles of history are available for this timeframe.",
        )
    if count < full_limit:
        return (
            HistorySufficiency.ADEQUATE,
            f"{count} of {full_limit} candles of standard trailing context are available.",
        )
    return (
        HistorySufficiency.FULL,
        f"{count} candles of history are available, the full trailing context this timeframe uses.",
    )


def _signal_validation(gate_repository: SignalGateRepository) -> SignalValidationSummary:
    """(Part 13) Reads the last PERSISTED gate evaluation -- never
    recomputed per thesis request. The gate is a global, cross-symbol
    statistical evaluation (app.validation.gate); re-running it on every
    `/thesis` request would be both wasteful (Part 11: no endpoint should
    blindly execute an expensive calculation on every render) and
    misleading (it would imply the gate is somehow specific to the symbol
    being viewed, when concentration limits mean it can never validly PASS
    from a single symbol's evidence alone)."""
    payload = gate_repository.get_latest_gate_result(gate_version=SIGNAL_GATE_VERSION)
    if payload is None:
        return SignalValidationSummary(
            gate_version=SIGNAL_GATE_VERSION,
            decision="not_enough_data",
            reasons=["The Signal Validation Gate has not been evaluated yet."],
        )
    return SignalValidationSummary(
        gate_version=payload.get("gate_version", SIGNAL_GATE_VERSION),
        decision=payload.get("decision", "not_enough_data"),
        reasons=list(payload.get("reasons", [])),
    )


def _bull_bear_and_contradictions(
    setup_section, multi_timeframe_trend: list[TimeframeTrendSummary]
) -> tuple[list[str], list[str], list[str]]:
    """Bull case / bear case / contradictions, built only from real
    deterministic factors already produced elsewhere (Part 3): the bound
    setup's own qualification/rejection/near-miss/conflict reasons
    (app.ai_analysis.schemas.EvidenceSetupSection, itself a verbatim
    reuse of SetupCandidate.hard_checks/soft_checks/conflicts), plus one
    cross-timeframe disagreement check over the already-computed trend
    rows. Never a fabricated count, never hidden."""
    evidence_for: list[str] = []
    evidence_against: list[str] = []
    contradictions: list[str] = []

    if setup_section is not None:
        evidence_for.extend(setup_section.qualification_reasons)
        evidence_against.extend(setup_section.rejection_reasons)
        evidence_against.extend(setup_section.near_miss_reasons)
        contradictions.extend(setup_section.conflict_reasons)

    directional = [row for row in multi_timeframe_trend if row.trend.value in ("bullish", "bearish")]
    bullish_tfs = [row.timeframe.value for row in directional if row.trend.value == "bullish"]
    bearish_tfs = [row.timeframe.value for row in directional if row.trend.value == "bearish"]
    if bullish_tfs:
        evidence_for.append(f"Bullish structure on: {', '.join(bullish_tfs)}")
    if bearish_tfs:
        evidence_against.append(f"Bearish structure on: {', '.join(bearish_tfs)}")
    if bullish_tfs and bearish_tfs:
        contradictions.append(
            f"Structure disagrees across timeframes -- bullish on {', '.join(bullish_tfs)}, "
            f"bearish on {', '.join(bearish_tfs)}."
        )

    return evidence_for, evidence_against, contradictions


def _research_lean(
    decision_plan: Optional[DecisionPlan],
    setup_section,
    evidence_for: list[str],
    evidence_against: list[str],
    contradictions: list[str],
) -> tuple[ResearchLean, list[str]]:
    """(Part 3) Deterministic, conservative-by-default. Never a numeric
    score, never LLM-derived. Order of checks matters: an ABSTAIN
    DecisionPlan always wins (the Decision Engine already made that call
    with more context than this function has); otherwise no evidence at
    all is INSUFFICIENT_EVIDENCE before anything else is considered."""
    if decision_plan is not None and decision_plan.state == DecisionState.ABSTAIN:
        reason = (
            "The current DecisionPlan is ABSTAIN"
            + (f" ({decision_plan.abstention_reason.value})." if decision_plan.abstention_reason else ".")
        )
        return ResearchLean.ABSTAIN, [reason]

    if not evidence_for and not evidence_against:
        return ResearchLean.INSUFFICIENT_EVIDENCE, [
            "No qualified setup, rejected candidate, or directional structure evidence is available."
        ]

    if contradictions:
        return ResearchLean.MIXED, [
            "Contradicting evidence is present (see Contradictions) -- a directional lean is not justified."
        ]

    if evidence_for and not evidence_against:
        direction = setup_section.candidate.direction.value if setup_section is not None else None
        if direction == "bullish" or (direction is None and any("Bullish" in e for e in evidence_for)):
            return ResearchLean.BULLISH_LEAN, list(evidence_for)
        if direction == "bearish":
            return ResearchLean.BEARISH_LEAN, list(evidence_for)
        return ResearchLean.MIXED, ["Directional evidence exists but does not resolve to one clear side."]

    if evidence_against and not evidence_for:
        direction = setup_section.candidate.direction.value if setup_section is not None else None
        if direction == "bearish" or (direction is None and any("Bearish" in e for e in evidence_against)):
            return ResearchLean.BEARISH_LEAN, list(evidence_against)
        return ResearchLean.MIXED, ["Directional evidence exists but does not resolve to one clear side."]

    return ResearchLean.MIXED, ["Both supporting and opposing evidence are present."]


def _strengthen_weaken_invalidation(
    decision_plan: Optional[DecisionPlan], setup_section
) -> tuple[list[str], list[str], list[str]]:
    """(Part 3) Reuses frozen DecisionPlan condition descriptions verbatim
    -- never displays a future condition as already known before
    confirmation, since these are exactly the conditions the plan itself
    was built with and their `status` reflects only what has already been
    evaluated. Falls back to the bound setup candidate's own deterministic
    `invalidation_criteria` when no DecisionPlan exists yet."""
    if decision_plan is None:
        invalidation = (
            list(setup_section.candidate.invalidation_criteria) if setup_section is not None else []
        )
        return [], [], invalidation

    strengthens = [
        c.description
        for c in decision_plan.monitoring_conditions
        if c.role == ConditionRole.MONITORING and c.status != ConditionStatus.PASSED
    ]
    weakens = [
        c.description
        for c in decision_plan.exit_conditions
        if c.role == ConditionRole.EXIT and c.status != ConditionStatus.PASSED
    ]
    invalidation = [c.description for c in decision_plan.invalidation_conditions]
    return strengthens, weakens, invalidation


def build_stock_thesis(
    *,
    symbol: str,
    timeframe: Timeframe,
    market_provider: "MarketDataProvider",
    news_provider: "NewsProvider",
    news_repository: "NewsRepository",
    research_repository: "ResearchRepository",
    decision_repository: DecisionEngineRepository,
    gate_repository: SignalGateRepository,
    as_of: Optional[datetime] = None,
) -> StockThesis:
    resolved_as_of = as_of or datetime.now(timezone.utc)
    if resolved_as_of.tzinfo is None:
        resolved_as_of = resolved_as_of.replace(tzinfo=timezone.utc)

    market_snapshot = build_market_snapshot(symbol, timeframe, market_provider, resolved_as_of)
    setup_snapshot = market_snapshot.setup_snapshot
    levels_snapshot = market_snapshot.levels_snapshot
    feature_snapshot = market_snapshot.feature_snapshot

    open_plans = decision_repository.list_plans(
        symbol=symbol, timeframe=timeframe.value, open_only=True, limit=1
    )
    decision_plan = open_plans[0] if open_plans else None
    evidence_diffs = (
        decision_repository.list_evidence_diffs(decision_plan.decision_plan_id) if decision_plan else []
    )

    setup_id = _select_setup_id(decision_plan, setup_snapshot)
    evidence_packet = build_evidence_packet(
        symbol=symbol,
        timeframe=timeframe,
        market_provider=market_provider,
        news_provider=news_provider,
        news_repository=news_repository,
        research_repository=research_repository,
        setup_id=setup_id,
        as_of=resolved_as_of,
        include_analogs=True,
        include_catalyst=True,
        catalyst_config=DEFAULT_CATALYST_CONFIG,
    )

    multi_timeframe_trend = _multi_timeframe_trend(symbol, market_snapshot, market_provider, resolved_as_of)
    key_levels = _key_levels(levels_snapshot)
    near_misses = _near_misses(setup_snapshot)

    evidence_for, evidence_against, contradictions = _bull_bear_and_contradictions(
        evidence_packet.setup, multi_timeframe_trend
    )
    research_lean, research_lean_reasons = _research_lean(
        decision_plan, evidence_packet.setup, evidence_for, evidence_against, contradictions
    )
    strengthens_if, weakens_if, invalidation = _strengthen_weaken_invalidation(
        decision_plan, evidence_packet.setup
    )

    history_sufficiency, history_sufficiency_reason = _history_sufficiency(setup_snapshot, timeframe)
    signal_validation = _signal_validation(gate_repository)

    ranking_gate_status = (
        decision_plan.ranking_gate_status if decision_plan else evidence_packet.ranking_gate_status
    )
    ranking_validation_message = (
        "VALIDATED RELATIVE RANKING: UNAVAILABLE"
        if ranking_gate_status.lower() != "pass"
        else "Validated relative ranking is available for this symbol."
    )

    session_label = feature_snapshot.data_quality.latest_candle_session

    return StockThesis(
        symbol=symbol,
        timeframe=timeframe,
        as_of=resolved_as_of,
        generated_at=evidence_packet.generated_at,
        market_data_provider=evidence_packet.provenance.market_data_provider,
        market_data_cutoff=evidence_packet.market_data_cutoff,
        current_price=evidence_packet.current_price,
        session=session_label.value if session_label is not None else None,
        multi_timeframe_trend=multi_timeframe_trend,
        key_levels=key_levels,
        decision_plan=decision_plan,
        evidence_diffs=evidence_diffs,
        active_setups=setup_snapshot.qualified_setups,
        near_misses=near_misses,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        contradictions=contradictions,
        catalyst_context=evidence_packet.catalyst_context,
        nearest_catalyst_event=evidence_packet.nearest_catalyst_event,
        historical_analogs=evidence_packet.historical_analogs,
        signal_validation=signal_validation,
        ranking_gate_status=ranking_gate_status,
        ranking_validation_message=ranking_validation_message,
        history_sufficiency=history_sufficiency,
        history_sufficiency_reason=history_sufficiency_reason,
        research_lean=research_lean,
        research_lean_reasons=research_lean_reasons,
        strengthens_if=strengthens_if,
        weakens_if=weakens_if,
        invalidation=invalidation,
        data_limitations=evidence_packet.data_quality.research_limitations
        + evidence_packet.data_quality.provider_limitations,
    )
