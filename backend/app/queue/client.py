"""Async client for the custom Redis queue (TDD §5.3).

:class:`JobQueue` wraps the raw Redis commands and the all-at-once or not-at-all (atomic)
Lua scripts into a small, typed API the rest of the backend uses: ``enqueue`` (producers),
``claim``/``ack``/``nack`` (workers), ``reap`` (the recovery loop), and read helpers for the
dashboard.

Built on ``redis.asyncio`` so the FastAPI app, the reaper loop, and the WebSocket layer
never block the event loop. All deadline math happens inside the Lua scripts using
Redis ``TIME``; this client passes only durations sourced from :mod:`app.config`.
"""

from __future__ import annotations

from pathlib import Path

from redis.asyncio import Redis
from redis.commands.core import AsyncScript

from app.config import settings

from .protocol import (
    COUNT_FIELDS,
    COUNTS_KEY,
    DELAYED_KEY,
    LEASES_KEY,
    READY_KEY,
    STATE_CHANNEL,
    JobRecord,
    QueueFullError,
    job_key,
    processing_key,
)

# Most jobs the recovery sweep (reaper) handles per pass, so one tick can't take over Redis
# under a flood.
DEFAULT_REAP_BATCH = 100

_SCRIPTS_DIR = Path(__file__).parent / "scripts"


def _load_script(name: str) -> str:
    """Read a Lua script's source from the ``scripts/`` directory next to this module."""
    return (_SCRIPTS_DIR / f"{name}.lua").read_text(encoding="utf-8")


def _decodes_responses(redis: Redis) -> bool:
    """Whether a Redis client was built with ``decode_responses=True`` (text replies)."""
    return bool(redis.connection_pool.connection_kwargs.get("decode_responses", False))


# Read the script sources once at import; each JobQueue registers them on its client.
_CLAIM_SOURCE = _load_script("claim")
_ACK_SOURCE = _load_script("ack")
_NACK_SOURCE = _load_script("nack")
_REAP_SOURCE = _load_script("reap")


class JobQueue:
    """The custom Redis queue, as an async, dependency-injectable client."""

    def __init__(self, redis: Redis) -> None:
        # The client reads job ids and hashes back as text (e.g. the id returned by the
        # grab-and-move (`BLMOVE`) is used to build key names, hash values are decoded into
        # JobRecord). A bytes-mode client would silently build keys like ``ql:job:b'...'``,
        # so require text mode.
        if not _decodes_responses(redis):
            raise ValueError("JobQueue requires a Redis client created with decode_responses=True")
        self._redis = redis
        # register_script computes the script's hash (SHA1) and returns a callable that runs
        # the script by that hash (`EVALSHA`) and automatically re-uploads it (`SCRIPT LOAD`)
        # if Redis doesn't have it yet (`NOSCRIPT`) — so a Redis restart self-heals.
        self._claim: AsyncScript = redis.register_script(_CLAIM_SOURCE)
        self._ack: AsyncScript = redis.register_script(_ACK_SOURCE)
        self._nack: AsyncScript = redis.register_script(_NACK_SOURCE)
        self._reap: AsyncScript = redis.register_script(_REAP_SOURCE)

    @classmethod
    def from_settings(cls) -> JobQueue:
        """Build a queue against the configured Redis URL with string responses."""
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return cls(redis)

    async def aclose(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._redis.aclose()

    # ---- Producer side -----------------------------------------------------------

    async def enqueue(self, job: JobRecord) -> str:
        """Write a job and push it onto the ready queue; return its id.

        Raises :class:`QueueFullError` when the system-wide queued cap is already met.
        This is a soft check (concurrent enqueues can slightly overshoot); a hard cap
        would need its own Lua script.
        """
        if await self.total_queued() >= settings.max_total_queued:
            raise QueueFullError(f"queue at capacity ({settings.max_total_queued} queued)")

        job.state = "queued"
        # Stamp the submission time from Redis TIME (the one authoritative clock), so the
        # hot record carries an enqueued_at even before the worker touches it.
        seconds, microseconds = await self._redis.time()
        job.enqueued_at = (seconds * 1000) + (microseconds // 1000)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(job_key(job.id), mapping=job.to_hash())
            pipe.lpush(READY_KEY, job.id)
            pipe.hincrby(COUNTS_KEY, "queued", 1)
            await pipe.execute()
        return job.id

    # ---- Worker side -------------------------------------------------------------

    async def claim(self, worker_id: str, timeout: float = 0) -> JobRecord | None:
        """Block until a job is available (or ``timeout`` seconds), then claim it.

        Returns ``None`` if the wait timed out with no job. ``timeout=0`` blocks forever,
        so a polling loop should pass a finite value to stay responsive.
        """
        # The blocking grab-and-move (`BLMOVE`) is the all-at-once or not-at-all (atomic)
        # claim: two workers can never pop the same id. Oldest job sits at the right
        # (producers push to the left with `LPUSH`), so pop RIGHT, push LEFT.
        claimed_id = await self._redis.blmove(
            READY_KEY, processing_key(worker_id), timeout, "RIGHT", "LEFT"
        )
        if claimed_id is None:
            return None

        await self._claim(
            keys=[job_key(claimed_id), LEASES_KEY, COUNTS_KEY],
            args=[
                claimed_id,
                worker_id,
                settings.visibility_timeout_seconds * 1000,
                STATE_CHANNEL,
            ],
        )
        raw = await self._redis.hgetall(job_key(claimed_id))
        return JobRecord.from_hash(raw)

    async def ack(self, job_id: str, worker_id: str) -> None:
        """Mark a finished job ``completed`` and clear its in-flight claim.

        Does nothing and returns (no-op) if ``worker_id`` no longer owns the job (its
        time-limited claim, or lease, expired and the recovery sweep (reaper) already put it
        back on the queue (requeue)), so an out-of-date (stale) finish signal can't overwrite
        a newer worker's claim.
        """
        await self._ack(
            keys=[job_key(job_id), processing_key(worker_id), LEASES_KEY, COUNTS_KEY],
            args=[job_id, worker_id, settings.redis_job_ttl_seconds, STATE_CHANNEL],
        )

    async def nack(self, job_id: str, worker_id: str, error: str = "") -> None:
        """Fail a job: retry it with backoff, or mark it terminally ``failed``.

        Like :meth:`ack`, does nothing and returns (no-op) if ``worker_id`` no longer owns
        the job.
        """
        await self._nack(
            keys=[
                job_key(job_id),
                processing_key(worker_id),
                LEASES_KEY,
                DELAYED_KEY,
                COUNTS_KEY,
            ],
            args=[job_id, worker_id, settings.redis_job_ttl_seconds, error, STATE_CHANNEL],
        )

    # ---- Recovery (used by the reaper loop, Epic 9) ------------------------------

    async def reap(self, max_batch: int = DEFAULT_REAP_BATCH) -> tuple[int, int]:
        """Run one all-at-once or not-at-all (atomic) recovery sweep; return
        ``(promoted, recovered)`` counts.

        Moves ready delayed jobs to the active queue (promote) and puts jobs back on the queue
        (requeue) whose claim deadline (lease) passed (a dead worker's in-flight job).
        """
        promoted, recovered = await self._reap(
            keys=[DELAYED_KEY, READY_KEY, LEASES_KEY, COUNTS_KEY],
            args=[settings.redis_job_ttl_seconds, max_batch, STATE_CHANNEL],
        )
        return int(promoted), int(recovered)

    async def promote_due_delayed(self, max_batch: int = DEFAULT_REAP_BATCH) -> int:
        """Run a sweep and return how many delayed jobs were moved to the active queue (promote)."""
        promoted, _ = await self.reap(max_batch)
        return promoted

    async def reap_expired_leases(self, max_batch: int = DEFAULT_REAP_BATCH) -> int:
        """Run a sweep and return how many jobs with an expired claim (lease) were recovered."""
        _, recovered = await self.reap(max_batch)
        return recovered

    # ---- Read helpers ------------------------------------------------------------

    async def counts(self) -> dict[str, int]:
        """Return the live state counts, defaulting any missing field to zero."""
        raw = await self._redis.hgetall(COUNTS_KEY)
        return {field: int(raw.get(field, 0)) for field in COUNT_FIELDS}

    async def queue_depth(self) -> int:
        """Return how many jobs are waiting on the ready queue."""
        return await self._redis.llen(READY_KEY)

    async def total_queued(self) -> int:
        """Return jobs counting toward the cap: ready + delayed (running ones have left)."""
        ready = await self._redis.llen(READY_KEY)
        delayed = await self._redis.zcard(DELAYED_KEY)
        return ready + delayed
