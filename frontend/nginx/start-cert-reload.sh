#!/bin/sh
# /docker-entrypoint.d hook (Epic 19): launch the cert-reload loop in the BACKGROUND, then return
# so the stock nginx entrypoint goes on to exec nginx in the foreground. Without the `&` this
# would block startup forever.
set -eu
/usr/local/bin/queuelab-cert-reload.sh &
echo "[start-cert-reload] cert-reload loop started in background."
