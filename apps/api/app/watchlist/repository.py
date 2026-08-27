"""Watchlist storage abstraction.

InMemoryWatchlistRepository is the only implementation for now — it works
without a database connection. A SQLAlchemy-backed repository implementing
the same interface (against the `watchlists`/`watchlist_symbols` tables
already defined in app.database.models) can replace it once DATABASE_URL
points at a reachable Postgres; nothing above this interface would need to
change.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.symbols import normalize_ticker

DEFAULT_WATCHLIST_SYMBOLS = ("SPY", "QQQ", "NVDA", "AAPL", "MSFT", "META", "AMZN", "TSLA")


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    added_at: datetime


class SymbolAlreadyInWatchlistError(ValueError):
    def __init__(self, ticker: str) -> None:
        super().__init__(f"{ticker} is already in the watchlist")
        self.ticker = ticker


class SymbolNotInWatchlistError(ValueError):
    def __init__(self, ticker: str) -> None:
        super().__init__(f"{ticker} is not in the watchlist")
        self.ticker = ticker


class WatchlistRepository(ABC):
    @abstractmethod
    def list_symbols(self) -> list[WatchlistEntry]: ...

    @abstractmethod
    def add_symbol(self, ticker: str) -> WatchlistEntry: ...

    @abstractmethod
    def remove_symbol(self, ticker: str) -> None: ...


class InMemoryWatchlistRepository(WatchlistRepository):
    def __init__(self, initial_symbols: tuple[str, ...] = DEFAULT_WATCHLIST_SYMBOLS) -> None:
        self._lock = threading.Lock()
        now = datetime.now(timezone.utc)
        self._entries: dict[str, WatchlistEntry] = {
            ticker: WatchlistEntry(ticker=ticker, added_at=now) for ticker in initial_symbols
        }

    def list_symbols(self) -> list[WatchlistEntry]:
        with self._lock:
            return sorted(self._entries.values(), key=lambda e: e.ticker)

    def add_symbol(self, ticker: str) -> WatchlistEntry:
        normalized = normalize_ticker(ticker)
        with self._lock:
            if normalized in self._entries:
                raise SymbolAlreadyInWatchlistError(normalized)
            entry = WatchlistEntry(ticker=normalized, added_at=datetime.now(timezone.utc))
            self._entries[normalized] = entry
            return entry

    def remove_symbol(self, ticker: str) -> None:
        normalized = normalize_ticker(ticker)
        with self._lock:
            if normalized not in self._entries:
                raise SymbolNotInWatchlistError(normalized)
            del self._entries[normalized]
