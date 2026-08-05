from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_login_email_protection"
down_revision = "0004_data_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("account_security", sa.Column("login_email_encrypted", sa.Text(), nullable=True))
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "login_email_whitelist",
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("tg_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "login_email_protection_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("tg_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "service_message_id",
            sa.Integer(),
            sa.ForeignKey("service_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("selected_domain", sa.String(length=253), nullable=True),
        sa.Column("target_email_encrypted", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("email_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("service_message_id", name="uq_login_email_event_message"),
    )
    op.create_index(
        "ix_login_email_protection_events_account_id",
        "login_email_protection_events",
        ["account_id"],
    )
    op.create_index(
        "ix_login_email_protection_events_status",
        "login_email_protection_events",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_login_email_protection_events_status", table_name="login_email_protection_events")
    op.drop_index("ix_login_email_protection_events_account_id", table_name="login_email_protection_events")
    op.drop_table("login_email_protection_events")
    op.drop_table("login_email_whitelist")
    op.drop_table("runtime_settings")
    op.drop_column("account_security", "login_email_encrypted")
