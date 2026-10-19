"""Phase 20: structural smoke test for migration 0013, same discipline as
test_migrations.py's 0009/0011/0012 coverage -- run against a fresh SQLite
engine seeded with the exact pre-0013 schema, using
Operations(MigrationContext.configure(conn)) so `migration.op.*` calls
work exactly as they would under a real `alembic upgrade head`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0013_push_notifications.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0013", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fresh_pre_0013_engine() -> sa.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
        conn.execute(
            sa.text(
                "CREATE TABLE user_alert_deliveries (id CHAR(32) PRIMARY KEY, user_id CHAR(32), "
                "alert_id VARCHAR(64), symbol VARCHAR(16), delivered_at DATETIME, acknowledged_at DATETIME)"
            )
        )
    return engine


def test_upgrade_creates_user_push_preferences_table():
    engine = _fresh_pre_0013_engine()
    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        tables = sa.inspect(conn).get_table_names()
        columns = {c["name"] for c in sa.inspect(conn).get_columns("user_push_preferences")}
    assert "user_push_preferences" in tables
    assert {"push_enabled", "pushover_user_key_encrypted"} <= columns


def test_upgrade_adds_push_columns_to_user_alert_deliveries():
    engine = _fresh_pre_0013_engine()
    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    with engine.connect() as conn:
        columns = {c["name"] for c in sa.inspect(conn).get_columns("user_alert_deliveries")}
    assert {"push_status", "push_attempted_at", "push_error"} <= columns


def test_user_push_preferences_user_id_is_unique():
    import uuid

    engine = _fresh_pre_0013_engine()
    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()

    user_id = uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO users (id) VALUES (:id)"), {"id": user_id})
        conn.execute(
            sa.text("INSERT INTO user_push_preferences (id, user_id, push_enabled) VALUES (:id, :uid, 1)"),
            {"id": uuid.uuid4().hex, "uid": user_id},
        )

    with engine.connect() as conn:
        try:
            with conn.begin():
                conn.execute(
                    sa.text(
                        "INSERT INTO user_push_preferences (id, user_id, push_enabled) VALUES (:id, :uid, 0)"
                    ),
                    {"id": uuid.uuid4().hex, "uid": user_id},
                )
            raised = False
        except sa.exc.IntegrityError:
            raised = True
    assert raised is True


def test_downgrade_removes_everything_it_added():
    engine = _fresh_pre_0013_engine()
    migration = _load_migration()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()

    with engine.connect() as conn:
        tables = sa.inspect(conn).get_table_names()
        columns = {c["name"] for c in sa.inspect(conn).get_columns("user_alert_deliveries")}
    assert "user_push_preferences" not in tables
    assert not ({"push_status", "push_attempted_at", "push_error"} & columns)
