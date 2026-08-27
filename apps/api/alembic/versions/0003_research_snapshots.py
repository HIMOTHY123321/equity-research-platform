"""Phase 8: research snapshots

Revision ID: 0003_research_snapshots
Revises: 0002_research_tables
Create Date: 2026-08-25

An immutable record of one research conclusion (#34) -- which run(s),
rules, dataset, and query produced it. Rows are never updated in place; a
changed conclusion is always a new row, so an old snapshot stays
inspectable even after detector logic changes later. Same dialect-agnostic
`op.create_table` convention as 0002.
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_research_snapshots"
down_revision = "0002_research_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("research_run_ids", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(32), nullable=False, index=True),
        sa.Column("dataset_manifest", sa.JSON(), nullable=False),
        sa.Column("cohort_definition", sa.JSON(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("statistical_output", sa.JSON(), nullable=False),
        sa.Column("warning_flags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("research_snapshots")
