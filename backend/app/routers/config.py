"""The live config endpoint: read and retune the autoscaler thresholds at runtime (Epic 11d-2).

``GET /api/config`` returns the autoscaler thresholds currently in force — the env-loaded defaults
with any ``ql:config`` override applied — and ``PUT /api/config`` writes a partial patch of them.
The autoscaler process merges the same ``ql:config`` hash over its base settings every tick, so a
change here takes effect within a tick or two without a redeploy. Validation reuses the
:class:`app.config.Settings` model: the patch is merged into a full settings object and revalidated,
so an out-of-range value or a cross-field violation (``scale_down_threshold`` above
``scale_up_threshold``) is rejected here in the system voice rather than poisoning the control loop.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.config import OVERRIDABLE_CONFIG_KEYS, Settings, settings
from app.dependencies import get_queue
from app.models.schemas import AutoscalerConfig, AutoscalerConfigUpdate
from app.queue.client import JobQueue

router = APIRouter(prefix="/api", tags=["config"])


def _effective_config(overrides: dict[str, int]) -> AutoscalerConfig:
    """Fold the stored overrides over the env defaults and return the values now in force."""
    effective = {key: overrides.get(key, getattr(settings, key)) for key in OVERRIDABLE_CONFIG_KEYS}
    return AutoscalerConfig(**effective)


@router.get("/config", response_model=AutoscalerConfig)
async def get_config(
    queue: Annotated[JobQueue, Depends(get_queue)],
) -> AutoscalerConfig:
    """Return the autoscaler thresholds in force (env defaults with live overrides applied)."""
    return _effective_config(await queue.get_config())


@router.put("/config", response_model=AutoscalerConfig)
async def update_config(
    update: AutoscalerConfigUpdate,
    queue: Annotated[JobQueue, Depends(get_queue)],
) -> AutoscalerConfig:
    """Write a partial patch of autoscaler thresholds and return the new values in force.

    Only the keys present in the body are written; the rest keep their prior override or env
    default. The merged result is revalidated through :class:`Settings`, so a bad value or an
    inconsistent pair is rejected with a ``422`` in the system voice before anything is stored.
    """
    patch: dict[str, int] = update.model_dump(exclude_unset=True)
    if not patch:
        return _effective_config(await queue.get_config())

    overrides = await queue.get_config()
    merged = {**settings.model_dump(), **overrides, **patch}
    try:
        Settings(**merged)
    except ValidationError as error:
        message = error.errors()[0].get("msg", "invalid value")
        raise HTTPException(
            status_code=422,
            detail=f"[ERR] invalid config: {message}",
        ) from error

    await queue.set_config(patch)
    return _effective_config({**overrides, **patch})
