"""The WebSocket connection manager: track clients and seed each with a snapshot (Epic 10b).

A single :class:`ConnectionManager` lives on ``app.state`` for the life of the process. The
``WS /ws`` endpoint hands it every new connection; the manager accepts the socket, remembers
it, and immediately sends a *snapshot* frame so a freshly-connected browser sees the current
queue state without waiting for the next change. The broadcaster (Epic 10b, phase 2) then calls
:meth:`broadcast` to fan a per-job *delta* frame out to every remembered socket.

Two envelope types travel over the socket, both ``{"type": …}``:

- ``snapshot`` — sent once on connect: the live counts plus the in-flight jobs.
- ``delta``    — sent per state change by the broadcaster.

The per-job projection deliberately drops ``session_id``. That id is the rate-limit key and
the REST layer never returns it (see :class:`app.models.schemas.JobResponse`); this shared,
broadcast-to-everyone view keeps the same posture.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from app.queue.client import JobQueue
from app.queue.protocol import JobRecord

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Track connected WebSocket clients and send them snapshot/delta frames."""

    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new client, send the opening snapshot frame, then remember it.

        The snapshot is sent *before* the socket joins the broadcast set so two things hold: a
        send that fails never leaves a dead socket registered, and the client's first frame is
        always the snapshot — never a delta that raced ahead of it.
        """
        await websocket.accept()
        await websocket.send_json(await self._build_snapshot())
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Forget a client once it has gone away. Safe to call for an unknown socket."""
        self._connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send one frame to every connected client, dropping any socket that fails.

        Iterates a copy of the connection set so a disconnect mid-fan-out can't disturb the
        loop, and removes any socket whose send raises — one dead client must never stop the
        rest from getting the delta (the same "skip one bad thing, carry on" posture the
        durable-writer takes with a bad event).
        """
        for websocket in list(self._connections):
            try:
                await websocket.send_json(message)
            except Exception:
                logger.debug("realtime: dropping a client that failed mid-broadcast")
                self._connections.discard(websocket)

    async def _build_snapshot(self) -> dict[str, Any]:
        """Build the snapshot frame: the live counts plus every in-flight job (public fields)."""
        counts = await self._queue.counts()
        records = await self._queue.active_jobs()
        return {
            "type": "snapshot",
            "counts": counts,
            "jobs": [_project_job(record) for record in records],
        }


def _project_job(record: JobRecord) -> dict[str, Any]:
    """Project a hot :class:`JobRecord` to the public fields broadcast over the socket.

    Drops ``session_id`` (the rate-limit key, never exposed) and lifts ``type``/``complexity``
    out of the opaque payload so the dashboard grid can label each job.
    """
    return {
        "job_id": record.id,
        "state": record.state,
        "attempts": record.attempts,
        "worker_id": record.worker_id,
        "type": record.payload.get("type"),
        "complexity": record.payload.get("complexity"),
        "enqueued_at": record.enqueued_at,
        "started_at": record.started_at,
    }
