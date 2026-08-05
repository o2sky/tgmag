import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.config import settings
from app.tg.client_pool import ClientPool


class FakeSession:
    def __init__(self, record):
        self.record = record
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def scalar(self, statement):
        return self.record

    async def commit(self):
        self.committed = True


class FakeSessionmaker:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


def test_existing_service_row_still_reaches_protector() -> None:
    text = "Login code: 97588. Do not give this code to anyone."
    record = SimpleNamespace(
        id=73,
        text=text,
        text_preview=text,
        text_hash="outdated",
    )
    session = FakeSession(record)
    pool = ClientPool.__new__(ClientPool)
    pool.sessionmaker = FakeSessionmaker(session)
    pool.bot = SimpleNamespace(send_message=AsyncMock())
    pool.login_email_protector = SimpleNamespace(handle=AsyncMock())
    pool._service_message_locks = {}
    pool._protection_tasks = set()
    pool._is_post_session_login_alert = AsyncMock(return_value=True)

    client = object()

    async def exercise() -> None:
        await pool._ingest_service_message(
            account_id=4,
            source_user_id=777000,
            message_id=99,
            text=text,
            received_at=datetime.now(UTC),
            client=client,
        )
        await asyncio.sleep(0)

    asyncio.run(exercise())

    pool.login_email_protector.handle.assert_awaited_once_with(4, 73, text, client)
    pool.bot.send_message.assert_not_awaited()
    assert session.committed is True


def test_initial_manual_login_alert_is_stored_without_protection() -> None:
    text = "Login code: 97588. Do not give this code to anyone."
    record = SimpleNamespace(
        id=74,
        text=text,
        text_preview=text,
        text_hash="current",
    )
    session = FakeSession(record)
    pool = ClientPool.__new__(ClientPool)
    pool.sessionmaker = FakeSessionmaker(session)
    pool.bot = SimpleNamespace(send_message=AsyncMock())
    pool.login_email_protector = SimpleNamespace(handle=AsyncMock())
    pool._service_message_locks = {}
    pool._protection_tasks = set()
    pool._is_post_session_login_alert = AsyncMock(return_value=False)

    async def exercise() -> None:
        await pool._ingest_service_message(
            account_id=4,
            source_user_id=777000,
            message_id=100,
            text=text,
            received_at=datetime.now(UTC),
            client=object(),
        )
        await asyncio.sleep(0)

    asyncio.run(exercise())

    pool.login_email_protector.handle.assert_not_awaited()
    pool.bot.send_message.assert_not_awaited()
    assert session.committed is True


def test_only_login_alerts_after_active_session_are_protected() -> None:
    baseline = datetime.now(UTC)
    session = FakeSession(baseline)
    pool = ClientPool.__new__(ClientPool)
    pool.sessionmaker = FakeSessionmaker(session)
    text = "登录验证码：97588。请勿将验证码告诉任何人。"

    assert (
        asyncio.run(pool._is_post_session_login_alert(8, text, baseline - timedelta(seconds=1)))
        is False
    )
    assert asyncio.run(pool._is_post_session_login_alert(8, text, baseline)) is False
    assert (
        asyncio.run(pool._is_post_session_login_alert(8, text, baseline + timedelta(seconds=1)))
        is True
    )


def test_reconnect_catches_up_only_fresh_login_alerts(monkeypatch) -> None:
    monkeypatch.setattr(settings, "login_email_protection_enabled", True)
    monkeypatch.setattr(settings, "login_email_catchup_seconds", 180)
    now = datetime.now(UTC)
    fresh = SimpleNamespace(id=3, message="登录验证码：97588", date=now - timedelta(seconds=30))
    old = SimpleNamespace(id=2, message="Login code: 12345", date=now - timedelta(minutes=10))
    unrelated = SimpleNamespace(id=1, message="Two-Step Verification changed", date=now)
    client = SimpleNamespace(get_messages=AsyncMock(return_value=[fresh, old, unrelated]))
    pool = ClientPool.__new__(ClientPool)
    pool.monitor_enabled = True
    pool._ingest_service_message = AsyncMock()

    asyncio.run(pool.catch_up_recent_login_alerts(8, client))

    pool._ingest_service_message.assert_awaited_once()
    assert pool._ingest_service_message.await_args.args[:4] == (8, 777000, 3, fresh.message)


def test_gmail_health_check_records_failure_and_recovery() -> None:
    reader = SimpleNamespace(
        validate_connection=AsyncMock(side_effect=RuntimeError("login failed"))
    )
    pool = ClientPool.__new__(ClientPool)
    pool.login_email_protector = SimpleNamespace(reader=reader)
    pool._login_email_health_lock = asyncio.Lock()
    pool.login_email_health_checked_at = None
    pool.login_email_health_error = None

    async def exercise() -> None:
        assert await pool.check_login_email_health() is False
        assert pool.login_email_health_checked_at is not None
        assert "login failed" in (pool.login_email_health_error or "")

        reader.validate_connection.side_effect = None
        assert await pool.check_login_email_health() is True
        assert pool.login_email_health_error is None

    asyncio.run(exercise())


def test_connected_account_ids_excludes_disconnected_clients() -> None:
    pool = ClientPool.__new__(ClientPool)
    pool.clients = {
        1: SimpleNamespace(is_connected=lambda: True),
        2: SimpleNamespace(is_connected=lambda: False),
    }
    assert pool.connected_account_ids == {1}


def test_monitor_runtime_state_requires_a_live_task() -> None:
    pool = ClientPool.__new__(ClientPool)
    pool.monitor_enabled = True
    pool._monitor_task = SimpleNamespace(done=lambda: False)
    assert pool.service_monitor_running is True

    pool._monitor_task = SimpleNamespace(done=lambda: True)
    assert pool.service_monitor_running is False
