from datetime import UTC, datetime

import pytest

from app.db.models import TempMailMessage
from app.services.login_email_protection import TempMailCodeReader
from app.services.temp_mail import (
    ALLOWED_TEMP_MAIL_DOMAINS,
    normalize_recipient,
    parse_allowed_recipients,
)


def test_all_configured_domains_accept_arbitrary_local_parts() -> None:
    for domain in ALLOWED_TEMP_MAIL_DOMAINS:
        address = f"arbitrary-123_{len(domain)}@{domain}"
        assert normalize_recipient(address) == (address, domain)


def test_recipient_parser_keeps_only_allowed_domains() -> None:
    assert parse_allowed_recipients(
        "Alice <ABC@mail.085580.xyz>, attacker@example.com"
    ) == (("abc@mail.085580.xyz", "mail.085580.xyz"),)


def test_invalid_recipient_is_rejected_for_queries() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        normalize_recipient("abc@example.com")


def test_temp_mail_reader_extracts_matching_telegram_code(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.login_email_sender", "noreply@telegram.org")
    message = TempMailMessage(
        id="cloudflare-message-1",
        recipient="abc@mail.085580.xyz",
        sender="Telegram <noreply@telegram.org>",
        domain="mail.085580.xyz",
        subject="Your Code - 853353",
        parsed_text="Your code is: 853353. Use it to verify your email for Login.",
        received_at=datetime.now(UTC),
    )
    assert TempMailCodeReader._extract_code(message, "abc@mail.085580.xyz") == "853353"
    assert TempMailCodeReader._extract_code(message, "other@mail.085580.xyz") is None
