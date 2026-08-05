from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db.models import Admin, RateLimit
from app.db.session import sessionmaker


async def bootstrap_defaults() -> None:
    async with sessionmaker() as session:
        for admin_id in settings.admin_ids:
            exists = await session.scalar(select(Admin).where(Admin.telegram_user_id == admin_id))
            if not exists:
                session.add(Admin(telegram_user_id=admin_id, role="owner", is_active=True))

        default_rate = await session.scalar(select(RateLimit).where(RateLimit.scope == "batch"))
        if not default_rate:
            session.add(
                RateLimit(
                    scope="batch",
                    max_actions=settings.default_rate_max_actions,
                    per_seconds=settings.default_rate_per_seconds,
                    jitter_min=settings.default_jitter_min,
                    jitter_max=settings.default_jitter_max,
                )
            )
        await session.commit()
