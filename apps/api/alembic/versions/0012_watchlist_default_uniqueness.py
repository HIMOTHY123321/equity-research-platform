"""Phase 19.5: fixes a production crash (sqlalchemy.exc.MultipleResultsFound
in app.watchlist.repository._get_or_create_default_watchlist) caused by a
race in that same function creating more than one `is_default=True`
watchlists row for a single user -- nothing in the schema previously
prevented it.

This migration does two things, in the only safe order:

1. Repairs any already-corrupted rows FIRST (via
   app.watchlist.repository.repair_duplicate_default_watchlists), merging
   every duplicate default watchlist's symbol memberships onto one
   canonical row (the oldest by created_at, ties broken by id) and only
   then deleting the now-empty duplicate rows. Never destructive to a
   user's actual watchlist symbols.

2. THEN adds `uq_watchlists_user_default`, a partial unique index on
   `watchlists.user_id` (`WHERE is_default = true`/`= 1`) -- this order
   matters: creating the index before repairing existing duplicates would
   fail outright with a constraint violation against the very rows this
   migration exists to fix.

See app.watchlist.repository._get_or_create_default_watchlist for the
matching application-level fix (catches the IntegrityError this index
makes possible under a race and re-reads the winning row instead of ever
creating a second default watchlist).

Revision ID: 0012_watchlist_default_uniqueness
Revises: 0011_user_sessions_monitoring_alert_delivery
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op

revision = "0012_watchlist_default_uniqueness"
down_revision = "0011_user_sessions_monitoring_alert_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Local import: app.watchlist.repository is apps/api application code,
    # not alembic infrastructure -- imported here (not at module level)
    # purely so `alembic history`/`alembic current` (which import every
    # version module) never need the full app import chain to resolve.
    from app.watchlist.repository import repair_duplicate_default_watchlists

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        repair_duplicate_default_watchlists(session)
    finally:
        session.close()

    op.create_index(
        "uq_watchlists_user_default",
        "watchlists",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_watchlists_user_default", table_name="watchlists")
