#!/bin/sh
# QueueLab nginx cert-reload loop (Epic 19).
#
# certbot (a sibling container) renews the TLS cert into the shared /etc/letsencrypt volume but
# has no way to signal THIS nginx — they share no process namespace and certbot has no docker
# socket. So nginx reloads itself on a timer to pick up a renewed cert with zero dropped
# connections (`nginx -s reload` does a graceful config/cert reload of the running master).
#
# Started in the BACKGROUND by the /docker-entrypoint.d hook before the stock entrypoint execs
# nginx in the foreground, so this loop runs alongside the server for the life of the container.
set -eu

while true; do
  # 6h cadence: certs renew at most ~monthly, so this picks up a fresh cert within a few hours
  # of certbot writing it, well before the old one expires.
  sleep 6h
  if nginx -t >/dev/null 2>&1; then
    nginx -s reload && echo "[cert-reload] reloaded nginx to pick up any renewed cert."
  else
    echo "[cert-reload] nginx -t failed; skipping reload this cycle."
  fi
done
