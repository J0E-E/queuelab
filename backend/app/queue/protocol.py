"""The custom Redis queue protocol: key names, state machine, and payload schema.

This module is the single source of truth for how a job is represented in Redis and
how its state moves (``queued -> running -> completed | failed | retrying -> queued``,
per TDD §5.3). It is intentionally queue-only: it knows nothing about the Postgres
durable record (Epic 4) or HTTP submission DTOs. Producers build a :class:`JobRecord`
and hand it to the client; the client and Lua scripts read/write the keys defined here.

Redis structures (TDD §5.3):

- ``ql:queue:ready``      List   — job IDs awaiting a worker (first-in-first-out (FIFO); add
  to the left (`LPUSH`), claim from the right).
- ``ql:queue:delayed``   ZSet   — retry backoff, scored by ready-at epoch ms.
- ``ql:leases``          ZSet   — in-flight job IDs scored by lease deadline (epoch ms).
- ``ql:job:{id}``        Hash   — the full job payload + state + attempt counters.
- ``ql:processing:{w}``  List   — the single job worker ``w`` is currently running.
- ``ql:counts``          Hash   — live counts for O(1) dashboard reads.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---- Fixed key names (single-keyspace, no per-tenant prefixing) -------------------
READY_KEY = "ql:queue:ready"
DELAYED_KEY = "ql:queue:delayed"
LEASES_KEY = "ql:leases"
COUNTS_KEY = "ql:counts"

# Worker registry (TDD §5.4): a Hash mapping ``worker_id -> JSON {state, current_job,
# last_heartbeat}``. Each worker is the only writer of its own field; the autoscaler
# (Epic 11) reads this to count live workers and reap ones whose heartbeat has gone stale.
WORKERS_KEY = "ql:workers"

# Single pub/sub channel for state-change events. The real-time layer (Epic 10)
# subscribes here and fans messages out to WebSocket clients; each message is a JSON
# blob carrying job_id, the new state, session_id, and timing fields.
STATE_CHANNEL = "ql:events:state"

# Pub/sub channel for autoscaler actions (Epic 11c). The autoscaler runs in its own process and
# publishes each scaling action here; the api's scaling-feed subscriber renders it as an activity
# line. A dedicated channel keeps these off STATE_CHANNEL, whose subscribers (broadcaster,
# durable-writer) would otherwise misread a scaling action as a job state-change.
SCALING_CHANNEL = "ql:events:scaling"

# Pub/sub channel for manual scaling commands (Epic 11d-1). This is the *request* side that mirrors
# SCALING_CHANNEL's *outcome* side: an operator trigger publishes a command here and the autoscaler
# process consumes it and carries it out. The publishers are Epic 12 (chaos endpoints) and Epic 14
# (the frontend's scale/destroy controls); both send the shape
# ``{"command": "scale_up", "count": N}`` / ``{"command": "scale_down", "worker_id": "X"}``. The key
# is ``command`` (the imperative request), distinct from the ``action`` key on SCALING_CHANNEL, but
# the verbs match the ``ScalingDecision.action`` vocabulary so they map straight onto the policy.
CONTROL_CHANNEL = "ql:control"


def job_key(job_id: str) -> str:
    """Return the Redis Hash key holding the full record for ``job_id``."""
    return f"ql:job:{job_id}"


def processing_key(worker_id: str) -> str:
    """Return the Redis List key holding the in-flight job for ``worker_id``.

    Lua scripts that recover a dead worker's job build this same string inline (a
    single-node assumption — Redis Cluster forbids touching keys not in ``KEYS``).
    """
    return f"ql:processing:{worker_id}"


class JobState(StrEnum):
    """The states a job moves through. Values are stored verbatim in the job hash."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class JobType(StrEnum):
    """The kinds of work a guest can submit (TDD §2.1, §5.7).

    This is the one canonical list of job types. It lives here in the queue protocol so the
    worker (Epic 8), which vendors :mod:`app.queue`, reads the same vocabulary when it picks a
    per-type duration and failure profile. The submission endpoint (Epic 7) validates the
    requested type against these values and stores the chosen one verbatim.
    """

    EMAIL = "email"
    REPORT = "report"
    IMAGE = "image"
    WEBHOOK = "webhook"


# Field names inside the ``ql:counts`` hash. They mirror the state values exactly so a
# Lua script can adjust a count by name with one step (``HINCRBY ql:counts <state> ±1``,
# which adds ±1 to a hash field). ``queued``,
# ``running``, and ``retrying`` are live gauges (up and down); ``completed`` and
# ``failed`` are cumulative lifetime totals that are never decremented (so a dashboard
# read stays O(1) even after a job hash ages out via TTL).
COUNT_FIELDS: tuple[str, ...] = (
    JobState.QUEUED.value,
    JobState.RUNNING.value,
    JobState.COMPLETED.value,
    JobState.FAILED.value,
    JobState.RETRYING.value,
)


class QueueFullError(RuntimeError):
    """Raised when an enqueue would exceed the system-wide queued cap (TDD §5.9)."""


# Field groups that drive hash encode/decode, kept together so to_hash and from_hash
# stay in lockstep. Required-int fields are always present; nullable fields are omitted
# from the hash when None.
_INT_FIELDS = ("attempts", "max_retries", "retry_delay_ms")
_NULLABLE_INT_FIELDS = ("enqueued_at", "started_at", "completed_at")
_NULLABLE_STRING_FIELDS = ("worker_id", "last_error")


class JobRecord(BaseModel):
    """A job as the queue sees it — payload, state, attempt counters, and timing.

    Timestamps are epoch milliseconds (the same unit the Lua scripts compute from
    ``redis.call('TIME')``). ``payload`` is opaque submission data, serialized into the
    hash as a single ``payload_json`` string.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: str
    session_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    state: JobState = JobState.QUEUED
    attempts: int = 0
    max_retries: int
    retry_delay_ms: int
    worker_id: str | None = None
    enqueued_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None
    last_error: str | None = None

    def to_hash(self) -> dict[str, str]:
        """Encode this record as a flat string→string mapping for ``HSET``.

        Every value is a UTF-8 string. ``None`` fields are omitted entirely (never the
        literal ``"None"``), so ``from_hash`` can treat an absent key as ``None``.
        """
        hash_fields: dict[str, str] = {
            "id": self.id,
            "session_id": self.session_id,
            "state": self.state if isinstance(self.state, str) else self.state.value,
            "attempts": str(self.attempts),
            "max_retries": str(self.max_retries),
            "retry_delay_ms": str(self.retry_delay_ms),
            "payload_json": json.dumps(self.payload, separators=(",", ":")),
        }
        for name in _NULLABLE_INT_FIELDS:
            value = getattr(self, name)
            if value is not None:
                hash_fields[name] = str(value)
        for name in _NULLABLE_STRING_FIELDS:
            value = getattr(self, name)
            if value is not None:
                hash_fields[name] = value
        return hash_fields

    @classmethod
    def from_hash(cls, raw: Mapping[Any, Any]) -> JobRecord:
        """Rebuild a record from ``HGETALL`` output, tolerating bytes or str keys/values."""
        decoded = {_as_text(key): _as_text(value) for key, value in raw.items()}
        if not decoded:
            raise KeyError("cannot build JobRecord from an empty hash")

        fields: dict[str, Any] = {
            "id": decoded["id"],
            "session_id": decoded["session_id"],
            "state": decoded["state"],
            "payload": json.loads(decoded.get("payload_json", "{}")),
        }
        for name in _INT_FIELDS:
            fields[name] = int(decoded[name])
        for name in _NULLABLE_INT_FIELDS:
            if name in decoded:
                fields[name] = int(decoded[name])
        for name in _NULLABLE_STRING_FIELDS:
            if name in decoded:
                fields[name] = decoded[name]
        return cls(**fields)


def _as_text(value: Any) -> str:
    """Decode a Redis bytes value to str; pass through values already decoded."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
