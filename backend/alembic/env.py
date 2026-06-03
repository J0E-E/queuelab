"""Alembic migration environment, wired to the async engine.

Unlike a stock Alembic setup, the database URL comes from app settings (not alembic.ini),
so there is one source of truth. Online migrations run through the async engine: Alembic's
migration context is synchronous, so we open an async connection and hand control to it via
``connection.run_sync`` (run this sync function on the async connection).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

import app.models  # noqa: F401  -- registers all tables on Base.metadata
from alembic import context
from app.config import settings
from app.db.base import Base
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Alembic's .ini config object; used here only for logging setup.
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The full schema Alembic compares against for autogenerate.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without connecting to a database (--sql mode)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run the migrations against an already-open (sync-facing) connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Open an async connection and run the migrations on it."""
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
