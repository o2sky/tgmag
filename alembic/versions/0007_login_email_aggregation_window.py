from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_login_email_window"
down_revision = "0006_login_email_retry_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "login_email_protection_events"
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    indexes = {index["name"] for index in inspector.get_indexes(table)}
    if "parent_event_id" not in columns:
        op.add_column(
            table,
            sa.Column(
                "parent_event_id",
                sa.Integer(),
                sa.ForeignKey(f"{table}.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
    if "ix_login_email_protection_events_parent_event_id" not in indexes:
        op.create_index(
            "ix_login_email_protection_events_parent_event_id",
            table,
            ["parent_event_id"],
        )
    if "window_ends_at" not in columns:
        op.add_column(table, sa.Column("window_ends_at", sa.DateTime(timezone=True)))
    if "last_detected_at" not in columns:
        op.add_column(table, sa.Column("last_detected_at", sa.DateTime(timezone=True)))
    if "alert_count" not in columns:
        op.add_column(
            table,
            sa.Column("alert_count", sa.Integer(), server_default="1", nullable=False),
        )
    if "ix_login_email_events_waiting_window" not in indexes:
        op.create_index(
            "ix_login_email_events_waiting_window",
            table,
            ["account_id", "status", "window_ends_at"],
        )


def downgrade() -> None:
    table = "login_email_protection_events"
    op.drop_index("ix_login_email_events_waiting_window", table_name=table)
    op.drop_column(table, "alert_count")
    op.drop_column(table, "last_detected_at")
    op.drop_column(table, "window_ends_at")
    op.drop_index("ix_login_email_protection_events_parent_event_id", table_name=table)
    op.drop_column(table, "parent_event_id")
