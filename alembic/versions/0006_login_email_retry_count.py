from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_login_email_retry_count"
down_revision = "0005_login_email_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("login_email_protection_events")
    }
    if "attempt_count" not in columns:
        op.add_column(
            "login_email_protection_events",
            sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        )


def downgrade() -> None:
    op.drop_column("login_email_protection_events", "attempt_count")
