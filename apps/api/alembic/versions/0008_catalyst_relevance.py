"""POST-BROWSER-TEST CORRECTION PASS #2 (#13/#14): catalyst relevance +
source enrichment

Revision ID: 0008_catalyst_relevance
Revises: 0007_forecasting_tables
Create Date: 2026-09-21

Adds `relevance` (deterministic PRIMARY/BACKGROUND/UNKNOWN classification,
app.news.relevance), `primary_source`, and `primary_url` to catalyst_events
-- sourced from the event's anchor article, never fabricated. Existing rows
default to relevance="unknown" (honest -- they predate this classifier) and
null source/url.
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_catalyst_relevance"
down_revision = "0007_forecasting_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalyst_events",
        sa.Column("relevance", sa.String(16), nullable=False, server_default="unknown"),
    )
    op.add_column("catalyst_events", sa.Column("primary_source", sa.String(200), nullable=True))
    op.add_column("catalyst_events", sa.Column("primary_url", sa.String(2000), nullable=True))


def downgrade() -> None:
    op.drop_column("catalyst_events", "primary_url")
    op.drop_column("catalyst_events", "primary_source")
    op.drop_column("catalyst_events", "relevance")
