from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db.models import Admin


@dataclass(frozen=True)
class MiniAppUser:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


def validate_init_data(init_data: str) -> MiniAppUser:
    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", None)
    if not received_hash:
        raise web.HTTPUnauthorized(text="missing hash")

    auth_date_raw = values.get("auth_date")
    if not auth_date_raw:
        raise web.HTTPUnauthorized(text="missing auth_date")
    try:
        auth_date = int(auth_date_raw)
    except ValueError as exc:
        raise web.HTTPUnauthorized(text="invalid auth_date") from exc
    age = time.time() - auth_date
    if age < -60:
        raise web.HTTPUnauthorized(text="auth_date is in the future")
    if age > settings.mini_app_auth_max_age_seconds:
        raise web.HTTPUnauthorized(text="init data expired")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise web.HTTPUnauthorized(text="invalid init data")

    user_raw = values.get("user")
    if not user_raw:
        raise web.HTTPUnauthorized(text="missing user")
    try:
        user_data = json.loads(user_raw)
        user_id = int(user_data["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise web.HTTPUnauthorized(text="invalid user") from exc
    return MiniAppUser(
        id=user_id,
        username=user_data.get("username"),
        first_name=user_data.get("first_name"),
        last_name=user_data.get("last_name"),
    )


async def require_admin(
    request: web.Request,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> MiniAppUser:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_init_data(init_data)
    async with sessionmaker() as session:
        admin = await session.scalar(
            select(Admin).where(
                Admin.telegram_user_id == user.id,
            )
        )
    allowed = admin.is_active if admin is not None else user.id in settings.admin_ids
    if not allowed:
        raise web.HTTPForbidden(text="not an admin")
    return user
