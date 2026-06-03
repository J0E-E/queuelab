"""The shared declarative base for all ORM models.

Every model inherits from :class:`Base`, so they all register their tables on one
``Base.metadata`` object. Alembic points its ``target_metadata`` at that same object to
see the full schema, and the tests build it directly with ``Base.metadata.create_all``.
Keeping the base in its own tiny module avoids import cycles (models import only this,
not the engine).
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base; one metadata object for models + Alembic."""
