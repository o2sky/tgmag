from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import settings
from app.services import login_email_protection
from app.services.login_email_protection import (
    GmailCodeReader,
    LoginEmailProtector,
    build_alias,
    is_login_code_alert,
    normalize_domain,
    parse_telegram_login_email,
    recover_incomplete_events,
)


SAMPLE_EMAIL = b"""From: Telegram <noreply@telegram.org>
To: testime001@mail.example.com
Date: Wed, 5 Aug 2026 13:46:00 +0800
Subject: Your Code - 853353
Content-Type: text/plain; charset=utf-8

Dear he,

Your code is: 853353. Use it to verify your email for Login.

If you didn't request this, simply ignore this message.

Yours,
The Telegram Team
"""


def test_login_code_alert_matches_supported_777000_wording() -> None:
    assert is_login_code_alert(
        "Login code:97588. Do not give this code to anyone, even if they say they are from Telegram!"
    )
    assert is_login_code_alert(
        "Your login code is 97588. Enter it in the Telegram app where you are trying to log in."
    )
    assert is_login_code_alert("登录验证码：97588。请勿将验证码告诉任何人。")
    assert is_login_code_alert("Код для входа: 97588. Никому не сообщайте этот код.")
    assert is_login_code_alert("Código de inicio de sesión: 97588")
    assert not is_login_code_alert("Your code is: 853353. Use it to verify your email for Login.")
    assert not is_login_code_alert("Login code requested, but the numeric code is absent.")
    assert not is_login_code_alert("Two-Step Verification settings changed on 05/08/2026.")


def test_telegram_email_parser_correlates_sender_recipient_purpose_and_code() -> None:
    parsed = parse_telegram_login_email(SAMPLE_EMAIL, "testime001@mail.example.com")
    assert parsed is not None
    assert parsed.code == "853353"
    assert parsed.recipient == "testime001@mail.example.com"
    assert parsed.sent_at is not None


def test_telegram_email_parser_omits_missing_recipient_headers(monkeypatch) -> None:
    original = login_email_protection.getaddresses

    def strict_getaddresses(values):
        if any(not value for value in values):
            return []
        return original(values)

    monkeypatch.setattr(login_email_protection, "getaddresses", strict_getaddresses)
    parsed = parse_telegram_login_email(SAMPLE_EMAIL, "testime001@mail.example.com")
    assert parsed is not None
    assert parsed.code == "853353"


def test_telegram_email_parser_rejects_wrong_alias_or_sender() -> None:
    assert parse_telegram_login_email(SAMPLE_EMAIL, "another@mail.example.com") is None
    forged = SAMPLE_EMAIL.replace(b"noreply@telegram.org", b"attacker@example.org")
    assert parse_telegram_login_email(forged, "testime001@mail.example.com") is None


def test_telegram_email_parser_rejects_mismatched_subject_code() -> None:
    mismatched = SAMPLE_EMAIL.replace(b"Your Code - 853353", b"Your Code - 111111")
    assert parse_telegram_login_email(mismatched, "testime001@mail.example.com") is None


def test_alias_uses_timestamp_and_phone_digits() -> None:
    assert build_alias("+1 202 555 0147", "mail.example.com", 1775550123) == (
        "1775550123_12025550147@mail.example.com"
    )


def test_domain_normalization_and_validation() -> None:
    assert normalize_domain(" @Mail.Example.COM ") == "mail.example.com"
    for invalid in ("", "https://example.com", "user@example.com", "-bad.example"):
        try:
            normalize_domain(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid domain: {invalid}")


def test_failed_event_retry_button_uses_inline_callback() -> None:
    payload = LoginEmailProtector._retry_markup(42).model_dump(exclude_none=True)
    button = payload["inline_keyboard"][0][0]
    assert button["text"] == "快捷换绑登录邮箱"
    assert button["callback_data"] == "emailguard:retrymenu:42"


def test_gmail_reader_finds_exact_forwarded_alias(monkeypatch) -> None:
    class FakeImap:
        def __init__(self, *args, **kwargs):
            self.logged_in = False

        def login(self, username, password):
            assert username == "owner@gmail.com"
            assert password == "app-password"
            self.logged_in = True
            return "OK", []

        def select(self, folder, readonly=False):
            assert self.logged_in and folder == "INBOX" and readonly is True
            return "OK", []

        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"101"]
            assert command == "fetch" and args[0] == b"101"
            return "OK", [(b"101 (BODY[] {1})", SAMPLE_EMAIL), b")"]

        def logout(self):
            return "BYE", []

    monkeypatch.setattr("app.services.login_email_protection.imaplib.IMAP4_SSL", FakeImap)
    monkeypatch.setattr(settings, "login_email_gmail_username", "owner@gmail.com")
    monkeypatch.setattr(settings, "login_email_gmail_app_password", "app-password")
    monkeypatch.setattr(settings, "login_email_poll_timeout_seconds", 1)
    monkeypatch.setattr(settings, "login_email_poll_interval_seconds", 0.01)
    code = GmailCodeReader().wait_for_code_sync(
        "testime001@mail.example.com",
        datetime(2026, 8, 5, 5, 45, tzinfo=timezone.utc),
    )
    assert code == "853353"


def test_incomplete_protection_events_become_retryable() -> None:
    class Result:
        rowcount = 3

    class Session:
        committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def execute(self, statement):
            assert "login_email_protection_events" in str(statement)
            return Result()

        async def commit(self):
            self.committed = True

    session = Session()

    class Sessionmaker:
        def __call__(self):
            return session

    assert asyncio.run(recover_incomplete_events(Sessionmaker())) == 3
    assert session.committed is True
