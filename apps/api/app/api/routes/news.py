"""Phase 10 API surface: normalized news, catalyst events, market-reaction
measurement, and setup <-> catalyst linking. Thin orchestration only (same
convention as app/api/routes/market.py) -- all domain logic lives in
app.news.*.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_market_data_provider, get_news_provider
from app.database.session import get_db
from app.market_data.provider import MarketDataProvider
from app.news.config import DEFAULT_CATALYST_CONFIG
from app.news.provider import NewsProvider
from app.news.reaction import measure_market_reaction
from app.news.repository import SqlAlchemyNewsRepository
from app.news.schemas import CatalystEvent, MarketReaction, NormalizedNewsArticle, SetupCatalystContext
from app.news.setup_linking import build_setup_catalyst_context
from app.schemas.market_data import Timeframe
from app.schemas.symbols import InvalidTickerError, normalize_ticker
from app.setup_detection.schemas import SetupCandidate

logger = logging.getLogger(__name__)

news_router = APIRouter(prefix="/api/news", tags=["news"])
catalyst_router = APIRouter(prefix="/api/catalysts", tags=["catalysts"])

_DEFAULT_LOOKBACK_DAYS = 30
_MAX_LOOKBACK_DAYS = 365
_REACTION_CANDLE_LIMIT = 2000


def _repository(db: Session = Depends(get_db)) -> SqlAlchemyNewsRepository:
    return SqlAlchemyNewsRepository(db)


def _validated_symbol(symbol: str) -> str:
    try:
        return normalize_ticker(symbol)
    except InvalidTickerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _window(days: int, as_of: Optional[datetime]) -> tuple[datetime, datetime, datetime]:
    if not (1 <= days <= _MAX_LOOKBACK_DAYS):
        raise HTTPException(status_code=422, detail=f"days must be between 1 and {_MAX_LOOKBACK_DAYS}")
    resolved_as_of = as_of or datetime.now(timezone.utc)
    if resolved_as_of.tzinfo is None:
        resolved_as_of = resolved_as_of.replace(tzinfo=timezone.utc)
    start = resolved_as_of - timedelta(days=days)
    return start, resolved_as_of, resolved_as_of


# ---- Articles ---------------------------------------------------------------


@news_router.get("/{symbol}", response_model=list[NormalizedNewsArticle])
def get_symbol_news(
    symbol: str,
    days: int = Query(_DEFAULT_LOOKBACK_DAYS, ge=1, le=_MAX_LOOKBACK_DAYS),
    as_of: Optional[datetime] = Query(None),
    provider: NewsProvider = Depends(get_news_provider),
    repository: SqlAlchemyNewsRepository = Depends(_repository),
) -> list[NormalizedNewsArticle]:
    validated_symbol = _validated_symbol(symbol)
    start, end, resolved_as_of = _window(days, as_of)

    # A live provider fetch is best-effort (#M "provider failure"): a
    # transient outage falls back to whatever this symbol already has
    # persisted rather than a hard 500 -- news is context, not a
    # load-bearing dependency for the rest of the app.
    try:
        fetched = provider.fetch_symbol_news(validated_symbol, start, end, resolved_as_of)
        repository.upsert_articles(fetched)
    except Exception:  # noqa: BLE001 -- degrade to cached data, never crash the request
        logger.warning("News provider fetch failed for %s", validated_symbol, exc_info=True)

    return sorted(
        repository.get_articles_for_symbol(validated_symbol, start, end, resolved_as_of),
        key=lambda a: a.published_at,
        reverse=True,
    )


class WhatsMovingResponse(BaseModel):
    events: list[CatalystEvent]
    symbols_covered: list[str]
    symbols_failed: dict[str, str]


@news_router.get("/market/whats-moving", response_model=WhatsMovingResponse)
def whats_moving(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. AAPL,MSFT,SPY"),
    days: int = Query(3, ge=1, le=_MAX_LOOKBACK_DAYS),
    as_of: Optional[datetime] = Query(None),
    provider: NewsProvider = Depends(get_news_provider),
    repository: SqlAlchemyNewsRepository = Depends(_repository),
) -> WhatsMovingResponse:
    """Cross-symbol catalyst view (#K.1). yfinance (this phase's dev
    provider) has no true market-wide news endpoint (see
    app/news/yfinance_provider.py) -- this aggregates fetch_symbol_news
    across the caller-supplied symbol list instead, documented as a real
    limitation of the dev provider rather than hidden behind a fake
    "market news" call."""
    start, end, resolved_as_of = _window(days, as_of)
    symbols_covered: list[str] = []
    symbols_failed: dict[str, str] = {}
    all_events: list[CatalystEvent] = []

    for raw_symbol in symbols.split(","):
        raw_symbol = raw_symbol.strip()
        if not raw_symbol:
            continue
        try:
            symbol = normalize_ticker(raw_symbol)
            fetched = provider.fetch_symbol_news(symbol, start, end, resolved_as_of)
            repository.upsert_articles(fetched)
            events = repository.events_for_symbol_as_of(symbol, start, end, resolved_as_of)
            repository.persist_events_snapshot(events)
            all_events.extend(events)
            symbols_covered.append(symbol)
        except InvalidTickerError as exc:
            symbols_failed[raw_symbol] = str(exc)
        except Exception as exc:  # noqa: BLE001 -- one symbol's provider failure must not abort the rest
            symbols_failed[raw_symbol] = f"News fetch failed: {exc}"

    deduped = {e.event_id: e for e in all_events}
    ordered = sorted(deduped.values(), key=lambda e: e.primary_timestamp, reverse=True)
    return WhatsMovingResponse(events=ordered, symbols_covered=symbols_covered, symbols_failed=symbols_failed)


# ---- Catalyst events ----------------------------------------------------


@catalyst_router.get("/{symbol}", response_model=list[CatalystEvent])
def get_symbol_catalysts(
    symbol: str,
    days: int = Query(_DEFAULT_LOOKBACK_DAYS, ge=1, le=_MAX_LOOKBACK_DAYS),
    as_of: Optional[datetime] = Query(None),
    provider: NewsProvider = Depends(get_news_provider),
    repository: SqlAlchemyNewsRepository = Depends(_repository),
) -> list[CatalystEvent]:
    """Always recomputed from as_of-filtered articles (#E) -- see
    app.news.repository's module docstring for why this is never served
    from the persisted "current" snapshot table."""
    validated_symbol = _validated_symbol(symbol)
    start, end, resolved_as_of = _window(days, as_of)

    try:
        fetched = provider.fetch_symbol_news(validated_symbol, start, end, resolved_as_of)
        repository.upsert_articles(fetched)
    except Exception:  # noqa: BLE001 -- degrade to cached data, never crash the request
        logger.warning("News provider fetch failed for %s", validated_symbol, exc_info=True)

    events = repository.events_for_symbol_as_of(validated_symbol, start, end, resolved_as_of)
    repository.persist_events_snapshot(events)
    return sorted(events, key=lambda e: e.primary_timestamp, reverse=True)


class CatalystEventDetail(BaseModel):
    event: CatalystEvent
    articles: list[NormalizedNewsArticle]


@catalyst_router.get("/event/{event_id}", response_model=CatalystEventDetail)
def get_catalyst_event(
    event_id: str, repository: SqlAlchemyNewsRepository = Depends(_repository)
) -> CatalystEventDetail:
    event = repository.get_event_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Catalyst event {event_id!r} not found")
    articles = repository.get_articles_by_ids(event.contributing_article_ids)
    return CatalystEventDetail(event=event, articles=sorted(articles, key=lambda a: a.published_at))


@catalyst_router.get("/event/{event_id}/reaction", response_model=MarketReaction)
def get_catalyst_reaction(
    event_id: str,
    symbol: str = Query(...),
    timeframe: str = Query("1h"),
    provider: MarketDataProvider = Depends(get_market_data_provider),
    repository: SqlAlchemyNewsRepository = Depends(_repository),
) -> MarketReaction:
    validated_symbol = _validated_symbol(symbol)
    try:
        validated_timeframe = Timeframe(timeframe)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {timeframe!r}") from None

    event = repository.get_event_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Catalyst event {event_id!r} not found")

    cached = repository.get_reaction(event_id, validated_symbol, validated_timeframe.value)
    if cached is not None:
        return cached

    candles = provider.get_candles(validated_symbol, validated_timeframe, limit=_REACTION_CANDLE_LIMIT)
    reaction = measure_market_reaction(
        event, validated_symbol, validated_timeframe.value, candles, DEFAULT_CATALYST_CONFIG
    )
    if reaction.evaluation_quality is not None and reaction.evaluation_quality.fully_evaluated:
        repository.upsert_reaction(reaction)
    return reaction


# ---- Setup <-> catalyst linking ---------------------------------------------


class SetupCatalystContextRequest(BaseModel):
    candidate: SetupCandidate
    lookback_days: int = 5


@catalyst_router.post("/setup-context", response_model=SetupCatalystContext)
def get_setup_catalyst_context(
    body: SetupCatalystContextRequest,
    news_provider: NewsProvider = Depends(get_news_provider),
    market_provider: MarketDataProvider = Depends(get_market_data_provider),
    repository: SqlAlchemyNewsRepository = Depends(_repository),
) -> SetupCatalystContext:
    """Works identically whether `candidate` came from a live `/setups`
    response or a historical ledger entry's `detection` (same convention as
    `/api/research/analogs`'s `query_candidate`) -- this route only ever
    looks at catalysts up to the candidate's own `candidate_candle_timestamp`
    plus a bounded lookahead window, never anything the candidate itself
    couldn't have known plus what has since become observable (#E)."""
    candidate = body.candidate
    config = DEFAULT_CATALYST_CONFIG
    detection_time = candidate.candidate_candle_timestamp
    start = detection_time - timedelta(hours=config.catalyst_lookback_hours_for_setup_linking)
    # as_of for this query is "now" -- reaction/after-catalysts may use data
    # observed since detection, exactly like Phase 7 outcome evaluation does
    # for setups themselves.
    as_of = datetime.now(timezone.utc)
    end = min(detection_time + timedelta(hours=config.catalyst_lookahead_hours_for_setup_linking), as_of)

    fetched = news_provider.fetch_symbol_news(candidate.symbol, start, end, as_of)
    repository.upsert_articles(fetched)
    events = repository.events_for_symbol_as_of(candidate.symbol, start, end, as_of)
    repository.persist_events_snapshot(events)

    reaction_by_event_id: dict[str, MarketReaction] = {}
    if events:
        candles = market_provider.get_candles(
            candidate.symbol, Timeframe(candidate.timeframe.value), limit=_REACTION_CANDLE_LIMIT
        )
        for event in events:
            cached = repository.get_reaction(event.event_id, candidate.symbol, candidate.timeframe.value)
            if cached is not None:
                reaction_by_event_id[event.event_id] = cached
                continue
            reaction = measure_market_reaction(
                event, candidate.symbol, candidate.timeframe.value, candles, config
            )
            reaction_by_event_id[event.event_id] = reaction
            if reaction.evaluation_quality is not None and reaction.evaluation_quality.fully_evaluated:
                repository.upsert_reaction(reaction)

    return build_setup_catalyst_context(candidate, events, reaction_by_event_id, config)
