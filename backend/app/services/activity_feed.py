"""Render job state-changes as a human-readable activity feed (Epic 10d).

The dashboard already gets raw ``delta`` frames over ``WS /ws``, but a person watching wants a
plain-language line they can read at a glance — "worker-1 started job-7", "job-7 failed after 3
attempts: …". This module is the two pieces behind that feed:

- :func:`format_activity_line` turns one public state-change event into a single readable line.
- :class:`ActivityFeed` keeps a bounded, in-memory ring buffer of the most recent lines, so a
  freshly-connected client can be seeded with recent history.

The buffer is ephemeral by design — Postgres remains the durable record (Epic 10a); this is just
the last few lines for a late-joiner's screen.

A line is built only from the fields the event itself carries (``job_id``, ``state``,
``worker_id``, ``attempts``, ``last_error``). It deliberately does **not** reach for the job's
``type``/``complexity`` — those live in the Redis hash, which this event-driven path never
re-reads — and it never names ``session_id`` (the rate-limit key the broadcast view withholds).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from app.queue.protocol import JobState


def format_activity_line(event: dict[str, Any]) -> str:
    """Turn one public state-change event into a single human-readable line.

    Each state has its own phrasing; optional fields (``worker_id``, ``attempts``,
    ``last_error``) are read defensively so a sparse event still yields a sensible line, and an
    unrecognized state falls back to a plain ``"<job> → <state>"`` so nothing is ever dropped (a
    missing state reads ``"<job> → unknown"`` rather than leaking a literal ``None``).
    """
    state = event.get("state")
    job_id = event.get("job_id", "a job")

    if state == JobState.RUNNING:
        return f"{_worker(event)} started {job_id}"
    if state == JobState.COMPLETED:
        return f"{_worker(event)} finished {job_id}"
    if state == JobState.FAILED:
        return f"{job_id} failed{_attempt_count(event)}{_reason(event)}"
    if state == JobState.RETRYING:
        return f"{job_id} retrying{_attempt_number(event)}"
    if state == JobState.QUEUED:
        return f"{job_id} queued"
    return f"{job_id} → {state or 'unknown'}"


def format_scaling_line(event: dict[str, Any]) -> str:
    """Turn one autoscaler action (Epic 11c) into a single human-readable activity line.

    The event is the payload the autoscaler publishes on ``SCALING_CHANNEL``: ``action``,
    ``worker_id``, ``reason``, and ``worker_count_after``. The ``reason`` already spells out the
    trigger (e.g. "queue_depth 12 > threshold 5 → +2"), so it rides along as a suffix; an
    unrecognized action still yields a sensible line rather than being dropped.
    """
    action = event.get("action")
    worker_count_after = event.get("worker_count_after")
    reason = event.get("reason")
    suffix = f" — {reason}" if reason else ""

    if action == "scale_up":
        return f"scaled up to {_workers_phrase(worker_count_after)}{suffix}"
    if action == "scale_down":
        return f"scaled down to {_workers_phrase(worker_count_after)}{suffix}"
    if action == "replace":
        return f"replaced {event.get('worker_id') or 'a worker'}{suffix}"
    if action == "destroy":
        return f"destroyed {event.get('worker_id') or 'a worker'}{suffix}"
    return f"{action or 'scaling'}{suffix}"


def _workers_phrase(count: Any) -> str:
    """``"1 worker"`` / ``"2 workers"`` — pluralize so a single-worker line reads naturally."""
    return f"{count} worker" if count == 1 else f"{count} workers"


def _worker(event: dict[str, Any]) -> str:
    """The worker that owns the job, or a neutral stand-in when the event omits one."""
    return event.get("worker_id") or "a worker"


def _attempt_count(event: dict[str, Any]) -> str:
    """An " after N attempts" clause for a failed job, or empty when the count is absent."""
    attempts = event.get("attempts")
    if attempts is None:
        return ""
    unit = "attempt" if attempts == 1 else "attempts"
    return f" after {attempts} {unit}"


def _attempt_number(event: dict[str, Any]) -> str:
    """A " (attempt N)" clause for a retrying job, or empty when the count is absent."""
    attempts = event.get("attempts")
    if attempts is None:
        return ""
    return f" (attempt {attempts})"


def _reason(event: dict[str, Any]) -> str:
    """A ": <error>" clause for a failed job, or empty when no error message rode along."""
    last_error = event.get("last_error")
    if not last_error:
        return ""
    return f": {last_error}"


class ActivityFeed:
    """A bounded, in-memory ring buffer of the most recent activity lines.

    Backed by a :class:`collections.deque` with a fixed ``maxlen``, so recording past capacity
    silently drops the oldest line — the buffer always holds the latest ``max_lines`` and never
    grows without bound. One instance lives on ``app.state`` for the life of the process: the
    activity subscriber fills it and the connection manager reads it to seed new clients.
    """

    def __init__(self, max_lines: int = 50) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)

    def record(self, line: str) -> None:
        """Append a line, evicting the oldest if the buffer is already at capacity."""
        self._lines.append(line)

    def recent(self) -> list[str]:
        """Return the buffered lines, oldest first, as a fresh list (a safe copy to send)."""
        return list(self._lines)
