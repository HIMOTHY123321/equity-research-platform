"""Phase 19.5: SqlAlchemyWatchlistRepository against a real (SQLite-
backed) session -- the exact MultipleResultsFound crash
(app.watchlist.repository._get_or_create_default_watchlist) and its fix,
plus repair_duplicate_default_watchlists for already-corrupted legacy
data. Base.metadata.create_all (called by the repository's own
__init__) always includes the new uq_watchlists_user_default partial
index from app.database.models.Watchlist.__table_args__, so these tests
also implicitly prove the index is wired correctly for a brand-new
deployment, not just migration 0012's repair path for an existing one.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.models import Watchlist, WatchlistSymbol
from app.watchlist.repository import (
    DEFAULT_WATCHLIST_SYMBOLS,
    SqlAlchemyWatchlistRepository,
    repair_duplicate_default_watchlists,
)


def _count_default_watchlists(session, user_id) -> int:
    return len(
        session.execute(
            select(Watchlist).where(Watchlist.user_id == user_id, Watchlist.is_default.is_(True))
        )
        .scalars()
        .all()
    )


def test_user_with_no_default_watchlist_gets_one_created_and_seeded(file_session_factory):
    session = file_session_factory()()
    user_id = uuid.uuid4()
    repo = SqlAlchemyWatchlistRepository(session, user_id)

    entries = repo.list_symbols()

    assert {e.ticker for e in entries} == set(DEFAULT_WATCHLIST_SYMBOLS)
    assert _count_default_watchlists(session, user_id) == 1


def test_user_with_one_default_watchlist_reuses_it_without_reseeding(file_session_factory):
    session = file_session_factory()()
    user_id = uuid.uuid4()
    repo = SqlAlchemyWatchlistRepository(session, user_id)
    repo.list_symbols()  # creates + seeds
    repo.remove_symbol("SPY")  # mutate so a reseed would be detectable

    entries = repo.list_symbols()

    assert "SPY" not in {e.ticker for e in entries}
    assert _count_default_watchlists(session, user_id) == 1


def test_concurrent_default_watchlist_creation_does_not_duplicate(file_session_factory):
    """The exact production race: two near-simultaneous requests for the
    SAME user (e.g. two dashboard panels both calling GET /api/watchlist
    on first page load) must never both succeed at creating a default
    watchlist -- the loser must detect the winner's row via
    uq_watchlists_user_default and return it, never raise, never create
    a second row."""
    path = file_session_factory.new_db_path()
    session_a = file_session_factory(path)()
    session_b = file_session_factory(path)()
    user_id = uuid.uuid4()
    repo_a = SqlAlchemyWatchlistRepository(session_a, user_id)
    repo_b = SqlAlchemyWatchlistRepository(session_b, user_id)

    # Both see "no default watchlist yet" before either commits -- the
    # exact window the race lives in.
    assert repo_a._select_default_watchlist() is None
    assert repo_b._select_default_watchlist() is None

    winner = repo_b._get_or_create_default_watchlist()
    loser_result = repo_a._get_or_create_default_watchlist()

    assert loser_result.id == winner.id
    assert _count_default_watchlists(session_a, user_id) == 1


def test_repeated_requests_after_a_restart_never_create_a_second_default(file_session_factory):
    """Simulates a process restart against the same on-disk DB: a fresh
    Session/repository instance for the same user must find the
    already-existing row, never create a second one."""
    path = file_session_factory.new_db_path()
    session_1 = file_session_factory(path)()
    user_id = uuid.uuid4()
    first = SqlAlchemyWatchlistRepository(session_1, user_id)
    original = first.list_symbols()
    session_1.close()

    session_2 = file_session_factory(path)()
    second = SqlAlchemyWatchlistRepository(session_2, user_id)
    after_restart = second.list_symbols()

    assert {e.ticker for e in after_restart} == {e.ticker for e in original}
    assert _count_default_watchlists(session_2, user_id) == 1


def _drop_default_uniqueness_index(session) -> None:
    """Simulates a DB that predates migration 0012 -- the only way to get
    duplicate `is_default=True` rows back into a schema that otherwise
    always carries `uq_watchlists_user_default` via
    Watchlist.__table_args__ (every table in this suite is created
    through that same metadata, including the repository's own
    __init__). Dropping the index is exactly what the real, already-
    corrupted production database looked like before this migration ran."""
    from sqlalchemy import text

    session.execute(text("DROP INDEX uq_watchlists_user_default"))
    session.commit()


def test_legacy_user_with_duplicate_default_watchlists_crashes_before_repair(file_session_factory):
    """Reproduces the exact reported production crash directly against
    the repository: two is_default=True rows for one user makes
    scalar_one_or_none() raise MultipleResultsFound -- this is the bug
    report's root cause, proven here rather than assumed."""
    from sqlalchemy.exc import MultipleResultsFound

    session = file_session_factory()()
    user_id = uuid.uuid4()
    repo = SqlAlchemyWatchlistRepository(session, user_id)
    repo.list_symbols()  # creates the first default watchlist

    _drop_default_uniqueness_index(session)
    session.add(Watchlist(user_id=user_id, name="My Watchlist", is_default=True))
    session.commit()

    with pytest.raises(MultipleResultsFound):
        repo.list_symbols()


def test_repair_merges_duplicate_symbols_and_leaves_exactly_one_default_watchlist(file_session_factory):
    session = file_session_factory()()
    user_id = uuid.uuid4()
    repo = SqlAlchemyWatchlistRepository(session, user_id)
    original_entries = {e.ticker for e in repo.list_symbols()}

    # Recreate the corrupted (pre-migration-0012) state: a second (newer)
    # default watchlist for the same user with a DIFFERENT symbol the
    # canonical one never had.
    _drop_default_uniqueness_index(session)
    duplicate = Watchlist(user_id=user_id, name="My Watchlist", is_default=True)
    session.add(duplicate)
    session.commit()
    extra_symbol = repo._get_or_create_symbol("GOOGL")
    session.add(WatchlistSymbol(watchlist_id=duplicate.id, symbol_id=extra_symbol.id))
    session.commit()
    assert _count_default_watchlists(session, user_id) == 2

    removed = repair_duplicate_default_watchlists(session)

    assert removed == 1
    assert _count_default_watchlists(session, user_id) == 1
    repaired_entries = {e.ticker for e in repo.list_symbols()}
    assert repaired_entries == original_entries | {"GOOGL"}


def test_repair_is_a_no_op_for_users_with_a_single_default_watchlist(file_session_factory):
    session = file_session_factory()()
    user_id = uuid.uuid4()
    repo = SqlAlchemyWatchlistRepository(session, user_id)
    repo.list_symbols()

    removed = repair_duplicate_default_watchlists(session)

    assert removed == 0
    assert _count_default_watchlists(session, user_id) == 1


def test_the_unique_index_itself_rejects_a_second_default_watchlist_insert(file_session_factory):
    """Belt-and-suspenders: proves uq_watchlists_user_default is actually
    present and enforced on a brand-new (post-fix) schema, independent
    of the repository's own race-recovery code path."""
    session = file_session_factory()()
    user_id = uuid.uuid4()
    repo = SqlAlchemyWatchlistRepository(session, user_id)
    repo.list_symbols()

    session.add(Watchlist(user_id=user_id, name="My Watchlist", is_default=True))
    with pytest.raises(IntegrityError):
        session.commit()
