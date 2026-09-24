"""Caching decorator over any MarketDataProvider. Keeps the raw provider free
of caching concerns so it stays simple to test in isolation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.market_data.cache import Cache
from app.market_data.capabilities import ProviderCapabilities
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Candle, PreviousClose, Quote, Timeframe

DEFAULT_CANDLES_TTL_SECONDS = 30.0
DEFAULT_QUOTE_TTL_SECONDS = 5.0
DEFAULT_PREVIOUS_CLOSE_TTL_SECONDS = 3600.0


class CachedMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        inner: MarketDataProvider,
        cache: Cache,
        candles_ttl: float = DEFAULT_CANDLES_TTL_SECONDS,
        quote_ttl: float = DEFAULT_QUOTE_TTL_SECONDS,
        previous_close_ttl: float = DEFAULT_PREVIOUS_CLOSE_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._candles_ttl = candles_ttl
        self._quote_ttl = quote_ttl
        self._previous_close_ttl = previous_close_ttl

    def capabilities(self) -> ProviderCapabilities:
        return self._inner.capabilities()

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 200,
        before: Optional[datetime] = None,
    ) -> list[Candle]:
        # (FINAL TERMINAL POLISH PASS #1: lazy pan-left pagination) `before`
        # is part of the cache key -- an older-history page and the base
        # "most recent" page for the same symbol/timeframe/limit are
        # different requests and must never collide in the cache.
        cursor_key = before.isoformat() if before is not None else "latest"
        key = f"candles:{symbol}:{timeframe.value}:{limit}:{cursor_key}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        candles = self._inner.get_candles(symbol, timeframe, limit, before=before)
        self._cache.set(key, candles, self._candles_ttl)
        return candles

    def get_latest_quote(self, symbol: str) -> Quote:
        key = f"quote:{symbol}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        quote = self._inner.get_latest_quote(symbol)
        self._cache.set(key, quote, self._quote_ttl)
        return quote

    def get_previous_close(self, symbol: str) -> PreviousClose:
        key = f"previous_close:{symbol}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        previous_close = self._inner.get_previous_close(symbol)
        self._cache.set(key, previous_close, self._previous_close_ttl)
        return previous_close
