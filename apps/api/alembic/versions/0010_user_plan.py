"""Phase 16 (§48): add `plan` to `users` for billing-ready entitlements.

Revision ID: 0010_user_plan
Revises: 0009_decision_alerts_monitoring_validation_auth
Create Date: 2026-09-27
"""

import sqlalchemy as sa

from alembic import op

revision = "0010_user_plan"
down_revision = "0009_decision_alerts_monitoring_validation_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("plan", sa.String(32), nullable=False, server_default="free"))


def downgrade() -> None:
    op.drop_column("users", "plan")
