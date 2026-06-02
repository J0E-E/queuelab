"""Unit tests for the centralized backend settings (Epic 2)."""

import pytest
from app.config import Settings, get_settings
from pydantic import ValidationError

# Env vars the Settings model reads; cleared before each test so OS/CI env can't leak in.
SETTINGS_ENV_VARS = (
    "DATABASE_URL",
    "REDIS_URL",
    "MAX_JOBS_PER_SUBMISSION",
    "MAX_TOTAL_QUEUED",
    "MAX_WORKERS",
    "SUBMIT_RATE_SECONDS",
    "CHAOS_RATE_SECONDS",
    "VISIBILITY_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY_MS",
    "MIN_WORKERS",
    "SCALE_UP_THRESHOLD",
    "SCALE_DOWN_THRESHOLD",
    "IDLE_TIMEOUT_SECONDS",
    "AUTOSCALER_LOOP_SECONDS",
    "REDIS_JOB_TTL_SECONDS",
    "JOB_RETENTION_HOURS",
    "SCALING_EVENT_RETENTION_HOURS",
    "WORKER_IMAGE",
)


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Isolate from OS env and any real .env file, so defaults are deterministic."""
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Run from a directory with no .env so file loading can't override defaults.
    monkeypatch.chdir(tmp_path)


def test_defaults_match_tdd(clean_env):
    settings = Settings()

    # Caps (§5.9)
    assert settings.max_jobs_per_submission == 100
    assert settings.max_total_queued == 1000
    assert settings.max_workers == 10

    # Rate limits (§5.9)
    assert settings.submit_rate_seconds == 5
    assert settings.chaos_rate_seconds == 10

    # Queue / lease (§5.3)
    assert settings.visibility_timeout_seconds == 30
    assert settings.default_max_retries == 3
    assert settings.default_retry_delay_ms == 2000

    # Autoscaler (§5.5)
    assert settings.min_workers == 1
    assert settings.scale_up_threshold == 5
    assert settings.scale_down_threshold == 1
    assert settings.idle_timeout_seconds == 30
    assert settings.autoscaler_loop_seconds == 2

    # Retention / TTLs (§5.7, §5.9)
    assert settings.redis_job_ttl_seconds == 3600
    assert settings.job_retention_hours == 24
    assert settings.scaling_event_retention_hours == 24

    # Datastores + worker image
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.worker_image == "queuelab-worker:latest"


def test_env_overrides(clean_env, monkeypatch):
    monkeypatch.setenv("MAX_WORKERS", "3")
    monkeypatch.setenv("SUBMIT_RATE_SECONDS", "15")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("WORKER_IMAGE", "queuelab-worker:dev")

    settings = Settings()

    assert settings.max_workers == 3
    assert settings.submit_rate_seconds == 15
    assert settings.redis_url == "redis://localhost:6379/1"
    assert settings.worker_image == "queuelab-worker:dev"
    # Untouched fields keep their defaults.
    assert settings.max_total_queued == 1000


def test_loads_from_env_file(clean_env, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAX_WORKERS=7\nMAX_TOTAL_QUEUED=500\nDATABASE_URL=postgresql+psycopg://u:p@db:5432/x\n",
        encoding="utf-8",
    )
    # clean_env already chdir'd into tmp_path, so this .env is the one that loads.

    settings = Settings()

    assert settings.max_workers == 7
    assert settings.max_total_queued == 500
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/x"


def test_min_workers_above_max_is_rejected(clean_env):
    with pytest.raises(ValidationError, match="min_workers"):
        Settings(min_workers=12, max_workers=10)


def test_scale_down_above_scale_up_is_rejected(clean_env):
    with pytest.raises(ValidationError, match="scale_down_threshold"):
        Settings(scale_down_threshold=6, scale_up_threshold=5)


@pytest.mark.parametrize(
    "field", ["max_workers", "visibility_timeout_seconds", "submit_rate_seconds"]
)
def test_non_positive_values_are_rejected(clean_env, field):
    with pytest.raises(ValidationError):
        Settings(**{field: 0})


@pytest.mark.parametrize("field", ["min_workers", "scale_down_threshold"])
def test_zero_is_allowed_for_non_negative_fields(clean_env, field):
    settings = Settings(**{field: 0})
    assert getattr(settings, field) == 0


def test_get_settings_is_cached(clean_env):
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second
