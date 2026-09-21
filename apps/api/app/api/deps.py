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

from app.config import get_settings
from app.market_data.alpaca_provider import AlpacaMarketDataProvider
from app.market_data.cache import InMemoryCache
from app.market_data.cached_provider import CachedMarketDataProvider
from app.market_data.massive_provider import MassiveMarketDataProvider
from app.market_data.provider import MarketDataProvider
from app.market_data.yfinance_provider import YFinanceMarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from app.news.provider import NewsProvider
from app.news.yfinance_provider import YFinanceNewsProvider
from app.watchlist.repository import InMemoryWatchlistRepository, WatchlistRepository

if TYPE_CHECKING:
    from app.ai_analysis.provider import AIAnalysisProvider
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
    raise ValueError(
        f"Unknown MARKET_DATA_PROVIDER {provider_name!r}; expected 'yfinance', 'alpaca', or 'massive'"
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
    MARKET_DATA_PROVIDER=massive and MASSIVE_API_KEY is set.

    Import of MassiveStreamingProvider is local (not module-level): it pulls
    in the `websockets` package only when actually needed, so a deployment
    that never sets MARKET_DATA_PROVIDER=massive never pays for it."""
    settings = get_settings()
    if settings.market_data_provider.lower() != "massive" or not settings.massive_api_key:
        return None
    from app.market_data.massive_streaming import MassiveStreamingProvider

    return MassiveStreamingProvider(settings.massive_api_key, url=settings.massive_ws_url)


@lru_cache
def get_watchlist_repository() -> WatchlistRepository:
    return InMemoryWatchlistRepository()


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
