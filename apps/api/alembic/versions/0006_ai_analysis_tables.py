"""Phase 11: AI Research Analyst evidence packet / research brief tables

Revision ID: 0006_ai_analysis_tables
Revises: 0005_news_catalyst_tables
Create Date: 2026-09-01

Immutable EvidencePacket/ResearchBrief snapshots (#A/#D/#K) -- see
app/ai_analysis/repository.py and docs/decisions/0014-ai-research-analyst.md.
Same dialect-agnostic `op.create_table` convention as 0002-0005.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_ai_analysis_tables"
down_revision = "0005_news_catalyst_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_packets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("packet_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("schema_version", sa.String(16), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False, index=True),
        sa.Column("setup_id", sa.String(80), nullable=True, index=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "research_briefs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("brief_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("evidence_packet_id", sa.String(64), nullable=False, index=True),
        sa.Column("mode", sa.String(32), nullable=False, index=True),
        sa.Column("provider", sa.String(64), nullable=False, index=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("grounding_rejected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("research_briefs")
    op.drop_table("evidence_packets")
