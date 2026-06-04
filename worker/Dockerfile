# QueueLab worker image — the container the autoscaler launches at runtime (Epic 11) to
# claim and run simulated jobs. Built from the repo root so it can vendor the backend queue
# protocol and settings, the single source of truth: `app.queue.client` imports
# `from app.config import settings`, so both `app/queue` and `app/config.py` must land in the
# image as the importable `app` package.
#
#   docker build -f worker/Dockerfile -t queuelab-worker:latest .
#
FROM python:3.12-slim

# Pinned uv (not :latest) so the uv binary itself can't drift between builds.
COPY --from=ghcr.io/astral-sh/uv:0.9.12 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    # Put the uv-managed virtualenv on PATH so `python` in the CMD is the venv interpreter
    # (which has redis/pydantic installed), not the bare system Python.
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

# Install dependencies from the lockfile first for better layer caching.
COPY worker/pyproject.toml worker/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Vendor the backend queue protocol + settings as the `app` package (single source of truth).
COPY backend/app/__init__.py ./app/__init__.py
COPY backend/app/config.py ./app/config.py
COPY backend/app/queue ./app/queue

# Worker source (flat layout — claim loop + simulated work profiles).
COPY worker/worker.py worker/simulate.py ./

CMD ["python", "worker.py"]
