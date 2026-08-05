from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobItem


async def create_job(session: AsyncSession, job_type: str, params: dict[str, Any]) -> Job:
    job = Job(type=job_type, status="running", params_json=params, started_at=datetime.now(timezone.utc))
    session.add(job)
    await session.flush()
    return job


async def add_job_item(
    session: AsyncSession,
    job: Job,
    account_id: int | None,
    target_ref: str | None,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    session.add(
        JobItem(
            job_id=job.id,
            account_id=account_id,
            target_ref=target_ref,
            status=status,
            result_json=result,
            error=error,
        )
    )


async def finish_job(session: AsyncSession, job: Job, status: str, error: str | None = None) -> None:
    job.status = status
    job.error = error
    job.finished_at = datetime.now(timezone.utc)
