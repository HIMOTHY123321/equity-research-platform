"""Phase 10: news/catalyst context tables

Revision ID: 0005_news_catalyst_tables
Revises: 0004_candle_cache
Create Date: 2026-08-31

Normalized article metadata, deterministic catalyst events, event/article
membership, and cached market-reaction measurements (#L) -- see
app/news/repository.py and docs/decisions/0013-news-catalyst-context-engine.md.
Same dialect-agnostic `op.create_table` convention as 0002/0003/0004.
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_news_catalyst_tables"
down_revision = "0004_candle_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("article_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("provider", sa.String(32), nullable=False, index=True),
        sa.Column("source", sa.String(200), nullable=True),
        sa.Column("headline", sa.String(500), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("raw_category", sa.String(100), nullable=True),
        sa.Column("category", sa.String(64), nullable=False, index=True),
        sa.Column("classification", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "catalyst_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("primary_timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("category", sa.String(64), nullable=False, index=True),
        sa.Column("affected_symbols", sa.JSON(), nullable=False),
        sa.Column("contributing_article_ids", sa.JSON(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("earliest_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_update_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "catalyst_event_articles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False, index=True),
        sa.Column("article_id", sa.String(64), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("event_id", "article_id", name="uq_event_article"),
    )

    op.create_table(
        "catalyst_reactions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("reaction", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("event_id", "symbol", "timeframe", name="uq_reaction_event_symbol_timeframe"),
    )


def downgrade() -> None:
    op.drop_table("catalyst_reactions")
    op.drop_table("catalyst_event_articles")
    op.drop_table("catalyst_events")
    op.drop_table("news_articles")
