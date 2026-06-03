"""Retention prune: delete aged durable rows so the database stays bounded (TDD §5.9).

On a small single-instance deployment the durable record can't grow forever, so a
periodic caller (wired up in a later epic) runs these helpers to drop old rows:

- finished ``job`` rows older than ``job_retention_hours`` (default 24h),
- ``scaling_event`` rows older than ``scaling_event_retention_hours`` (default 24h).

Each function returns how many rows it deleted so callers and tests can assert on the
effect. Jobs that haven't finished yet (null ``finished_at``) are never pruned — a null
never compares as less-than the cutoff — so in-flight work is safe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.job import Job
from app.models.scaling_event import ScalingEvent


async def _delete_finished_jobs(session: AsyncSession, hours: int) -> int:
    """Delete finished jobs older than ``hours`` and return the count; does not save (no commit).

    Filters on ``finished_at``, which is deliberately left unindexed (§5.7 only indexes
    ``submitted_at``/``state``): under 24h retention on this bounded single-instance
    deployment the table stays tiny, so a full-table scan is cheap. Add an index on
    ``finished_at`` only if the row volume ever grows.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    result = await session.execute(delete(Job).where(Job.finished_at < cutoff))
    return result.rowcount or 0


async def _delete_aged_scaling_events(session: AsyncSession, hours: int) -> int:
    """Delete scaling events older than ``hours`` and return the count; does not commit."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    result = await session.execute(delete(ScalingEvent).where(ScalingEvent.at < cutoff))
    return result.rowcount or 0


async def prune_jobs(session: AsyncSession, *, retention_hours: int | None = None) -> int:
    """Delete finished jobs older than the retention window; return the count removed.

    ``retention_hours`` defaults to ``settings.job_retention_hours`` but is overridable so
    tests can use a tight window.
    """
    hours = settings.job_retention_hours if retention_hours is None else retention_hours
    removed = await _delete_finished_jobs(session, hours)
    await session.commit()
    return removed


async def prune_scaling_events(session: AsyncSession, *, retention_hours: int | None = None) -> int:
    """Delete scaling events older than the retention window; return the count removed.

    ``retention_hours`` defaults to ``settings.scaling_event_retention_hours`` but is
    overridable so tests can use a tight window.
    """
    hours = settings.scaling_event_retention_hours if retention_hours is None else retention_hours
    removed = await _delete_aged_scaling_events(session, hours)
    await session.commit()
    return removed


async def prune_aged_rows(session: AsyncSession) -> tuple[int, int]:
    """Run both prunes with the configured windows; return ``(jobs, scaling_events)`` removed.

    Both deletes are saved together in a single transaction (one commit), so the combined
    prune either fully applies or not at all (atomic) and never commits unrelated pending
    changes on the caller's session twice.
    """
    pruned_jobs = await _delete_finished_jobs(session, settings.job_retention_hours)
    pruned_events = await _delete_aged_scaling_events(
        session, settings.scaling_event_retention_hours
    )
    await session.commit()
    return pruned_jobs, pruned_events
