"""FastAPI dependency wiring. Routes only ever depend on the
MarketDataProvider/WatchlistRepository interfaces — tests override these
with fakes via app.dependency_overrides instead of hitting a real provider.

Which market-data provider backs `get_market_data_provider()` is decided in
exactly one place: `settings.market_data_provider`. Nothing else in the
codebase should import AlpacaMarketDataProvider or YFinanceMarketDataProvider
directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Optional

from fastapi import Depends

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.database.session import get_db
from app.market_data.alpaca_provider import AlpacaMarketDataProvider
from app.market_data.cache import InMemoryCache
from app.market_data.cached_provider import CachedMarketDataProvider
from app.market_data.massive_provider import MassiveMarketDataProvider
from app.market_data.provider import MarketDataProvider
from app.market_data.twelve_data_provider import TwelveDataMarketDataProvider
from app.market_data.yfinance_provider import YFinanceMarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from app.news.provider import NewsProvider
from app.news.yfinance_provider import YFinanceNewsProvider
from app.watchlist.repository import SqlAlchemyWatchlistRepository, WatchlistRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.ai_analysis.provider import AIAnalysisProvider
    from app.database.models import User
    from app.live.entitlement import MarketDataEntitlement
    from app.live.mock_streaming import MockStreamingProvider
    from app.live.streaming import StreamingMarketDataProvider


@lru_cache
def _shared_cache() -> InMemoryCache:
    return InMemoryCache()


def get_shared_market_data_cache() -> InMemoryCache:
    """Public accessor for the same process-wide cache instance
    get_market_data_provider() uses underneath -- Phase 12.1's
    RecomputationEngine needs this exact instance (not a new one) so a
    completed-candle-triggered cache invalidation actually affects what
    routes/build_market_snapshot see next."""
    return _shared_cache()


def _build_inner_provider() -> MarketDataProvider:
    provider_name = get_settings().market_data_provider.lower()
    if provider_name == "alpaca":
        return AlpacaMarketDataProvider()
    if provider_name == "yfinance":
        return YFinanceMarketDataProvider()
    if provider_name == "massive":
        return MassiveMarketDataProvider()
    if provider_name == "twelve_data":
        return TwelveDataMarketDataProvider()
    raise ValueError(
        f"Unknown MARKET_DATA_PROVIDER {provider_name!r}; expected 'yfinance', 'alpaca', 'massive', "
        "or 'twelve_data'"
    )


@lru_cache
def get_market_data_provider() -> MarketDataProvider:
    return CachedMarketDataProvider(_build_inner_provider(), _shared_cache())


@lru_cache
def get_streaming_provider() -> "Optional[StreamingMarketDataProvider]":
    """Phase 12.2 (§C): None whenever push streaming isn't actually
    configured/available -- LiveMarketService must keep working via its
    existing per-symbol poll loop in that case, exactly as Phase 12.1 did.
    Never required for tests or app startup; only meaningful when
    MARKET_DATA_PROVIDER=massive and MASSIVE_API_KEY is set, or
    MARKET_DATA_PROVIDER=twelve_data and TWELVE_DATA_API_KEY is set.

    Imports are local (not module-level): each pulls in the `websockets`
    package only when actually needed, so a deployment that never
    configures streaming never pays for it."""
    settings = get_settings()
    provider_name = settings.market_data_provider.lower()
    if provider_name == "massive" and settings.massive_api_key:
        from app.market_data.massive_streaming import MassiveStreamingProvider

        return MassiveStreamingProvider(settings.massive_api_key, url=settings.massive_ws_url)
    if provider_name == "twelve_data" and settings.twelve_data_api_key:
        from app.market_data.twelve_data_streaming import TwelveDataStreamingProvider

        # TWELVE_DATA_WS_BASE_URL is the bare host (e.g.
        # wss://ws.twelvedata.com); the price-stream path is appended here
        # so the config value matches Twelve Data's own documented base URL
        # convention exactly, same as the other provider base-URL settings.
        ws_url = f"{settings.twelve_data_ws_base_url.rstrip('/')}/v1/quotes/price"
        return TwelveDataStreamingProvider(settings.twelve_data_api_key, url=ws_url)
    return None


@lru_cache
def get_dev_mock_streaming_provider() -> "Optional[MockStreamingProvider]":
    """Phase 17 (§60/§79/§99): the dev-only, hand-scriptable streaming
    provider behind /api/dev/live-simulator -- None (and so unreachable)
    unless BOTH settings.enable_dev_live_simulator is true AND environment
    is not production (the config validator already makes that combination
    impossible to configure at all, but this is checked again here so the
    provider is never even constructed if that check were ever bypassed)."""
    settings = get_settings()
    if settings.is_production or not settings.enable_dev_live_simulator:
        return None
    from app.live.mock_streaming import MockStreamingProvider

    return MockStreamingProvider()


@lru_cache
def get_market_data_entitlement() -> "MarketDataEntitlement":
    """Phase 17/19.1 (§1/§27): resolved once per process from operator-set
    config only -- never from whether get_streaming_provider() above
    happens to return non-None (a configured key proves nothing about plan
    tier; see app.live.entitlement). This initial resolution is only a
    starting point for Twelve Data -- LiveMarketService upgrades/downgrades
    it dynamically at runtime from TwelveDataStreamingProvider.
    entitlement_hint() once genuine subscription evidence exists."""
    from app.live.entitlement import resolve_streaming_entitlement

    settings = get_settings()
    provider_name = settings.market_data_provider
    if provider_name.lower() == "twelve_data":
        return resolve_streaming_entitlement(
            provider_name=provider_name,
            api_key=settings.twelve_data_api_key,
            streaming_entitled_flag=None,
        )
    return resolve_streaming_entitlement(
        provider_name=provider_name,
        api_key=settings.massive_api_key,
        streaming_entitled_flag=settings.massive_streaming_entitled,
    )


def get_watchlist_repository(
    current_user: "User" = Depends(get_current_user),
    db: "Session" = Depends(get_db),
) -> WatchlistRepository:
    """Phase 16 (§9/§96): the personal, per-user Watchlist -- every query
    this repository makes is scoped to `current_user.id`, resolved only
    from a validated session token, never from a caller-supplied id. This
    is intentionally NOT the dependency the global monitoring universe
    uses (see app.monitoring.universe.MonitoringUniverse, which no longer
    depends on any WatchlistRepository at all)."""
    return SqlAlchemyWatchlistRepository(db, user_id=current_user.id)


@lru_cache
def get_session_factory():
    """The DB session factory background lifespan services (ForecastMonitor/
    NewsMonitor/MonitoringService) use -- routed through this override point
    the same way get_market_data_provider/get_news_provider already are, so
    a test that triggers the real app lifespan (`with TestClient(app) as c`)
    can override it with an isolated in-memory DB instead of these
    always-on background loops hitting the real on-disk database on every
    such test (see app.main.lifespan; Phase 14.1 root-caused a full-suite
    hang to exactly this -- MonitoringService, unlike the two pre-existing
    monitors, does real per-symbol setup-detection work on its very first
    tick and had no override point, so every lifespan-triggering test in
    test_live_routes.py raced concurrent `checkfirst=True` table creation
    and writes against one shared real SQLite file for the life of the
    whole pytest session)."""
    from app.database.session import SessionLocal

    return SessionLocal


@lru_cache
def get_news_provider() -> NewsProvider:
    provider_name = get_settings().news_provider.lower()
    if provider_name == "yfinance":
        return YFinanceNewsProvider()
    if provider_name == "fixture":
        return FixtureNewsProvider([])
    raise ValueError(f"Unknown NEWS_PROVIDER {provider_name!r}; expected 'yfinance' or 'fixture'")


@lru_cache
def get_ai_analysis_provider() -> "AIAnalysisProvider":
    """Never raises for a missing/invalid OpenAI key -- an unusable "openai"
    selection silently falls back to the mock provider so the product keeps
    working with deterministic evidence only (#C), matching
    AIAnalysisUnavailableError's contract at the provider-method level.

    Imports are local, not module-level: app.ai_analysis.schemas embeds
    route-defined response models (the same cross-module reuse
    research_catalysts.py already does for research_intelligence.py's
    ResearchQueryResponse), which makes app.ai_analysis import back through
    app.api.routes.* -- a module-level import here would be circular."""
    from app.ai_analysis.mock_provider import MockAIAnalysisProvider

    provider_name = get_settings().ai_analysis_provider.lower()
    if provider_name == "mock":
        return MockAIAnalysisProvider()
    if provider_name == "openai":
        from app.ai_analysis.openai_provider import OpenAIAnalysisProvider
        from app.ai_analysis.provider import AIAnalysisUnavailableError

        settings = get_settings()
        try:
            return OpenAIAnalysisProvider(settings.openai_api_key, settings.openai_model)
        except AIAnalysisUnavailableError:
            return MockAIAnalysisProvider()
    raise ValueError(f"Unknown AI_ANALYSIS_PROVIDER {provider_name!r}; expected 'mock' or 'openai'")
