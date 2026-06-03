"""Integration tests for the durable Postgres layer (Epic 4), against a real Postgres.

Covers ORM round-trips for both tables, that the retention prune removes only aged rows,
and that ``alembic upgrade head`` builds the same schema. Requires a Docker daemon (the
shared conftest spins a throwaway Postgres container).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from app.db.prune import prune_aged_rows, prune_jobs, prune_scaling_events
from app.models import Job, ScalingEvent
from sqlalchemy import create_engine, inspect, select, text

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _make_job_row(**overrides) -> Job:
    """Build a Job ORM row with sensible defaults, overridable per test."""
    now = datetime.now(UTC)
    defaults = {
        "id": uuid4(),
        "session_id": "session-amber",
        "guest_handle": "guest-amber",
        "type": "email",
        "complexity": 1,
        "max_retries": 3,
        "retry_delay_ms": 2000,
        "state": "queued",
        "attempts": 0,
        "submitted_at": now,
    }
    defaults.update(overrides)
    return Job(**defaults)


# ---- ORM round-trips ---------------------------------------------------------------


async def test_job_round_trip(db_session):
    """A fully populated job persists and reads back with every field intact."""
    started = datetime.now(UTC) - timedelta(seconds=5)
    finished = datetime.now(UTC)
    job = _make_job_row(
        type="report",
        complexity=4,
        state="completed",
        attempts=2,
        worker_id="worker-3",
        started_at=started,
        finished_at=finished,
        duration_ms=5000,
        last_error=None,
    )
    db_session.add(job)
    await db_session.commit()

    fetched = await db_session.get(Job, job.id)
    assert fetched is not None
    assert fetched.type == "report"
    assert fetched.complexity == 4
    assert fetched.state == "completed"
    assert fetched.attempts == 2
    assert fetched.worker_id == "worker-3"
    assert fetched.duration_ms == 5000


async def test_job_nullable_columns_default_to_none(db_session):
    """A freshly queued job leaves the in-flight/outcome columns null."""
    job = _make_job_row()
    db_session.add(job)
    await db_session.commit()

    fetched = await db_session.get(Job, job.id)
    assert fetched.worker_id is None
    assert fetched.started_at is None
    assert fetched.finished_at is None
    assert fetched.duration_ms is None
    assert fetched.last_error is None
    # attempts has a server default of 0 even though it was not set explicitly here.
    assert fetched.attempts == 0


async def test_scaling_event_round_trip(db_session):
    """A scaling event persists and its bigserial id is auto-assigned."""
    event = ScalingEvent(
        at=datetime.now(UTC),
        action="scale_up",
        worker_id="worker-4",
        reason="queue_depth 142 > threshold",
        worker_count_after=4,
    )
    db_session.add(event)
    await db_session.commit()

    rows = (await db_session.execute(select(ScalingEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id is not None
    assert rows[0].action == "scale_up"
    assert rows[0].worker_count_after == 4


# ---- Retention prune ---------------------------------------------------------------


async def test_prune_jobs_removes_only_aged_finished_rows(db_session):
    """Prune deletes finished jobs past the window, keeping fresh and unfinished ones."""
    now = datetime.now(UTC)
    aged = _make_job_row(state="completed", finished_at=now - timedelta(hours=48))
    fresh = _make_job_row(state="completed", finished_at=now - timedelta(hours=1))
    running = _make_job_row(state="running", finished_at=None)
    db_session.add_all([aged, fresh, running])
    await db_session.commit()

    deleted = await prune_jobs(db_session, retention_hours=24)
    assert deleted == 1

    survivors = {row.id for row in (await db_session.execute(select(Job))).scalars().all()}
    assert survivors == {fresh.id, running.id}


async def test_prune_scaling_events_removes_only_aged_rows(db_session):
    """Prune deletes scaling events older than the window, keeping recent ones."""
    now = datetime.now(UTC)
    db_session.add_all(
        [
            ScalingEvent(at=now - timedelta(hours=48), action="scale_up", worker_count_after=2),
            ScalingEvent(at=now - timedelta(hours=1), action="scale_down", worker_count_after=1),
        ]
    )
    await db_session.commit()

    deleted = await prune_scaling_events(db_session, retention_hours=24)
    assert deleted == 1

    remaining = (await db_session.execute(select(ScalingEvent))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].action == "scale_down"


async def test_prune_aged_rows_uses_configured_windows(db_session):
    """The combined prune reports both counts using the default 24h windows."""
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_job_row(state="completed", finished_at=now - timedelta(hours=48)),
            ScalingEvent(at=now - timedelta(hours=48), action="destroy", worker_count_after=0),
        ]
    )
    await db_session.commit()

    pruned_jobs, pruned_events = await prune_aged_rows(db_session)
    assert (pruned_jobs, pruned_events) == (1, 1)


# ---- Alembic migration -------------------------------------------------------------


def test_alembic_upgrade_creates_schema(database_url, monkeypatch):
    """``alembic upgrade head`` builds both tables + indexes; downgrade tears them down."""
    from app import config

    # env.py reads the URL from app settings — point it at the throwaway container.
    monkeypatch.setattr(config.settings, "database_url", database_url)

    sync_engine = create_engine(database_url)
    # Reset to a clean schema first: other tests may have created tables on this shared
    # container via Base.metadata.create_all, which would collide with the migration.
    with sync_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

    command.upgrade(alembic_config, "head")
    inspector = inspect(sync_engine)
    assert {"job", "scaling_event"}.issubset(set(inspector.get_table_names()))
    job_indexes = {index["name"] for index in inspector.get_indexes("job")}
    assert {"ix_job_submitted_at", "ix_job_state"}.issubset(job_indexes)
    event_indexes = {index["name"] for index in inspector.get_indexes("scaling_event")}
    assert "ix_scaling_event_at" in event_indexes

    command.downgrade(alembic_config, "base")
    inspector = inspect(sync_engine)
    remaining = set(inspector.get_table_names())
    assert "job" not in remaining
    assert "scaling_event" not in remaining
    sync_engine.dispose()
