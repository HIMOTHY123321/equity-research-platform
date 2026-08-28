from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_market_data_provider
from app.config import get_settings
from app.database.session import get_db
from app.market_data.candle_cache import SqlAlchemyCandleCacheRepository, fetch_candles_cached
from app.market_data.provider import MarketDataProvider
from app.research.engine import execute_research_run
from app.research.repository import ResearchRunNotFoundError, SqlAlchemyResearchRepository
from app.research.schemas import ResearchRunSummary, SetupLedgerEntry
from app.research.validation import InvalidReplayRangeError, validate_replay_range
from app.schemas.market_data import Timeframe
from app.schemas.symbols import InvalidTickerError, normalize_ticker

router = APIRouter(prefix="/api/research", tags=["research"])

# Large enough that the yfinance provider's own real-limit trimming (see
# docs/decisions/0006) is always the binding constraint, not this number.
_FETCH_LIMIT = 50_000


class ReplayRequest(BaseModel):
    symbol: str
    timeframe: str = "1h"
    start: datetime
    end: datetime


class ReplayResponse(BaseModel):
    run_id: str
    status: str


class RunResponse(BaseModel):
    id: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    status: str
    config_hash: str
    bars_processed: Optional[int]
    qualified_count: Optional[int]
    rejected_count: Optional[int]
    runtime_seconds: Optional[float]
    error: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]


class LedgerEntriesResponse(BaseModel):
    run_id: str
    count: int
    entries: list[SetupLedgerEntry]


def _repository(db: Session = Depends(get_db)) -> SqlAlchemyResearchRepository:
    return SqlAlchemyResearchRepository(db)


def _candle_cache_repository(db: Session = Depends(get_db)) -> SqlAlchemyCandleCacheRepository:
    return SqlAlchemyCandleCacheRepository(db)


@router.post("/replay", response_model=ReplayResponse)
def run_replay(
    body: ReplayRequest,
    provider: MarketDataProvider = Depends(get_market_data_provider),
    repository: SqlAlchemyResearchRepository = Depends(_repository),
    candle_cache: SqlAlchemyCandleCacheRepository = Depends(_candle_cache_repository),
) -> ReplayResponse:
    try:
        symbol = normalize_ticker(body.symbol)
    except InvalidTickerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        timeframe = Timeframe(body.timeframe)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {body.timeframe!r}") from None
    if timeframe not in (
        Timeframe.FIVE_MIN,
        Timeframe.FIFTEEN_MIN,
        Timeframe.ONE_HOUR,
        Timeframe.FOUR_HOUR,
        Timeframe.ONE_DAY,
    ):
        raise HTTPException(status_code=422, detail=f"Unsupported timeframe for replay: {body.timeframe!r}")

    start = body.start if body.start.tzinfo else body.start.replace(tzinfo=timezone.utc)
    end = body.end if body.end.tzinfo else body.end.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    provider_name = get_settings().market_data_provider.lower()
    try:
        validate_replay_range(provider_name, timeframe.value, start, end, now)
    except InvalidReplayRangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            provider, candle_cache, provider_name, symbol, Timeframe.FOUR_HOUR, start, end, _FETCH_LIMIT
        )
    )

    try:
        run_id = execute_research_run(
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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Replay failed: {exc}") from exc

    return ReplayResponse(run_id=run_id, status="completed")


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, repository: SqlAlchemyResearchRepository = Depends(_repository)) -> RunResponse:
    record = repository.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Research run {run_id!r} not found")
    return RunResponse(
        id=record.id,
        symbol=record.symbol,
        timeframe=record.timeframe,
        start_date=record.start_date,
        end_date=record.end_date,
        status=record.status,
        config_hash=record.config_hash,
        bars_processed=record.bars_processed,
        qualified_count=record.qualified_count,
        rejected_count=record.rejected_count,
        runtime_seconds=record.runtime_seconds,
        error=record.error,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


@router.get("/runs/{run_id}/summary", response_model=ResearchRunSummary)
def get_run_summary(
    run_id: str, repository: SqlAlchemyResearchRepository = Depends(_repository)
) -> ResearchRunSummary:
    summary = repository.get_summary(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No summary available for run {run_id!r}")
    return summary


@router.get("/runs/{run_id}/setups", response_model=LedgerEntriesResponse)
def get_run_setups(
    run_id: str,
    setup_type: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    repository: SqlAlchemyResearchRepository = Depends(_repository),
) -> LedgerEntriesResponse:
    if repository.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Research run {run_id!r} not found")
    try:
        entries = repository.list_ledger_entries(
            run_id, setup_type=setup_type, state=state, limit=limit, offset=offset
        )
    except ResearchRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return LedgerEntriesResponse(run_id=run_id, count=len(entries), entries=entries)


@router.get("/runs", response_model=list[RunResponse])
def list_runs(
    limit: int = Query(50, ge=1, le=200), repository: SqlAlchemyResearchRepository = Depends(_repository)
) -> list[RunResponse]:
    records = repository.list_runs(limit=limit)
    return [
        RunResponse(
            id=r.id,
            symbol=r.symbol,
            timeframe=r.timeframe,
            start_date=r.start_date,
            end_date=r.end_date,
            status=r.status,
            config_hash=r.config_hash,
            bars_processed=r.bars_processed,
            qualified_count=r.qualified_count,
            rejected_count=r.rejected_count,
            runtime_seconds=r.runtime_seconds,
            error=r.error,
            created_at=r.created_at,
            completed_at=r.completed_at,
        )
        for r in records
    ]
