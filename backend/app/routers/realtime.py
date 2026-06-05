"""The real-time WebSocket endpoint: snapshot on connect, then live deltas (Epic 10b).

``WS /ws`` is the browser's live view of the queue. On connect the
:class:`app.realtime.connection_manager.ConnectionManager` accepts the socket and sends a
snapshot frame; from then on the broadcaster pushes a delta frame for every job state change.
This is a shared, multiplayer view — every client sees the same stream, so there is no
per-session filtering or auth here. The endpoint itself only holds the socket open and
deregisters it on disconnect; all fan-out lives in the manager and the broadcaster.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.dependencies import get_connection_manager
from app.realtime.connection_manager import ConnectionManager

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def realtime_feed(
    websocket: WebSocket,
    manager: Annotated[ConnectionManager, Depends(get_connection_manager)],
) -> None:
    """Stream the live queue feed: a snapshot on connect, then per-job deltas.

    The receive loop never expects a client message — this view is read-only — but awaiting
    ``receive_text`` is how Starlette surfaces a disconnect, so the socket is held open until
    the client goes away. Deregistration runs in ``finally`` so the socket is always forgotten,
    whether it left via a clean disconnect or any other error.
    """
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
