from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="owner")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TgAccount(Base):
    __tablename__ = "tg_accounts"
    __table_args__ = (
        CheckConstraint(
            "login_email_window_hours >= 0 AND login_email_window_hours <= 720",
            name="ck_tg_accounts_login_email_window_hours",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_encrypted: Mapped[str] = mapped_column(Text)
    phone_masked: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128))
    last_name: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    login_email_window_hours: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    sessions: Mapped[list[TgSession]] = relationship(back_populates="account", cascade="all, delete-orphan")


class TgSession(Base):
    __tablename__ = "tg_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("tg_accounts.id", ondelete="CASCADE"), index=True)
    session_encrypted: Mapped[str] = mapped_column(Text)
    session_type: Mapped[str] = mapped_column(String(32), default="string")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    account: Mapped[TgAccount] = relationship(back_populates="sessions")


class AccountSecurity(Base):
    __tablename__ = "account_security"

    account_id: Mapped[int] = mapped_column(ForeignKey("tg_accounts.id", ondelete="CASCADE"), primary_key=True)
    has_2fa: Mapped[bool] = mapped_column(Boolean, default=False)
    twofa_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    hint_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    email_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    login_email_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PrivacySettings(Base):
    __tablename__ = "privacy_settings"

    account_id: Mapped[int] = mapped_column(ForeignKey("tg_accounts.id", ondelete="CASCADE"), primary_key=True)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ServiceMessage(Base):
    __tablename__ = "service_messages"
    __table_args__ = (UniqueConstraint("account_id", "source_user_id", "message_id", name="uq_service_account_source_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("tg_accounts.id", ondelete="CASCADE"), index=True)
    source_user_id: Mapped[int] = mapped_column(BigInteger, default=777000)
    message_id: Mapped[int] = mapped_column(BigInteger)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[Optional[str]] = mapped_column(Text)
    text_preview: Mapped[Optional[str]] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SpamCheck(Base):
    __tablename__ = "spam_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("tg_accounts.id", ondelete="CASCADE"), index=True)
    response_text: Mapped[Optional[str]] = mapped_column(Text)
    status_detected: Mapped[str] = mapped_column(String(64), default="unknown")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AllowedTarget(Base):
    __tablename__ = "allowed_targets"
    __table_args__ = (UniqueConstraint("target_type", "target_ref", name="uq_allowed_target"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_ref: Mapped[str] = mapped_column(String(256))
    title: Mapped[Optional[str]] = mapped_column(String(256))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RateLimit(Base):
    __tablename__ = "rate_limits"
    __table_args__ = (
        CheckConstraint("max_actions > 0", name="ck_rate_max_actions_positive"),
        CheckConstraint("per_seconds > 0", name="ck_rate_per_seconds_positive"),
        CheckConstraint(
            "jitter_min >= 0 AND jitter_max >= jitter_min",
            name="ck_rate_jitter_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), unique=True)
    max_actions: Mapped[int] = mapped_column(Integer)
    per_seconds: Mapped[int] = mapped_column(Integer)
    jitter_min: Mapped[int] = mapped_column(Integer, default=0)
    jitter_max: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)


class JobItem(Base):
    __tablename__ = "job_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tg_accounts.id", ondelete="SET NULL"), index=True)
    target_ref: Mapped[Optional[str]] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(64))
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LoginEmailWhitelist(Base):
    __tablename__ = "login_email_whitelist"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("tg_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginEmailProtectionEvent(Base):
    __tablename__ = "login_email_protection_events"
    __table_args__ = (
        UniqueConstraint("service_message_id", name="uq_login_email_event_message"),
        Index(
            "ix_login_email_events_waiting_window",
            "account_id",
            "status",
            "window_ends_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("tg_accounts.id", ondelete="CASCADE"), index=True
    )
    service_message_id: Mapped[int] = mapped_column(
        ForeignKey("service_messages.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    selected_domain: Mapped[Optional[str]] = mapped_column(String(253))
    target_email_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    parent_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("login_email_protection_events.id", ondelete="CASCADE"), index=True
    )
    window_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_detected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    alert_count: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[Optional[str]] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    email_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


Index(
    "uq_tg_accounts_user_id_not_null",
    TgAccount.user_id,
    unique=True,
    postgresql_where=TgAccount.user_id.is_not(None),
)
Index(
    "uq_tg_sessions_one_active_per_account",
    TgSession.account_id,
    unique=True,
    postgresql_where=TgSession.is_active.is_(True),
)
