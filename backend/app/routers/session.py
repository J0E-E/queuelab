"""The session endpoint: hand a visitor an ephemeral guest identity (TDD §5.8).

``POST /api/session`` is the first call the frontend makes. It mints a throwaway handle
and color (see :mod:`app.services.identity`) and returns them so the UI can show "you are
guest-teal" and attribute this visitor's actions in the activity feed.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.identity import GuestIdentity, create_guest_identity

router = APIRouter(prefix="/api", tags=["session"])


@router.post("/session", response_model=GuestIdentity)
async def create_session() -> GuestIdentity:
    """Create a fresh guest identity (``{session_id, guest_handle, color}``)."""
    return create_guest_identity()
