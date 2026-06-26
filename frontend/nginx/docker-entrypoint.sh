#!/bin/sh
# Bootstrap shim for the QueueLab nginx image (Epic 19).
#
# The stock nginx image runs every executable in /docker-entrypoint.d/ before launching nginx.
# This script solves the TLS chicken-and-egg: the :443 server block references
# /etc/letsencrypt/live/$DOMAIN/{fullchain,privkey}.pem, but on a brand-new host certbot has
# not issued anything yet, so nginx would fail to start and certbot's HTTP-01 challenge (served
# by THIS nginx) could never be answered.
#
# Fix: if no cert exists for $DOMAIN, mint a throwaway self-signed pair at that exact path so
# nginx starts. The certbot sidecar then issues the real Let's Encrypt cert via HTTP-01 and
# reloads nginx, replacing this placeholder. This runs ahead of nginx's own template step
# (20-envsubst...) by filename order? No — it must run AFTER, so it is numbered 40 (envsubst is
# 20-envsubst-on-templates.sh), guaranteeing ${DOMAIN} is already known here via the env var.
set -eu

: "${DOMAIN:?DOMAIN env var is required (the public hostname, e.g. queuelab.joeyshub.com)}"

LIVE_DIR="/etc/letsencrypt/live/${DOMAIN}"
FULLCHAIN="${LIVE_DIR}/fullchain.pem"
PRIVKEY="${LIVE_DIR}/privkey.pem"

# Make sure the ACME webroot exists so the challenge location never 404s on a fresh volume.
mkdir -p /var/www/certbot

if [ -s "${FULLCHAIN}" ] && [ -s "${PRIVKEY}" ]; then
  echo "[queuelab-bootstrap] cert already present for ${DOMAIN}; leaving it untouched."
  exit 0
fi

echo "[queuelab-bootstrap] no cert for ${DOMAIN} yet; minting a throwaway self-signed pair so nginx can start."
mkdir -p "${LIVE_DIR}"
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout "${PRIVKEY}" \
  -out "${FULLCHAIN}" \
  -subj "/CN=${DOMAIN}"

echo "[queuelab-bootstrap] placeholder cert written; certbot will replace it on first issue."
