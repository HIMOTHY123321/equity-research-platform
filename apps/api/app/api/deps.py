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

from app.config import get_settings
from app.market_data.alpaca_provider import AlpacaMarketDataProvider
from app.market_data.cache import InMemoryCache
from app.market_data.cached_provider import CachedMarketDataProvider
from app.market_data.provider import MarketDataProvider
from app.market_data.yfinance_provider import YFinanceMarketDataProvider
from app.news.fixture_provider import FixtureNewsProvider
from app.news.provider import NewsProvider
from app.news.yfinance_provider import YFinanceNewsProvider
from app.watchlist.repository import InMemoryWatchlistRepository, WatchlistRepository


@lru_cache
def _shared_cache() -> InMemoryCache:
    return InMemoryCache()


def _build_inner_provider() -> MarketDataProvider:
    provider_name = get_settings().market_data_provider.lower()
    if provider_name == "alpaca":
        return AlpacaMarketDataProvider()
    if provider_name == "yfinance":
        return YFinanceMarketDataProvider()
    raise ValueError(
        f"Unknown MARKET_DATA_PROVIDER {provider_name!r}; expected 'yfinance' or 'alpaca'"
    )


@lru_cache
def get_market_data_provider() -> MarketDataProvider:
    return CachedMarketDataProvider(_build_inner_provider(), _shared_cache())


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
