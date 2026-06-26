#!/bin/bash
# CodeDeploy ValidateService hook (Epic 19).
#
# The deploy succeeds only if the live stack actually serves. We curl the health endpoint
# THROUGH the running nginx (not the api directly) so this proves the whole public path —
# nginx up, TLS server listening, reverse-proxy to api:8000, api healthy.
#
# We hit it on the host's published :443 with --resolve so SNI/Host = DOMAIN, and -k because a
# brand-new host may still be on the throwaway self-signed cert when this runs (certbot issues
# asynchronously). The check is about "does the path serve", not "is the cert trusted" — cert
# trust is verified manually in the runbook.
set -euo pipefail

APP_DIR="/opt/queuelab"
cd "${APP_DIR}"
set -a; . ./prod.env; set +a

: "${DOMAIN:?DOMAIN must be set in prod.env}"
HEALTH_URL="https://${DOMAIN}/health"

echo "[validate_service] checking ${HEALTH_URL} through the running stack..."
for i in $(seq 1 20); do
  # --resolve pins DOMAIN to the loopback-published 443 so we exercise nginx on this host.
  if curl -fsS -k --resolve "${DOMAIN}:443:127.0.0.1" "${HEALTH_URL}" >/dev/null 2>&1; then
    echo "[validate_service] health endpoint OK — deploy validated."
    exit 0
  fi
  echo "[validate_service] not healthy yet (attempt ${i}/20); retrying..."
  sleep 5
done

echo "[validate_service] ERROR: health endpoint never responded; failing the deploy." >&2
docker compose -p queuelab -f docker-compose.yml -f docker-compose.prod.yml ps || true
exit 1
