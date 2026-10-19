"""Long-Term Investing Research scan (app.long_term_research) -- a
feature wholly separate from the Decision Engine's short/medium-term
setup tracking.

Adds:
- `long_term_push_enabled` column on the existing `user_push_preferences`
  table: a SEPARATE on/off switch from `push_enabled`, sharing the same
  encrypted Pushover destination key.
- `long_term_research_snapshots`: one append-only, frozen row per
  (symbol, as_of) daily research conclusion -- never updated in place.
- `long_term_scheduled_scan_runs`: idempotency guard for the externally
  (cron-)triggered daily scan only; the manual "RUN LONG-TERM SCAN"
  button never writes here.

Revision ID: 0014_long_term_research
Revises: 0013_push_notifications
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0014_long_term_research"
down_revision = "0013_push_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_push_preferences",
        sa.Column("long_term_push_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "long_term_research_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float, nullable=True),
        sa.Column("research_state", sa.String(64), nullable=False),
        sa.Column("evidence_quality", sa.String(32), nullable=False),
        sa.Column("factors_json", sa.JSON, nullable=False),
        sa.Column("positive_evidence_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("negative_evidence_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("contradictions_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("missing_evidence_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("what_would_change_state", sa.String(1000), nullable=False),
        sa.Column("market_data_provider", sa.String(32), nullable=False),
        sa.Column("fundamentals_provider", sa.String(32), nullable=False),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("ai_summary", sa.String(4000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_long_term_research_snapshots_symbol", "long_term_research_snapshots", ["symbol"])
    op.create_index("ix_long_term_research_snapshots_as_of", "long_term_research_snapshots", ["as_of"])
    op.create_index(
        "ix_ltr_snapshot_symbol_as_of", "long_term_research_snapshots", ["symbol", "as_of"]
    )

    op.create_table(
        "long_term_scheduled_scan_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("run_date", sa.String(10), nullable=False, unique=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_long_term_scheduled_scan_runs_run_date",
        "long_term_scheduled_scan_runs",
        ["run_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_long_term_scheduled_scan_runs_run_date", table_name="long_term_scheduled_scan_runs")
    op.drop_table("long_term_scheduled_scan_runs")

    op.drop_index("ix_ltr_snapshot_symbol_as_of", table_name="long_term_research_snapshots")
    op.drop_index("ix_long_term_research_snapshots_as_of", table_name="long_term_research_snapshots")
    op.drop_index("ix_long_term_research_snapshots_symbol", table_name="long_term_research_snapshots")
    op.drop_table("long_term_research_snapshots")

    op.drop_column("user_push_preferences", "long_term_push_enabled")
