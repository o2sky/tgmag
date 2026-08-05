from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_data_integrity"
down_revision = "0003_service_source_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_tg_accounts_user_id_not_null",
        "tg_accounts",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_tg_sessions_one_active_per_account",
        "tg_sessions",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_check_constraint("ck_rate_max_actions_positive", "rate_limits", "max_actions > 0")
    op.create_check_constraint("ck_rate_per_seconds_positive", "rate_limits", "per_seconds > 0")
    op.create_check_constraint(
        "ck_rate_jitter_valid",
        "rate_limits",
        "jitter_min >= 0 AND jitter_max >= jitter_min",
    )


def downgrade() -> None:
    op.drop_constraint("ck_rate_jitter_valid", "rate_limits", type_="check")
    op.drop_constraint("ck_rate_per_seconds_positive", "rate_limits", type_="check")
    op.drop_constraint("ck_rate_max_actions_positive", "rate_limits", type_="check")
    op.drop_index("uq_tg_sessions_one_active_per_account", table_name="tg_sessions")
    op.drop_index("uq_tg_accounts_user_id_not_null", table_name="tg_accounts")
