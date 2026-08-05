from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select

from app.config import settings
from app.db.models import Admin


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        else:
            user = None
        if user is None:
            return await handler(event, data)
        sessionmaker = data["sessionmaker"]
        async with sessionmaker() as session:
            admin = await session.scalar(
                select(Admin).where(
                    Admin.telegram_user_id == user.id,
                )
            )
            allowed = admin.is_active if admin is not None else user.id in settings.admin_ids
            if not allowed:
                if isinstance(event, CallbackQuery):
                    await event.answer("未授权。", show_alert=True)
                else:
                    await event.answer("未授权。")
                return None
            data["admin"] = admin if admin and admin.is_active else None
        return await handler(event, data)
