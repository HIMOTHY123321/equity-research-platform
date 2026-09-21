"""The provider abstraction. Nothing outside this module should import Alpaca
directly — routes, caching, and every future consumer depend on this interface
so the data source can be swapped without touching call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.market_data.capabilities import ProviderCapabilities
from app.schemas.market_data import Candle, PreviousClose, Quote, Timeframe


class MarketDataProvider(ABC):
    @abstractmethod
    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 200,
    ) -> list[Candle]:
        """Return normalized candles, oldest first, deduplicated, no fabricated bars."""

    @abstractmethod
    def get_latest_quote(self, symbol: str) -> Quote:
        """Return the most recent bid/ask quote."""

    @abstractmethod
    def get_previous_close(self, symbol: str) -> PreviousClose:
        """Return the close of the last fully completed trading day before today."""

    def capabilities(self) -> ProviderCapabilities:
        """What this specific implementation truthfully supports (Phase 12.1
        #C/#D) -- streaming vs. polling, measured/unmeasured delay, a safe
        poll floor. Never a hardcoded assumption made elsewhere in the
        codebase; app.live.service.LiveMarketService is the only consumer
        that should read this to decide its cadence/labeling.

        Concrete (not abstract) with a conservative, honest "capabilities
        unknown" default -- real providers (yfinance/alpaca) override this
        with their actual, verified values; the many test-only fake
        providers across the suite never need to know or care about live
        cadence, so they are never forced to implement it."""
        return ProviderCapabilities(
            real_time_quotes=False,
            streaming_quotes=False,
            streaming_trades=False,
            streaming_bars=False,
            streaming_news=False,
            historical_intraday=False,
            quote_delay_seconds=None,
            news_delay_seconds=None,
            min_poll_interval_seconds=5.0,
        )
