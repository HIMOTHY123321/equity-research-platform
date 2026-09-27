"""Watchlist storage abstraction.

Phase 16 (§9/§96): `SqlAlchemyWatchlistRepository` is now the real,
user-scoped, multi-tenant implementation, built against the
`watchlists`/`watchlist_symbols`/`symbols` tables already defined in
app.database.models -- `symbols` rows are shared/global (the same AAPL row
is reused across every user's watchlist), while `watchlists`/
`watchlist_symbols` rows belong to exactly one user, enforced by scoping
every query on `user_id`, never trusting a caller-supplied filter alone.

InMemoryWatchlistRepository remains for tests/fixtures that don't need
persistence or multi-tenancy at all -- it must never be wired into a
real deployment (see app.api.deps.get_watchlist_repository)."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Base, Symbol, Watchlist, WatchlistSymbol
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


class SqlAlchemyWatchlistRepository(WatchlistRepository):
    """One instance is scoped to exactly one user's default watchlist for
    the lifetime of one request -- every query below filters on
    `Watchlist.user_id == self._user_id`, so there is no code path in this
    class that can read or write another user's rows, even if a caller
    passed a bad ticker or malformed input."""

    def __init__(self, session: Session, user_id: UUID) -> None:
        self._session = session
        self._user_id = user_id
        Base.metadata.create_all(
            bind=session.get_bind(),
            tables=[Symbol.__table__, Watchlist.__table__, WatchlistSymbol.__table__],
            checkfirst=True,
        )

    def _get_or_create_default_watchlist(self) -> Watchlist:
        watchlist = self._session.execute(
            select(Watchlist).where(Watchlist.user_id == self._user_id, Watchlist.is_default.is_(True))
        ).scalar_one_or_none()
        if watchlist is not None:
            return watchlist

        watchlist = Watchlist(user_id=self._user_id, name="My Watchlist", is_default=True)
        self._session.add(watchlist)
        self._session.commit()
        self._session.refresh(watchlist)

        # First-time seed only (mirrors InMemoryWatchlistRepository's own
        # default-symbols behavior) -- a brand-new user gets a populated
        # starting watchlist instead of an empty one; every subsequent
        # call finds the row above and never reseeds.
        now = datetime.now(timezone.utc)
        for ticker in DEFAULT_WATCHLIST_SYMBOLS:
            symbol = self._get_or_create_symbol(ticker)
            self._session.add(WatchlistSymbol(watchlist_id=watchlist.id, symbol_id=symbol.id, added_at=now))
        self._session.commit()
        return watchlist

    def _get_or_create_symbol(self, ticker: str) -> Symbol:
        symbol = self._session.execute(select(Symbol).where(Symbol.ticker == ticker)).scalar_one_or_none()
        if symbol is not None:
            return symbol
        symbol = Symbol(ticker=ticker)
        self._session.add(symbol)
        self._session.commit()
        self._session.refresh(symbol)
        return symbol

    def list_symbols(self) -> list[WatchlistEntry]:
        watchlist = self._get_or_create_default_watchlist()
        rows = self._session.execute(
            select(WatchlistSymbol, Symbol)
            .join(Symbol, WatchlistSymbol.symbol_id == Symbol.id)
            .where(WatchlistSymbol.watchlist_id == watchlist.id)
            .order_by(Symbol.ticker)
        ).all()
        return [WatchlistEntry(ticker=symbol.ticker, added_at=entry.added_at) for entry, symbol in rows]

    def add_symbol(self, ticker: str) -> WatchlistEntry:
        normalized = normalize_ticker(ticker)
        watchlist = self._get_or_create_default_watchlist()
        symbol = self._get_or_create_symbol(normalized)

        existing = self._session.execute(
            select(WatchlistSymbol).where(
                WatchlistSymbol.watchlist_id == watchlist.id, WatchlistSymbol.symbol_id == symbol.id
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise SymbolAlreadyInWatchlistError(normalized)

        entry = WatchlistSymbol(watchlist_id=watchlist.id, symbol_id=symbol.id)
        self._session.add(entry)
        self._session.commit()
        self._session.refresh(entry)
        return WatchlistEntry(ticker=normalized, added_at=entry.added_at)

    def remove_symbol(self, ticker: str) -> None:
        normalized = normalize_ticker(ticker)
        watchlist = self._get_or_create_default_watchlist()
        symbol = self._session.execute(
            select(Symbol).where(Symbol.ticker == normalized)
        ).scalar_one_or_none()
        entry = (
            self._session.execute(
                select(WatchlistSymbol).where(
                    WatchlistSymbol.watchlist_id == watchlist.id, WatchlistSymbol.symbol_id == symbol.id
                )
            ).scalar_one_or_none()
            if symbol is not None
            else None
        )
        if entry is None:
            raise SymbolNotInWatchlistError(normalized)
        self._session.delete(entry)
        self._session.commit()
