"""Unit tests for the Docker control wrapper (Epic 11b): :class:`DockerControl`.

The wrapper only translates autoscaler intent into Docker SDK calls, so these are pure unit tests
against a mocked client — no daemon required. They pin that a spawned worker gets the right image,
network, label, and ``REDIS_URL``; that listing filters by exactly the worker label; and that a
kill stops/removes the container while swallowing an already-gone (``NotFound``) container.
"""

from unittest.mock import MagicMock

from app.config import settings
from app.services.docker_control import (
    WORKER_LABEL,
    WORKER_LABEL_VALUE,
    DockerControl,
)
from docker.errors import NotFound


def make_control() -> tuple[DockerControl, MagicMock]:
    """A ``DockerControl`` over a mock client; returns both so tests can assert on the client."""
    client = MagicMock()
    return DockerControl(client), client


def test_start_worker_runs_image_with_network_label_and_redis_url():
    control, client = make_control()

    container = control.start_worker()

    client.containers.run.assert_called_once_with(
        settings.worker_image,
        detach=True,
        network=settings.worker_network,
        labels={WORKER_LABEL: WORKER_LABEL_VALUE},
        environment={"REDIS_URL": settings.redis_url},
    )
    assert container is client.containers.run.return_value


def test_list_workers_filters_by_the_worker_label():
    control, client = make_control()
    fake_workers = [MagicMock(), MagicMock()]
    client.containers.list.return_value = fake_workers

    workers = control.list_workers()

    client.containers.list.assert_called_once_with(
        filters={"label": f"{WORKER_LABEL}={WORKER_LABEL_VALUE}"}
    )
    assert workers == fake_workers


def test_kill_worker_gets_and_force_removes_the_container():
    control, client = make_control()
    container = MagicMock()
    client.containers.get.return_value = container

    control.kill_worker("worker-abc123")

    client.containers.get.assert_called_once_with("worker-abc123")
    container.remove.assert_called_once_with(force=True)


def test_kill_worker_swallows_a_missing_container():
    control, client = make_control()
    client.containers.get.side_effect = NotFound("no such container")

    # Already gone is success — no raise, and nothing to remove.
    control.kill_worker("worker-gone")

    client.containers.get.assert_called_once_with("worker-gone")


def test_close_closes_the_client():
    control, client = make_control()

    control.close()

    client.close.assert_called_once_with()
