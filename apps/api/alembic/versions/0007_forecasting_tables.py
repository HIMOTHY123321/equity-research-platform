"""Phase 12: forward forecast / outcome / validation-gate tables

Revision ID: 0007_forecasting_tables
Revises: 0006_ai_analysis_tables
Create Date: 2026-09-09

Immutable forecast ledger, outcome resolutions, and versioned forward-
validation-gate records (#F/#G/#P) -- see app/forecasting/repository.py and
docs/decisions/0016-prospective-forward-validation.md. Same dialect-
agnostic `op.create_table` convention as 0002-0006.
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_forecasting_tables"
down_revision = "0006_ai_analysis_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forward_forecasts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("forecast_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("market_as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False, index=True),
        sa.Column("forecast_category", sa.String(32), nullable=False, index=True),
        sa.Column("forecast_value", sa.String(64), nullable=True, index=True),
        sa.Column("forecast_horizon_bars", sa.Integer(), nullable=False),
        sa.Column("evidence_packet_id", sa.String(64), nullable=False, index=True),
        sa.Column("origin", sa.String(32), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("run_mode", sa.String(16), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "forecast_outcomes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("outcome_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("forecast_id", sa.String(64), nullable=False, index=True),
        sa.Column("outcome", sa.String(32), nullable=False, index=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "forward_validation_gate_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("gate_version", sa.String(32), nullable=False, unique=True, index=True),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "forward_validation_gate_results",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("gate_version", sa.String(32), nullable=False, index=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("decision", sa.String(32), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("row_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("forward_validation_gate_results")
    op.drop_table("forward_validation_gate_versions")
    op.drop_table("forecast_outcomes")
    op.drop_table("forward_forecasts")
