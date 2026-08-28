"""Phase 9: candle cache and frozen datasets

Revision ID: 0004_candle_cache
Revises: 0003_research_snapshots
Create Date: 2026-08-27

A local candle cache keyed on the full (provider, symbol, timeframe,
requested range, adjustment, session settings) tuple (#32), and a
separate, permanently-immutable frozen-dataset table for exact
reproducibility (#33) -- see app/market_data/candle_cache.py for the
repository and the staleness policy that keeps the cache from ever being
silently stale. Same dialect-agnostic `op.create_table` convention as
0002/0003.
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_candle_cache"
down_revision = "0003_research_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cached_candle_series",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("requested_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adjustment_mode", sa.String(32), nullable=False),
        sa.Column("session_settings", sa.String(64), nullable=False),
        sa.Column("candles", sa.JSON(), nullable=False),
        sa.Column("data_hash", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "symbol",
            "timeframe",
            "requested_start",
            "requested_end",
            "adjustment_mode",
            "session_settings",
            name="uq_candle_cache_key",
        ),
    )
    op.create_table(
        "frozen_datasets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("requested_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adjustment_mode", sa.String(32), nullable=False),
        sa.Column("session_settings", sa.String(64), nullable=False),
        sa.Column("candles", sa.JSON(), nullable=False),
        sa.Column("data_hash", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("frozen_datasets")
    op.drop_table("cached_candle_series")
