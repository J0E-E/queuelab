#!/bin/sh
# QueueLab certbot sidecar (Epic 19) — issue once via HTTP-01 webroot, then renew ~twice daily.
#
# Runs as the `certbot` service in docker-compose.prod.yml, sharing two volumes with nginx:
#   /etc/letsencrypt  (certs)   — certbot writes the issued cert here; nginx reads it.
#   /var/www/certbot  (webroot) — certbot drops the ACME HTTP-01 challenge token here; nginx
#                                 serves it at /.well-known/acme-challenge/ over plain HTTP.
#
# Bootstrap chicken-and-egg: nginx must already be up (serving the challenge) before certbot can
# validate. nginx starts on a throwaway self-signed cert (frontend image's bootstrap shim), so it
# is always reachable first; certbot then replaces that placeholder with the real cert.
#
# nginx picks up the new/renewed cert via its own periodic `nginx -s reload` loop (the frontend
# image runs one) — certbot has no docker socket, so it cannot signal nginx directly.
set -eu

: "${DOMAIN:?DOMAIN env var is required}"
: "${CERTBOT_EMAIL:?CERTBOT_EMAIL env var is required}"

WEBROOT="/var/www/certbot"

# Staging flag: CERTBOT_STAGING=1 issues against the untrusted staging CA (no rate limits) for a
# dry run. See ops/deploy/DEPLOY.md. Real issuance leaves it unset/0.
STAGING_ARG=""
if [ "${CERTBOT_STAGING:-0}" = "1" ]; then
  STAGING_ARG="--staging"
  echo "[certbot] CERTBOT_STAGING=1 — issuing against the Let's Encrypt STAGING CA (untrusted certs)."
fi

# `certbot certonly` writes a REAL cert directory to the same /etc/letsencrypt/live/$DOMAIN path
# the throwaway placeholder used, replacing it. We detect "already real" by the renewal config
# certbot maintains (presence of /etc/letsencrypt/renewal/$DOMAIN.conf), not the cert file (which
# the placeholder also creates).
issue_if_needed() {
  if [ -f "/etc/letsencrypt/renewal/${DOMAIN}.conf" ]; then
    echo "[certbot] a managed cert for ${DOMAIN} already exists; skipping initial issue."
    return 0
  fi

  echo "[certbot] requesting initial cert for ${DOMAIN} via HTTP-01 webroot..."
  # --webroot serves the challenge from the shared webroot that nginx exposes.
  # --keep-until-expiring + --non-interactive keep this idempotent and unattended.
  certbot certonly \
    --webroot --webroot-path "${WEBROOT}" \
    --email "${CERTBOT_EMAIL}" \
    --agree-tos --no-eff-email \
    --non-interactive --keep-until-expiring \
    ${STAGING_ARG} \
    -d "${DOMAIN}"
  echo "[certbot] initial issue complete; nginx will pick it up on its next reload."
}

issue_if_needed || echo "[certbot] initial issue failed; the renewal loop will retry."

# Renewal loop: certbot renews only when within ~30 days of expiry, so running it twice a day is
# the recommended cadence. Sleep first is fine — the cert is good for 90 days.
while true; do
  sleep 12h
  echo "[certbot] running scheduled renewal check..."
  certbot renew --webroot --webroot-path "${WEBROOT}" --non-interactive ${STAGING_ARG} || \
    echo "[certbot] renew check reported an error; will retry next cycle."
done
