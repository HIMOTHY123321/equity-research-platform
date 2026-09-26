"""FastAPI application entrypoint.

Route modules are added phase-by-phase as the pipeline is built out.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import (
    get_market_data_provider,
    get_news_provider,
    get_session_factory,
    get_shared_market_data_cache,
    get_streaming_provider,
    get_watchlist_repository,
)
from app.api.routes import (
    alerts,
    analysis,
    decisions,
    forecasts,
    live,
    market,
    monitoring,
    news,
    research,
    research_catalysts,
    research_intelligence,
    symbols,
    watchlist,
)
from app.config import get_settings
from app.database.models import Base
from app.database.session import engine
from app.live.config import DEFAULT_LIVE_CONFIG
from app.live.forecast_monitor import ForecastMonitor
from app.live.news_monitor import NewsMonitor
from app.live.recompute import RecomputationEngine
from app.live.service import LiveMarketService
from app.market_data.exceptions import (
    AuthenticationError,
    InvalidSymbolError,
    MarketDataError,
    ProviderError,
    RateLimitError,
)
from app.monitoring.service import MonitoringService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Every repository creates its own tables lazily, on first
    # instantiation (`Base.metadata.create_all(..., checkfirst=True)`) --
    # safe under normal single-request-at-a-time access, but Phase 12.1
    # adds several background threads (RecomputationEngine/ForecastMonitor/
    # NewsMonitor, each doing their own DB work via asyncio.to_thread) that
    # now routinely start at the same moment as the first browser request's
    # own (thread-pooled) route handlers. On a brand-new SQLite file,
    # checkfirst's own "inspect, then create if missing" is not atomic
    # across separate connections/threads -- two threads can both see a
    # table as missing and both issue CREATE TABLE, and the loser raises
    # "table already exists" (observed live during this phase's browser
    # validation). Creating every table once, synchronously, before any
    # background thread starts closes that race outright: by the time
    # anything concurrent runs, there is no "missing table" window left for
    # two threads to race over.
    Base.metadata.create_all(bind=engine, checkfirst=True)

    # Phase 12.1: the one set of process-wide live-engine singletons --
    # every WebSocket connection shares these, never spinning up its own
    # poll loop/monitor (#O). Real network/DB work only ever happens once a
    # symbol is actually subscribed or a monitor's own timer fires; nothing
    # here talks to a provider at startup.
    #
    # Respects app.dependency_overrides the same way route-level Depends()
    # already does -- lifespan itself isn't a request, so FastAPI's own
    # override mechanism doesn't reach it automatically; this is what lets
    # integration tests inject a deterministic fake provider for the live
    # engines instead of always hitting the real configured one.
    market_provider = app.dependency_overrides.get(get_market_data_provider, get_market_data_provider)()
    news_provider = app.dependency_overrides.get(get_news_provider, get_news_provider)()
    # Phase 12.2: None whenever push streaming isn't actually configured
    # (no MASSIVE_API_KEY, or MARKET_DATA_PROVIDER != "massive") --
    # LiveMarketService transparently falls back to its Phase 12.1
    # per-symbol poll loop in that case.
    streaming_provider = app.dependency_overrides.get(get_streaming_provider, get_streaming_provider)()
    cache = get_shared_market_data_cache()
    live_config = getattr(app.state, "live_config", DEFAULT_LIVE_CONFIG)
    # Phase 14.1: routed through the same override point as every other
    # lifespan dependency above -- previously ForecastMonitor/NewsMonitor/
    # MonitoringService imported SessionLocal directly, so a test triggering
    # the real lifespan (`with TestClient(app) as c`) had no way to keep
    # these background loops off the real on-disk database. MonitoringService
    # does real per-symbol setup-detection work on its very first tick
    # (unlike the other two, which no-op quickly against an empty table),
    # and that -- concurrent `checkfirst=True` table creation plus real
    # writes racing across every lifespan-triggering test in the same
    # pytest session -- was the root cause of a full-suite hang.
    session_factory = app.dependency_overrides.get(get_session_factory, get_session_factory)()

    live_service = LiveMarketService(
        market_provider,
        provider_name=settings.market_data_provider,
        config=live_config,
        streaming_provider=streaming_provider,
    )
    recompute_engine = RecomputationEngine(live_service, market_provider, cache)
    forecast_monitor = ForecastMonitor(session_factory, market_provider, news_provider, config=live_config)
    news_monitor = NewsMonitor(session_factory, news_provider, config=live_config)

    # Phase 14: the background monitor that finally drives the Decision
    # Engine across a whole configurable universe rather than only ever
    # reacting to a manual `/scan` click (§11). Shares the same process-wide
    # WatchlistRepository singleton every /api/watchlist request uses, so
    # what it seeds the monitoring universe from is the user's actual
    # watchlist, not a second divergent one.
    watchlist_repository = app.dependency_overrides.get(
        get_watchlist_repository, get_watchlist_repository
    )()
    monitoring_service = MonitoringService(
        session_factory, watchlist_repository, market_provider, config=live_config
    )

    app.state.live_service = live_service
    app.state.recompute_engine = recompute_engine
    app.state.forecast_monitor = forecast_monitor
    app.state.news_monitor = news_monitor
    app.state.monitoring_service = monitoring_service
    app.state.alert_event_bus = monitoring_service.event_bus

    await recompute_engine.start()
    await forecast_monitor.start()
    await news_monitor.start()
    await monitoring_service.start()

    try:
        yield
    finally:
        await monitoring_service.stop()
        await news_monitor.stop()
        await forecast_monitor.stop()
        await recompute_engine.stop()
        await live_service.shutdown()


app = FastAPI(title="AI Market Desk API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(watchlist.router)
app.include_router(research.router)
app.include_router(research_intelligence.router)
app.include_router(news.news_router)
app.include_router(news.catalyst_router)
app.include_router(research_catalysts.router)
app.include_router(analysis.router)
app.include_router(forecasts.router)
app.include_router(decisions.router)
app.include_router(live.router)
app.include_router(symbols.router)
app.include_router(alerts.router)
app.include_router(monitoring.router)


@app.exception_handler(AuthenticationError)
def handle_authentication_error(request: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(InvalidSymbolError)
def handle_invalid_symbol_error(request: Request, exc: InvalidSymbolError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(RateLimitError)
def handle_rate_limit_error(request: Request, exc: RateLimitError) -> JSONResponse:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
    return JSONResponse(status_code=503, content={"detail": str(exc)}, headers=headers)


@app.exception_handler(ProviderError)
def handle_provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(MarketDataError)
def handle_market_data_error(request: Request, exc: MarketDataError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}
