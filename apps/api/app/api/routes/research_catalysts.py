"""Phase 10 (#H) / Phase 10.1 Research Lab catalyst extension: study
cohorts like "earnings + breakout_retest" or "catalyst with elevated RVOL
vs without" with the same statistical rigor as Phase 8/9, without
duplicating a single line of that machinery.

The approach: compute each pooled ledger entry's `SetupCatalystContext`
(app.news.setup_linking -- the exact same function `/api/catalysts/
setup-context` uses for a single live setup), filter the population to
entries matching the requested catalyst criteria, then hand the filtered
population to `app.api.routes.research_intelligence
.compute_research_query_response` -- the identical evidence-card/decay/
excursion/stability/concentration/overlap/contradictions/independence
(RAW/EPISODE/PURGED, block bootstrap, walk-forward) pipeline `/api/research
/query` already runs, completely unmodified. This is a pre-filter, never a
parallel statistics stack (#H "reuse Phase 8/9 methodology").

Phase 10.1 fix (#B): the catalyst filter is now threaded through BOTH the
`entries` population AND the `raw_pool` population `compute_research_query
_response` uses internally for its own qualified-vs-rejected conclusion-
stability check (`setup_type_direction_filter`) -- previously only `entries`
was catalyst-filtered, so that one internal comparison silently ignored the
catalyst filter entirely. Qualification lift, rejection value, and an
explicit catalyst-cohort-vs-baseline comparison are computed the same way
Phase 9 already computes them elsewhere (`independence_adjusted_
qualification_lift`/`independence_adjusted_rejection_value`/
`conclusion_stability`) -- reused verbatim, not reimplemented.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_market_data_provider, get_news_provider
from app.api.routes.research_intelligence import (
    ResearchQueryRequest,
    ResearchQueryResponse,
    _pooled_entries,
    _repository,
    compute_research_query_response,
    setup_type_direction_filter,
)
from app.database.session import get_db
from app.market_data.provider import MarketDataProvider
from app.news.config import DEFAULT_CATALYST_CONFIG
from app.news.provider import NewsProvider
from app.news.repository import SqlAlchemyNewsRepository
from app.news.schemas import SetupCatalystContext
from app.news.setup_linking import build_setup_catalyst_contexts_batch
from app.research.repository import SqlAlchemyResearchRepository
from app.research.schemas import SetupLedgerEntry
from app.research_intelligence.conclusion_stability import conclusion_stability
from app.research_intelligence.config import DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
from app.research_intelligence.qualification import independence_adjusted_qualification_lift
from app.research_intelligence.rejection_value import independence_adjusted_rejection_value
from app.research_intelligence.schemas import ConclusionStabilityReport
from app.schemas.market_data import Timeframe

router = APIRouter(prefix="/api/research/catalysts", tags=["research-catalysts"])

_FETCH_LIMIT = 50_000


def _news_repository(db: Session = Depends(get_db)) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(db)


class CatalystResearchQueryRequest(ResearchQueryRequest):
    # Additive catalyst filters (#H) -- every field optional; leaving all of
    # them unset reproduces `/api/research/query`'s exact behavior.
    require_catalyst: bool = False
    catalyst_category: Optional[str] = None
    catalyst_max_hours_since: Optional[float] = None
    catalyst_rvol_elevated: Optional[bool] = None
    # Phase 10.1 (#B): when true and a catalyst filter is actually active,
    # also compare the catalyst-matching cohort against its own complement
    # (the same setup_type/direction population that did NOT match the
    # filter -- "no catalyst + same setup type" is exactly this with
    # require_catalyst=True) via the same conclusion_stability machinery
    # used for qualified-vs-rejected.
    compare_to_no_catalyst: bool = False


class CatalystResearchQueryResponse(ResearchQueryResponse):
    # Explicitly RAW ledger-entry counts -- NEVER the independent sample
    # size (#B "never present raw article count or raw ledger count as
    # independent sample size"). The actual independence-adjusted counts
    # (episode/purged) are in `independence.sample_composition`, computed
    # from the catalyst-filtered population like everything else here.
    catalyst_filtered_raw_sample_count: int
    unfiltered_raw_sample_count: int
    catalyst_filters_applied: dict

    # Phase 10.1 (#B) -- reused verbatim from app.research_intelligence.qualification
    # /rejection_value/conclusion_stability, computed on the catalyst-filtered
    # (setup_type/direction-scoped) population's own qualified/rejected split.
    qualification_lift: Optional[ConclusionStabilityReport] = None
    rejection_value: dict[str, ConclusionStabilityReport] = {}
    catalyst_vs_baseline: Optional[ConclusionStabilityReport] = None


def _build_catalyst_context_by_setup_id(
    entries: list[SetupLedgerEntry],
    news_provider: NewsProvider,
    market_provider: MarketDataProvider,
    news_repository: SqlAlchemyNewsRepository,
) -> dict[str, SetupCatalystContext]:
    """Thin wrapper: ledger entries carry their frozen `SetupCandidate` as
    `.detection`, whose `.id` equals the entry's own `setup_id` -- so this
    just delegates to the shared batch helper
    (app.news.setup_linking.build_setup_catalyst_contexts_batch), the same
    one the analog engine's optional catalyst context uses."""
    return build_setup_catalyst_contexts_batch(
        [e.detection for e in entries],
        news_provider,
        market_provider,
        news_repository,
        DEFAULT_CATALYST_CONFIG,
        _FETCH_LIMIT,
    )


def _matches_catalyst_filters(context: SetupCatalystContext, body: CatalystResearchQueryRequest) -> bool:
    if body.require_catalyst and context.nearest_catalyst is None:
        return False
    if body.catalyst_category is not None:
        category = context.nearest_catalyst.category.value if context.nearest_catalyst else None
        if category != body.catalyst_category:
            return False
    if body.catalyst_max_hours_since is not None:
        hours = context.nearest_catalyst.hours_before_setup if context.nearest_catalyst else None
        if hours is None or hours > body.catalyst_max_hours_since:
            return False
    if body.catalyst_rvol_elevated is not None:
        rvol = context.nearest_reaction.rvol_at_event if context.nearest_reaction else None
        if rvol is None:
            return False
        elevated = rvol >= DEFAULT_CATALYST_CONFIG.reaction_rvol_elevated_threshold
        if elevated != body.catalyst_rvol_elevated:
            return False
    return True


def _has_catalyst_filters(body: CatalystResearchQueryRequest) -> bool:
    return (
        body.require_catalyst
        or body.catalyst_category is not None
        or body.catalyst_max_hours_since is not None
        or body.catalyst_rvol_elevated is not None
    )


@router.post("/query", response_model=CatalystResearchQueryResponse)
def catalyst_research_query(
    body: CatalystResearchQueryRequest,
    provider: MarketDataProvider = Depends(get_market_data_provider),
    news_provider: NewsProvider = Depends(get_news_provider),
    repository: SqlAlchemyResearchRepository = Depends(_repository),
    news_repository: SqlAlchemyNewsRepository = Depends(_news_repository),
) -> CatalystResearchQueryResponse:
    raw_pool = _pooled_entries(body.run_ids, repository)

    # The population a catalyst filter applies within: setup_type/direction
    # only, deliberately ignoring qualification_state (#B) -- the exact same
    # pool `compute_research_query_response` derives internally for its own
    # qualified-vs-rejected comparison, reused here (not re-derived) so both
    # ends up catalyst-filtered consistently.
    setup_type_direction_pool = setup_type_direction_filter(raw_pool, body)
    if not setup_type_direction_pool:
        raise HTTPException(status_code=404, detail="No ledger entries matched the requested run(s)/filters")

    has_filters = _has_catalyst_filters(body)
    if has_filters:
        context_by_setup_id = _build_catalyst_context_by_setup_id(
            setup_type_direction_pool, news_provider, provider, news_repository
        )
        catalyst_matched_stdp = [
            e
            for e in setup_type_direction_pool
            if _matches_catalyst_filters(context_by_setup_id[e.setup_id], body)
        ]
        catalyst_unmatched_stdp = [
            e
            for e in setup_type_direction_pool
            if not _matches_catalyst_filters(context_by_setup_id[e.setup_id], body)
        ]
    else:
        catalyst_matched_stdp = setup_type_direction_pool
        catalyst_unmatched_stdp = []

    if not catalyst_matched_stdp:
        raise HTTPException(
            status_code=404, detail="No ledger entries matched the requested catalyst filters"
        )

    # `entries` additionally respects qualification_state (a subset of
    # catalyst_matched_stdp), matching what `/api/research/query` does for
    # its own `entries` vs `raw_pool` split.
    entries = catalyst_matched_stdp
    if body.qualification_state is not None:
        entries = [e for e in entries if e.detection.current_state == body.qualification_state]
    if not entries:
        raise HTTPException(
            status_code=404,
            detail="No ledger entries matched the requested run(s)/catalyst/qualification filters",
        )

    base_response = compute_research_query_response(entries, catalyst_matched_stdp, body, provider)

    timeframe = Timeframe(entries[0].timeframe)
    config = DEFAULT_RESEARCH_INTELLIGENCE_CONFIG
    horizons = (body.horizon_bars,)

    qualified = [e for e in catalyst_matched_stdp if e.detection.current_state == "qualified"]
    rejected = [e for e in catalyst_matched_stdp if e.detection.current_state == "rejected"]

    qualification_lift = None
    if qualified and rejected:
        qualification_lift = independence_adjusted_qualification_lift(
            qualified, rejected, horizons, timeframe, body.seed, config
        )[0]

    rejection_value: dict[str, ConclusionStabilityReport] = {}
    if rejected and qualified:
        rejection_value = {
            code: reports[0]
            for code, reports in independence_adjusted_rejection_value(
                rejected, qualified, horizons, timeframe, body.seed, config
            ).items()
        }

    catalyst_vs_baseline = None
    if body.compare_to_no_catalyst and has_filters and catalyst_unmatched_stdp:
        catalyst_vs_baseline = conclusion_stability(
            catalyst_matched_stdp,
            catalyst_unmatched_stdp,
            group_a_label="catalyst_match",
            group_b_label="baseline_no_match",
            finding_label=f"{body.setup_type or 'all'} catalyst filter vs baseline",
            horizon_bars=body.horizon_bars,
            timeframe=timeframe,
            seed=body.seed,
            config=config,
        )

    return CatalystResearchQueryResponse(
        **base_response.model_dump(),
        catalyst_filtered_raw_sample_count=len(catalyst_matched_stdp),
        unfiltered_raw_sample_count=len(setup_type_direction_pool),
        catalyst_filters_applied={
            "require_catalyst": body.require_catalyst,
            "catalyst_category": body.catalyst_category,
            "catalyst_max_hours_since": body.catalyst_max_hours_since,
            "catalyst_rvol_elevated": body.catalyst_rvol_elevated,
        },
        qualification_lift=qualification_lift,
        rejection_value=rejection_value,
        catalyst_vs_baseline=catalyst_vs_baseline,
    )
