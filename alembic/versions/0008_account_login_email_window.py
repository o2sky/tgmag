from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_account_email_window"
down_revision = "0007_login_email_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "tg_accounts"
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints(table)}
    if "login_email_window_hours" not in columns:
        op.add_column(
            table,
            sa.Column(
                "login_email_window_hours",
                sa.Integer(),
                server_default="0",
                nullable=False,
            ),
        )
    if "ck_tg_accounts_login_email_window_hours" not in constraints:
        op.create_check_constraint(
            "ck_tg_accounts_login_email_window_hours",
            table,
            "login_email_window_hours >= 0 AND login_email_window_hours <= 720",
        )


def downgrade() -> None:
    table = "tg_accounts"
    op.drop_constraint(
        "ck_tg_accounts_login_email_window_hours",
        table,
        type_="check",
    )
    op.drop_column(table, "login_email_window_hours")
