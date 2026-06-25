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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.queue.protocol import JobState


@dataclass(frozen=True)
class ActivityLine:
    """The structured parts of one feed line (Epic 17b).

    A line used to be a single pre-baked string. It is now split into parts so the frontend can
    color each piece independently: ``action`` is the body text (rendered in body color), ``state``
    is the job-state word (for its state hue and the failures-only filter), ``attempts`` rides
    along for failures, and ``is_terminal`` marks a *dead* job — one whose retries are exhausted.

    The acting guest's ``handle`` and ``color`` are **not** here: they are resolved per event by the
    subscriber (from ``session_id`` for a job line, or echoed onto a scaling event) and folded in by
    :func:`build_activity_frame`. The flat ``line`` the wire carries for back-compat and screen
    readers is likewise built there, since it needs the resolved handle.
    """

    action: str
    state: str | None = None
    attempts: int | None = None
    is_terminal: bool = False


def format_activity_line(event: dict[str, Any]) -> ActivityLine:
    """Turn one public state-change event into the structured parts of a readable line.

    Each state has its own phrasing; optional fields (``worker_id``, ``attempts``,
    ``last_error``) are read defensively so a sparse event still yields a sensible line, and an
    unrecognized state falls back to a plain ``"<job> → <state>"`` so nothing is ever dropped (a
    missing state reads ``"<job> → unknown"`` rather than leaking a literal ``None``).

    ``is_terminal`` is derived, not stored on the event: a ``failed`` state is only ever published
    once a job's retries are exhausted (``nack.lua`` / ``reap.lua`` keep that invariant), so
    ``state == failed`` *is* "dead". A ``retrying`` line is a will-retry failure, not terminal.
    """
    state = event.get("state")
    job_id = event.get("job_id", "a job")

    if state == JobState.RUNNING:
        action = f"{_worker(event)} started {job_id}"
    elif state == JobState.COMPLETED:
        action = f"{_worker(event)} finished {job_id}"
    elif state == JobState.FAILED:
        action = f"{job_id} failed{_attempt_count(event)}{_reason(event)}"
    elif state == JobState.RETRYING:
        action = f"{job_id} retrying{_attempt_number(event)}"
    elif state == JobState.QUEUED:
        action = f"{job_id} queued"
    else:
        action = f"{job_id} → {state or 'unknown'}"

    return ActivityLine(
        action=action,
        state=state,
        attempts=event.get("attempts"),
        is_terminal=state == JobState.FAILED,
    )


def format_scaling_line(event: dict[str, Any]) -> ActivityLine:
    """Turn one autoscaler action (Epic 11c) into the structured parts of an activity line.

    The event is the payload the autoscaler publishes on ``SCALING_CHANNEL``: ``action``,
    ``worker_id``, ``reason``, and ``worker_count_after``. The ``reason`` already spells out the
    trigger (e.g. "queue_depth 12 > threshold 5 → +2"), so it rides along as a suffix; an
    unrecognized action still yields a sensible line rather than being dropped.

    A scaling action is not a job state, so ``state`` stays ``None`` (it never matches the
    failures-only filter) and it is never terminal — the failure lifecycle is a job concept.
    """
    action = event.get("action")
    worker_count_after = event.get("worker_count_after")
    reason = event.get("reason")
    suffix = f" — {reason}" if reason else ""

    if action == "scale_up":
        body = f"scaled up to {_workers_phrase(worker_count_after)}{suffix}"
    elif action == "scale_down":
        body = f"scaled down to {_workers_phrase(worker_count_after)}{suffix}"
    elif action == "replace":
        body = f"replaced {event.get('worker_id') or 'a worker'}{suffix}"
    elif action == "destroy":
        body = f"destroyed {event.get('worker_id') or 'a worker'}{suffix}"
    else:
        body = f"{action or 'scaling'}{suffix}"
    return ActivityLine(action=body)


def current_time_label() -> str:
    """The ``HH:MM:SS`` stamp the feed shows for an event — the moment the api processed it.

    UTC so every connected client reads the same clock (the dashboard is one shared view, Guide
    §7.6). The events themselves carry no display time, so the subscriber stamps it on arrival.
    """
    return datetime.now(UTC).strftime("%H:%M:%S")


def build_activity_entry(
    parts: ActivityLine,
    *,
    time: str,
    handle: str | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Assemble one structured feed entry from the formatted parts plus the resolved actor.

    Folds the stamped ``time`` and the resolved guest/system ``handle``/``color`` in around the
    structured parts. ``line`` is the flat, readable sentence kept alongside for screen readers and
    for back-compat with a client that has not yet learned the structured shape — it leads with the
    handle when one resolved (``"guest-teal destroyed worker-3"``) so a screen reader still hears
    who acted, and is just the action body when the actor is unattributed.

    This is the shape stored in the ring buffer and carried in the snapshot's ``activity`` list; the
    live ``activity`` WS frame is the same entry with a ``{"type": "activity"}`` envelope added.
    """
    line = f"{handle} {parts.action}" if handle else parts.action
    return {
        "time": time,
        "handle": handle,
        "color": color,
        "action": parts.action,
        "state": parts.state,
        "attempts": parts.attempts,
        "is_terminal": parts.is_terminal,
        "line": line,
    }


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
    """A bounded, in-memory ring buffer of the most recent activity entries.

    Backed by a :class:`collections.deque` with a fixed ``maxlen``, so recording past capacity
    silently drops the oldest entry — the buffer always holds the latest ``max_lines`` and never
    grows without bound. One instance lives on ``app.state`` for the life of the process: the
    activity subscriber fills it and the connection manager reads it to seed new clients.

    Each entry is a structured feed entry (:func:`build_activity_entry`), so a late-joiner is seeded
    with the same colored, attributed history the live stream carries — not a flat string (Epic
    17b).
    """

    def __init__(self, max_lines: int = 50) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_lines)

    def record(self, entry: dict[str, Any]) -> None:
        """Append an entry, evicting the oldest if the buffer is already at capacity."""
        self._entries.append(entry)

    def recent(self) -> list[dict[str, Any]]:
        """Return the buffered entries, oldest first, as a fresh list (a safe copy to send)."""
        return list(self._entries)
