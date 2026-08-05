from __future__ import annotations

import asyncio
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import RateLimit


def validate_rate_values(
    max_actions: int,
    per_seconds: int,
    jitter_min: int,
    jitter_max: int,
) -> tuple[int, int, int, int]:
    if not 1 <= max_actions <= 1000:
        raise ValueError("max_actions 必须在 1 到 1000 之间")
    if not 1 <= per_seconds <= 86400:
        raise ValueError("per_seconds 必须在 1 到 86400 之间")
    if jitter_min < 0 or jitter_max < jitter_min or jitter_max > 3600:
        raise ValueError("jitter 必须满足 0 <= min <= max <= 3600")
    return max_actions, per_seconds, jitter_min, jitter_max


async def get_rate(session: AsyncSession, scope: str = "batch") -> RateLimit:
    rate = await session.scalar(select(RateLimit).where(RateLimit.scope == scope))
    if rate:
        return rate
    return RateLimit(
        scope=scope,
        max_actions=settings.default_rate_max_actions,
        per_seconds=settings.default_rate_per_seconds,
        jitter_min=settings.default_jitter_min,
        jitter_max=settings.default_jitter_max,
    )


class RateGate:
    def __init__(self, rate: RateLimit):
        self.rate = rate
        self._count = 0
        self._window_started = asyncio.get_event_loop().time()

    async def wait(self) -> None:
        now = asyncio.get_event_loop().time()
        elapsed = now - self._window_started
        if elapsed >= self.rate.per_seconds:
            self._window_started = now
            self._count = 0
        if self._count >= self.rate.max_actions:
            await asyncio.sleep(max(0, self.rate.per_seconds - elapsed))
            self._window_started = asyncio.get_event_loop().time()
            self._count = 0
        self._count += 1
        if self.rate.jitter_max > 0:
            await asyncio.sleep(random.uniform(self.rate.jitter_min, self.rate.jitter_max))
