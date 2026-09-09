"""Phase 11 (#A): builds the deterministic EvidencePacket by composing
already-computed Phase 1-10.1 engine outputs -- market data -> features ->
structure -> support/resistance -> setup detection (the exact same chain
`app.api.routes.market.get_setups` runs), plus historical research/analogs
(app.api.routes.research_intelligence / research_catalysts) and catalyst
context (app.news.setup_linking), all bound to one explicit `as_of`.

Anti-lookahead discipline: every engine call below already truncates its own
candles to `as_of` (app.features.common.truncate_to_as_of /
app.market_structure.common.truncate_to_as_of), so this module fetches a
generous, fixed-size candle window and lets those engines do the actual
point-in-time bounding -- the identical mechanism the live `/api/market/*`
routes already rely on, just with an explicit `as_of` instead of an implicit
`datetime.now()`. The catalyst/news and historical-research/analog sections
are separately as_of-bounded below (news fetches never look past `as_of`;
research runs are excluded unless their own `end_date <= as_of`). See
tests/unit/ai_analysis/test_evidence_packet_determinism.py for the proof
that a fixed `as_of` produces a byte-identical packet even after future
candles/news/research runs are added.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException

from app.ai_analysis.market_snapshot import build_market_snapshot
from app.ai_analysis.schemas import (
    EvidenceDataQuality,
    EvidenceMode,
    EvidencePacket,
    EvidenceProvenance,
    EvidenceSetupSection,
)
from app.api.routes.market import CANDLE_LIMIT_BY_TIMEFRAME
from app.api.routes.research_catalysts import (
    CatalystResearchQueryRequest,
    compute_catalyst_research_query_response,
)
from app.api.routes.research_intelligence import AnalogQueryRequest, compute_analog_query_response
from app.config import get_settings
from app.news.config import DEFAULT_CATALYST_CONFIG, CatalystConfig
from app.news.reaction import measure_market_reaction
from app.news.schemas import CatalystEvent, MarketReaction, SetupCatalystContext
from app.news.setup_linking import build_setup_catalyst_context
from app.research.repository import ResearchRepository
from app.schemas.market_data import Timeframe
from app.setup_detection.schemas import SetupCandidate, SetupDetectionSnapshot

if TYPE_CHECKING:
    from app.market_data.provider import MarketDataProvider
    from app.news.provider import NewsProvider
    from app.news.repository import NewsRepository

EVIDENCE_HORIZON_BARS = 5
EVIDENCE_ANALOG_TOP_N = 10
_MAX_RESEARCH_RUNS_SCANNED = 200


def _ensure_utc(value: datetime) -> datetime:
    """Same SQLite-naive-datetime-round-trip defense as
    app.news.repository._ensure_utc -- `ResearchRunRecord.end_date` is
    written UTC-aware but can come back naive from SQLite's
    `DateTime(timezone=True)` column."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class SetupNotFoundError(LookupError):
    def __init__(self, setup_id: str) -> None:
        super().__init__(f"Setup {setup_id!r} not found in the current detection snapshot")
        self.setup_id = setup_id


def _deterministic_packet_id(symbol: str, timeframe: str, as_of: datetime, setup_id: Optional[str]) -> str:
    """Same sha256-hex[:40] convention as app.news.normalization/events --
    two builds for the same (symbol, timeframe, as_of, setup) are the same
    packet, even if built minutes apart, matching the news layer's
    idempotency convention."""
    digest_source = f"{symbol}|{timeframe}|{as_of.isoformat()}|{setup_id or 'symbol-level'}"
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:40]


def _find_candidate(snapshot: SetupDetectionSnapshot, setup_id: str) -> Optional[SetupCandidate]:
    for pool in (
        snapshot.qualified_setups,
        snapshot.candidates,
        snapshot.rejected_candidates,
        snapshot.recently_invalidated,
        snapshot.recently_expired,
    ):
        for candidate in pool:
            if candidate.id == setup_id:
                return candidate
    return None


def _build_setup_section(candidate: SetupCandidate) -> EvidenceSetupSection:
    qualification_reasons = [c.label for c in candidate.hard_checks if c.passed]
    rejection_reasons = [c.label for c in candidate.hard_checks if not c.passed]
    near_miss_reasons = [c.label for c in candidate.soft_checks if not c.passed]
    conflict_reasons = [c.label for c in candidate.conflicts]
    return EvidenceSetupSection(
        candidate=candidate,
        qualified=candidate.current_state.value in ("qualified", "triggered"),
        qualification_reasons=qualification_reasons,
        rejection_reasons=rejection_reasons,
        near_miss_reasons=near_miss_reasons,
        conflict_reasons=conflict_reasons,
    )


def _matching_runs(
    research_repository: ResearchRepository, symbol: str, timeframe: str, as_of: datetime
) -> list:
    """Every persisted, completed research run for this exact symbol/
    timeframe whose own `end_date` is at or before `as_of` -- never a run
    whose replay window extends past the instant this packet claims to
    represent. Deliberately *not* a caller-supplied run_id list: a live
    "Analyze with AI" click has no Research Lab selection to draw on, so the
    packet uses everything persisted and records exactly which run_ids it
    used in `provenance` (auditable, per #J)."""
    runs = research_repository.list_runs(limit=_MAX_RESEARCH_RUNS_SCANNED)
    return [
        run
        for run in runs
        if run.symbol == symbol
        and run.timeframe == timeframe
        and run.status == "completed"
        and _ensure_utc(run.end_date) <= as_of
    ]


def _catalyst_context_and_event(
    candidate: Optional[SetupCandidate],
    symbol: str,
    timeframe: Timeframe,
    as_of: datetime,
    market_provider: "MarketDataProvider",
    news_provider: "NewsProvider",
    news_repository: "NewsRepository",
    config: CatalystConfig,
) -> tuple[Optional[SetupCatalystContext], Optional[CatalystEvent], list[str]]:
    """Mirrors app.api.routes.news.get_setup_catalyst_context's fetch/group/
    react orchestration exactly, except `as_of` is this function's own
    parameter rather than a hardcoded `datetime.now()` -- the only change
    needed to make it safe for a historical packet. `build_setup_catalyst_
    context` itself performs no fetching (see its docstring), so this is the
    caller-side as_of-filtering it requires."""
    limitations: list[str] = []
    detection_time = candidate.candidate_candle_timestamp if candidate else as_of
    lookback = timedelta(hours=config.catalyst_lookback_hours_for_setup_linking)
    lookahead = timedelta(hours=config.catalyst_lookahead_hours_for_setup_linking)
    start = detection_time - lookback
    end = min(detection_time + lookahead, as_of)

    fetched = news_provider.fetch_symbol_news(symbol, start, end, as_of)
    news_repository.upsert_articles(fetched)
    events = news_repository.events_for_symbol_as_of(symbol, start, end, as_of)
    news_repository.persist_events_snapshot(events)

    if not events:
        limitations.append(f"No catalyst news events found for {symbol} in the lookback window")

    reaction_by_event_id: dict[str, MarketReaction] = {}
    if events:
        candles = market_provider.get_candles(symbol, timeframe, limit=CANDLE_LIMIT_BY_TIMEFRAME[timeframe])
        for event in events:
            cached = news_repository.get_reaction(event.event_id, symbol, timeframe.value)
            if cached is not None:
                reaction_by_event_id[event.event_id] = cached
                continue
            reaction = measure_market_reaction(event, symbol, timeframe.value, candles, config)
            reaction_by_event_id[event.event_id] = reaction
            if reaction.evaluation_quality is not None and reaction.evaluation_quality.fully_evaluated:
                news_repository.upsert_reaction(reaction)

    if candidate is None:
        nearest_event = max(events, key=lambda e: e.primary_timestamp) if events else None
        return None, nearest_event, limitations

    context = build_setup_catalyst_context(candidate, events, reaction_by_event_id, config)
    nearest_event = None
    if context.nearest_catalyst is not None:
        nearest_event = next(
            (e for e in events if e.event_id == context.nearest_catalyst.event_id), None
        )
    return context, nearest_event, limitations


def build_evidence_packet(
    *,
    symbol: str,
    timeframe: Timeframe,
    market_provider: "MarketDataProvider",
    news_provider: "NewsProvider",
    news_repository: "NewsRepository",
    research_repository: ResearchRepository,
    setup_id: Optional[str] = None,
    as_of: Optional[datetime] = None,
    include_analogs: bool = True,
    include_catalyst: bool = True,
    catalyst_config: CatalystConfig = DEFAULT_CATALYST_CONFIG,
) -> EvidencePacket:
    # `mode` reflects caller intent, not clock proximity (#L): omitting
    # `as_of` means "give me the current state" (LIVE); passing one --
    # even a recent one -- means "give me exactly what was known at this
    # instant" (HISTORICAL_SNAPSHOT). The two are never blurred.
    mode = EvidenceMode.LIVE if as_of is None else EvidenceMode.HISTORICAL_SNAPSHOT
    resolved_as_of = as_of or datetime.now(timezone.utc)
    if resolved_as_of.tzinfo is None:
        resolved_as_of = resolved_as_of.replace(tzinfo=timezone.utc)

    missing_evidence: list[str] = []
    research_limitations: list[str] = []
    provider_limitations: list[str] = [
        "News provider coverage is not a guaranteed complete historical archive (ADR 0013).",
    ]

    market_snapshot = build_market_snapshot(symbol, timeframe, market_provider, resolved_as_of)
    feature_snapshot = market_snapshot.feature_snapshot
    structure_by_timeframe = market_snapshot.structure_by_timeframe
    levels_snapshot = market_snapshot.levels_snapshot
    setup_snapshot = market_snapshot.setup_snapshot

    if market_snapshot.market_data_cutoff is None or (
        mode == EvidenceMode.HISTORICAL_SNAPSHOT
        and setup_snapshot.data_quality.status.value == "unavailable"
    ):
        missing_evidence.append("market_data")
        research_limitations.append(
            f"Market data could not be reconstructed back to as_of={resolved_as_of.isoformat()} "
            "-- provider retention/history does not reach that far."
        )

    setup_section: Optional[EvidenceSetupSection] = None
    candidate: Optional[SetupCandidate] = None
    if setup_id is not None:
        candidate = _find_candidate(setup_snapshot, setup_id)
        if candidate is None:
            raise SetupNotFoundError(setup_id)
        setup_section = _build_setup_section(candidate)

    matching_runs = _matching_runs(research_repository, symbol, timeframe.value, resolved_as_of)
    run_ids = [run.id for run in matching_runs]
    research_snapshot_cutoff = (
        max(_ensure_utc(run.end_date) for run in matching_runs) if matching_runs else None
    )
    if not run_ids:
        research_limitations.append(
            f"No completed research runs persisted for {symbol}/{timeframe.value} at or before as_of"
        )
        missing_evidence.append("historical_research")

    historical_research = None
    if run_ids:
        research_request = CatalystResearchQueryRequest(
            run_ids=run_ids,
            setup_type=candidate.setup_type.value if candidate else None,
            direction=candidate.direction.value if candidate else None,
            horizon_bars=EVIDENCE_HORIZON_BARS,
        )
        try:
            historical_research = compute_catalyst_research_query_response(
                research_request, market_provider, news_provider, research_repository, news_repository
            )
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            missing_evidence.append("historical_research")
            research_limitations.append(str(exc.detail))

    historical_analogs = None
    if include_analogs and run_ids and candidate is not None:
        analog_request = AnalogQueryRequest(
            query_candidate=candidate,
            corpus_run_ids=run_ids,
            top_n=EVIDENCE_ANALOG_TOP_N,
            include_catalyst_context=include_catalyst,
        )
        historical_analogs = compute_analog_query_response(
            analog_request, market_provider, research_repository, news_provider, news_repository
        )
        if not historical_analogs.analogs:
            missing_evidence.append("historical_analogs")
    elif include_analogs:
        missing_evidence.append("historical_analogs")

    catalyst_context = None
    nearest_catalyst_event = None
    if include_catalyst:
        catalyst_context, nearest_catalyst_event, catalyst_limitations = _catalyst_context_and_event(
            candidate,
            symbol,
            timeframe,
            resolved_as_of,
            market_provider,
            news_provider,
            news_repository,
            catalyst_config,
        )
        research_limitations.extend(catalyst_limitations)
        if nearest_catalyst_event is None:
            missing_evidence.append("catalyst_context")

    data_quality = EvidenceDataQuality(
        missing_evidence=missing_evidence,
        stale_evidence=[],
        insufficient_history=not run_ids,
        provider_limitations=provider_limitations,
        research_limitations=research_limitations,
    )

    provenance = EvidenceProvenance(
        market_data_provider=get_settings().market_data_provider,
        news_provider=get_settings().news_provider,
        research_run_ids=run_ids,
        analog_corpus_run_ids=run_ids if historical_analogs is not None else [],
        generated_at=datetime.now(timezone.utc),
    )

    session_label = feature_snapshot.data_quality.latest_candle_session
    current_price = feature_snapshot.latest_candle.close

    return EvidencePacket(
        packet_id=_deterministic_packet_id(symbol, timeframe.value, resolved_as_of, setup_id),
        pipeline_version=market_snapshot.pipeline_version,
        mode=mode,
        as_of=resolved_as_of,
        generated_at=provenance.generated_at,
        symbol=symbol,
        timeframe=timeframe.value,
        session=session_label.value if session_label is not None else None,
        current_price=current_price,
        market_data_cutoff=market_snapshot.market_data_cutoff,
        news_cutoff=resolved_as_of if include_catalyst else None,
        research_snapshot_cutoff=research_snapshot_cutoff,
        setup=setup_section,
        structure=structure_by_timeframe[timeframe],
        multi_timeframe_structure={tf.value: snap for tf, snap in structure_by_timeframe.items()},
        support_resistance=levels_snapshot,
        features=feature_snapshot,
        historical_research=historical_research,
        historical_analogs=historical_analogs,
        catalyst_context=catalyst_context,
        nearest_catalyst_event=nearest_catalyst_event,
        data_quality=data_quality,
        provenance=provenance,
    )
