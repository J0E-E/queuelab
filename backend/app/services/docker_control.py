"""The autoscaler's hands: a thin Docker wrapper that spawns, lists, and kills workers (Epic 11b).

Epic 11a gave the autoscaler its brain (:func:`app.services.autoscaler.decide_scaling`, a pure
decision); this module gives it hands. :class:`DockerControl` wraps the Docker SDK and talks to
the daemon over the socket mounted into the ``autoscaler`` compose service
(``/var/run/docker.sock``): it can ``start_worker`` (run a fresh worker container), ``list_workers``
(every worker container it has spawned), and ``kill_worker`` (stop and remove one by id).

It does no scaling decisions and touches no Redis/Postgres — the ~1-2s control loop that ties this
to the policy lands in Epic 11c. The Docker client is injected, so the whole wrapper is unit-tested
with a mocked SDK and never needs a real daemon.

Every spawned worker carries the ``com.queuelab.role=worker`` label (so list/kill can filter to
just our workers) and joins ``settings.worker_network`` so it can reach the ``redis`` compose
service by hostname.
"""

from __future__ import annotations

import docker
from docker.errors import NotFound
from docker.models.containers import Container

from app.config import settings

# Label stamped on every worker container so the autoscaler can find exactly the containers it
# spawned (and never touch unrelated containers on the same daemon).
WORKER_LABEL = "com.queuelab.role"
WORKER_LABEL_VALUE = "worker"

# Compose project/service labels so Docker Desktop nests these runtime-spawned workers under the
# queuelab stack (grouped like the api/redis/postgres containers) instead of listing them loose at
# the top level. Docker Desktop groups by the project label; the service label gives them a tidy
# "worker" heading within that group. These are cosmetic — the role label above is what list/kill
# actually filter on.
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


class DockerControl:
    """Spawns, lists, and kills worker containers on the local Docker daemon."""

    def __init__(self, client: docker.DockerClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls) -> DockerControl:
        """Build a control wired to the daemon from the environment (the mounted socket)."""
        return cls(docker.from_env())

    def close(self) -> None:
        """Close the underlying Docker client connection."""
        self._client.close()

    def start_worker(self) -> Container:
        """Run a fresh worker container and return it.

        The container runs ``settings.worker_image`` detached, joins ``settings.worker_network`` so
        it can reach the ``redis`` service by hostname, carries the worker label (plus the Compose
        project/service labels so Docker Desktop nests it under the stack), and is handed its
        ``REDIS_URL`` (the only datastore a worker touches). Docker assigns the hostname (the short
        container id), which the worker reports as its id in ``ql:workers``.
        """
        return self._client.containers.run(
            settings.worker_image,
            detach=True,
            network=settings.worker_network,
            labels={
                WORKER_LABEL: WORKER_LABEL_VALUE,
                COMPOSE_PROJECT_LABEL: settings.worker_compose_project,
                COMPOSE_SERVICE_LABEL: "worker",
            },
            environment={"REDIS_URL": settings.redis_url},
        )

    def list_workers(self) -> list[Container]:
        """Return every running worker-labelled container on the daemon (filtered by the label)."""
        return self._client.containers.list(
            filters={"label": f"{WORKER_LABEL}={WORKER_LABEL_VALUE}"}
        )

    def kill_worker(self, worker_id: str) -> None:
        """Stop and remove the worker container named ``worker_id``.

        ``worker_id`` is the worker's id from ``ql:workers`` (its container hostname / short id),
        which ``containers.get`` resolves by id prefix. ``remove(force=True)`` stops and removes in
        one call. A container that is already gone (``NotFound``) is treated as success, so a
        double-kill or a worker that self-exited never raises.
        """
        try:
            container = self._client.containers.get(worker_id)
        except NotFound:
            return
        container.remove(force=True)
