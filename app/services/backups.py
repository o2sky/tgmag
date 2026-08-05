from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.config import settings


def create_database_backup(prefix: str = "manual") -> Path:
    """Create a restricted PostgreSQL custom-format backup without exposing credentials."""
    parsed = urlparse(settings.sync_database_url)
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.path:
        raise RuntimeError("DATABASE_URL 不是有效的 PostgreSQL 连接串")

    backup_dir = settings.backup_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"{prefix}_{timestamp}.dump"

    command = [
        "pg_dump",
        "--format=custom",
        "--no-password",
        "--file",
        str(path),
        "--dbname",
        unquote(parsed.path.lstrip("/")),
    ]
    if parsed.hostname:
        command.extend(["--host", parsed.hostname])
    if parsed.port:
        command.extend(["--port", str(parsed.port)])
    if parsed.username:
        command.extend(["--username", unquote(parsed.username)])

    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    try:
        result = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or "pg_dump 执行失败").strip()[:1000])
        path.chmod(0o600)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


async def create_database_backup_async(prefix: str = "manual") -> Path:
    return await asyncio.to_thread(create_database_backup, prefix)
