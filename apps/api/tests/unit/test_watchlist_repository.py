import pytest

from app.schemas.symbols import InvalidTickerError
from app.watchlist.repository import (
    DEFAULT_WATCHLIST_SYMBOLS,
    InMemoryWatchlistRepository,
    SymbolAlreadyInWatchlistError,
    SymbolNotInWatchlistError,
)


def test_default_watchlist_is_seeded():
    repo = InMemoryWatchlistRepository()
    tickers = {e.ticker for e in repo.list_symbols()}
    assert tickers == set(DEFAULT_WATCHLIST_SYMBOLS)


def test_list_symbols_is_sorted():
    repo = InMemoryWatchlistRepository()
    tickers = [e.ticker for e in repo.list_symbols()]
    assert tickers == sorted(tickers)


def test_add_symbol():
    repo = InMemoryWatchlistRepository(initial_symbols=())
    entry = repo.add_symbol("nvda")
    assert entry.ticker == "NVDA"
    assert "NVDA" in {e.ticker for e in repo.list_symbols()}


def test_add_duplicate_symbol_raises():
    repo = InMemoryWatchlistRepository(initial_symbols=("AAPL",))
    with pytest.raises(SymbolAlreadyInWatchlistError):
        repo.add_symbol("AAPL")


def test_add_invalid_ticker_raises():
    repo = InMemoryWatchlistRepository(initial_symbols=())
    with pytest.raises(InvalidTickerError):
        repo.add_symbol("123")


def test_remove_symbol():
    repo = InMemoryWatchlistRepository(initial_symbols=("AAPL",))
    repo.remove_symbol("AAPL")
    assert repo.list_symbols() == []


def test_remove_missing_symbol_raises():
    repo = InMemoryWatchlistRepository(initial_symbols=())
    with pytest.raises(SymbolNotInWatchlistError):
        repo.remove_symbol("AAPL")


def test_remove_invalid_ticker_raises():
    repo = InMemoryWatchlistRepository()
    with pytest.raises(InvalidTickerError):
        repo.remove_symbol("123")
