from __future__ import annotations

from cryptography.fernet import Fernet

from app.config import settings

fernet = Fernet(settings.fernet_key.encode())


def encrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    return fernet.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str | None) -> str | None:
    if value is None:
        return None
    return fernet.decrypt(value.encode("ascii")).decode("utf-8")


def mask_phone(phone: str) -> str:
    clean = phone.strip()
    if len(clean) <= 7:
        return clean[:2] + "***"
    return clean[:4] + "****" + clean[-3:]
