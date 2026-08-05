from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AllowedTarget


def canonicalize_target_ref(target_ref: str) -> str:
    value = target_ref.strip()
    if not value:
        raise ValueError("目标不能为空")
    if value.lstrip("-").isdigit():
        return str(int(value))
    if value.startswith("@"):
        return "@" + value[1:].lower()
    parsed = urlparse(value if "://" in value else "")
    if parsed.hostname in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        path = parsed.path.strip("/")
        if path and "/" not in path and not path.startswith("+"):
            return "@" + path.lower()
    return value


async def is_allowed_target(session: AsyncSession, target_ref: str) -> bool:
    normalized = canonicalize_target_ref(target_ref)
    if normalized.startswith("@"):
        condition = func.lower(AllowedTarget.target_ref) == normalized.lower()
    else:
        condition = AllowedTarget.target_ref == normalized
    target = await session.scalar(select(AllowedTarget).where(condition))
    return target is not None


async def require_allowed_target(session: AsyncSession, target_ref: str) -> None:
    if not await is_allowed_target(session, target_ref):
        raise ValueError("目标不在授权白名单中，请先使用 /target_allowlist add 添加。")
