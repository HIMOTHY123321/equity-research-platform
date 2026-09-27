"""Phase 16 (§6): Decision Engine, Alerts, Monitoring, and Signal
Validation Gate tables (Phase 13-15), plus auth columns on `users`.

Revision ID: 0009_decision_alerts_monitoring_validation_auth
Revises: 0008_catalyst_relevance
Create Date: 2026-09-26

These tables have existed since Phase 13-15 but were, until now, only ever
created at runtime via `Base.metadata.create_all(..., checkfirst=True)`
(app.main.lifespan and each repository's own `__init__`) -- convenient for
local SQLite development, but not a real production migration story.
This migration brings them under Alembic, matching every table's exact
current schema in app/database/models.py, with zero behavior change.
`checkfirst=True` runtime creation remains harmless for dev/test after
this (it becomes a no-op once the migration has already created the
table), so no application code needs to change alongside this migration.
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_decision_alerts_monitoring_validation_auth"
down_revision = "0008_catalyst_relevance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Phase 13: Decision Engine ------------------------------------
    op.create_table(
        "decision_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("decision_plan_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False, index=True),
        sa.Column("setup_id", sa.String(64), nullable=False, index=True),
        sa.Column("setup_type", sa.String(64), nullable=False, index=True),
        sa.Column("direction", sa.String(16), nullable=False, index=True),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "decision_transitions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("transition_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("decision_plan_id", sa.String(64), nullable=False, index=True),
        sa.Column("from_state", sa.String(32), nullable=True),
        sa.Column("to_state", sa.String(32), nullable=False, index=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "decision_condition_evaluations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("decision_plan_id", sa.String(64), nullable=False, index=True),
        sa.Column("condition_id", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "decision_evidence_diff_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("decision_plan_id", sa.String(64), nullable=False, index=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("classification", sa.String(16), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- Phase 14: Alerts + monitoring universe -----------------------
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("alert_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("decision_plan_id", sa.String(64), nullable=True, index=True),
        sa.Column("alert_type", sa.String(32), nullable=False, index=True),
        sa.Column("severity", sa.String(16), nullable=False, index=True),
        sa.Column("origin", sa.String(32), nullable=False, index=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("dedup_key", sa.String(255), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("dedup_key", name="uq_alert_events_dedup_key"),
    )

    op.create_table(
        "alert_acknowledgements",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("alert_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )

    op.create_table(
        "alert_preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("alert_type", sa.String(32), nullable=False, unique=True, index=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "monitoring_subscriptions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False, unique=True, index=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("decision_monitoring_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("preferred_timeframes", sa.JSON(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )

    # --- Phase 14.1 / 15: outcome resolution + Signal Validation Gate --
    op.create_table(
        "alert_outcomes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("outcome_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("alert_id", sa.String(64), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("alert_id", name="uq_alert_outcomes_alert_id"),
    )

    op.create_table(
        "alert_horizon_outcomes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("outcome_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("alert_id", sa.String(64), nullable=False, index=True),
        sa.Column("horizon_bars", sa.Integer(), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "alert_id", "horizon_bars", name="uq_alert_horizon_outcomes_alert_horizon"
        ),
    )

    op.create_table(
        "signal_gate_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("gate_version", sa.String(32), nullable=False, unique=True, index=True),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "signal_gate_results",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("gate_version", sa.String(32), nullable=False, index=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("decision", sa.String(32), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- Phase 16: real auth on the existing `users` table -------------
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=False, server_default=""))
    op.add_column(
        "users", sa.Column("status", sa.String(32), nullable=False, server_default="active")
    )
    op.add_column("users", sa.Column("role", sa.String(32), nullable=False, server_default="user"))
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/New_York"),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    # The blank server_default above exists only so pre-existing rows (if
    # any) don't violate NOT NULL -- it is never a valid bcrypt hash, so
    # any such row simply cannot authenticate until an admin resets it.
    # batch_alter_table (not a bare op.alter_column) so this also works on
    # SQLite, which cannot ALTER COLUMN ... DROP DEFAULT directly.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("password_hash", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "updated_at")
    op.drop_column("users", "timezone")
    op.drop_column("users", "role")
    op.drop_column("users", "status")
    op.drop_column("users", "password_hash")

    op.drop_table("signal_gate_results")
    op.drop_table("signal_gate_versions")
    op.drop_table("alert_horizon_outcomes")
    op.drop_table("alert_outcomes")
    op.drop_table("monitoring_subscriptions")
    op.drop_table("alert_preferences")
    op.drop_table("alert_acknowledgements")
    op.drop_table("alert_events")
    op.drop_table("decision_evidence_diff_snapshots")
    op.drop_table("decision_condition_evaluations")
    op.drop_table("decision_transitions")
    op.drop_table("decision_plans")
