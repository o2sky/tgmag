from __future__ import annotations

import pytest

from app.services.login_email_protection import parse_login_email_window_hours


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 0), (24, 24), ("8", 8), (720, 720)],
)
def test_parse_login_email_window_hours(raw: object, expected: int) -> None:
    assert parse_login_email_window_hours(raw) == expected


@pytest.mark.parametrize("raw", [None, True, -1, 721, 1.5, "abc"])
def test_parse_login_email_window_hours_rejects_invalid_values(raw: object) -> None:
    with pytest.raises(ValueError, match="0–720"):
        parse_login_email_window_hours(raw)
