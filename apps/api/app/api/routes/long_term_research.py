"""Long-Term Investing Research API -- wholly separate from
app.api.routes.decisions/alerts (the Decision Engine's short/medium-term
surface). Every user-scoped route reads/writes only the calling user's
own rows (watchlist membership, long-term push preference); the
universe a given scan covers is explicit in each route's own docstring
below, never implicit.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.api.deps import (
    get_fundamentals_provider,
    get_long_term_research_repository,
    get_market_data_provider,
)
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.database.models import User
from app.long_term_research.fundamentals import FundamentalsProvider
from app.long_term_research.repository import LongTermResearchRepository
from app.long_term_research.schemas import LongTermResearchResult
from app.long_term_research.service import run_scan
from app.market_data.provider import MarketDataProvider
from app.market_data.sessions import EXCHANGE_TZ

router = APIRouter(prefix="/api/long-term-research", tags=["long-term-research"])


def _settings_dep() -> Settings:
    return get_settings()


class ScanResponse(BaseModel):
    as_of: datetime
    results: list[LongTermResearchResult]


class ScheduledScanResponse(BaseModel):
    ran: bool
    """False when a scheduled scan already ran for today's America/
    New_York calendar date -- this is the idempotency guard, not an
    error; repeated/overlapping cron pings on the same day are expected
    and must be cheap no-ops, never duplicate scans or duplicate
    pushes."""
    as_of: datetime
    symbol_count: int


class LongTermPushPreferenceResponse(BaseModel):
    enabled: bool
    key_configured: bool


class SetLongTermPushPreferenceRequest(BaseModel):
    enabled: bool


def _now_et() -> datetime:
    return datetime.now(timezone.utc).astimezone(EXCHANGE_TZ)


@router.get("", response_model=list[LongTermResearchResult])
def list_long_term_research(
    current_user: User = Depends(get_current_user),
    repository: LongTermResearchRepository = Depends(get_long_term_research_repository),
) -> list[LongTermResearchResult]:
    """The latest snapshot (if any) for every symbol currently on the
    calling user's own watchlist -- never another user's watchlist,
    and never a symbol this user doesn't monitor."""
    symbols = repository.list_user_watchlist_symbols(current_user.id)
    latest = repository.list_latest_snapshots(symbols)
    return [latest[symbol] for symbol in symbols if symbol in latest]


@router.get("/{symbol}", response_model=LongTermResearchResult)
def get_long_term_research(
    symbol: str,
    current_user: User = Depends(get_current_user),
    repository: LongTermResearchRepository = Depends(get_long_term_research_repository),
) -> LongTermResearchResult:
    result = repository.get_latest_snapshot(symbol.upper())
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No long-term research snapshot exists yet for {symbol!r}"
        )
    return result


@router.post("/scan", response_model=ScanResponse)
def run_manual_scan(
    current_user: User = Depends(get_current_user),
    repository: LongTermResearchRepository = Depends(get_long_term_research_repository),
    market_data: MarketDataProvider = Depends(get_market_data_provider),
    fundamentals: FundamentalsProvider = Depends(get_fundamentals_provider),
    settings: Settings = Depends(_settings_dep),
) -> ScanResponse:
    """"RUN LONG-TERM SCAN" -- always runs immediately for the calling
    user's own watchlist, with NO idempotency gate (this is deliberately
    the on-demand testing/preview path; see /scheduled-scan for the
    once-per-day automated job, which DOES gate on "already ran today")."""
    symbols = repository.list_user_watchlist_symbols(current_user.id)
    as_of = datetime.now(timezone.utc)
    results = run_scan(
        symbols,
        as_of=as_of,
        repository=repository,
        market_data_provider=market_data,
        fundamentals_provider=fundamentals,
        settings=settings,
    )
    return ScanResponse(as_of=as_of, results=results)


@router.post("/scheduled-scan", response_model=ScheduledScanResponse)
def run_scheduled_scan(
    x_scheduler_secret: str | None = Header(default=None),
    repository: LongTermResearchRepository = Depends(get_long_term_research_repository),
    market_data: MarketDataProvider = Depends(get_market_data_provider),
    fundamentals: FundamentalsProvider = Depends(get_fundamentals_provider),
    settings: Settings = Depends(_settings_dep),
) -> ScheduledScanResponse:
    """The externally (cron-)triggered once-per-day entry point --
    deliberately UNAUTHENTICATED by user session (there is no logged-in
    user driving this), instead gated by a shared secret
    (`X-Scheduler-Secret` header must match `SCHEDULER_SHARED_SECRET`;
    an empty/unconfigured secret always rejects, there is no "open by
    default" fallback). Scans the UNION of every user's watchlist
    symbols (the full daily-batch universe), and is idempotent per
    America/New_York calendar date: a second trigger on the same day
    (an overlapping or retried cron ping) returns `ran=False` and does
    nothing further -- it never re-scans or re-pushes."""
    if not settings.scheduler_shared_secret or x_scheduler_secret != settings.scheduler_shared_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing scheduler secret")

    as_of = datetime.now(timezone.utc)
    run_date = _now_et().date().isoformat()
    symbols = repository.list_all_watchlist_symbols_union()

    claimed = repository.claim_scheduled_scan_run(run_date=run_date, as_of=as_of, symbol_count=len(symbols))
    if not claimed:
        return ScheduledScanResponse(ran=False, as_of=as_of, symbol_count=len(symbols))

    run_scan(
        symbols,
        as_of=as_of,
        repository=repository,
        market_data_provider=market_data,
        fundamentals_provider=fundamentals,
        settings=settings,
    )
    return ScheduledScanResponse(ran=True, as_of=as_of, symbol_count=len(symbols))


@router.get("/push-preference/me", response_model=LongTermPushPreferenceResponse)
def get_long_term_push_preference(
    current_user: User = Depends(get_current_user),
    repository: LongTermResearchRepository = Depends(get_long_term_research_repository),
) -> LongTermPushPreferenceResponse:
    return LongTermPushPreferenceResponse(
        enabled=repository.get_long_term_push_enabled(current_user.id),
        key_configured=repository.get_user_pushover_key_encrypted(current_user.id) is not None,
    )


@router.put("/push-preference/me", response_model=LongTermPushPreferenceResponse)
def set_long_term_push_preference(
    payload: SetLongTermPushPreferenceRequest,
    current_user: User = Depends(get_current_user),
    repository: LongTermResearchRepository = Depends(get_long_term_research_repository),
) -> LongTermPushPreferenceResponse:
    repository.set_long_term_push_enabled(current_user.id, payload.enabled)
    return LongTermPushPreferenceResponse(
        enabled=payload.enabled,
        key_configured=repository.get_user_pushover_key_encrypted(current_user.id) is not None,
    )
