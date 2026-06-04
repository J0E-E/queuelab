"""Shared fixtures for the backend integration suite (Epics 3 & 4).

A real Redis and a real Postgres are auto-provisioned with testcontainers (one container
each per test session). Redis is flushed before each test, and the Postgres schema is
dropped and recreated before each test, so cases stay isolated. Requires a working Docker
daemon on the test runner.

On Windows the default asyncio loop is the ProactorEventLoop, which psycopg3 cannot use in
async mode; we switch the policy to the SelectorEventLoop before any loop is created. This
is a no-op on Linux/CI (where containers run), so it only affects local Windows dev.
"""

import asyncio
import sys

import pytest
import pytest_asyncio
from app.db.base import Base
from app.db.engine import Database
from app.dependencies import get_database, get_queue, get_rate_limiter, get_session_store
from app.main import app
from app.queue.client import JobQueue
from app.queue.protocol import JobRecord
from app.services.rate_limit import RateLimiter
from app.services.session_store import SessionStore
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

# Set the loop policy at import time — this runs long before pytest-asyncio creates the
# first event loop, and before psycopg opens any async connection.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def redis_container():
    """A throwaway Redis 7 container, shared across the whole test session."""
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def redis_url(redis_container):
    """The connection URL for the session's Redis container."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def redis_client(redis_url):
    """A fresh async Redis client; flushes the keyspace before each test."""
    client = Redis.from_url(redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def queue(redis_client):
    """A JobQueue bound to the per-test Redis client."""
    return JobQueue(redis_client)


@pytest_asyncio.fixture
async def rate_limiter(redis_client):
    """A RateLimiter bound to the per-test Redis client."""
    return RateLimiter(redis_client)


@pytest_asyncio.fixture
async def session_store(redis_client):
    """A SessionStore bound to the per-test Redis client."""
    return SessionStore(redis_client)


@pytest.fixture(scope="session")
def postgres_container():
    """A throwaway Postgres 16 container, shared across the whole test session.

    ``driver="psycopg"`` makes the connection URL use the psycopg3 driver
    (``postgresql+psycopg://``), the same async-capable driver the app uses — psycopg2 is
    not installed.
    """
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres_container):
    """The async connection URL for the session's Postgres container."""
    return postgres_container.get_connection_url()


@pytest_asyncio.fixture
async def database(database_url):
    """A Database with a freshly created schema; drops and rebuilds tables per test."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    db = Database(engine)
    yield db
    await db.aclose()


@pytest_asyncio.fixture
async def db_session(database):
    """An open AsyncSession bound to the per-test Database."""
    async with database.session() as session:
        yield session


@pytest_asyncio.fixture
async def api_client(queue, database, rate_limiter, session_store):
    """An httpx client driving the FastAPI app against the per-test container clients.

    The app's lifespan would build its own ``from_settings()`` clients pointed at the compose
    URLs, so instead we override the dependency providers to hand routes the test fixtures.
    Driving the ASGI app directly (no lifespan) keeps all route I/O on this test's event loop —
    the same loop the async Redis/Postgres fixtures live on — which a threaded TestClient would
    not. Overrides are cleared after the test so cases stay isolated.
    """
    app.dependency_overrides[get_queue] = lambda: queue
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter
    app.dependency_overrides[get_session_store] = lambda: session_store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def make_job():
    """Factory for JobRecords with unique ids and small, fast retry backoff."""
    counter = {"created": 0}

    def _make(**overrides):
        counter["created"] += 1
        defaults = {
            "id": f"job-{counter['created']}",
            "session_id": "guest-amber",
            "payload": {"type": "email", "complexity": 1},
            "max_retries": 2,
            "retry_delay_ms": 50,
        }
        defaults.update(overrides)
        return JobRecord(**defaults)

    return _make
