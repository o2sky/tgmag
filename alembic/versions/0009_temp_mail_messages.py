from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_temp_mail_messages"
down_revision = "0008_account_email_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temp_mail_messages",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("to", sa.String(length=320), nullable=False),
        sa.Column("from", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=True),
        sa.Column("parsedText", sa.Text(), nullable=True),
        sa.Column("parsedHtml", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("aiExtractType", sa.Text(), nullable=True),
        sa.Column("aiExtractResult", sa.JSON(), nullable=True),
        sa.Column("aiExtractResultText", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", "to", name="pk_temp_mail_messages"),
    )
    op.create_index(
        "ix_temp_mail_recipient_received",
        "temp_mail_messages",
        ["to", "received_at"],
    )
    op.create_index(
        "ix_temp_mail_domain_received",
        "temp_mail_messages",
        ["domain", "received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_temp_mail_domain_received", table_name="temp_mail_messages")
    op.drop_index("ix_temp_mail_recipient_received", table_name="temp_mail_messages")
    op.drop_table("temp_mail_messages")
