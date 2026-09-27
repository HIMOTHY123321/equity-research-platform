"""Phase 16.1: real multi-user product completion -- server-verifiable
session revocation, and the per-user split of monitoring/alert delivery
that was global-only through Phase 16.

Revision ID: 0011_user_sessions_monitoring_alert_delivery
Revises: 0010_user_plan
Create Date: 2026-09-27
"""

import sqlalchemy as sa

from alembic import op

revision = "0011_user_sessions_monitoring_alert_delivery"
down_revision = "0010_user_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_sessions_jti", "user_sessions", ["jti"], unique=True)
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    op.create_table(
        "user_monitoring_subscriptions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("decision_monitoring_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("preferred_timeframes", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "symbol", name="uq_user_monitoring_symbol"),
    )
    op.create_index("ix_user_monitoring_subscriptions_user_id", "user_monitoring_subscriptions", ["user_id"])
    op.create_index("ix_user_monitoring_subscriptions_symbol", "user_monitoring_subscriptions", ["symbol"])

    op.create_table(
        "user_alert_deliveries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "alert_id", name="uq_user_alert_delivery"),
    )
    op.create_index("ix_user_alert_deliveries_user_id", "user_alert_deliveries", ["user_id"])
    op.create_index("ix_user_alert_deliveries_alert_id", "user_alert_deliveries", ["alert_id"])
    op.create_index("ix_user_alert_deliveries_symbol", "user_alert_deliveries", ["symbol"])

    op.create_table(
        "user_alert_preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "alert_type", name="uq_user_alert_preference"),
    )
    op.create_index("ix_user_alert_preferences_user_id", "user_alert_preferences", ["user_id"])
    op.create_index("ix_user_alert_preferences_alert_type", "user_alert_preferences", ["alert_type"])


def downgrade() -> None:
    op.drop_table("user_alert_preferences")
    op.drop_table("user_alert_deliveries")
    op.drop_table("user_monitoring_subscriptions")
    op.drop_table("user_sessions")
