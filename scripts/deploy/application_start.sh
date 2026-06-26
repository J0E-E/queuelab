#!/bin/bash
# CodeDeploy ApplicationStart hook (Epic 19).
#
# The new files are now in place at /opt/queuelab. Bring the production stack up:
#   1. Load prod.env into the shell so compose's top-level ${...} interpolation (ECR_REGISTRY,
#      IMAGE_TAG, DOMAIN, WORKER_*) resolves — compose only auto-reads `.env`, so we also link
#      prod.env -> .env for the interpolation, while each service additionally env_file's prod.env.
#   2. Pull the images this revision pins, then `up -d` the full prod stack (project "queuelab").
#   3. Wait for the api to be reachable, then run Alembic migrations explicitly (idempotent). The
#      api's compose command also runs `alembic upgrade head` before uvicorn; running it here too
#      makes a migration failure surface as a loud deploy failure instead of a crash-looping api.
#   4. Ensure the cert/nginx are healthy: nginx self-bootstraps a placeholder cert and certbot
#      issues the real one; reload nginx so it serves whatever cert is current.
set -euo pipefail

APP_DIR="/opt/queuelab"
cd "${APP_DIR}"

# Compose reads `.env` for top-level interpolation — point it at the host's prod.env.
ln -sf prod.env .env
set -a; . ./prod.env; set +a

COMPOSE="docker compose -p queuelab -f docker-compose.yml -f docker-compose.prod.yml"

echo "[application_start] pulling images (IMAGE_TAG=${IMAGE_TAG})..."
${COMPOSE} pull

# The worker is NOT a compose service — the autoscaler spawns it at runtime via the Docker socket
# (docker_control.start_worker), so `compose pull` above never fetches it. Pull it here, where the
# host root is logged in to ECR (before_install), so the image is present on the daemon before the
# autoscaler needs it. The autoscaler container itself has no ECR credentials and can't auto-pull.
echo "[application_start] pulling the worker image (not a compose service): ${WORKER_IMAGE}..."
docker pull "${WORKER_IMAGE}"

echo "[application_start] starting the stack..."
${COMPOSE} up -d

# Wait for the api container to accept connections before migrating.
echo "[application_start] waiting for api to come up..."
for i in $(seq 1 30); do
  if ${COMPOSE} exec -T api sh -c 'true' 2>/dev/null && \
     ${COMPOSE} exec -T api .venv/bin/python -c "import socket; socket.create_connection(('127.0.0.1',8000),2)" 2>/dev/null; then
    echo "[application_start] api is up."
    break
  fi
  sleep 3
done

# Explicit migration run. The api's compose command runs this same `alembic upgrade head` before
# uvicorn; running it here as well makes a failed migration fail the deploy loudly instead of
# silently looping a crashing container.
echo "[application_start] running database migrations..."
${COMPOSE} exec -T api .venv/bin/alembic upgrade head

# Make sure nginx is serving the current cert (placeholder on a brand-new host, real once
# certbot has issued). A graceful reload is a no-op if nothing changed.
echo "[application_start] reloading nginx to pick up the current cert..."
${COMPOSE} exec -T nginx nginx -s reload || echo "[application_start] nginx reload skipped (not ready yet); its own loop will reload."

echo "[application_start] stack is up."
