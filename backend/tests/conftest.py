"""Shared fixtures for the queue integration suite (Epic 3).

A real Redis is auto-provisioned with testcontainers (one container per test session),
and the keyspace is flushed before each test so cases stay isolated. Requires a working
Docker daemon on the test runner.
"""

import pytest
import pytest_asyncio
from app.queue.client import JobQueue
from app.queue.protocol import JobRecord
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer


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
