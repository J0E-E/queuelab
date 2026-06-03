"""Async SQLAlchemy engine and session factory for the durable Postgres record.

This mirrors the queue client's conventions (:mod:`app.queue.client`): an injectable
:class:`Database` plus a ``from_settings`` constructor that reads the configured
database URL. It is built on ``create_async_engine`` over the ``postgresql+psycopg``
driver (psycopg3 serves async), so the FastAPI app and background loops never block the
event loop while waiting on the database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


class Database:
    """The Postgres connection, as an async, dependency-injectable client."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        # A row's attributes stay readable after a save — without this, SQLAlchemy would
        # expire them on save (commit) and the next read would re-query — so a caller can
        # return a just-written object as-is (``expire_on_commit=False``).
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )

    @classmethod
    def from_settings(cls) -> Database:
        """Build a database client against the configured database URL.

        ``pool_pre_ping`` quietly checks a pooled connection is still alive before handing
        it out, so a connection dropped by Postgres or the network self-heals on next use.
        """
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        return cls(engine)

    @property
    def engine(self) -> AsyncEngine:
        """The underlying async engine (used by Alembic and the test schema setup)."""
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Open a session, closing it when the ``async with`` block exits.

        The caller is responsible for committing; the session only guarantees cleanup.
        """
        async with self._session_factory() as session:
            yield session

    async def aclose(self) -> None:
        """Dispose the engine and close its connection pool."""
        await self._engine.dispose()
