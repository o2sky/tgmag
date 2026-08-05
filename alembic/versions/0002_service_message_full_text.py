from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_service_message_full_text"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_messages", sa.Column("text", sa.Text(), nullable=True))
    op.execute("UPDATE service_messages SET text = text_preview WHERE text IS NULL")


def downgrade() -> None:
    op.drop_column("service_messages", "text")
