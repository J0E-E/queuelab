#!/bin/bash
# CodeDeploy BeforeInstall hook (Epic 19).
#
# Runs after ApplicationStop, before the Install step copies the new files. Two jobs:
#   1. Log in to ECR so the upcoming `docker compose pull` can fetch the new images.
#   2. Stamp this revision's IMAGE_TAG (+ ECR_REGISTRY) into the host's prod.env so the compose
#      override runs exactly the images CodeBuild just pushed for this commit.
#
# The host's prod.env (the real secret, written once by the operator) lives at /opt/queuelab and
# is preserved across deploys by the files: copy. We only rewrite the IMAGE_TAG/ECR_REGISTRY
# lines from image_tag.env (emitted by buildspec.yml into the bundle), leaving every other line.
set -euo pipefail

APP_DIR="/opt/queuelab"
# This hook script lives in the freshly-downloaded bundle; image_tag.env sits at the bundle root.
BUNDLE_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# --- Region + account (from the instance, no hardcoding) -------------------------------
TOKEN="$(curl -sf -X PUT 'http://169.254.169.254/latest/api/token' -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' || true)"
REGION="$(curl -sf -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/meta-data/placement/region)"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "[before_install] logging in to ECR ${ECR_REGISTRY} ..."
aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

# --- Stamp IMAGE_TAG / ECR_REGISTRY into the host prod.env ------------------------------
PROD_ENV="${APP_DIR}/prod.env"
if [ ! -f "${PROD_ENV}" ]; then
  echo "[before_install] ERROR: ${PROD_ENV} not found. The operator must create it once from ops/deploy/prod.env.example." >&2
  exit 1
fi

# Pull the tag CodeBuild resolved for this revision.
IMAGE_TAG="$(grep -E '^IMAGE_TAG=' "${BUNDLE_ROOT}/image_tag.env" | cut -d= -f2-)"
: "${IMAGE_TAG:?image_tag.env did not provide IMAGE_TAG}"

# Replace-or-append IMAGE_TAG and ECR_REGISTRY in prod.env (leave all other lines untouched).
upsert() {
  key="$1"; value="$2"
  if grep -qE "^${key}=" "${PROD_ENV}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${PROD_ENV}"
  else
    echo "${key}=${value}" >> "${PROD_ENV}"
  fi
}
upsert "IMAGE_TAG" "${IMAGE_TAG}"
upsert "ECR_REGISTRY" "${ECR_REGISTRY}"
# Pin the worker image to THIS revision's SHA too, so the autoscaler spawns workers built from the
# same commit as the api/autoscaler — not a drifting `latest`. Without this, a redeploy (or rollback)
# runs new api code against the previous worker until `latest` is overwritten. application_start.sh
# pulls this exact image before the stack comes up.
upsert "WORKER_IMAGE" "${ECR_REGISTRY}/${PROJECT:-queuelab}-worker:${IMAGE_TAG}"
echo "[before_install] stamped IMAGE_TAG=${IMAGE_TAG} ECR_REGISTRY=${ECR_REGISTRY} WORKER_IMAGE into prod.env."
