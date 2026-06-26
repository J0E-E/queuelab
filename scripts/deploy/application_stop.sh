#!/bin/bash
# CodeDeploy ApplicationStop hook (Epic 19).
#
# Bring the currently-running stack down BEFORE the new revision's files overwrite /opt/queuelab.
# CRITICAL: never pass `-v` — that would delete the postgres/redis data volumes. Data lives on
# the bind-mounted EBS volume (DATA_ROOT) and in named volumes; both must survive the redeploy.
#
# Runs from the PREVIOUS deployment's copy at /opt/queuelab, so it uses the previous compose
# files. On the very first deploy there is nothing to stop — that is fine, we no-op cleanly.
set -euo pipefail

APP_DIR="/opt/queuelab"

if [ ! -f "${APP_DIR}/docker-compose.prod.yml" ]; then
  echo "[application_stop] no previous stack at ${APP_DIR}; nothing to stop (first deploy)."
  exit 0
fi

cd "${APP_DIR}"
echo "[application_stop] stopping the running stack (KEEPING data volumes)..."
# -p queuelab pins the project name so the network/volume names stay stable across deploys.
docker compose -p queuelab -f docker-compose.yml -f docker-compose.prod.yml down --remove-orphans
echo "[application_stop] stack stopped."
