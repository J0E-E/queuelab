# Launch the whole QueueLab stack locally for testing, served at http://localhost:9002.
#
# Builds the worker image (the autoscaler spawns these at runtime), then brings up postgres, redis,
# the api (uvicorn + Alembic migrate), the autoscaler, and the Vite frontend via Compose. Only the
# frontend's :9002 is published; everything else stays on the internal network.
#
# Stop with Ctrl+C; tear down fully with:
#   docker compose -f docker-compose.yml -f docker-compose.dev.yml down

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host '==> Building the worker image (queuelab-worker:latest)...' -ForegroundColor Cyan
docker build -f worker/Dockerfile -t queuelab-worker:latest .

Write-Host '==> Bringing up the stack — open http://localhost:9002 once the frontend is ready...' -ForegroundColor Cyan
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
