"""Phase 10 (#H) Research Lab catalyst extension: study cohorts like
"earnings + breakout_retest" or "catalyst with elevated RVOL vs without"
without duplicating a single line of Phase 8/9's statistics machinery.

The approach: compute each pooled ledger entry's `SetupCatalystContext`
(app.news.setup_linking -- the exact same function `/api/catalysts/
setup-context` uses for a single live setup), filter the pool to entries
matching the requested catalyst criteria, then hand the filtered pool to
`app.api.routes.research_intelligence.compute_research_query_response` --
the identical evidence-card/decay/excursion/stability/concentration/overlap/
contradictions/independence pipeline `/api/research/query` already runs,
completely unmodified. This is a pre-filter, never a parallel statistics
stack (per #H: "reuse Phase 8/9 methodology").
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_market_data_provider, get_news_provider
from app.api.routes.research_intelligence import (
    ResearchQueryRequest,
    ResearchQueryResponse,
    _apply_filters,
    _pooled_entries,
    _repository,
    compute_research_query_response,
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


class CatalystResearchQueryResponse(ResearchQueryResponse):
    catalyst_filtered_sample_count: int
    unfiltered_sample_count: int
    catalyst_filters_applied: dict


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


@router.post("/query", response_model=CatalystResearchQueryResponse)
def catalyst_research_query(
    body: CatalystResearchQueryRequest,
    provider: MarketDataProvider = Depends(get_market_data_provider),
    news_provider: NewsProvider = Depends(get_news_provider),
    repository: SqlAlchemyResearchRepository = Depends(_repository),
    news_repository: SqlAlchemyNewsRepository = Depends(_news_repository),
) -> CatalystResearchQueryResponse:
    raw_pool = _pooled_entries(body.run_ids, repository)
    base_entries = _apply_filters(raw_pool, body)
    if not base_entries:
        raise HTTPException(status_code=404, detail="No ledger entries matched the requested run(s)/filters")

    no_catalyst_filters = (
        not body.require_catalyst
        and body.catalyst_category is None
        and body.catalyst_max_hours_since is None
        and body.catalyst_rvol_elevated is None
    )
    if no_catalyst_filters:
        filtered = base_entries
    else:
        context_by_setup_id = _build_catalyst_context_by_setup_id(
            base_entries, news_provider, provider, news_repository
        )
        filtered = [
            e for e in base_entries if _matches_catalyst_filters(context_by_setup_id[e.setup_id], body)
        ]

    if not filtered:
        raise HTTPException(
            status_code=404, detail="No ledger entries matched the requested catalyst filters"
        )

    base_response = compute_research_query_response(filtered, raw_pool, body, provider)
    return CatalystResearchQueryResponse(
        **base_response.model_dump(),
        catalyst_filtered_sample_count=len(filtered),
        unfiltered_sample_count=len(base_entries),
        catalyst_filters_applied={
            "require_catalyst": body.require_catalyst,
            "catalyst_category": body.catalyst_category,
            "catalyst_max_hours_since": body.catalyst_max_hours_since,
            "catalyst_rvol_elevated": body.catalyst_rvol_elevated,
        },
    )
