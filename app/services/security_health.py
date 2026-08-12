from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import TgSession
from app.services.login_email_protection import (
    email_backend_label,
    get_available_domains,
    get_domain_backends,
    get_selected_domain,
    get_whitelist_ids,
)


@dataclass(frozen=True)
class SecurityHealthCheck:
    name: str
    status: str
    detail: str
    fix: str | None = None


@dataclass(frozen=True)
class SecurityHealthReport:
    checks: tuple[SecurityHealthCheck, ...]
    checked_at: datetime

    @property
    def available(self) -> bool:
        return all(check.status == "pass" for check in self.checks)

    def render(self) -> str:
        failed = sum(check.status == "fail" for check in self.checks)
        warnings = sum(check.status == "warn" for check in self.checks)
        if failed:
            conclusion = f"❌ 不可用（{failed} 项失败，{warnings} 项待验证）"
        elif warnings:
            conclusion = f"⚠️ 未证实可用（基础检查通过，{warnings} 项待验证）"
        else:
            conclusion = "✅ 可用（当前配置和运行链路检查通过）"

        icons = {"pass": "✅", "fail": "❌", "warn": "⚠️"}
        lines = ["安全防护全链路检测", f"结论：{conclusion}", ""]
        for index, check in enumerate(self.checks, start=1):
            lines.append(f"{index}. {icons[check.status]} {check.name}：{check.detail}")
            if check.status != "pass" and check.fix:
                lines.append(f"   修复：{check.fix}")
        lines.extend(
            [
                "",
                "说明：本检测不会主动触发 Telegram 登录或修改登录邮箱；真实保护结果以保护成功或失败通知为准。",
                f"检测时间：{self.checked_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            ]
        )
        return "\n".join(lines)


def _check(name: str, ok: bool, detail: str, fix: str) -> SecurityHealthCheck:
    return SecurityHealthCheck(name, "pass" if ok else "fail", detail, None if ok else fix)


def _warning(name: str, detail: str, fix: str) -> SecurityHealthCheck:
    return SecurityHealthCheck(name, "warn", detail, fix)


def _format_account_ids(account_ids: set[int], limit: int = 12) -> str:
    ordered = sorted(account_ids)
    shown = ", ".join(f"#{account_id}" for account_id in ordered[:limit])
    remaining = len(ordered) - limit
    return shown + (f" 等 {len(ordered)} 个" if remaining > 0 else "")


async def run_security_health_check(
    session: AsyncSession,
    client_pool: object,
) -> SecurityHealthReport:
    """Run non-destructive checks across every operational protection dependency."""
    checked_at = datetime.now(UTC)
    checks: list[SecurityHealthCheck] = []

    try:
        await session.execute(text("SELECT 1"))
        domains = await get_available_domains(session)
        domain_backends = await get_domain_backends(session)
        selected_domain = await get_selected_domain(session)
        whitelist_ids = await get_whitelist_ids(session)
        active_account_ids = set(
            (
                await session.scalars(
                    select(TgSession.account_id).where(TgSession.is_active.is_(True))
                )
            ).all()
        )
        checks.append(SecurityHealthCheck("数据库", "pass", "连接及安全防护数据表读取正常"))
    except Exception as exc:  # noqa: BLE001 - surface any database/driver failure with repair guidance
        checks.append(
            SecurityHealthCheck(
                "数据库",
                "fail",
                f"读取失败：{type(exc).__name__}: {str(exc)[:220]}",
                "检查 PostgreSQL、DATABASE_URL 和服务日志，然后执行 .venv/bin/alembic upgrade head。",
            )
        )
        return SecurityHealthReport(tuple(checks), checked_at)

    enabled = settings.login_email_protection_enabled
    checks.append(
        _check(
            "功能开关",
            enabled,
            "LOGIN_EMAIL_PROTECTION_ENABLED 已开启" if enabled else "自动保护开关已关闭",
            "在 .env 设置 LOGIN_EMAIL_PROTECTION_ENABLED=true，并重启服务。",
        )
    )

    required_backends = set(domain_backends.values())
    configured_backends = settings.configured_login_email_backends
    credentials_ready = bool(required_backends) and required_backends.issubset(
        configured_backends
    )
    checks.append(
        _check(
            "邮件接收后端配置",
            credentials_ready,
            "、".join(email_backend_label(item) for item in sorted(required_backends))
            + " 凭据已加载"
            if credentials_ready
            else "域名使用的 Cloudflare TempMail 或 Gmail 后端凭据不完整",
            "按域名选择配置 TEMP_MAIL_WEBHOOK_SECRET 或 Gmail IMAP 凭据，然后重启服务。",
        )
    )

    domain_ready = bool(domains and selected_domain and selected_domain in domains)
    checks.append(
        _check(
            "保护域名",
            domain_ready,
            f"当前域名 @{selected_domain}，共 {len(domains)} 个候选域名"
            if domain_ready
            else "没有有效的当前域名，或当前域名不在候选列表中",
            "进入“邮箱域名管理”添加域名、选择接收后端并点选一个当前域名。",
        )
    )

    if credentials_ready:
        mail_reader_ok = await client_pool.check_login_email_health()
        mail_reader_error = getattr(client_pool, "login_email_health_error", None)
        checks.append(
            _check(
                "邮件接收链路实测",
                mail_reader_ok and not mail_reader_error,
                "当前域名使用到的 Cloudflare TempMail / Gmail 后端均可用"
                if mail_reader_ok and not mail_reader_error
                else f"检测失败：{mail_reader_error or '未知错误'}",
                "检查所选后端的 Webhook 数据表或 Gmail IMAP 凭据，并查看服务日志。",
            )
        )
    else:
        checks.append(
            _warning(
                "邮件接收链路实测",
                "因所需后端凭据不完整而跳过",
                "先配置域名选择对应的 Cloudflare 或 Gmail 凭据，再重新点击检测。",
            )
        )

    monitor_enabled = bool(getattr(client_pool, "monitor_enabled", False))
    monitor_running = bool(getattr(client_pool, "service_monitor_running", False))
    checks.append(
        _check(
            "实时监听任务",
            monitor_enabled and monitor_running,
            "监听开关开启且后台任务正在运行"
            if monitor_enabled and monitor_running
            else f"监听开关={'开启' if monitor_enabled else '关闭'}，后台任务={'运行' if monitor_running else '未运行/已退出'}",
            "到“监控中心”点击“开启监听”；若任务仍未运行，重启服务并查看 journalctl -u tg-account-bot 日志。",
        )
    )

    checks.append(
        _check(
            "Active Session",
            bool(active_account_ids),
            f"发现 {len(active_account_ids)} 个 active 账号"
            if active_account_ids
            else "没有 active 账号",
            "重新登录或导入有效 Session，并确认账号 Session 已设为 active。",
        )
    )

    connected_ids = active_account_ids.intersection(
        getattr(client_pool, "connected_account_ids", set())
    )
    telegram_ok = bool(active_account_ids) and connected_ids == active_account_ids
    if telegram_ok:
        telegram_detail = f"{len(connected_ids)}/{len(active_account_ids)} 个账号已连接"
    else:
        disconnected = active_account_ids - connected_ids
        parts = []
        if not active_account_ids:
            parts.append("无账号可检测")
        if disconnected:
            parts.append(f"未连接账号 {_format_account_ids(disconnected)}")
        telegram_detail = "；".join(parts) or "Telegram 实测未通过"
    checks.append(
        _check(
            "Telegram 账号连接",
            telegram_ok,
            telegram_detail,
            "先在监控中心重新开启监听；仍无法连接的账号需重新登录/导入 Session，并结合账号 last_error 与服务日志排查。",
        )
    )

    protected_ids = active_account_ids.difference(whitelist_ids)
    checks.append(
        _check(
            "自动保护范围",
            bool(protected_ids),
            f"{len(protected_ids)}/{len(active_account_ids)} 个 active 账号允许自动保护"
            if protected_ids
            else "所有 active 账号均在白名单，收到提醒时只会通知而不会换绑",
            "如需自动保护，请从“账号白名单”移出至少一个测试或受保护账号。",
        )
    )

    return SecurityHealthReport(tuple(checks), checked_at)
