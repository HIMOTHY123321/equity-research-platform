"""The provider abstraction (#A). Nothing outside app.news.*_provider should
construct a NormalizedNewsArticle directly or import a concrete provider --
routes and every future consumer depend on this interface (same convention
as app.market_data.provider.MarketDataProvider) so the news data source can
be swapped without touching call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.news.schemas import NormalizedNewsArticle


class NewsProvider(ABC):
    @abstractmethod
    def fetch_symbol_news(
        self, symbol: str, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        """Return normalized articles mentioning `symbol` with
        `start <= published_at <= end` AND `published_at <= as_of` -- an
        article published after `as_of` must never be returned, regardless
        of whether it falls inside [start, end] (#E)."""

    @abstractmethod
    def fetch_market_news(
        self, start: datetime, end: datetime, as_of: datetime
    ) -> list[NormalizedNewsArticle]:
        """Same as_of/window discipline as fetch_symbol_news, for
        market-wide (not single-symbol-scoped) articles."""
