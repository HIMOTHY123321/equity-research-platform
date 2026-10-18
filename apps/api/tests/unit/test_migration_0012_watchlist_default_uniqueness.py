"""Phase 19.5: migration 0012 must repair any already-corrupted duplicate
`is_default=True` watchlist rows (merging symbol memberships, never
dropping data) BEFORE adding `uq_watchlists_user_default` -- creating that
index first against unrepaired data would fail outright. Same structural-
smoke-test discipline as test_migrations.py's 0009/0011 coverage: run
against a fresh SQLite engine seeded with the exact pre-0012 schema
(mirroring alembic/versions/0001_initial_schema.py's raw CREATE TABLE),
using Operations(MigrationContext.configure(conn)) so `migration.op.*`
calls work exactly as they would under a real `alembic upgrade head`.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0012_watchlist_default_uniqueness.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0012", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _uuid_str() -> str:
    # .hex (32 chars, no dashes), matching exactly what
    # postgresql.UUID(as_uuid=True)'s bind processor produces when run
    # under a non-Postgres dialect (SQLite here) -- the application's own
    # ORM-level reads/writes of these same columns go through that exact
    # processor, so the migration's queries must find rows stored in the
    # same shape a real run would have left them in.
    return uuid.uuid4().hex


def _fresh_pre_0012_engine() -> sa.Engine:
    """The exact pre-0012 shape (migration 0001's `watchlists`/
    `watchlist_symbols`/`symbols` tables, no unique index on
    `watchlists` at all) -- a stand-in for the real, already-deployed
    Supabase schema this migration must run against."""
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            sa.text("CREATE TABLE users (id CHAR(32) PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL)")
        )
        conn.execute(
            sa.text(
                "CREATE TABLE symbols (id CHAR(32) PRIMARY KEY, ticker VARCHAR(16) UNIQUE NOT NULL, "
                "name VARCHAR(255), asset_class VARCHAR(32), is_active BOOLEAN, created_at DATETIME)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE watchlists (id CHAR(32) PRIMARY KEY, user_id CHAR(32), "
                "name VARCHAR(100) NOT NULL, is_default BOOLEAN NOT NULL, created_at DATETIME, "
                "FOREIGN KEY(user_id) REFERENCES users (id))"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE watchlist_symbols (id CHAR(32) PRIMARY KEY, watchlist_id CHAR(32) NOT NULL, "
                "symbol_id CHAR(32) NOT NULL, added_at DATETIME, "
                "CONSTRAINT uq_watchlist_symbol UNIQUE (watchlist_id, symbol_id))"
            )
        )
    return engine


def _insert_user(conn, user_id: str) -> None:
    conn.execute(
        sa.text("INSERT INTO users (id, email) VALUES (:id, :email)"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )


def _insert_watchlist(conn, wl_id: str, user_id: str, is_default: bool, created_at: str) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO watchlists (id, user_id, name, is_default, created_at) "
            "VALUES (:id, :user_id, 'My Watchlist', :is_default, :created_at)"
        ),
        {"id": wl_id, "user_id": user_id, "is_default": is_default, "created_at": created_at},
    )


def _insert_symbol(conn, symbol_id: str, ticker: str) -> None:
    conn.execute(
        sa.text("INSERT INTO symbols (id, ticker, is_active) VALUES (:id, :ticker, 1)"),
        {"id": symbol_id, "ticker": ticker},
    )


def _insert_membership(conn, membership_id: str, watchlist_id: str, symbol_id: str) -> None:
    conn.execute(
        sa.text("INSERT INTO watchlist_symbols (id, watchlist_id, symbol_id) VALUES (:id, :wl, :sym)"),
        {"id": membership_id, "wl": watchlist_id, "sym": symbol_id},
    )


def test_upgrade_adds_the_unique_index_when_no_duplicates_exist():
    engine = _fresh_pre_0012_engine()
    user_id = _uuid_str()
    wl_id = _uuid_str()
    with engine.begin() as conn:
        _insert_user(conn, user_id)
        _insert_watchlist(conn, wl_id, user_id, True, "2026-01-01 00:00:00")

    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        indexes = {ix["name"] for ix in sa.inspect(conn).get_indexes("watchlists")}
    assert "uq_watchlists_user_default" in indexes


def test_upgrade_merges_duplicate_default_watchlists_onto_the_oldest_one():
    engine = _fresh_pre_0012_engine()
    user_id = _uuid_str()
    older_id, newer_id = _uuid_str(), _uuid_str()
    with engine.begin() as conn:
        _insert_user(conn, user_id)
        _insert_watchlist(conn, older_id, user_id, True, "2026-01-01 00:00:00")
        _insert_watchlist(conn, newer_id, user_id, True, "2026-06-01 00:00:00")

    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT id FROM watchlists WHERE user_id = :uid AND is_default = 1"), {"uid": user_id}
        ).all()
    assert [r[0] for r in rows] == [older_id]


def test_upgrade_preserves_the_union_of_symbols_from_every_duplicate():
    engine = _fresh_pre_0012_engine()
    user_id = _uuid_str()
    older_id, newer_id = _uuid_str(), _uuid_str()
    spy_id, qqq_id, nvda_id = _uuid_str(), _uuid_str(), _uuid_str()
    with engine.begin() as conn:
        _insert_user(conn, user_id)
        _insert_watchlist(conn, older_id, user_id, True, "2026-01-01 00:00:00")
        _insert_watchlist(conn, newer_id, user_id, True, "2026-06-01 00:00:00")
        _insert_symbol(conn, spy_id, "SPY")
        _insert_symbol(conn, qqq_id, "QQQ")
        _insert_symbol(conn, nvda_id, "NVDA")
        # Older (canonical) watchlist already has SPY.
        _insert_membership(conn, _uuid_str(), older_id, spy_id)
        # Newer (duplicate) watchlist has SPY (overlap -- must not double
        # up) plus QQQ and NVDA (unique -- must be preserved, not lost).
        _insert_membership(conn, _uuid_str(), newer_id, spy_id)
        _insert_membership(conn, _uuid_str(), newer_id, qqq_id)
        _insert_membership(conn, _uuid_str(), newer_id, nvda_id)

    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        canonical_symbol_ids = {
            r[0]
            for r in conn.execute(
                sa.text("SELECT symbol_id FROM watchlist_symbols WHERE watchlist_id = :wl"), {"wl": older_id}
            ).all()
        }
        duplicate_still_has_rows = conn.execute(
            sa.text("SELECT COUNT(*) FROM watchlist_symbols WHERE watchlist_id = :wl"), {"wl": newer_id}
        ).scalar()
        duplicate_watchlist_still_exists = conn.execute(
            sa.text("SELECT COUNT(*) FROM watchlists WHERE id = :wl"), {"wl": newer_id}
        ).scalar()

    assert canonical_symbol_ids == {spy_id, qqq_id, nvda_id}
    assert duplicate_still_has_rows == 0
    assert duplicate_watchlist_still_exists == 0


def test_upgrade_leaves_users_with_a_single_default_watchlist_untouched():
    engine = _fresh_pre_0012_engine()
    user_a, user_b = _uuid_str(), _uuid_str()
    wl_a, wl_b = _uuid_str(), _uuid_str()
    with engine.begin() as conn:
        _insert_user(conn, user_a)
        _insert_user(conn, user_b)
        _insert_watchlist(conn, wl_a, user_a, True, "2026-01-01 00:00:00")
        _insert_watchlist(conn, wl_b, user_b, True, "2026-01-01 00:00:00")

    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        remaining_ids = {
            r[0] for r in conn.execute(sa.text("SELECT id FROM watchlists WHERE is_default = 1")).all()
        }
    assert remaining_ids == {wl_a, wl_b}


def test_downgrade_drops_the_unique_index():
    engine = _fresh_pre_0012_engine()
    migration = _load_migration()

    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()

    with engine.connect() as conn:
        indexes = {ix["name"] for ix in sa.inspect(conn).get_indexes("watchlists")}
    assert "uq_watchlists_user_default" not in indexes


def test_upgrade_then_reinserting_a_second_default_watchlist_is_rejected():
    """Proves the migration's end state actually enforces the invariant
    going forward -- the real regression guard, not just "an index with
    this name exists"."""
    engine = _fresh_pre_0012_engine()
    user_id = _uuid_str()
    with engine.begin() as conn:
        _insert_user(conn, user_id)
        _insert_watchlist(conn, _uuid_str(), user_id, True, "2026-01-01 00:00:00")

    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        try:
            with conn.begin():
                _insert_watchlist(conn, _uuid_str(), user_id, True, "2026-02-01 00:00:00")
            raised = False
        except sa.exc.IntegrityError:
            raised = True
    assert raised is True
