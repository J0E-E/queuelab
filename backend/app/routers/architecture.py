"""The architecture endpoint: in-context explanatory notes for the dashboard (Epic 15).

``GET /api/architecture`` returns the static architecture notes (see
:mod:`app.services.architecture`) so the frontend can surface the explanation of each mechanic
beside the live pane that shows it. Public and unauthenticated, like ``GET /api/metrics``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import ArchitectureResponse
from app.services.architecture import get_architecture_sections

router = APIRouter(prefix="/api", tags=["architecture"])


@router.get("/architecture", response_model=ArchitectureResponse)
async def get_architecture() -> ArchitectureResponse:
    """Return the in-context architecture notes the dashboard renders."""
    return ArchitectureResponse(sections=get_architecture_sections())
