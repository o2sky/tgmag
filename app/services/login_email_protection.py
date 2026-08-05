from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import imaplib
import json
import logging
import re
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient

from app.config import settings
from app.db.models import (
    AccountSecurity,
    LoginEmailProtectionEvent,
    LoginEmailWhitelist,
    RuntimeSetting,
    TgAccount,
)
from app.services.crypto import decrypt_text, encrypt_text
from app.tg import account_ops

logger = logging.getLogger(__name__)

SELECTED_DOMAIN_KEY = "login_email_protection.selected_domain"
DOMAINS_KEY = "login_email_protection.domains"
DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
LOGIN_CODE_VALUE_PATTERN = re.compile(r"(?<!\d)\d{5,8}(?!\d)")
LOGIN_CODE_ALERT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:your\s+)?login\s+code\b",
        r"登录(?:验证)?码|登录代码",
        r"код\s+для\s+входа",
        r"c[oó]digo\s+(?:de\s+)?(?:inicio\s+de\s+sesi[oó]n|login)",
        r"code\s+de\s+connexion",
        r"anmeldecode",
        r"codice\s+(?:di\s+)?accesso",
        r"giri[sş]\s+kodu",
        r"رمز\s+تسجيل\s+الدخول",
        r"کد\s+ورود",
        r"kode\s+login",
        r"m[aã]\s+(?:đăng\s+nhập|login)",
        r"로그인\s*코드",
        r"ログインコード",
    )
)
EMAIL_BODY_CODE_PATTERN = re.compile(
    r"\byour\s+code\s+is\s*:\s*(\d{5,8})\b",
    re.IGNORECASE,
)
EMAIL_SUBJECT_CODE_PATTERN = re.compile(
    r"\byour\s+code\s*[-:]\s*(\d{5,8})\b",
    re.IGNORECASE,
)
EMAIL_LOGIN_PURPOSE_PATTERN = re.compile(
    r"verify\s+your\s+email\s+for\s+login",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TelegramLoginEmailCode:
    code: str
    recipient: str
    sent_at: datetime | None


def is_login_code_alert(text: str) -> bool:
    """Recognize the 777000 login-code alert without depending on its full wording."""
    value = text or ""
    return bool(
        LOGIN_CODE_VALUE_PATTERN.search(value)
        and any(pattern.search(value) for pattern in LOGIN_CODE_ALERT_PATTERNS)
    )


async def recover_incomplete_events(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> int:
    """Make protection jobs left mid-flight by a hard stop retryable again."""
    async with sessionmaker() as session:
        result = await session.execute(
            update(LoginEmailProtectionEvent)
            .where(LoginEmailProtectionEvent.status.in_({"detected", "requesting", "waiting_email"}))
            .values(status="interrupted", error="服务曾异常停止，可从保护事件中重新发起换绑")
        )
        await session.commit()
    return int(result.rowcount or 0)


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for fragment, charset in decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts)


def _message_text(message: Message) -> str:
    if not message.is_multipart():
        payload = message.get_payload(decode=True)
        if payload is None:
            return str(message.get_payload() or "")
        return payload.decode(message.get_content_charset() or "utf-8", errors="replace")
    parts: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if payload is not None:
            parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    return "\n".join(parts)


def parse_telegram_login_email(
    raw_message: bytes,
    target_email: str,
    expected_sender: str = "noreply@telegram.org",
) -> TelegramLoginEmailCode | None:
    """Return a code only when sender, recipient and Login purpose all match."""
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    senders = {
        address.lower()
        for _, address in getaddresses([message.get("From", "")])
        if address
    }
    if expected_sender.lower() not in senders:
        return None

    # Newer Python patch releases reject the whole getaddresses() input when it
    # contains empty header values. Only pass headers that actually exist so a
    # normal To-only message remains valid with strict address parsing.
    recipient_headers = [
        value
        for name in ("To", "Delivered-To", "X-Original-To", "Envelope-To")
        if (value := message.get(name))
    ]
    recipients = {
        address.lower()
        for _, address in getaddresses(recipient_headers)
        if address
    }
    normalized_target = target_email.lower()
    if normalized_target not in recipients:
        return None

    subject = _decode_header(message.get("Subject"))
    body = _message_text(message)
    combined = f"{subject}\n{body}"
    if not EMAIL_LOGIN_PURPOSE_PATTERN.search(combined):
        return None
    body_match = EMAIL_BODY_CODE_PATTERN.search(body)
    subject_match = EMAIL_SUBJECT_CODE_PATTERN.search(subject)
    if body_match is None:
        return None
    if subject_match is not None and subject_match.group(1) != body_match.group(1):
        return None

    sent_at: datetime | None = None
    try:
        sent_at = parsedate_to_datetime(message.get("Date", ""))
        if sent_at is not None and sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        sent_at = None
    return TelegramLoginEmailCode(body_match.group(1), normalized_target, sent_at)


class GmailCodeReader:
    def validate_connection_sync(self) -> None:
        connection = imaplib.IMAP4_SSL(
            settings.login_email_imap_host,
            settings.login_email_imap_port,
            timeout=30,
        )
        try:
            connection.login(
                settings.login_email_gmail_username,
                settings.login_email_gmail_app_password,
            )
            status, _ = connection.select(settings.login_email_imap_folder, readonly=True)
            if status != "OK":
                raise RuntimeError("无法打开 Gmail IMAP 邮箱目录")
        finally:
            try:
                connection.logout()
            except Exception:
                pass

    async def validate_connection(self) -> None:
        await asyncio.to_thread(self.validate_connection_sync)

    def wait_for_code_sync(self, target_email: str, requested_at: datetime) -> str:
        deadline = time.monotonic() + settings.login_email_poll_timeout_seconds
        earliest = requested_at.astimezone(timezone.utc) - timedelta(minutes=2)
        since = earliest.strftime("%d-%b-%Y")
        connection = imaplib.IMAP4_SSL(
            settings.login_email_imap_host,
            settings.login_email_imap_port,
            timeout=30,
        )
        try:
            connection.login(
                settings.login_email_gmail_username,
                settings.login_email_gmail_app_password,
            )
            while time.monotonic() < deadline:
                status, _ = connection.select(settings.login_email_imap_folder, readonly=True)
                if status != "OK":
                    raise RuntimeError("无法打开 Gmail IMAP 邮箱目录")
                status, data = connection.uid(
                    "search",
                    None,
                    f'(FROM "{settings.login_email_sender}" SINCE "{since}")',
                )
                if status != "OK":
                    raise RuntimeError("Gmail IMAP 搜索失败")
                uids = (data[0] or b"").split()
                for uid in reversed(uids[-100:]):
                    status, fetched = connection.uid("fetch", uid, "(BODY.PEEK[])")
                    if status != "OK":
                        continue
                    raw = next(
                        (item[1] for item in fetched if isinstance(item, tuple) and isinstance(item[1], bytes)),
                        None,
                    )
                    if raw is None:
                        continue
                    parsed = parse_telegram_login_email(
                        raw,
                        target_email,
                        settings.login_email_sender,
                    )
                    if parsed is None:
                        continue
                    if parsed.sent_at is not None and parsed.sent_at.astimezone(timezone.utc) < earliest:
                        continue
                    return parsed.code
                time.sleep(settings.login_email_poll_interval_seconds)
        finally:
            try:
                connection.logout()
            except Exception:
                pass
        raise TimeoutError("等待 Telegram 登录邮箱验证码超时")

    async def wait_for_code(self, target_email: str, requested_at: datetime) -> str:
        return await asyncio.to_thread(self.wait_for_code_sync, target_email, requested_at)


def normalize_domain(domain: str) -> str:
    normalized = domain.strip().lower().lstrip("@")
    if not DOMAIN_PATTERN.fullmatch(normalized):
        raise ValueError("邮箱域名格式无效")
    return normalized


async def get_available_domains(session: AsyncSession) -> tuple[str, ...]:
    row = await session.get(RuntimeSetting, DOMAINS_KEY)
    if row is not None:
        try:
            values = json.loads(row.value)
            domains = tuple(normalize_domain(str(item)) for item in values)
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.error("Stored login email domain list is invalid; using environment defaults")
        else:
            if domains and len(domains) == len(set(domains)):
                return domains
    return settings.login_email_alias_domains


async def _store_available_domains(session: AsyncSession, domains: tuple[str, ...]) -> None:
    if not domains:
        raise ValueError("至少需要保留一个邮箱域名")
    row = await session.get(RuntimeSetting, DOMAINS_KEY)
    payload = json.dumps(domains, ensure_ascii=True)
    if row is None:
        session.add(RuntimeSetting(key=DOMAINS_KEY, value=payload))
    else:
        row.value = payload


async def add_available_domain(session: AsyncSession, domain: str) -> str:
    normalized = normalize_domain(domain)
    domains = await get_available_domains(session)
    if normalized in domains:
        raise ValueError("该邮箱域名已经存在")
    await _store_available_domains(session, (*domains, normalized))
    await session.commit()
    return normalized


async def delete_available_domain(session: AsyncSession, domain: str) -> None:
    normalized = normalize_domain(domain)
    domains = await get_available_domains(session)
    if normalized not in domains:
        raise ValueError("该邮箱域名不存在")
    remaining = tuple(item for item in domains if item != normalized)
    if not remaining:
        raise ValueError("至少需要保留一个邮箱域名")
    await _store_available_domains(session, remaining)
    selected = await session.get(RuntimeSetting, SELECTED_DOMAIN_KEY)
    if selected is not None and selected.value == normalized:
        selected.value = remaining[0]
    await session.commit()


async def get_selected_domain(session: AsyncSession) -> str | None:
    domains = await get_available_domains(session)
    if not domains:
        return None
    row = await session.get(RuntimeSetting, SELECTED_DOMAIN_KEY)
    if row is not None and row.value in domains:
        return row.value
    return domains[0]


async def set_selected_domain(session: AsyncSession, domain: str) -> None:
    domain = normalize_domain(domain)
    if domain not in await get_available_domains(session):
        raise ValueError("邮箱域名不在当前允许列表中")
    row = await session.get(RuntimeSetting, SELECTED_DOMAIN_KEY)
    if row is None:
        session.add(RuntimeSetting(key=SELECTED_DOMAIN_KEY, value=domain))
    else:
        row.value = domain
    await session.commit()


async def get_whitelist_ids(session: AsyncSession) -> set[int]:
    return set((await session.scalars(select(LoginEmailWhitelist.account_id))).all())


async def set_whitelisted(session: AsyncSession, account_id: int, enabled: bool) -> None:
    account = await session.get(TgAccount, account_id)
    if account is None:
        raise ValueError("账号不存在")
    if enabled:
        if await session.get(LoginEmailWhitelist, account_id) is None:
            session.add(LoginEmailWhitelist(account_id=account_id))
    else:
        await session.execute(
            delete(LoginEmailWhitelist).where(LoginEmailWhitelist.account_id == account_id)
        )
    await session.commit()


def build_alias(phone: str, domain: str, timestamp: int | None = None) -> str:
    digits = "".join(character for character in phone if character.isdigit())
    if not digits:
        raise ValueError("账号手机号不可用")
    local_part = f"{timestamp or int(time.time())}_{digits}"
    if len(local_part) > 64:
        raise ValueError("生成的邮箱前缀超过 64 字符")
    return f"{local_part}@{domain}"


class LoginEmailProtector:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        bot: Bot,
        reader: GmailCodeReader | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.bot = bot
        self.reader = reader or GmailCodeReader()
        self._account_locks: dict[int, asyncio.Lock] = {}
        self._gmail_slots = asyncio.Semaphore(3)

    async def _notify(
        self,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        for admin_id in settings.admin_ids:
            try:
                await self.bot.send_message(admin_id, text, reply_markup=reply_markup)
            except TelegramAPIError:
                logger.warning("Failed to send login email protection notice to %s", admin_id, exc_info=True)
            except Exception:
                logger.exception("Unexpected login email protection notification failure")

    @staticmethod
    def _retry_markup(event_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="快捷换绑登录邮箱",
                        callback_data=f"emailguard:retrymenu:{event_id}",
                    )
                ]
            ]
        )

    async def _set_event_status(
        self,
        event_id: int,
        status: str,
        *,
        error: str | None = None,
        email_requested_at: datetime | None = None,
        confirmed_at: datetime | None = None,
    ) -> None:
        async with self.sessionmaker() as session:
            event = await session.get(LoginEmailProtectionEvent, event_id)
            if event is None:
                return
            event.status = status
            event.error = error[:2000] if error else None
            if email_requested_at is not None:
                event.email_requested_at = email_requested_at
            if confirmed_at is not None:
                event.confirmed_at = confirmed_at
            await session.commit()

    async def handle(
        self,
        account_id: int,
        service_message_id: int,
        text: str,
        client: TelegramClient,
    ) -> None:
        if not is_login_code_alert(text):
            return
        lock = self._account_locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            await self._handle_locked(account_id, service_message_id, client)

    async def _handle_locked(
        self,
        account_id: int,
        service_message_id: int,
        client: TelegramClient,
    ) -> None:
        async with self.sessionmaker() as session:
            existing = await session.scalar(
                select(LoginEmailProtectionEvent).where(
                    LoginEmailProtectionEvent.service_message_id == service_message_id
                )
            )
            if existing is not None:
                return
            account = await session.get(TgAccount, account_id)
            if account is None:
                return
            whitelisted = await session.get(LoginEmailWhitelist, account_id) is not None
            domain = await get_selected_domain(session)
            event = LoginEmailProtectionEvent(
                account_id=account_id,
                service_message_id=service_message_id,
                status="detected",
                selected_domain=domain,
            )
            session.add(event)
            await session.flush()
            event_id = event.id
            if whitelisted:
                event.status = "whitelisted"
                await session.commit()
                await self._notify(
                    f"登录邮箱保护\n账号 #{account_id} 在白名单中：仅转发 777000 登录提醒，未更改登录邮箱。"
                )
                return
            if not settings.login_email_protection_enabled:
                event.status = "disabled"
                await session.commit()
                await self._notify(
                    f"登录邮箱保护\n账号 #{account_id} 检测到登录提醒，但自动换绑尚未启用。"
                )
                return
            if domain is None:
                event.status = "failed"
                event.error = "未配置登录邮箱域名"
                await session.commit()
                await self._notify(f"登录邮箱保护失败\n账号 #{account_id}\n原因：未配置邮箱域名。")
                return
            if settings.login_email_cooldown_seconds:
                cutoff = datetime.now(timezone.utc) - timedelta(
                    seconds=settings.login_email_cooldown_seconds
                )
                recent = await session.scalar(
                    select(LoginEmailProtectionEvent)
                    .where(
                        LoginEmailProtectionEvent.account_id == account_id,
                        LoginEmailProtectionEvent.status == "succeeded",
                        LoginEmailProtectionEvent.confirmed_at >= cutoff,
                    )
                    .order_by(desc(LoginEmailProtectionEvent.confirmed_at))
                    .limit(1)
                )
                if recent is not None:
                    event.status = "cooldown"
                    await session.commit()
                    await self._notify(
                        f"登录邮箱保护\n账号 #{account_id} 处于换绑冷却期，仅转发本次登录提醒。"
                    )
                    return
            phone = decrypt_text(account.phone_encrypted)
            target_email = build_alias(phone, domain)
            event.target_email_encrypted = encrypt_text(target_email)
            event.status = "requesting"
            event.attempt_count = 1
            await session.commit()

        await self._execute_change(event_id, account_id, target_email, domain, client)

    async def retry(
        self,
        event_id: int,
        domain: str,
        client: TelegramClient,
    ) -> None:
        domain = normalize_domain(domain)
        async with self.sessionmaker() as session:
            if domain not in await get_available_domains(session):
                raise ValueError("邮箱域名不在当前允许列表中")
            event = await session.get(LoginEmailProtectionEvent, event_id)
            if event is None:
                raise ValueError("保护事件不存在")
            account_id = event.account_id
        lock = self._account_locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            async with self.sessionmaker() as session:
                event = await session.get(LoginEmailProtectionEvent, event_id)
                if event is None:
                    raise ValueError("保护事件不存在")
                if event.status in {"requesting", "waiting_email"}:
                    raise ValueError("该账号已有换绑流程正在进行")
                account = await session.get(TgAccount, account_id)
                if account is None:
                    raise ValueError("账号不存在")
                target_email = build_alias(decrypt_text(account.phone_encrypted), domain)
                event.selected_domain = domain
                event.target_email_encrypted = encrypt_text(target_email)
                event.status = "requesting"
                event.error = None
                event.email_requested_at = None
                event.confirmed_at = None
                event.attempt_count += 1
                await session.commit()
            await self._notify(
                f"已开始快捷换绑\n账号：#{account_id}\n目标域名：@{domain}"
            )
            await self._execute_change(event_id, account_id, target_email, domain, client)

    async def _execute_change(
        self,
        event_id: int,
        account_id: int,
        target_email: str,
        domain: str,
        client: TelegramClient,
    ) -> None:
        try:
            await account_ops.send_login_email_code(client, target_email)
            requested_at = datetime.now(timezone.utc)
            await self._set_event_status(
                event_id,
                "waiting_email",
                email_requested_at=requested_at,
            )
            async with self._gmail_slots:
                code = await self.reader.wait_for_code(target_email, requested_at)
            result = await account_ops.confirm_login_email(client, code)
            confirmed_email = str(getattr(result, "email", "") or "")
            if confirmed_email and confirmed_email.lower() != target_email.lower():
                raise RuntimeError("Telegram 返回的确认邮箱与目标邮箱不一致")
            confirmed_at = datetime.now(timezone.utc)
            async with self.sessionmaker() as session:
                security = await session.get(AccountSecurity, account_id)
                if security is None:
                    security = AccountSecurity(account_id=account_id, has_2fa=False)
                    session.add(security)
                security.login_email_encrypted = encrypt_text(target_email)
                event = await session.get(LoginEmailProtectionEvent, event_id)
                if event is not None:
                    event.status = "succeeded"
                    event.error = None
                    event.confirmed_at = confirmed_at
                await session.commit()
            await self._notify(
                "登录邮箱保护成功\n"
                f"账号：#{account_id}\n"
                f"新登录邮箱：{target_email}\n"
                f"完成时间：{confirmed_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
        except asyncio.CancelledError:
            await self._set_event_status(event_id, "interrupted", error="服务停止，流程被中断")
            raise
        except Exception as exc:
            logger.exception("Login email protection failed for account %s", account_id)
            await self._set_event_status(event_id, "failed", error=str(exc))
            await self._notify(
                "登录邮箱保护失败\n"
                f"账号：#{account_id}\n"
                f"本次域名：@{domain}\n"
                f"原因：{str(exc)[:1000]}\n\n"
                "可点击下方按钮选择其他已配置域名重试。",
                reply_markup=self._retry_markup(event_id),
            )
