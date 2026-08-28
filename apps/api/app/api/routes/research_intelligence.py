"""Phase 8 API surface: multi-symbol universe replay, the consolidated
research query (evidence card + decay + excursion + stability +
concentration + contradictions + overlap), historical analogs, and research
snapshots. Built entirely on top of Phase 7's existing `execute_research_run`
/ `SqlAlchemyResearchRepository` -- no parallel persistence or detection
logic, only new read-side computation over already-persisted ledger
entries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_market_data_provider
from app.config import get_settings
from app.database.session import get_db
from app.market_data.candle_cache import SqlAlchemyCandleCacheRepository, fetch_candles_cached
from app.market_data.provider import MarketDataProvider
from app.research.config import DEFAULT_RESEARCH_CONFIG
from app.research.engine import execute_research_run
from app.research.repository import SqlAlchemyResearchRepository
from app.research.schemas import SetupLedgerEntry
from app.research.validation import InvalidReplayRangeError, validate_replay_range
from app.research_intelligence.analogs import (
    analog_diversity_report,
    attach_outcomes,
    detection_close_for,
    diverse_analogs,
    extract_features,
    rank_analogs,
)
from app.research_intelligence.concentration import detect_concentration
from app.research_intelligence.conclusion_stability import conclusion_stability
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.research_intelligence.contradictions import check_all_builtin_assumptions
from app.research_intelligence.decay import signal_decay_profile
from app.research_intelligence.dependence import detect_overlap
from app.research_intelligence.episodes import build_episodes, episode_by_setup_id
from app.research_intelligence.evidence_card import build_evidence_card
from app.research_intelligence.evidence_maturity import classify_evidence_maturity
from app.research_intelligence.excursions import excursion_profile, first_hit_analysis
from app.research_intelligence.independence import sample_composition
from app.research_intelligence.partitions import build_partition_plan, partition_for_timestamp
from app.research_intelligence.schemas import (
    AnalogDiversityReport,
    AnalogResult,
    ConclusionStabilityReport,
    ContradictionResult,
    CrossSymbolStabilityReport,
    ExcursionProfile,
    FirstHitResult,
    OverlapReport,
    ResearchEvidenceCard,
    ResearchSnapshot,
    SampleComposition,
    SampleConcentrationReport,
    SignalDecayProfile,
    SnapshotComparison,
    TemporalStabilityReport,
    WalkForwardReport,
)
from app.research_intelligence.snapshots import SqlAlchemySnapshotRepository, compare_snapshots
from app.research_intelligence.stability import cross_symbol_stability, temporal_stability
from app.research_intelligence.walk_forward import anchored_walk_forward
from app.schemas.market_data import Candle, Timeframe
from app.schemas.symbols import InvalidTickerError, normalize_ticker
from app.setup_detection.schemas import SetupCandidate

router = APIRouter(prefix="/api/research", tags=["research-intelligence"])

_FETCH_LIMIT = 50_000
_FORWARD_HORIZONS = DEFAULT_RESEARCH_CONFIG.forward_horizons


def _repository(db: Session = Depends(get_db)) -> SqlAlchemyResearchRepository:
    return SqlAlchemyResearchRepository(db)


def _snapshot_repository(db: Session = Depends(get_db)) -> SqlAlchemySnapshotRepository:
    return SqlAlchemySnapshotRepository(db)


def _candle_cache_repository(db: Session = Depends(get_db)) -> SqlAlchemyCandleCacheRepository:
    return SqlAlchemyCandleCacheRepository(db)


# ---- Universe replay -------------------------------------------------------


class UniverseReplayRequest(BaseModel):
    symbols: list[str]
    timeframe: str = "1h"
    start: datetime
    end: datetime


class UniverseReplayResponse(BaseModel):
    run_ids: dict[str, str]
    failures: dict[str, str]


@router.post("/universe-replay", response_model=UniverseReplayResponse)
def run_universe_replay(
    body: UniverseReplayRequest,
    provider: MarketDataProvider = Depends(get_market_data_provider),
    repository: SqlAlchemyResearchRepository = Depends(_repository),
    candle_cache: SqlAlchemyCandleCacheRepository = Depends(_candle_cache_repository),
) -> UniverseReplayResponse:
    """Runs Phase 7's single-symbol replay once per symbol in the universe
    -- never a parallel multi-symbol detection pipeline. Cross-symbol
    research (#22/#23) pools the resulting ledger entries afterward, at
    query time, rather than requiring a new detection concept."""
    try:
        timeframe = Timeframe(body.timeframe)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {body.timeframe!r}") from None

    start = body.start if body.start.tzinfo else body.start.replace(tzinfo=timezone.utc)
    end = body.end if body.end.tzinfo else body.end.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    provider_name = get_settings().market_data_provider.lower()

    run_ids: dict[str, str] = {}
    failures: dict[str, str] = {}
    for raw_symbol in body.symbols:
        try:
            symbol = normalize_ticker(raw_symbol)
            validate_replay_range(provider_name, timeframe.value, start, end, now)

            primary_candles = fetch_candles_cached(
                provider, candle_cache, provider_name, symbol, timeframe, start, end, _FETCH_LIMIT
            )
            daily_candles = (
                primary_candles
                if timeframe == Timeframe.ONE_DAY
                else fetch_candles_cached(
                    provider, candle_cache, provider_name, symbol, Timeframe.ONE_DAY, start, end, _FETCH_LIMIT
                )
            )
            four_hour_candles = (
                primary_candles
                if timeframe == Timeframe.FOUR_HOUR
                else fetch_candles_cached(
                    provider,
                    candle_cache,
                    provider_name,
                    symbol,
                    Timeframe.FOUR_HOUR,
                    start,
                    end,
                    _FETCH_LIMIT,
                )
            )
            run_ids[symbol] = execute_research_run(
                symbol=symbol,
                timeframe=timeframe,
                start_date=start,
                end_date=end,
                primary_candles=primary_candles,
                daily_candles=daily_candles,
                four_hour_candles=four_hour_candles,
                provider_name=provider_name,
                repository=repository,
            )
        except (InvalidTickerError, InvalidReplayRangeError) as exc:
            failures[raw_symbol] = str(exc)
        except Exception as exc:  # noqa: BLE001 -- one symbol's failure must not abort the whole universe
            failures[raw_symbol] = f"Replay failed: {exc}"

    return UniverseReplayResponse(run_ids=run_ids, failures=failures)


# ---- Consolidated research query -------------------------------------------


class ResearchQueryRequest(BaseModel):
    run_ids: list[str]
    setup_type: Optional[str] = None
    direction: Optional[str] = None
    qualification_state: Optional[str] = None
    horizon_bars: int = 5
    seed: int = 0
    partition_ratios: bool = True
    favorable_atr: Optional[float] = None
    adverse_atr: Optional[float] = None


class IndependenceSection(BaseModel):
    """(Phase 9 #25) Independence-adjusted view of the same query result --
    computed alongside, never in place of, everything above. `conclusion_stability`
    is only populated when the setup_type/direction-filtered pool (ignoring
    `qualification_state`) actually contains both a qualified and a rejected
    member to compare."""

    sample_composition: SampleComposition
    walk_forward: WalkForwardReport
    evidence_maturity: str
    evidence_maturity_basis: str
    conclusion_stability: Optional[ConclusionStabilityReport] = None


class ResearchQueryResponse(BaseModel):
    sample_count: int
    evidence_card: ResearchEvidenceCard
    signal_decay: SignalDecayProfile
    excursions: ExcursionProfile
    first_hit: Optional[FirstHitResult] = None
    temporal_stability: TemporalStabilityReport
    cross_symbol_stability: CrossSymbolStabilityReport
    concentration: SampleConcentrationReport
    overlap: OverlapReport
    contradictions: list[ContradictionResult]
    independence: IndependenceSection


def _pooled_entries(run_ids: list[str], repository: SqlAlchemyResearchRepository) -> list[SetupLedgerEntry]:
    entries: list[SetupLedgerEntry] = []
    for run_id in run_ids:
        if repository.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"Research run {run_id!r} not found")
        entries.extend(repository.list_ledger_entries(run_id, limit=10_000))
    return entries


def _apply_filters(entries: list[SetupLedgerEntry], body: ResearchQueryRequest) -> list[SetupLedgerEntry]:
    filtered = entries
    if body.setup_type is not None:
        filtered = [e for e in filtered if e.setup_type == body.setup_type]
    if body.direction is not None:
        filtered = [e for e in filtered if e.direction == body.direction]
    if body.qualification_state is not None:
        filtered = [e for e in filtered if e.detection.current_state == body.qualification_state]
    return filtered


@router.post("/query", response_model=ResearchQueryResponse)
def research_query(
    body: ResearchQueryRequest,
    provider: MarketDataProvider = Depends(get_market_data_provider),
    repository: SqlAlchemyResearchRepository = Depends(_repository),
) -> ResearchQueryResponse:
    raw_pool = _pooled_entries(body.run_ids, repository)
    entries = _apply_filters(raw_pool, body)
    if not entries:
        raise HTTPException(status_code=404, detail="No ledger entries matched the requested run(s)/filters")

    timeframe = Timeframe(entries[0].timeframe)
    config = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG

    partition_by_setup_id = None
    if body.partition_ratios:
        timestamps = sorted(e.candidate_candle_timestamp for e in entries)
        plan = build_partition_plan(entries[0].symbol, entries[0].timeframe, timestamps, config)
        partition_by_setup_id = {
            e.setup_id: partition_for_timestamp(plan, e.candidate_candle_timestamp) for e in entries
        }

    evidence_card = build_evidence_card(
        body.setup_type or "all",
        entries,
        body.horizon_bars,
        timeframe,
        direction=body.direction,
        partition_by_setup_id=partition_by_setup_id,
        seed=body.seed,
    )
    decay = signal_decay_profile(entries, _FORWARD_HORIZONS, seed=body.seed, config=config)
    excursions = excursion_profile(entries)

    first_hit = None
    if body.favorable_atr is not None or body.adverse_atr is not None:
        symbols = {e.symbol for e in entries}
        candles_by_symbol = {s: provider.get_candles(s, timeframe, limit=_FETCH_LIMIT) for s in symbols}
        first_hit = first_hit_analysis(
            entries, candles_by_symbol, body.favorable_atr, body.adverse_atr, config=config
        )

    episodes = build_episodes(entries)
    walk_forward = anchored_walk_forward(
        entries,
        body.horizon_bars,
        finding_label=f"{body.setup_type or 'all'} {body.direction or ''}".strip(),
    )
    maturity, maturity_basis = classify_evidence_maturity(evidence_card, config=config)

    stability_comparison = None
    setup_type_direction_pool = [
        e
        for e in raw_pool
        if (body.setup_type is None or e.setup_type == body.setup_type)
        and (body.direction is None or e.direction == body.direction)
    ]
    qualified = [e for e in setup_type_direction_pool if e.detection.current_state == "qualified"]
    rejected = [e for e in setup_type_direction_pool if e.detection.current_state == "rejected"]
    if qualified and rejected:
        stability_comparison = conclusion_stability(
            qualified,
            rejected,
            group_a_label="qualified",
            group_b_label="rejected",
            finding_label=f"{body.setup_type or 'all'} qualified vs rejected",
            horizon_bars=body.horizon_bars,
            timeframe=timeframe,
            seed=body.seed,
            config=config,
        )

    independence = IndependenceSection(
        sample_composition=sample_composition(entries, episodes, timeframe, horizons=_FORWARD_HORIZONS),
        walk_forward=walk_forward,
        evidence_maturity=maturity.value,
        evidence_maturity_basis=maturity_basis,
        conclusion_stability=stability_comparison,
    )

    return ResearchQueryResponse(
        sample_count=len(entries),
        evidence_card=evidence_card,
        signal_decay=decay,
        excursions=excursions,
        first_hit=first_hit,
        temporal_stability=temporal_stability(entries, body.horizon_bars),
        cross_symbol_stability=cross_symbol_stability(entries, body.horizon_bars),
        concentration=detect_concentration(entries, config),
        overlap=detect_overlap(entries, body.horizon_bars, timeframe),
        contradictions=check_all_builtin_assumptions(
            entries, body.horizon_bars, body.seed, partition_by_setup_id, config
        ),
        independence=independence,
    )


# ---- Historical analogs -----------------------------------------------------


class AnalogQueryRequest(BaseModel):
    query_candidate: SetupCandidate
    corpus_run_ids: list[str]
    top_n: Optional[int] = None


class AnalogQueryResponse(BaseModel):
    analogs: list[AnalogResult]
    diversity: AnalogDiversityReport
    diverse_analogs: list[AnalogResult]


@router.post("/analogs", response_model=AnalogQueryResponse)
def query_analogs(
    body: AnalogQueryRequest,
    provider: MarketDataProvider = Depends(get_market_data_provider),
    repository: SqlAlchemyResearchRepository = Depends(_repository),
) -> AnalogQueryResponse:
    """Works identically whether `query_candidate` came from a live
    `/setups` response or a historical ledger entry's `detection` -- both
    are the same `SetupCandidate` shape, and this route never looks past
    each candidate's own `candidate_candle_timestamp` (#25)."""
    corpus_entries: list[SetupLedgerEntry] = []
    for run_id in body.corpus_run_ids:
        if repository.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"Research run {run_id!r} not found")
        corpus_entries.extend(repository.list_ledger_entries(run_id, limit=10_000))
    if not corpus_entries:
        return AnalogQueryResponse(analogs=[], diversity=analog_diversity_report([], {}), diverse_analogs=[])

    symbols = {body.query_candidate.symbol} | {e.symbol for e in corpus_entries}
    candles_by_symbol: dict[str, list[Candle]] = {}
    for symbol in symbols:
        timeframe = Timeframe(body.query_candidate.timeframe.value)
        candles_by_symbol[symbol] = provider.get_candles(symbol, timeframe, limit=_FETCH_LIMIT)

    query_close = detection_close_for(body.query_candidate, candles_by_symbol)
    query_features = extract_features(body.query_candidate, query_close)

    candidates = []
    for entry in corpus_entries:
        if entry.setup_id == body.query_candidate.id:
            continue  # never rank a case against itself
        close = detection_close_for(entry.detection, candles_by_symbol)
        candidates.append((entry, extract_features(entry.detection, close)))

    ranked = rank_analogs(query_features, candidates, top_n=body.top_n)
    entries_by_id = {e.setup_id: e for e in corpus_entries}
    decorated = attach_outcomes(ranked, entries_by_id)

    # (#20/#21) Read-only over the already-ranked/decorated list -- never
    # changes similarity ranking or distances, only reports/filters episode
    # duplication among the corpus entries actually being compared against.
    episode_lookup = episode_by_setup_id(build_episodes(corpus_entries))
    diversity = analog_diversity_report(
        decorated, episode_lookup, config=DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
    )
    diverse = diverse_analogs(decorated, episode_lookup, limit=body.top_n)

    return AnalogQueryResponse(analogs=decorated, diversity=diversity, diverse_analogs=diverse)


# ---- Research snapshots -----------------------------------------------------


class CreateSnapshotRequest(BaseModel):
    label: str
    research_run_ids: list[str]
    config_hash: str
    dataset_manifest: dict
    cohort_definition: dict
    filters: dict
    statistical_output: dict
    warning_flags: list[str]


class CreateSnapshotResponse(BaseModel):
    snapshot_id: str


@router.post("/snapshots", response_model=CreateSnapshotResponse)
def create_snapshot(
    body: CreateSnapshotRequest, repository: SqlAlchemySnapshotRepository = Depends(_snapshot_repository)
) -> CreateSnapshotResponse:
    snapshot_id = repository.create_snapshot(
        label=body.label,
        research_run_ids=body.research_run_ids,
        config_hash=body.config_hash,
        dataset_manifest=body.dataset_manifest,
        cohort_definition=body.cohort_definition,
        filters=body.filters,
        statistical_output=body.statistical_output,
        warning_flags=body.warning_flags,
    )
    return CreateSnapshotResponse(snapshot_id=snapshot_id)


@router.get("/snapshots", response_model=list[ResearchSnapshot])
def list_snapshots(
    limit: int = 50, repository: SqlAlchemySnapshotRepository = Depends(_snapshot_repository)
) -> list[ResearchSnapshot]:
    return repository.list_snapshots(limit=limit)


@router.get("/snapshots/compare", response_model=SnapshotComparison)
def compare_snapshots_route(
    snapshot_a: str, snapshot_b: str, repository: SqlAlchemySnapshotRepository = Depends(_snapshot_repository)
) -> SnapshotComparison:
    a = repository.get_snapshot(snapshot_a)
    b = repository.get_snapshot(snapshot_b)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_a!r} not found")
    if b is None:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_b!r} not found")
    return compare_snapshots(a, b)


@router.get("/snapshots/{snapshot_id}", response_model=ResearchSnapshot)
def get_snapshot(
    snapshot_id: str, repository: SqlAlchemySnapshotRepository = Depends(_snapshot_repository)
) -> ResearchSnapshot:
    snapshot = repository.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id!r} not found")
    return snapshot
