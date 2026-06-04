"""The session endpoint: hand a visitor an ephemeral guest identity (TDD §5.8).

``POST /api/session`` is the first call the frontend makes. It mints a throwaway handle
and color (see :mod:`app.services.identity`) and returns them so the UI can show "you are
guest-teal" and attribute this visitor's actions in the activity feed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_rate_limiter, get_session_store
from app.services.identity import GuestIdentity, create_guest_identity
from app.services.rate_limit import RateLimiter
from app.services.session_store import SessionStore

router = APIRouter(prefix="/api", tags=["session"])


def client_ip(request: Request) -> str:
    """Best-effort caller IP for throttling session minting.

    In production the api sits behind nginx, which sets ``X-Forwarded-For``; the left-most
    entry is the original client, so we use it when present (this trusts nginx to set and
    sanitize that header — a deploy concern, Epic 19). Otherwise we fall back to the direct
    peer address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/session", response_model=GuestIdentity)
async def create_session(
    request: Request,
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> GuestIdentity:
    """Create a fresh guest identity (``{session_id, guest_handle, color}``).

    Minting is rate-limited per client IP so a caller can't spin up sessions faster than it
    could submit (which would otherwise dodge the per-session submit limit). The identity is
    then persisted server-side before it is returned, so a later ``POST /api/jobs`` can trust
    the session id and derive the handle from this record instead of believing the request body.
    """
    await rate_limiter.check_session(client_ip(request))
    identity = create_guest_identity()
    await session_store.save(identity)
    return identity
