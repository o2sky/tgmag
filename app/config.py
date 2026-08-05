from __future__ import annotations

import json
import re
from functools import cached_property
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(..., alias="BOT_TOKEN")
    tg_api_id: int = Field(..., alias="TG_API_ID")
    tg_api_hash: str = Field(..., alias="TG_API_HASH")
    admin_ids: Annotated[list[int], NoDecode] = Field(..., alias="ADMIN_IDS")
    database_url: str = Field(..., alias="DATABASE_URL")
    fernet_key: str = Field(..., alias="FERNET_KEY")
    session_dir: Path = Field(default=Path("./data/sessions"), alias="SESSION_DIR")
    backup_dir: Path = Field(default=Path("./data/backups"), alias="BACKUP_DIR")
    default_rate_max_actions: int = Field(default=8, ge=1, le=1000, alias="DEFAULT_RATE_MAX_ACTIONS")
    default_rate_per_seconds: int = Field(default=60, ge=1, le=86400, alias="DEFAULT_RATE_PER_SECONDS")
    default_jitter_min: int = Field(default=2, ge=0, le=3600, alias="DEFAULT_JITTER_MIN")
    default_jitter_max: int = Field(default=6, ge=0, le=3600, alias="DEFAULT_JITTER_MAX")
    service_monitor_interval_seconds: int = Field(default=300, ge=30, alias="SERVICE_MONITOR_INTERVAL_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    mini_app_enabled: bool = Field(default=False, alias="MINI_APP_ENABLED")
    mini_app_host: str = Field(default="127.0.0.1", alias="MINI_APP_HOST")
    mini_app_port: int = Field(default=8080, ge=1, le=65535, alias="MINI_APP_PORT")
    mini_app_public_url: str = Field(default="", alias="MINI_APP_PUBLIC_URL")
    mini_app_auth_max_age_seconds: int = Field(default=3600, ge=60, le=86400, alias="MINI_APP_AUTH_MAX_AGE_SECONDS")
    login_email_protection_enabled: bool = Field(default=True, alias="LOGIN_EMAIL_PROTECTION_ENABLED")
    login_email_alias_domains_raw: str = Field(default="", alias="LOGIN_EMAIL_ALIAS_DOMAINS")
    login_email_gmail_username: str = Field(default="", alias="LOGIN_EMAIL_GMAIL_USERNAME")
    login_email_gmail_app_password: str = Field(default="", alias="LOGIN_EMAIL_GMAIL_APP_PASSWORD")
    login_email_imap_host: str = Field(default="imap.gmail.com", alias="LOGIN_EMAIL_IMAP_HOST")
    login_email_imap_port: int = Field(default=993, ge=1, le=65535, alias="LOGIN_EMAIL_IMAP_PORT")
    login_email_imap_folder: str = Field(default="INBOX", alias="LOGIN_EMAIL_IMAP_FOLDER")
    login_email_sender: str = Field(default="noreply@telegram.org", alias="LOGIN_EMAIL_SENDER")
    login_email_poll_timeout_seconds: int = Field(default=180, ge=30, le=900, alias="LOGIN_EMAIL_POLL_TIMEOUT_SECONDS")
    login_email_poll_interval_seconds: int = Field(default=3, ge=1, le=30, alias="LOGIN_EMAIL_POLL_INTERVAL_SECONDS")
    login_email_cooldown_seconds: int = Field(default=300, ge=0, le=86400, alias="LOGIN_EMAIL_COOLDOWN_SECONDS")
    login_email_catchup_seconds: int = Field(default=180, ge=0, le=3600, alias="LOGIN_EMAIL_CATCHUP_SECONDS")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> list[int]:
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                decoded = json.loads(stripped)
                if not isinstance(decoded, list):
                    raise ValueError("ADMIN_IDS JSON value must be a list")
                parsed = [int(v) for v in decoded]
            else:
                parsed = [int(v.strip()) for v in stripped.split(",") if v.strip()]
            if parsed:
                return parsed
            raise ValueError("ADMIN_IDS must not be empty")
        raise ValueError("ADMIN_IDS must be a comma separated list, JSON list, or integer")

    @field_validator("login_email_alias_domains_raw")
    @classmethod
    def validate_login_email_alias_domains(cls, value: str) -> str:
        domains = [item.strip().lower().lstrip("@") for item in value.split(",") if item.strip()]
        pattern = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
        invalid = [domain for domain in domains if not pattern.fullmatch(domain)]
        if invalid:
            raise ValueError(f"invalid login email alias domain: {invalid[0]}")
        if len(domains) != len(set(domains)):
            raise ValueError("LOGIN_EMAIL_ALIAS_DOMAINS contains duplicates")
        return ",".join(domains)

    @field_validator("login_email_gmail_username")
    @classmethod
    def normalize_gmail_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("login_email_gmail_app_password")
    @classmethod
    def normalize_gmail_app_password(cls, value: str) -> str:
        return "".join(value.split())

    @model_validator(mode="after")
    def validate_login_email_protection(self) -> Settings:
        if self.login_email_protection_enabled:
            required = {
                "LOGIN_EMAIL_ALIAS_DOMAINS": self.login_email_alias_domains_raw,
                "LOGIN_EMAIL_GMAIL_USERNAME": self.login_email_gmail_username,
                "LOGIN_EMAIL_GMAIL_APP_PASSWORD": self.login_email_gmail_app_password,
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise ValueError(f"login email protection is enabled but missing: {', '.join(missing)}")
        return self

    @cached_property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "")

    @cached_property
    def bot_user_id(self) -> int:
        try:
            return int(self.bot_token.split(":", 1)[0])
        except (TypeError, ValueError, IndexError):
            return 0

    @cached_property
    def login_email_alias_domains(self) -> tuple[str, ...]:
        return tuple(item for item in self.login_email_alias_domains_raw.split(",") if item)


settings = Settings()
