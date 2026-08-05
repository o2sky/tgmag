import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest
from aiohttp import web

from app.config import settings
from app.webapp.auth import validate_init_data
from app.webapp.server import error_middleware


def signed_init_data(auth_date: int) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "test-query",
        "user": json.dumps({"id": settings.admin_ids[0], "first_name": "Test"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_valid_init_data_is_accepted() -> None:
    user = validate_init_data(signed_init_data(int(time.time())))
    assert user.id == settings.admin_ids[0]


@pytest.mark.parametrize("offset", [-settings.mini_app_auth_max_age_seconds - 1, 61])
def test_stale_or_future_init_data_is_rejected(offset: int) -> None:
    with pytest.raises(web.HTTPUnauthorized):
        validate_init_data(signed_init_data(int(time.time()) + offset))


def test_mini_app_escapes_dynamic_html() -> None:
    source = Path("app/webapp/static/app.js").read_text(encoding="utf-8")
    assert "function escapeHtml" in source
    assert "${target.target_ref}" not in source
    assert "${account.name ||" not in source


def test_mini_app_reads_telegram_auth_at_request_time() -> None:
    source = Path("app/webapp/static/app.js").read_text(encoding="utf-8")
    assert "function telegramInitData" in source
    assert "const initData = tg?.initData" not in source


def test_mini_app_value_errors_become_bad_requests() -> None:
    request = type("Request", (), {"method": "POST", "path": "/mini-app/api/test"})()

    async def invalid_handler(_request):
        raise ValueError("invalid input")

    with pytest.raises(web.HTTPBadRequest) as captured:
        asyncio.run(error_middleware(request, invalid_handler))
    assert captured.value.text == "invalid input"
