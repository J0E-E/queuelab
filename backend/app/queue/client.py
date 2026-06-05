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

import json
from pathlib import Path

from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.commands.core import AsyncScript

from app.config import settings

from .protocol import (
    COUNT_FIELDS,
    COUNTS_KEY,
    DELAYED_KEY,
    LEASES_KEY,
    READY_KEY,
    STATE_CHANNEL,
    WORKERS_KEY,
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
_RENEW_SOURCE = _load_script("renew")
_REQUEUE_SOURCE = _load_script("requeue")
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
        self._renew: AsyncScript = redis.register_script(_RENEW_SOURCE)
        self._requeue: AsyncScript = redis.register_script(_REQUEUE_SOURCE)
        self._reap: AsyncScript = redis.register_script(_REAP_SOURCE)

    @classmethod
    def from_settings(cls) -> JobQueue:
        """Build a queue against the configured Redis URL with string responses."""
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return cls(redis)

    async def aclose(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._redis.aclose()

    def pubsub(self) -> PubSub:
        """Return a fresh pub/sub handle on the shared Redis connection pool.

        The durable-writer (Epic 10a) and the real-time broadcaster (Epic 10b) subscribe to
        the state-change channel through this, reusing the queue's connection pool rather than
        opening a second Redis client. Each handle checks out its own dedicated connection, so
        a subscription never contends with the queue's regular command traffic.
        """
        return self._redis.pubsub()

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

    async def renew_lease(self, job_id: str, worker_id: str) -> None:
        """Push out the claim deadline (lease) for a job this worker is still running.

        A worker calls this periodically while a long job runs so the recovery sweep (reaper)
        doesn't treat a slow-but-alive worker as dead and put its in-flight job back on the
        queue (requeue). Does nothing and returns (no-op) if ``worker_id`` no longer owns the
        job — the same stale-owner fence as :meth:`ack` / :meth:`nack`.
        """
        await self._renew(
            keys=[job_key(job_id), LEASES_KEY],
            args=[job_id, worker_id, settings.visibility_timeout_seconds * 1000],
        )

    async def requeue(self, job_id: str, worker_id: str) -> None:
        """Cleanly return an in-flight job to the ready queue as ``queued`` (TDD §5.4).

        Used by a worker's graceful shutdown to hand its in-flight job straight back without
        burning a retry: unlike :meth:`nack` it **does not touch ``attempts``** and skips the
        retry backoff. Does nothing and returns (no-op) if ``worker_id`` no longer owns the
        job — the same stale-owner fence as :meth:`ack` / :meth:`nack`.
        """
        await self._requeue(
            keys=[
                job_key(job_id),
                processing_key(worker_id),
                LEASES_KEY,
                READY_KEY,
                COUNTS_KEY,
            ],
            args=[job_id, worker_id, STATE_CHANNEL],
        )

    # ---- Worker registry (TDD §5.4; read by the autoscaler, Epic 11) -------------

    async def heartbeat(
        self, worker_id: str, *, state: str, current_job: str | None = None
    ) -> None:
        """Register the worker (first call) and refresh its liveness in ``ql:workers``.

        Writes the worker's ``{state, current_job, last_heartbeat}`` record, stamping
        ``last_heartbeat`` from Redis ``TIME`` (the one authoritative clock, so the
        autoscaler's staleness check is free of cross-container clock skew). Each worker is
        the sole writer of its own field, so a plain timestamp-then-write needs no Lua script.
        """
        seconds, microseconds = await self._redis.time()
        now_ms = (seconds * 1000) + (microseconds // 1000)
        record = json.dumps(
            {"state": state, "current_job": current_job, "last_heartbeat": now_ms},
            separators=(",", ":"),
        )
        await self._redis.hset(WORKERS_KEY, worker_id, record)

    async def deregister_worker(self, worker_id: str) -> None:
        """Remove a worker's registry field, so a cleanly stopped worker disappears at once.

        A hard-killed worker can't call this; its stale field lingers until the autoscaler
        (Epic 11) reaps it by heartbeat age.
        """
        await self._redis.hdel(WORKERS_KEY, worker_id)

    async def list_workers(self) -> dict[str, dict]:
        """Return the registry as ``{worker_id: {state, current_job, last_heartbeat}}``."""
        raw = await self._redis.hgetall(WORKERS_KEY)
        return {worker_id: json.loads(record) for worker_id, record in raw.items()}

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

    async def active_jobs(self) -> list[JobRecord]:
        """Return the records of every job currently in the system, for a fresh snapshot.

        "Active" means not yet aged out: jobs waiting on the ready queue, in flight under a
        claim (lease), or waiting on the delayed (retry-backoff) set. The real-time layer
        (Epic 10b) sends these the moment a browser connects, so a late-joiner sees the live
        grid seeded rather than just the aggregate counts.

        A job sits in exactly one of those three structures at a time, but ids are de-duplicated
        defensively (a claim or requeue racing this read could briefly show one in two places).
        Each id's full record lives in its own ``ql:job:{id}`` hash; those are read in a single
        pipeline. A hash that vanished between listing its id and reading it (a TTL lapse or a
        concurrent ack) is skipped, so the snapshot is best-effort and never raises on a
        mid-flight change.
        """
        ready = await self._redis.lrange(READY_KEY, 0, -1)
        leased = await self._redis.zrange(LEASES_KEY, 0, -1)
        delayed = await self._redis.zrange(DELAYED_KEY, 0, -1)

        seen: set[str] = set()
        ordered_ids: list[str] = []
        for job_id in (*ready, *leased, *delayed):
            if job_id not in seen:
                seen.add(job_id)
                ordered_ids.append(job_id)
        if not ordered_ids:
            return []

        async with self._redis.pipeline(transaction=False) as pipe:
            for job_id in ordered_ids:
                pipe.hgetall(job_key(job_id))
            hashes = await pipe.execute()

        return [JobRecord.from_hash(raw) for raw in hashes if raw]
