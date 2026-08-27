"""Phase 7: setup ledger, research runs, and outcomes

Revision ID: 0002_research_tables
Revises: 0001_initial_schema
Create Date: 2026-08-25

Unlike 0001 (hand-authored raw SQL, Postgres-only), this migration uses
Alembic's dialect-agnostic `op.create_table` so it applies cleanly to both
Postgres and SQLite -- see docs/decisions/0008-setup-ledger-and-replay-engine.md
for why these tables are new rather than built on 0001's schema, and for why
0001 itself is not retrofitted for SQLite (local SQLite dev instead bootstraps
just these three tables directly; this migration remains authoritative for
Postgres deployments, where both 0001 and 0002 apply in sequence).
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_research_tables"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False, index=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="running", index=True),
        sa.Column("config_hash", sa.String(32), nullable=False, index=True),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("dataset_provenance", sa.JSON(), nullable=False),
        sa.Column("bars_processed", sa.Integer()),
        sa.Column("qualified_count", sa.Integer()),
        sa.Column("rejected_count", sa.Integer()),
        sa.Column("runtime_seconds", sa.Float()),
        sa.Column("error", sa.String(2000)),
        sa.Column("summary", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "setup_ledger_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "research_run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("setup_id", sa.String(80), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("setup_type", sa.String(64), nullable=False, index=True),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("candidate_candle_timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("detection_snapshot", sa.JSON(), nullable=False),
        sa.Column("current_state", sa.String(16), nullable=False, index=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("research_run_id", "setup_id", name="uq_run_setup"),
    )

    op.create_table(
        "setup_outcomes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "ledger_entry_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("setup_ledger_entries.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("setup_outcomes")
    op.drop_table("setup_ledger_entries")
    op.drop_table("research_runs")
