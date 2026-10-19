"""Phase 20/20.1: phone-push notification delivery (Pushover).

Adds:
- `user_push_preferences`: one per-user push on/off switch (defaulting
  to disabled) PLUS that user's own Pushover destination key, stored
  ENCRYPTED (never plaintext) -- see
  app.database.models.UserPushPreferenceRecord and
  app.notifications.secret_crypto for why. Deliberately NOT per-alert-
  type or per-symbol (both of those are already covered by existing
  tables: UserAlertPreferenceRecord and UserMonitoringSubscriptionRecord
  respectively). Revised during the same pre-deploy review that added
  the encrypted-key column -- this migration has never been applied to
  any real database, so it was edited in place rather than patched by a
  follow-up 0014.
- Three new nullable columns on the existing `user_alert_deliveries`
  table recording the outcome of a Pushover send attempt for that
  delivery, never a new delivery-tracking table of its own (reuses the
  row app.alerts.repository.deliver_alert_to_subscribed_users already
  creates exactly once per (user, alert)).

Revision ID: 0013_push_notifications
Revises: 0012_watchlist_default_uniqueness
Create Date: 2026-10-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_push_notifications"
down_revision = "0012_watchlist_default_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_push_preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("push_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("pushover_user_key_encrypted", sa.String(500), nullable=True),
        sa.Column(
            "row_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_user_push_preferences_user_id", "user_push_preferences", ["user_id"], unique=True)

    op.add_column("user_alert_deliveries", sa.Column("push_status", sa.String(16), nullable=True))
    op.add_column(
        "user_alert_deliveries", sa.Column("push_attempted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("user_alert_deliveries", sa.Column("push_error", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("user_alert_deliveries", "push_error")
    op.drop_column("user_alert_deliveries", "push_attempted_at")
    op.drop_column("user_alert_deliveries", "push_status")
    op.drop_index("ix_user_push_preferences_user_id", table_name="user_push_preferences")
    op.drop_table("user_push_preferences")
