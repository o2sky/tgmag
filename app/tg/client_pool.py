from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient, events
from telethon.errors import AuthKeyDuplicatedError
from telethon.sessions import StringSession

from app.config import settings
from app.db.models import LoginEmailProtectionEvent, ServiceMessage, TgAccount, TgSession
from app.services.crypto import decrypt_text
from app.services.login_email_protection import LoginEmailProtector, is_login_code_alert

logger = logging.getLogger(__name__)
REALTIME_SERVICE_SOURCE_IDS = {777000}


class ClientPool:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], bot: Bot):
        self.sessionmaker = sessionmaker
        self.bot = bot
        self.clients: dict[int, TelegramClient] = {}
        self._lock = asyncio.Lock()
        self.monitor_enabled = True
        self._monitor_task: asyncio.Task[None] | None = None
        self.login_email_protector = LoginEmailProtector(sessionmaker, bot)
        self._protection_tasks: set[asyncio.Task[None]] = set()
        self._service_message_locks: dict[int, asyncio.Lock] = {}
        self._login_email_health_lock = asyncio.Lock()
        self.login_email_health_checked_at: datetime | None = None
        self.login_email_health_error: str | None = None

    @property
    def connected_account_ids(self) -> set[int]:
        return {
            account_id
            for account_id, client in self.clients.items()
            if client.is_connected()
        }

    @property
    def service_monitor_running(self) -> bool:
        """Report the task's real state instead of trusting the enabled flag alone."""
        task = self._monitor_task
        return bool(self.monitor_enabled and task is not None and not task.done())

    async def start_service_monitor(self) -> None:
        self.monitor_enabled = True
        await self.connect_all_active()
        if settings.login_email_protection_enabled:
            await self.check_login_email_health()
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(),
                name="telegram-service-monitor",
            )

    async def stop_service_monitor(self) -> None:
        self.monitor_enabled = False
        task, self._monitor_task = self._monitor_task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        protection_tasks = list(self._protection_tasks)
        for protection_task in protection_tasks:
            protection_task.cancel()
        if protection_tasks:
            await asyncio.gather(*protection_tasks, return_exceptions=True)
        await self.disconnect_all()

    async def _monitor_loop(self) -> None:
        while self.monitor_enabled:
            await asyncio.sleep(max(30, settings.service_monitor_interval_seconds))
            if not self.monitor_enabled:
                break
            try:
                await self.connect_all_active()
            except Exception:
                logger.exception("Periodic Telegram client reconnect failed")

    async def connect_all_active(self) -> None:
        async with self.sessionmaker() as session:
            rows = await session.scalars(
                select(TgSession.account_id)
                .where(TgSession.is_active.is_(True))
                .order_by(TgSession.account_id)
            )
            account_ids = list(rows.all())
        for account_id in account_ids:
            try:
                await self.get_client(account_id)
            except Exception:
                logger.exception("Failed to connect account %s", account_id)

    async def disconnect_all(self) -> None:
        for account_id, client in list(self.clients.items()):
            try:
                await client.disconnect()
            except Exception:
                logger.exception("Failed to disconnect account %s", account_id)
        self.clients.clear()

    async def check_login_email_health(self) -> bool:
        """Validate the configured IMAP mailbox and retain the real runtime result."""
        async with self._login_email_health_lock:
            self.login_email_health_checked_at = datetime.now(timezone.utc)
            try:
                await self.login_email_protector.reader.validate_connection()
            except Exception as exc:
                self.login_email_health_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                logger.exception("Login email protection Gmail health check failed")
                return False
            self.login_email_health_error = None
            return True

    def _track_protection_task(self, task: asyncio.Task[None]) -> None:
        self._protection_tasks.add(task)
        task.add_done_callback(self._protection_task_done)

    def _protection_task_done(self, task: asyncio.Task[None]) -> None:
        self._protection_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            logger.error(
                "Unhandled login email protection task failure",
                exc_info=(type(exception), exception, exception.__traceback__),
            )

    async def drop(self, account_id: int) -> None:
        client = self.clients.pop(account_id, None)
        if client:
            try:
                await client.disconnect()
            except Exception:
                logger.exception("Failed to disconnect dropped account %s", account_id)

    async def retry_login_email_protection(self, event_id: int, domain: str) -> None:
        async with self.sessionmaker() as session:
            event = await session.get(LoginEmailProtectionEvent, event_id)
            if event is None:
                raise ValueError("保护事件不存在")
            account_id = event.account_id
        client = await self.get_client(account_id)

        async def run() -> None:
            try:
                await self.login_email_protector.retry(event_id, domain, client)
            except Exception:
                logger.exception("Manual login email protection retry failed for event %s", event_id)

        task = asyncio.create_task(run(), name=f"login-email-protection-retry-{event_id}")
        self._track_protection_task(task)

    async def get_client(self, account_id: int) -> TelegramClient:
        async with self._lock:
            existing = self.clients.get(account_id)
            if existing and existing.is_connected():
                return existing
            async with self.sessionmaker() as session:
                tg_session = await session.scalar(
                    select(TgSession)
                    .where(TgSession.account_id == account_id, TgSession.is_active.is_(True))
                    .order_by(TgSession.id.desc())
                )
                if not tg_session:
                    raise ValueError(f"账号 {account_id} 没有可用 session")
                session_str = decrypt_text(tg_session.session_encrypted)
            client = TelegramClient(StringSession(session_str), settings.tg_api_id, settings.tg_api_hash)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    await self._mark_session_invalid(account_id, "session 未授权或已失效")
                    raise ValueError(f"账号 {account_id} session 已失效，请重新登录")
            except AuthKeyDuplicatedError as exc:
                await client.disconnect()
                await self._mark_session_invalid(account_id, str(exc))
                raise ValueError(f"账号 {account_id} session 授权密钥已失效，请重新登录") from exc
            client.add_event_handler(
                lambda event, aid=account_id: self._handle_service_message(aid, event),
                events.NewMessage(incoming=True),
            )
            self.clients[account_id] = client
            await self.catch_up_recent_login_alerts(account_id, client)
            return client

    async def _mark_session_invalid(self, account_id: int, error: str) -> None:
        async with self.sessionmaker() as session:
            await session.execute(
                update(TgSession)
                .where(TgSession.account_id == account_id, TgSession.is_active.is_(True))
                .values(is_active=False, rotated_at=datetime.now(timezone.utc))
            )
            account = await session.get(TgAccount, account_id)
            if account is not None:
                account.status = "session_invalid"
                account.last_error = error[:2000]
            await session.commit()

    async def catch_up_recent_login_alerts(
        self,
        account_id: int,
        client: TelegramClient,
    ) -> None:
        catchup_seconds = settings.login_email_catchup_seconds
        if not self.monitor_enabled or not settings.login_email_protection_enabled or not catchup_seconds:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=catchup_seconds)
        try:
            messages = await client.get_messages(777000, limit=10)
        except Exception:
            logger.exception("Failed to catch up recent 777000 messages for account %s", account_id)
            return
        for message in reversed(messages):
            text = message.message or ""
            received_at = message.date or datetime.now(timezone.utc)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
            if received_at < cutoff or not is_login_code_alert(text):
                continue
            await self._ingest_service_message(
                account_id,
                777000,
                int(message.id),
                text,
                received_at,
                client,
            )

    def _schedule_login_email_protection(
        self,
        account_id: int,
        service_message_id: int,
        text: str,
        client: TelegramClient,
    ) -> None:
        if not is_login_code_alert(text):
            return
        task = asyncio.create_task(
            self.login_email_protector.handle(account_id, service_message_id, text, client),
            name=f"login-email-protection-{account_id}-{service_message_id}",
        )
        self._track_protection_task(task)

    async def _ingest_service_message(
        self,
        account_id: int,
        source_user_id: int,
        message_id: int,
        text: str,
        received_at: datetime,
        client: TelegramClient,
    ) -> None:
        lock = self._service_message_locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            async with self.sessionmaker() as session:
                record = await session.scalar(
                    select(ServiceMessage).where(
                        ServiceMessage.account_id == account_id,
                        ServiceMessage.source_user_id == source_user_id,
                        ServiceMessage.message_id == message_id,
                    )
                )
                created = record is None
                if record is None:
                    record = ServiceMessage(
                        account_id=account_id,
                        source_user_id=source_user_id,
                        message_id=message_id,
                        text_hash=text_hash,
                        text=text,
                        text_preview=text[:1000],
                        received_at=received_at,
                        notified_at=datetime.now(timezone.utc),
                    )
                    session.add(record)
                    await session.flush()
                elif text and (
                    record.text != text
                    or record.text_preview != text[:1000]
                    or record.text_hash != text_hash
                ):
                    record.text = text
                    record.text_preview = text[:1000]
                    record.text_hash = text_hash
                await session.commit()
                service_message_id = record.id

        # Existing service rows must still reach the idempotent protector. A
        # manual history pull may have stored the row just before the live event.
        self._schedule_login_email_protection(account_id, service_message_id, text, client)
        if not created:
            return
        for admin_id in settings.admin_ids:
            try:
                await self.bot.send_message(
                    admin_id,
                    f"服务消息\n账号ID: {account_id}\n来源: {source_user_id}\n消息ID: {message_id}\n内容:\n{text[:3500]}",
                )
            except TelegramAPIError:
                logger.warning(
                    "Failed to notify admin %s for service message %s",
                    admin_id,
                    message_id,
                    exc_info=True,
                )
            except Exception:
                logger.exception("Unexpected notify failure for admin %s", admin_id)

    async def _handle_service_message(self, account_id: int, event: events.NewMessage.Event) -> None:
        if not self.monitor_enabled:
            return
        if not event.is_private:
            return
        source_user_id = int(event.sender_id or 0)
        if source_user_id <= 0:
            return
        if source_user_id == settings.bot_user_id:
            return
        if source_user_id not in REALTIME_SERVICE_SOURCE_IDS:
            return
        text = event.raw_text or ""
        if not text.strip():
            return
        received_at = event.message.date or datetime.now(timezone.utc)
        client = self.clients.get(account_id)
        if client is None:
            logger.error("Received a service message for untracked account %s", account_id)
            return
        await self._ingest_service_message(
            account_id,
            source_user_id,
            int(event.message.id),
            text,
            received_at,
            client,
        )
