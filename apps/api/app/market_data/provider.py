"""The provider abstraction. Nothing outside this module should import Alpaca
directly — routes, caching, and every future consumer depend on this interface
so the data source can be swapped without touching call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

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
