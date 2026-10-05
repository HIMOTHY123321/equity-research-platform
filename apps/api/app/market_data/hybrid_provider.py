"""Phase 19.2: the smallest clean composition that lets Twelve Data serve
genuine live/latest quotes while yfinance stays the historical/research
source of truth -- never a single exclusive REST provider for everything.

Why this shape: MarketDataProvider is already the one seam every consumer
(routes, LiveMarketService, CachedMarketDataProvider) depends on, never a
concrete class. A provider that itself delegates to two other
MarketDataProvider instances slots into that exact seam with zero changes
anywhere else -- `app.api.deps.get_market_data_provider()` just wraps this
in the same CachedMarketDataProvider every other provider already gets,
so caching/coalescing (free-tier safety) comes for free, not reimplemented
here.

Split of responsibilities:
- get_candles / get_previous_close: ALWAYS yfinance. Twelve Data's free-tier
  REST credits are small and precious; yfinance already handles broad
  historical/research pulls well, so there is nothing to gain by spending
  Twelve Data credits on history.
- get_latest_quote: Twelve Data first (genuine current price when the
  account is working), falls back to yfinance on RateLimitError or
  ProviderError (429, timeout, 5xx, transient network failure, or Twelve
  Data's own embedded error payload for an unsupported request) -- but
  AuthenticationError and InvalidSymbolError are never caught: a bad key or
  a genuinely unknown symbol must stay visible, never silently papered
  over by a fallback that would just hide a real misconfiguration.

This class never touches REAL TIME eligibility at all -- that is decided
exclusively by app.live.service.LiveMarketService from genuine WebSocket
ticks (see app.live.streaming.TwelveDataStreamingProvider). A fallback
quote from this class is REST, always, and is wired into
LiveMarketService's poll loop (app.live.service._poll_loop) only when no
streaming provider is configured at all -- the two paths are mutually
exclusive per `LiveMarketService._use_streaming()`, so a yfinance- or
Twelve-Data-REST-sourced quote can never masquerade as a live tick.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.market_data.capabilities import ProviderCapabilities
from app.market_data.exceptions import ProviderError, RateLimitError
from app.market_data.provider import MarketDataProvider
from app.schemas.market_data import Candle, PreviousClose, Quote, Timeframe

logger = logging.getLogger(__name__)

DEFAULT_PRIMARY_NAME = "twelve_data"
DEFAULT_HISTORICAL_NAME = "yfinance"


class HybridMarketDataProvider(MarketDataProvider):
    def __init__(
        self,
        primary: MarketDataProvider,
        historical: MarketDataProvider,
        primary_name: str = DEFAULT_PRIMARY_NAME,
        historical_name: str = DEFAULT_HISTORICAL_NAME,
    ) -> None:
        self._primary = primary
        self._historical = historical
        self._primary_name = primary_name
        self._historical_name = historical_name

    def capabilities(self) -> ProviderCapabilities:
        primary_caps = self._primary.capabilities()
        historical_caps = self._historical.capabilities()
        return ProviderCapabilities(
            real_time_quotes=primary_caps.real_time_quotes,
            streaming_quotes=primary_caps.streaming_quotes,
            streaming_trades=primary_caps.streaming_trades,
            streaming_bars=primary_caps.streaming_bars,
            streaming_news=primary_caps.streaming_news,
            # Historical capability reflects whichever provider actually
            # serves get_candles -- always the historical provider here.
            historical_intraday=historical_caps.historical_intraday,
            quote_delay_seconds=primary_caps.quote_delay_seconds,
            news_delay_seconds=primary_caps.news_delay_seconds,
            # The slower (more conservative) of the two floors -- never
            # poll faster than either provider's own honest limit.
            min_poll_interval_seconds=max(
                primary_caps.min_poll_interval_seconds, historical_caps.min_poll_interval_seconds
            ),
        )

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 200,
        before: Optional[datetime] = None,
    ) -> list[Candle]:
        return self._historical.get_candles(symbol, timeframe, limit=limit, before=before)

    def get_previous_close(self, symbol: str) -> PreviousClose:
        return self._historical.get_previous_close(symbol)

    def get_latest_quote(self, symbol: str) -> Quote:
        try:
            quote = self._primary.get_latest_quote(symbol)
        except (RateLimitError, ProviderError) as exc:
            logger.warning(
                "Twelve Data latest quote unavailable for %s (%s) -- falling back to yfinance",
                symbol,
                type(exc).__name__,
            )
            quote = self._historical.get_latest_quote(symbol)
            return quote.model_copy(update={"provider": self._historical_name})
        return quote.model_copy(update={"provider": self._primary_name})
