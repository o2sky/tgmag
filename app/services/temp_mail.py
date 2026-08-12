from __future__ import annotations

import json
from collections.abc import Mapping
from email.utils import getaddresses
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TempMailMessage

ALLOWED_TEMP_MAIL_DOMAINS = frozenset(
    {
        "mail.085580.xyz",
        "yheblog.dpdns.org",
        "maaqidahusymuni.eu.org",
        "yhewall.dpdns.org",
        "yhedesk.dpdns.org",
    }
)


def normalize_recipient(address: str) -> tuple[str, str]:
    normalized = address.strip().lower()
    if len(normalized) > 320 or normalized.count("@") != 1:
        raise ValueError("invalid recipient address")
    local_part, domain = normalized.rsplit("@", 1)
    if not local_part or len(local_part) > 64 or domain not in ALLOWED_TEMP_MAIL_DOMAINS:
        raise ValueError("recipient domain is not allowed")
    return normalized, domain


def parse_allowed_recipients(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, str):
        headers = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        headers = value
    else:
        raise ValueError("to must be an email address or a list of email addresses")
    recipients: list[tuple[str, str]] = []
    seen: set[str] = set()
    for _, address in getaddresses(headers):
        try:
            recipient, domain = normalize_recipient(address)
        except ValueError:
            continue
        if recipient not in seen:
            recipients.append((recipient, domain))
            seen.add(recipient)
    return tuple(recipients)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def store_temp_mail_payload(session: AsyncSession, payload: Mapping[str, Any]) -> int:
    message_id = str(payload.get("id") or "").strip()
    if not message_id or len(message_id) > 255:
        raise ValueError("id must be a non-empty string no longer than 255 characters")
    recipients = parse_allowed_recipients(payload.get("to"))
    if not recipients:
        return 0
    sender = _optional_text(payload.get("from")) or ""
    rows = [
        {
            "id": message_id,
            "to": recipient,
            "from": sender,
            "domain": domain,
            "subject": _optional_text(payload.get("subject")),
            "raw": _optional_text(payload.get("raw")),
            "parsedText": _optional_text(payload.get("parsedText")),
            "parsedHtml": _optional_text(payload.get("parsedHtml")),
            "url": _optional_text(payload.get("url")),
            "aiExtractType": _optional_text(payload.get("aiExtractType")),
            "aiExtractResult": payload.get("aiExtractResult"),
            "aiExtractResultText": _optional_text(payload.get("aiExtractResultText")),
        }
        for recipient, domain in recipients
    ]
    statement = insert(TempMailMessage).values(rows)
    statement = statement.on_conflict_do_nothing(index_elements=["id", "to"])
    result = await session.execute(statement)
    await session.commit()
    return int(result.rowcount or 0)


async def list_messages_for_recipient(
    session: AsyncSession,
    recipient: str,
    *,
    limit: int = 100,
) -> list[TempMailMessage]:
    normalized, _ = normalize_recipient(recipient)
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    result = await session.scalars(
        select(TempMailMessage)
        .where(TempMailMessage.recipient == normalized)
        .order_by(desc(TempMailMessage.received_at))
        .limit(limit)
    )
    return list(result.all())


async def latest_message_for_recipient(
    session: AsyncSession,
    recipient: str,
) -> TempMailMessage | None:
    messages = await list_messages_for_recipient(session, recipient, limit=1)
    return messages[0] if messages else None
