# QueueLab worker image — the container the autoscaler launches at runtime to claim
# and run simulated jobs. Base image only at this stage; worker logic arrives in Epic 8,
# which also vendors `backend/app/queue` into the image (the single source of truth for
# the queue protocol).
FROM python:3.12-slim

# Pinned uv (not :latest) so the uv binary itself can't drift between builds.
COPY --from=ghcr.io/astral-sh/uv:0.9.12 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
