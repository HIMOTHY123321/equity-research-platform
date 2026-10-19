"""Phase 16 (§7/§118): migration 0009 must create exactly the Phase 13-15
tables (plus auth columns on `users`) with the same columns as the current
ORM models in app.database.models, and its downgrade must cleanly reverse
every change. Run against SQLite here as a structural smoke test (batch
mode makes the ALTER COLUMN portable) -- production migrations run against
Postgres; see docs for the Postgres migration procedure.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.database.models import Base

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0009_decision_alerts_monitoring_validation_auth.py"
)

_NEW_TABLES = (
    "decision_plans",
    "decision_transitions",
    "decision_condition_evaluations",
    "decision_evidence_diff_snapshots",
    "alert_events",
    "alert_acknowledgements",
    "alert_preferences",
    "monitoring_subscriptions",
    "alert_outcomes",
    "alert_horizon_outcomes",
    "signal_gate_versions",
    "signal_gate_results",
)

_NEW_USER_COLUMNS = {"password_hash", "status", "role", "timezone", "updated_at"}


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0009", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fresh_engine_with_pre_0009_users_table() -> sa.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE users (id CHAR(32) PRIMARY KEY, "
                "email VARCHAR(255) UNIQUE NOT NULL, created_at DATETIME)"
            )
        )
    return engine


def test_upgrade_creates_every_new_table_matching_the_current_orm_columns():
    engine = _fresh_engine_with_pre_0009_users_table()
    migration = _load_migration()

    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        table_names = set(inspector.get_table_names())
        assert set(_NEW_TABLES).issubset(table_names)

        for table in _NEW_TABLES:
            migrated_columns = {c["name"] for c in inspector.get_columns(table)}
            orm_columns = {c.name for c in Base.metadata.tables[table].columns}
            assert migrated_columns == orm_columns, f"{table} column mismatch"


def test_upgrade_adds_every_new_auth_column_to_users():
    engine = _fresh_engine_with_pre_0009_users_table()
    migration = _load_migration()

    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        columns = {c["name"] for c in sa.inspect(conn).get_columns("users")}
    assert _NEW_USER_COLUMNS.issubset(columns)


def test_downgrade_cleanly_reverses_the_upgrade():
    engine = _fresh_engine_with_pre_0009_users_table()
    migration = _load_migration()

    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        table_names = set(inspector.get_table_names())
        assert table_names == {"users"}
        columns = {c["name"] for c in inspector.get_columns("users")}
        assert columns == {"id", "email", "created_at"}


# ---------------------------------------------------------------------------
# Phase 16.1: migration 0011 -- user_sessions, user_monitoring_subscriptions,
# user_alert_deliveries, user_alert_preferences. Same structural-smoke-test
# discipline as 0009 above, run against a DB already at the (Phase 16) 0010
# state (a bare `users` table is enough -- 0011 only adds FKs to it, never
# alters it).
# ---------------------------------------------------------------------------

_MIGRATION_0011_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0011_user_sessions_monitoring_alert_delivery.py"
)

_0011_NEW_TABLES = (
    "user_sessions",
    "user_monitoring_subscriptions",
    "user_alert_deliveries",
    "user_alert_preferences",
)


def _load_migration_0011():
    spec = importlib.util.spec_from_file_location("migration_0011", _MIGRATION_0011_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Phase 20: migration 0013 later adds push_status/push_attempted_at/
# push_error columns to user_alert_deliveries (one of 0011's own new
# tables). It never depends on 0012's watchlist tables existing, so it's
# safe to apply directly on top of 0011 here without reproducing the
# whole chain in between.
_MIGRATION_0013_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0013_push_notifications.py"
)


def _load_migration_0013():
    spec = importlib.util.spec_from_file_location("migration_0013", _MIGRATION_0013_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fresh_engine_with_pre_0011_users_table() -> sa.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE users (id CHAR(32) PRIMARY KEY, "
                "email VARCHAR(255) UNIQUE NOT NULL, created_at DATETIME)"
            )
        )
    return engine


def test_0011_upgrade_creates_every_new_table_matching_the_current_orm_columns():
    engine = _fresh_engine_with_pre_0011_users_table()
    migration = _load_migration_0011()

    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    # Phase 20: user_alert_deliveries gains three more columns under
    # 0013 -- apply that too so this comparison is against the schema as
    # it exists after every migration that touches these tables, not
    # just 0011 in isolation (which would now always mismatch the
    # current ORM model).
    migration_0013 = _load_migration_0013()
    with engine.begin() as conn:
        migration_0013.op = Operations(MigrationContext.configure(conn))
        migration_0013.upgrade()

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        table_names = set(inspector.get_table_names())
        assert set(_0011_NEW_TABLES).issubset(table_names)

        for table in _0011_NEW_TABLES:
            migrated_columns = {c["name"] for c in inspector.get_columns(table)}
            orm_columns = {c.name for c in Base.metadata.tables[table].columns}
            assert migrated_columns == orm_columns, f"{table} column mismatch"


def test_0011_downgrade_cleanly_reverses_the_upgrade():
    engine = _fresh_engine_with_pre_0011_users_table()
    migration = _load_migration_0011()

    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()

    with engine.connect() as conn:
        table_names = set(sa.inspect(conn).get_table_names())
        assert table_names == {"users"}
