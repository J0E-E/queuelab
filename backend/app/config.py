"""Centralized, env-driven backend settings.

A single :class:`Settings` model is the source of truth for guardrail caps, rate
limits, TTLs, queue/lease behavior, autoscaler thresholds, and datastore URLs. Every
backend service (queue client, FastAPI app, reaper, autoscaler, chaos) imports the
shared ``settings`` instance instead of hardcoding magic numbers. Defaults mirror the
TDD (§5.3, §5.5, §5.7, §5.9) and the variable names in ``.env.example``.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Positive-integer field: rejects zero and negatives at load time.
PositiveInt = Annotated[int, Field(gt=0)]
# Non-negative-integer field: allows zero (e.g. scale fully down to no workers).
NonNegativeInt = Annotated[int, Field(ge=0)]


class Settings(BaseSettings):
    """All backend configuration, read from the environment (or a ``.env`` file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Datastores ----
    database_url: str = "postgresql+psycopg://queuelab:change-me@postgres:5432/queuelab"
    redis_url: str = "redis://redis:6379/0"

    # ---- Guardrails: caps (TDD §5.9) ----
    max_jobs_per_submission: PositiveInt = 100
    max_total_queued: PositiveInt = 1000
    max_workers: PositiveInt = 10

    # ---- Guardrails: per-session rate limits, token bucket (TDD §5.9) ----
    submit_rate_seconds: PositiveInt = 5
    chaos_rate_seconds: PositiveInt = 10
    # Session minting is throttled per client IP at the submit interval, so a caller can't
    # rotate fresh sessions faster than it could submit anyway.
    session_rate_seconds: PositiveInt = 5

    # ---- Guest sessions (identity binding) ----
    # How long a minted guest identity stays valid server-side. The submission endpoint
    # derives the trusted guest_handle from this record, so an abandoned session self-cleans
    # once it expires (a day comfortably covers a single visit).
    session_ttl_seconds: PositiveInt = 86_400

    # ---- Queue / lease behavior (TDD §5.3) ----
    visibility_timeout_seconds: PositiveInt = 30
    default_max_retries: PositiveInt = 3
    default_retry_delay_ms: PositiveInt = 2000

    # ---- Reaper (recovery loop, TDD §5.3) ----
    # How often the api process's reaper sweeps: promote due delayed (retrying) jobs back to
    # the ready queue and requeue jobs whose claim deadline (lease) lapsed. A ~1-2s tick,
    # mirroring the autoscaler control loop.
    reaper_loop_seconds: PositiveInt = 2

    # ---- Metrics (snapshot & throttled tick, Epic 10c) ----
    # How often the api process pushes the aggregate queue vitals (counts + queue depth +
    # worker count) to every WS /ws client. The tick timer is itself the throttle, so the
    # dashboard's vitals stay live without re-polling GET /api/metrics.
    metrics_tick_seconds: PositiveInt = 1

    # ---- Activity feed (Epic 10d) ----
    # How many recent activity lines the in-memory ring buffer keeps. A late-joining client is
    # seeded with these on connect (folded into the snapshot frame); past this length the oldest
    # line is dropped. Ephemeral by design — Postgres remains the durable record.
    activity_feed_max_lines: PositiveInt = 50

    # ---- Autoscaler thresholds (TDD §5.5) ----
    # min_workers may be 0 (scale all the way down when idle); scale_down_threshold may be
    # 0 (only scale down when the queue is fully empty).
    min_workers: NonNegativeInt = 1
    scale_up_threshold: PositiveInt = 5
    scale_down_threshold: NonNegativeInt = 1
    idle_timeout_seconds: PositiveInt = 30
    # Control-loop tick; the TDD describes a ~1-2s loop.
    autoscaler_loop_seconds: PositiveInt = 2

    # ---- Retention / TTLs (TDD §5.7, §5.9) ----
    # Hot Redis job records expire after 1h; durable Postgres rows are pruned after 24h.
    redis_job_ttl_seconds: PositiveInt = 3600
    job_retention_hours: PositiveInt = 24
    scaling_event_retention_hours: PositiveInt = 24

    # ---- Worker liveness / registry (TDD §5.4) ----
    # How often a worker refreshes its heartbeat in ``ql:workers``. Several times faster than
    # the visibility timeout so the autoscaler (Epic 11) can spot a dead worker promptly.
    worker_heartbeat_seconds: PositiveInt = 5
    # How stale a worker's last heartbeat may get before the autoscaler treats it as unhealthy
    # and replaces it (Epic 11a). A few heartbeat intervals, so a single missed refresh doesn't
    # condemn a healthy worker.
    worker_unhealthy_after_seconds: PositiveInt = 15

    # ---- Worker image the autoscaler launches at runtime ----
    worker_image: str = "queuelab-worker:latest"

    @model_validator(mode="after")
    def check_worker_bounds(self) -> "Settings":
        """The standing-worker floor must not exceed the hard worker cap."""
        if self.min_workers > self.max_workers:
            raise ValueError(
                f"min_workers ({self.min_workers}) must be <= max_workers ({self.max_workers})"
            )
        return self

    @model_validator(mode="after")
    def check_scale_thresholds(self) -> "Settings":
        """Scale-down must trigger below scale-up, otherwise the loop oscillates."""
        if self.scale_down_threshold > self.scale_up_threshold:
            raise ValueError(
                f"scale_down_threshold ({self.scale_down_threshold}) must be "
                f"<= scale_up_threshold ({self.scale_up_threshold})"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""
    return Settings()


# Module-level convenience singleton for simple imports: ``from app.config import settings``.
settings = get_settings()
