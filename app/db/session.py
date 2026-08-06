from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
EXPECTED_DB_REVISION = "0007_login_email_window"


async def init_db() -> None:
    """Verify that explicit Alembic migrations ran before the service starts."""
    async with engine.connect() as conn:
        try:
            revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        except Exception as exc:
            raise RuntimeError("数据库尚未初始化，请先执行 alembic upgrade head") from exc
    if revision != EXPECTED_DB_REVISION:
        raise RuntimeError(
            f"数据库迁移版本为 {revision!r}，期望 {EXPECTED_DB_REVISION!r}；请执行 alembic upgrade head"
        )


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session
