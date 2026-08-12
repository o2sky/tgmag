import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models import RuntimeSetting, TempMailMessage
from app.services import login_email_protection
from app.services.login_email_protection import (
    DOMAIN_BACKENDS_KEY,
    DOMAINS_KEY,
    RoutedCodeReader,
    TempMailCodeReader,
    get_domain_backends,
    set_domain_backend,
)
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


def test_recipient_parser_can_restrict_webhook_to_cloudflare_domains() -> None:
    assert parse_allowed_recipients(
        "cf@mail.085580.xyz, gmail@yheblog.dpdns.org",
        {"mail.085580.xyz"},
    ) == (("cf@mail.085580.xyz", "mail.085580.xyz"),)


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


def test_routed_reader_selects_backend_from_target_domain(monkeypatch) -> None:
    class Sessionmaker:
        def __call__(self):
            class Context:
                async def __aenter__(self):
                    return SimpleNamespace()

                async def __aexit__(self, exc_type, exc, traceback):
                    return False

            return Context()

    reader = RoutedCodeReader(Sessionmaker())
    cloudflare_reader = SimpleNamespace(wait_for_code=AsyncMock(return_value="111111"))
    gmail_reader = SimpleNamespace(wait_for_code=AsyncMock(return_value="222222"))
    reader.readers = {"cloudflare": cloudflare_reader, "gmail": gmail_reader}
    selected_backend = AsyncMock(side_effect=["cloudflare", "gmail"])
    monkeypatch.setattr(login_email_protection, "get_domain_backend", selected_backend)
    requested_at = datetime.now(UTC)

    async def exercise() -> None:
        assert (
            await reader.wait_for_code("a@mail.085580.xyz", requested_at, 30)
            == "111111"
        )
        assert (
            await reader.wait_for_code("b@yheblog.dpdns.org", requested_at, 30)
            == "222222"
        )

    asyncio.run(exercise())
    cloudflare_reader.wait_for_code.assert_awaited_once_with(
        "a@mail.085580.xyz", requested_at, 30
    )
    gmail_reader.wait_for_code.assert_awaited_once_with(
        "b@yheblog.dpdns.org", requested_at, 30
    )


def test_domain_backend_selection_is_persisted(monkeypatch) -> None:
    rows = {
        DOMAINS_KEY: RuntimeSetting(
            key=DOMAINS_KEY,
            value='["mail.085580.xyz", "yheblog.dpdns.org"]',
        )
    }

    class Session:
        committed = False

        async def get(self, model, key):
            assert model is RuntimeSetting
            return rows.get(key)

        def add(self, row):
            rows[row.key] = row

        async def commit(self):
            self.committed = True

    session = Session()
    monkeypatch.setattr(
        "app.config.settings.login_email_gmail_username", "owner@gmail.com"
    )
    monkeypatch.setattr(
        "app.config.settings.login_email_gmail_app_password", "app-password"
    )

    async def exercise() -> None:
        await set_domain_backend(session, "yheblog.dpdns.org", "gmail")
        routes = await get_domain_backends(session)
        assert routes == {
            "mail.085580.xyz": "cloudflare",
            "yheblog.dpdns.org": "gmail",
        }

    asyncio.run(exercise())
    assert session.committed is True
    assert '"yheblog.dpdns.org": "gmail"' in rows[DOMAIN_BACKENDS_KEY].value
