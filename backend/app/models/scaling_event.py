"""The durable ``scaling_event`` row — an audit trail of every autoscaler action.

The autoscaler (Epic 11) records each thing it does — scaling up, scaling down,
destroying a worker, replacing an unhealthy one, or acting on a manual command — as one
row here and also publishes it to the activity feed (TDD §5.5, §5.7). The feed and the
retention prune both read by time, so ``at`` is indexed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScalingEvent(Base):
    """One recorded autoscaler action and the worker count that resulted from it."""

    __tablename__ = "scaling_event"

    # A monotonically increasing big integer (bigserial) — cheap to generate and order by.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # scale_up | scale_down | destroy | replace | manual.
    action: Mapped[str] = mapped_column(String, nullable=False)
    # Set only for actions aimed at a specific worker (destroy/replace); null otherwise.
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Free text explaining why, e.g. "queue_depth 142 > threshold".
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_count_after: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    def __repr__(self) -> str:
        return f"<ScalingEvent id={self.id} action={self.action} at={self.at}>"
