"""The durable ``job`` row — the permanent outcome record behind the Redis hot record.

The Redis :class:`~app.queue.protocol.JobRecord` is the *live* view of a job and expires
an hour after it finishes (TDD §5.7). This table is the *durable* copy the dashboard
reads back from. Its shape follows TDD §5.7: the opaque Redis payload is broken out into
explicit ``type``/``complexity`` columns, the guest's display name (``guest_handle``) is
recorded, and timestamps are real ``timestamptz`` values rather than epoch milliseconds.
The one addition beyond §5.7 is ``last_error``, carried over from the Redis record so a
failure reason is durably stored too.

The durable-writer (Epic 10) maps Redis state-change events onto these rows at runtime;
this module only defines the target shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, SmallInteger, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Job(Base):
    """A single submitted job and its final (or in-progress) outcome."""

    __tablename__ = "job"

    # The API generates the UUID at submission and uses it verbatim as the Redis job id,
    # so the durable row and the hot record always share one key (Epic 7).
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    guest_handle: Mapped[str] = mapped_column(String, nullable=False)
    # Job kind (email|report|image|webhook) and its 1..5 difficulty, broken out of the
    # opaque Redis payload into queryable columns.
    type: Mapped[str] = mapped_column(String, nullable=False)
    complexity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    max_retries: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    retry_delay_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # Stored as text and kept byte-for-byte aligned with the Redis hash values
    # (queued|running|completed|failed|retrying — see app.queue.protocol.JobState).
    state: Mapped[str] = mapped_column(String, nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Indexed for the metrics queries and the retention prune, which both filter by time.
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Wall time spent running, computed by the durable-writer (finished_at - started_at).
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Job id={self.id} state={self.state} type={self.type}>"
