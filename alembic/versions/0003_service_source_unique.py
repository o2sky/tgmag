from __future__ import annotations

from alembic import op

revision = "0003_service_source_unique"
down_revision = "0002_service_message_full_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_service_account_message", "service_messages", type_="unique")
    op.create_unique_constraint(
        "uq_service_account_source_message",
        "service_messages",
        ["account_id", "source_user_id", "message_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_service_account_source_message", "service_messages", type_="unique")
    op.create_unique_constraint("uq_service_account_message", "service_messages", ["account_id", "message_id"])
