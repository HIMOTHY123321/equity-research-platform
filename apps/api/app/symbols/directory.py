"""SymbolDirectory abstraction (#3): the one seam a licensed reference-data
provider (exchange listing files, a paid security-master API, ...) plugs
into later without any route or frontend change -- callers depend only on
this ABC, never on `StaticSymbolDirectory` directly (same
provider-abstraction convention as `app.market_data.provider`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.symbols.schemas import SymbolMatch


class SymbolDirectory(ABC):
    @abstractmethod
    def search(
        self, query: str, *, watchlist_tickers: Optional[list[str]] = None, limit: int = 20
    ) -> list[SymbolMatch]:
        """Ticker and company-name search. `watchlist_tickers`, when given,
        breaks ties among equally-matched results in the caller's favor
        (#3 ranking tier 5) -- never changes whether something matches."""
        ...

    @abstractmethod
    def get(self, ticker: str) -> Optional[SymbolMatch]:
        """Exact-ticker lookup, used to validate a typed/URL-supplied
        symbol without a full search (#4: 'Symbol not found' must be able
        to say so definitively)."""
        ...
