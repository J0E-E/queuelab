# QueueLab backend image — serves both the FastAPI api and the autoscaler entrypoints.
# Base image only at this stage; application logic and CMD arrive in later epics.
FROM python:3.12-slim

# uv for fast, reproducible dependency installs. Pinned (not :latest) so the uv binary
# itself can't drift between builds.
COPY --from=ghcr.io/astral-sh/uv:0.9.12 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install dependencies from the lockfile first for better layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application source (currently an empty package skeleton).
COPY app ./app
