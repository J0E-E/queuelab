# QueueLab — Epic Plan

Source TDD: [.development-docs/tdd-queuelab.md](.development-docs/tdd-queuelab.md)

This plan decomposes the QueueLab TDD into small, independently reviewable epics.
Each epic leaves `development` working when merged. Scaffolding comes first, the
custom Redis queue and backend mechanics next, then the autoscaler/chaos/real-time
layers, then the frontend, and finally infrastructure and CI/CD. Dependencies are
explicit and acyclic.

---

## Epic 1 — Monorepo & tooling scaffold — **COMPLETED**
- **Intent:** Establish the empty monorepo skeleton and shared conventions so every
  later epic has a home and consistent tooling.
- **Scope:** `/backend`, `/frontend`, `/worker`, `/infra` directories; root
  `docker-compose.yml` (api, autoscaler, postgres, redis, nginx — services declared
  but minimal); base Dockerfiles for backend and worker; Python tooling
  (`pyproject.toml`/`requirements`, ruff/black config), Node tooling skeleton
  (`package.json`, prettier/eslint); `.env.example` and env/config conventions;
  README stub. No application logic.
- **Verification:** `docker compose config` parses; linters run clean on the empty
  trees; directory layout matches TDD §5.2.
- **Depends on:** none.

### Implementation notes
- **Python tooling:** `uv` + `pyproject.toml` (+ `uv.lock`) for backend and worker,
  not `requirements.txt`. Reproducible installs via `uv sync --frozen` in both
  Dockerfiles. Python 3.12 (`python:3.12-slim` base images).
- **Lint/format:** **Ruff only** — `ruff format` replaces Black, so Black was dropped
  (deliberate deviation from the "ruff/black" wording above). Worker mirrors the
  backend Ruff config so both trees lint identically.
- **Node tooling:** `npm`; frontend is a tooling skeleton only (`package.json` +
  flat-config ESLint + Prettier). The full Vite/React/Tailwind app is deferred to
  Epic 13 — no Vite/React deps added yet.
- **Skeleton:** backend dirs are real Python packages (`__init__.py` with one-line
  docstrings); non-package placeholders (`queue/scripts/`, `worker/`, `frontend/src/`,
  `infra/`) use `.gitkeep` noting which epic fills them.
- **Compose:** `env_file` entries are marked `required: false` so a fresh checkout
  parses without a `.env`; interpolation uses `${VAR:-default}` fallbacks. Worker
  containers are intentionally absent (autoscaler spawns them at runtime, §5.1).
- **Verified:** `docker compose config` parses; Ruff lint + format clean on backend
  and worker; ESLint + Prettier clean on frontend; all three images
  (`queuelab-api`, `queuelab-autoscaler`, `queuelab-worker`) build successfully.

## Epic 2 — Backend config & settings — **COMPLETED**
- **Intent:** Centralized env-driven settings (guardrails, TTLs, thresholds, caps,
  rate limits) that all backend services read.
- **Scope:** `backend/app/config.py` (Pydantic Settings: caps 100/1000/10, rate
  limits 1/5s & 1/10s, visibility timeout, retry defaults, Redis/Postgres URLs,
  autoscaler thresholds/idle timeout). Unit tests for defaults and env overrides.
- **Verification:** Pytest covers default values and env-var overrides; importing
  settings with a sample `.env` yields expected config.
- **Depends on:** Epic 1.

### Implementation notes
- **Single `Settings` model:** one `pydantic_settings.BaseSettings` class in
  `backend/app/config.py` holds every value, grouped by concern (datastores, caps, rate
  limits, queue/lease, autoscaler, retention, worker image). `SettingsConfigDict` loads a
  `.env` file with `extra="ignore"` so unknown keys don't crash.
- **Added settings the TDD required but `.env.example` lacked:** `REDIS_JOB_TTL_SECONDS=3600`
  (§5.7 1h hot-record TTL), `JOB_RETENTION_HOURS=24` + `SCALING_EVENT_RETENTION_HOURS=24`
  (§5.9 Postgres prune), and `AUTOSCALER_LOOP_SECONDS=2` (§5.5 ~1–2s control loop).
  `.env.example` was updated to stay one-to-one with the model defaults.
- **Validation:** two integer field aliases — `PositiveInt` (`Annotated[int, Field(gt=0)]`)
  rejects zero/negative at load, and `NonNegativeInt` (`Field(ge=0)`) allows zero for fields
  that legitimately reach it (`min_workers`, `scale_down_threshold` — scale all the way down
  to an empty queue). Two `model_validator(mode="after")` checks: `min_workers <= max_workers`,
  and `scale_down_threshold <= scale_up_threshold` (so the control loop can't oscillate).
- **Access:** `get_settings()` is `lru_cache`-wrapped for a process-wide cached instance;
  a module-level `settings = get_settings()` gives simple `from app.config import settings`
  imports. Tests build fresh `Settings(...)` instances to exercise overrides/validation.
- **Verified:** Ruff lint + format clean; `pytest tests/test_config.py` green (11 tests:
  defaults, env overrides, `.env` file load, both bounds validators, non-positive rejection,
  zero-allowed for non-negative fields, cache identity). Local dev/test ran against the
  existing `backend/.venv` (`uv` not on PATH on this machine; Dockerfile still uses `uv sync`).

## Epic 3 — Custom Redis queue protocol & client — **COMPLETED**
- **Intent:** The core mechanic — the custom Redis-primitive queue with real
  claiming, leases, retries, and recovery, as a standalone tested module.
- **Scope:** `backend/app/queue/protocol.py` (key names, payload schema, state
  machine), `backend/app/queue/scripts/` (atomic Lua: claim, ack, nack, reap),
  `backend/app/queue/client.py` (enqueue/claim/ack/nack/requeue wrappers, leases,
  delayed set, counts). Integration tests against a **real Redis** covering
  claim/ack/nack, retry/backoff, lease-expiry requeue.
- **Verification:** Pytest integration suite (real Redis) green: enqueue→claim→ack,
  nack→retrying→requeue, lease expiry requeues a dead worker's job, counts stay
  consistent.
- **Depends on:** Epic 2.

### Implementation notes
- **Async client.** `JobQueue` (`backend/app/queue/client.py`) is built on
  `redis.asyncio` so the api, reaper loop, and WS layer never block the event loop. It
  takes an injected `Redis` (for tests) plus a `from_settings()` constructor, and reads
  every timeout/TTL/cap from the shared `app.config.settings`.
- **Redis `TIME` is the only clock.** All deadline math (lease deadline, retry ready-at,
  delayed scores) is computed inside the Lua scripts from `redis.call('TIME')`; Python
  passes only durations. One authoritative clock across worker containers with skewed
  wall clocks, and the timestamp is atomic with the write. Implies primary-only / no
  Redis Cluster.
- **Reap uses `worker_id` on the job hash.** `claim.lua` writes `worker_id` into
  `ql:job:{id}`; `ql:leases` stays a pure `{job_id → deadline}` sorted set. `reap.lua`
  reads `worker_id` off the hash to clean the right `ql:processing:{worker_id}` list — no
  second lease→worker map. (Reap builds `ql:job:` / `ql:processing:` keys inline, a
  documented single-node assumption.)
- **One reap script, two passes.** `reap.lua` promotes due `delayed→ready` and recovers
  expired-lease jobs in a single atomic sweep, so a job can't be both promoted and
  re-leased. The failure branch is duplicated from `nack.lua` (Lua has no imports) — both
  copies are marked `RETRY-DECISION (keep in sync)`. Recovery reads each job's own
  `retry_delay_ms` so jobs keep their backoff.
- **Counts semantics.** `ql:counts` holds `queued/running/retrying` as live gauges and
  `completed/failed` as cumulative lifetime totals (never decremented, even when the job
  hash TTLs out) — keeps dashboard reads O(1). A mixed-path test asserts gauges equal the
  actual structure contents.
- **`protocol.py` is queue-only.** A lean `JobRecord` Pydantic model (`StrEnum` state,
  `to_hash`/`from_hash` that omit `None` rather than writing `"None"`, bytes/str-tolerant
  decode) with no Postgres ORM/DTO coupling — that mapping lands in Epic 4.
- **Capacity cap** (`max_total_queued`) is a soft Python-side check in `enqueue`
  (ready + delayed), raising `QueueFullError`; concurrent enqueues can slightly
  overshoot. A hard cap would need its own Lua script (noted as future tightening).
- **Documented tradeoffs (in code comments):** at-least-once delivery (a slow-but-alive
  worker's lease can expire → job runs twice; consumers must be idempotent); orphan-in-
  processing gap (crash between `BLMOVE` and `claim.lua` strands a job with no lease —
  flagged for a future scan pass).
- **Tests.** `backend/tests/` gained `conftest.py` (testcontainers auto-spins
  `redis:7-alpine`, keyspace flushed per test, a `make_job` factory) and `test_queue.py`
  (10 integration cases). Time is controlled by rewriting lease/delayed scores into the
  past then reaping — no 30s sleeps. Added dev deps `pytest-asyncio` + `testcontainers`
  and `asyncio_mode = "auto"`; `uv.lock` regenerated to stay frozen-installable.
- **Verified:** Ruff lint + format clean; `pytest` green (21 tests: 11 Epic 2 config +
  10 queue) against the auto-spun real Redis; `uv lock --check` passes. Requires a Docker
  daemon for the integration suite.

## Epic 4 — Postgres models & migrations — **COMPLETED**
- **Intent:** Durable, verifiable outcome record (jobs, scaling events) with bounded
  retention.
- **Scope:** `backend/app/models/` (SQLAlchemy ORM `job`, `scaling_event` per §5.7;
  Pydantic DTOs), `backend/app/db/` (engine, session), Alembic setup + first
  migration, indexes on `(submitted_at)`/`(state)`/`(at)`, prune helper
  (jobs >24h, scaling_events >24h). Integration tests against a **real Postgres**.
- **Verification:** `alembic upgrade head` creates tables; Pytest inserts/queries job
  and scaling_event rows; prune deletes only aged rows.
- **Depends on:** Epic 2.

### Implementation notes
- **Async SQLAlchemy.** `backend/app/db/engine.py` exposes a `Database` class built on
  `create_async_engine` over the `postgresql+psycopg` driver (psycopg3 serves async). It
  mirrors `JobQueue`'s conventions — injectable engine, `from_settings()` constructor
  (`pool_pre_ping=True`), an `async with db.session()` context manager, and `aclose()`.
  The declarative `Base` lives in `db/base.py` so models and Alembic share one metadata
  object without import cycles.
- **`job` schema follows §5.7 plus `last_error`.** Columns match §5.7 verbatim (UUID PK,
  `guest_handle`, broken-out `type`/`complexity`, `timestamptz` times, `duration_ms`);
  the one addition is a nullable `last_error` (carried over from the Redis `JobRecord`) so
  a failure reason is durably stored. `state` is plain text kept byte-for-byte aligned
  with the Redis hash values (`app.queue.protocol.JobState`). Indexes via `index=True`:
  `ix_job_submitted_at`, `ix_job_state`, `ix_scaling_event_at` (names matched in the
  migration).
- **Redis↔Postgres divergence is deliberate.** The Redis record stores `type`/`complexity`
  inside an opaque payload and uses `enqueued_at`/`completed_at`; Postgres breaks those
  into columns and adds `guest_handle` + `duration_ms`. The durable-writer (Epic 10) owns
  the runtime mapping; this epic only defines the target shape.
- **DTOs are read-side only.** `models/schemas.py` defines `JobResponse`/`ScalingEventResponse`
  with `from_attributes=True`, so a route can build one straight from an ORM row without
  hand-copying fields. `JobResponse` currently carries the internal `session_id`/`worker_id`;
  whether to expose those to clients (or drop them) is flagged in the DTO for Epic 7's
  `GET /api/jobs`.
- **Alembic reads the URL from settings, not `alembic.ini`.** `alembic/env.py` is async:
  it builds an async engine from `app.config.settings.database_url` and runs migrations
  through `connection.run_sync(...)`. The first migration (`alembic/versions/0001_initial_schema.py`)
  is hand-written (not autogenerated) so types/nullability match §5.7 exactly.
- **Prune helper, no scheduler.** `backend/app/db/prune.py` has `prune_jobs`,
  `prune_scaling_events`, and a combined `prune_aged_rows`; each reads its window from
  settings, returns the deleted-row count, and a null `finished_at` (still-running job)
  never matches the cutoff so in-flight work is safe. `prune_aged_rows` saves both deletes
  in one transaction (atomic). The prune filters on the unindexed `finished_at` (§5.7
  indexes only `submitted_at`/`state`) — a deliberate cheap full scan while the table
  stays small under 24h retention; index `finished_at` only if volume ever grows. Wiring a
  periodic caller is left to a later epic.
- **Tests.** `conftest.py` gained a session-scoped `PostgresContainer` (`driver="psycopg"`,
  since psycopg2 isn't installed) and a `db_session` fixture that drops+recreates the
  schema per test. `test_models.py` (7 cases): ORM round-trips for both tables, prune
  deletes only aged rows, and an `alembic upgrade head`/`downgrade base` smoke test that
  asserts tables + indexes exist.
- **Windows-dev deviation.** psycopg3 async cannot use the `ProactorEventLoop`, so
  `conftest.py` switches to the `WindowsSelectorEventLoopPolicy` on Windows only (no-op on
  Linux/CI, where the containers actually run). The same switch will be needed if anyone
  runs the api under uvicorn on Windows (Epic 5 concern).
- **Verified:** Ruff lint + format clean; `pytest` green (28 tests: 11 config + 10 queue +
  7 Postgres) against an auto-spun real Postgres 16 + Redis 7. No new dependencies —
  sqlalchemy/alembic/psycopg (and the test deps) were already in `pyproject.toml`, so
  `uv.lock` is unchanged. Requires a Docker daemon for the integration suite.

## Epic 5 — FastAPI app skeleton, identity & session — **COMPLETED**
- **Intent:** A runnable FastAPI app with lifespan wiring and ephemeral guest
  identity, ready to hang routers off.
- **Scope:** `backend/app/main.py` (app, lifespan opening Redis/Postgres, health
  route), `backend/app/services/identity.py` (guest handle + color assignment),
  `POST /api/session`. Unit tests for identity; smoke test that the app boots and
  `/api/session` returns a handle/color.
- **Verification:** `uvicorn` boots; `GET /health` 200; `POST /api/session` returns
  `{session_id, guest_handle, color}`; Pytest for identity assignment.
- **Depends on:** Epic 3, Epic 4.

### Implementation notes
- **Handle = color (style guide §3.4).** `services/identity.py` is a pure, no-I/O module:
  one constant `GUEST_COLORS` maps the six fixed names → hex (`teal #2dd4bf`, `pink
  #ff5fd2`, `lime #aaff00`, `sky #5ab0ff`, `orange #ff8c42`, `lavender #c77dff`).
  `create_guest_identity()` picks a name at random, builds the handle as `guest-<name>`,
  sets `color` to that name's hex, and stamps `session_id = uuid4().hex`. Returns a
  `GuestIdentity` Pydantic model (doubles as the `POST /api/session` response shape).
- **Random, stateless color assignment (decision).** No Redis/round-robin. With only six
  colors two visitors can share one — acceptable, since the identity is for feed
  attribution only, not authentication. Keeps identity trivially unit-testable.
- **Lazy lifespan clients.** `main.py` lifespan opens `JobQueue.from_settings()` and
  `Database.from_settings()` onto `app.state` and `aclose()`s both on shutdown. Both
  constructors are lazy (no socket until the first command), so the app — and the boot
  smoke test — start without live Redis/Postgres. `get_queue`/`get_database` dependency
  providers read off `app.state` for later epics' routes.
- **Shallow `/health` (decision).** Returns `200 {"status": "ok"}` without touching the
  datastores, matching the epic's verification and letting the smoke test run container-
  free. A deeper datastore ping (Redis `PING` / Postgres `SELECT 1`) is left for later.
- **Router split.** `POST /api/session` lives in `app/routers/session.py` (an
  `APIRouter` with `prefix="/api"`) included from `main.py`; `/health` stays in `main.py`.
  Establishes the pattern later epics' routers follow.
- **Tests.** `test_identity.py` (5 unit cases: handle/color rules, session-id uniqueness,
  every color reachable) and `test_app.py` (2 smoke cases via FastAPI `TestClient`, which
  runs lifespan: boot + `/health`, and `/api/session` shape). Neither needs containers.
- **Dependency.** Added dev dep `httpx>=0.28` (FastAPI `TestClient` drives the app through
  it); `uv.lock` regenerated (48 packages, `uv lock --check` clean). Starlette emits a
  deprecation warning preferring `httpx2` — noted, not actioned.
- **Verified:** Ruff lint + format clean; `pytest` green (35 tests: 28 prior + 7 new);
  `uvicorn app.main:app` boots, `GET /health` → 200, `POST /api/session` →
  `{session_id, guest_handle: "guest-pink", color: "#ff5fd2"}` (handle/color matched).

## Epic 6 — Guardrails: rate limiting & validation — **COMPLETED**
- **Intent:** Per-session token-bucket rate limiting and reusable validation/cap
  enforcement, surfaced in the system voice.
- **Scope:** `backend/app/services/rate_limit.py` (Redis token bucket: 1 submit/5s,
  1 chaos/10s), shared validation helpers (caps, capacity), error shaping
  (`[ERR]`/`[WARN]` messages, `429` + `Retry-After`, `409` at capacity). Unit +
  integration tests (real Redis) for bucket refill and limit responses.
- **Verification:** Pytest: bucket allows/denies on schedule; over-cap and
  at-capacity produce 422/429/409 with correct messages.
- **Depends on:** Epic 5.

### Implementation notes
- **Token bucket in Lua, capacity 1.** `backend/app/services/scripts/token_bucket.lua`
  is the bucket math — atomic, with `redis.call('TIME')` as the one clock (mirrors the
  queue's `claim.lua`/`reap.lua`). Capacity is fixed at **1** (no burst): one action,
  then a full interval's wait — exactly "1 submission / 5s". The script reads/refills
  (`elapsed_ms / refill_ms` tokens, capped) and spends in one step, and `PEXPIRE`s the
  bucket once it would be full again so idle sessions self-clean. Returns
  `{allowed, retry_after_ms}`.
- **`RateLimiter` mirrors `JobQueue`.** `backend/app/services/rate_limit.py` is an
  injected-Redis client with `from_settings()`/`aclose()` and a `register_script`
  callable. `check_submission`/`check_chaos` read `submit_rate_seconds`/`chaos_rate_seconds`
  and key the bucket `ql:ratelimit:{action}:{session_id}` so submit and chaos budgets are
  independent. A denial raises `RateLimitedError`; `retry_after_seconds = max(1,
  ceil(retry_after_ms / 1000))`.
- **Error shaping lives in one module.** `backend/app/services/guardrails.py` holds the
  guardrail exceptions and `register_guardrail_handlers(app)` so `rate_limit.py` and
  `validation.py` import the error types without importing each other (no cycle). Mapping:
  `InvalidSubmissionError → 422`, `RateLimitedError → 429` (+ `Retry-After` header),
  `QueueFullError → 409`. We **reuse the existing `QueueFullError`** (from
  `app.queue.protocol`) for 409 rather than inventing a second capacity exception.
- **429 message vs header (decision).** The body `detail` states the rule
  (`[WARN] rate limit: 1 submission / 5s`), while the precise remaining wait goes in the
  `Retry-After` header — a stable, descriptive message plus an exact machine-readable wait.
- **Validation helpers.** `backend/app/services/validation.py`:
  `validate_submission_count` (pure) rejects `< 1` or `> max_jobs_per_submission` with
  `[ERR] --count exceeds cap (max N)` / `[ERR] --count must be at least 1`;
  `ensure_within_capacity(queue)` (async) pre-checks `total_queued()` and raises
  `QueueFullError` at the cap. `JobQueue.enqueue`'s own soft check stays as a backstop.
- **Pre-wired for Epic 7 (decision).** `main.py` lifespan now builds
  `app.state.rate_limiter = RateLimiter.from_settings()` (closed on shutdown), adds a
  `get_rate_limiter` dependency provider, and calls `register_guardrail_handlers(app)`.
  Harmless until a route raises a guardrail error — `POST /api/jobs` (Epic 7) is the first.
- **Tests.** `test_rate_limit.py` (7, real Redis) — allow→deny→refill on schedule via
  rewinding the bucket's `updated_at_ms` into the past (the queue tests' time-travel
  trick, no real sleeps), partial-wait `Retry-After` rounding, independent
  sessions/actions, and a `from_settings` smoke. `test_validation.py` (5) — cap bounds
  (unit) + at-capacity (real queue with the ready list stuffed). `test_guardrails.py` (3)
  — a throwaway FastAPI app proves 422/429/409 shaping, the `Retry-After` header, and
  the system-voice `detail`. A `rate_limiter` fixture was added to `conftest.py`.
- **Verified:** Ruff lint + format clean; `pytest` green (50 tests: 35 prior + 15 new)
  against an auto-spun real Redis; the app still boots (the `test_app.py` lifespan smoke
  runs `RateLimiter.from_settings()`). No new dependencies. Requires a Docker daemon for
  the integration suite.

## Epic 7 — Job submission & job-records endpoints — **COMPLETED**
- **Intent:** Submit a validated batch into the queue and read back durable job
  records — the producer side of the core flow.
- **Scope:** `backend/app/services/submission.py` (validate caps/rate/capacity, write
  job rows to Postgres, enqueue to `ql:queue:ready`), `POST /api/jobs`,
  `GET /api/jobs?session=&state=` (paged). Integration tests (real Redis + Postgres).
- **Verification:** `POST /api/jobs` returns `201 {batch_id, accepted}`, rows appear
  in Postgres, IDs land on `ql:queue:ready`; over-limit paths return 422/429/409;
  `GET /api/jobs` pages records.
- **Depends on:** Epic 6.

### Implementation notes
- **Identity travels in the request body (decision; `guest_handle` later removed).** The TDD
  body (`{count, type, complexity, max_retries, retry_delay_ms}`) omits identity, but the durable
  `job` row needs both `session_id` and `guest_handle` (NOT NULL). The body originally carried
  both; review round 2 made the handle **server-derived** instead (see *Review fixes (4b — round
  2)* below), so `JobSubmission` now carries only `session_id`. `max_retries`/`retry_delay_ms`
  are optional and fall back to `default_max_retries` (3) / `default_retry_delay_ms` (2000).
- **`JobType` enum is the canonical vocabulary.** `email|report|image|webhook` lives as a
  `StrEnum` in `app/queue/protocol.py` beside `JobState`, so the worker (Epic 8, which vendors
  `app/queue`) reads the same list for its per-type simulate profiles. `validate_job_type`,
  `validate_complexity` (1..5), and `validate_retry_settings` (`max_retries` 0..10,
  `retry_delay_ms` 0..60000) were added to `services/validation.py` with system-voice
  `[ERR] ...` messages; the `JobSubmission` fields stay loosely typed so these checks shape the
  422 rather than Pydantic's default error body.
- **Capacity is batch-aware.** `ensure_within_capacity(queue, count=1)` gained a `count`
  argument and now rejects when `total_queued() + count > max_total_queued`, so an over-large
  batch is turned away up front instead of partially enqueued. The default keeps the Epic 6
  callers and tests unchanged.
- **Submission service order: validate → session → capacity → rate → write → enqueue.**
  `submit_batch` runs the pure field checks first (422), then derives the trusted handle from the
  session (422 if unknown), then batch capacity (409), then the rate limit (429), then commits one
  `Job` row per job in a single transaction, then enqueues each to Redis (durable-first, per §5.12).
  One `uuid4()` per job is the shared id for both the Postgres PK and the Redis `JobRecord.id`, so
  Epic 10's durable-writer can match a state event to its row. (Order revised twice in review — see
  both *Review fixes* blocks below.)
- **Documented trade-offs (in code).** `batch_id` is a transient correlation id returned to the
  client — there is no batch column, so it is not persisted. A batch is all-or-nothing
  (`accepted == count`); there is no cross-store transaction, so a mid-batch enqueue failure can
  strand committed rows — an accepted edge consistent with Epic 3's best-effort enqueue.
- **`GET /api/jobs` shape (decision).** Returns a paged envelope
  `{items, total, limit, offset}` (`JobPage`). `limit` defaults to 50 and is clamped to 1..200,
  `offset` to 0..10000; rows are ordered `submitted_at` desc then `id` so a batch sharing one
  timestamp pages stably. `session`/`state` are optional filters; an unknown `state` yields an
  empty page rather than an error. `JobResponse` exposes `worker_id` (which worker ran a job)
  but **not** `session_id` (revised in review — see *Review fixes* below).
- **Dependency providers moved to `app/dependencies.py`.** `get_queue`/`get_database`/
  `get_rate_limiter` were lifted out of `main.py` (which re-exports them) so the new
  `routers/jobs.py` can import them without an import cycle. Routes use the
  `Annotated[..., Depends(...)]` form (avoids Ruff `B008`).
- **Tests.** `test_jobs.py` (14, real Redis + Postgres) drives the app through a new
  `api_client` fixture — an httpx `AsyncClient` over `ASGITransport` with the queue/database/
  rate_limiter dependencies overridden to the container fixtures, so route I/O stays on the
  test event loop (a threaded `TestClient` would cross loops and break async psycopg/redis). It
  covers the happy path (rows in Postgres + ids on `ql:queue:ready` + shared ids), the
  422/429/409 guardrails (including out-of-range retry overrides), default vs custom retry
  settings, that `session_id` is not exposed, and `GET` paging/filters/limit-and-offset
  clamping. `test_validation.py` gained 11 unit cases for the new validators and batch-aware
  capacity.
- **Review fixes (4b).** Four findings applied:
  1. *Retry overrides validated.* `max_retries`/`retry_delay_ms` were written to the durable
     columns unchecked, so an out-of-range value caused an unhandled `500` (smallint/integer
     overflow) and a negative value stored silently. `validate_retry_settings` now bounds them
     (`max_retries` 0..10, `retry_delay_ms` 0..60000) and shapes a `422`.
  2. *`session_id` dropped from `JobResponse`.* It is the rate-limit / identity key and
     `GET /api/jobs` is unscoped, so exposing it let one visitor grief another's submit budget
     or spoof attribution. Reversed the earlier "keep it" decision; `guest_handle` stays.
  3. *Guardrail order reversed* to pure field checks → rate limit → capacity, so a malformed
     request no longer burns the session's rate-limit budget before it is rejected.
  4. *`offset` clamped* to 0..10000 (`MAX_PAGE_OFFSET`) so a caller can't request an
     arbitrarily deep (expensive) page.
  *Deferred (defer-to-note):* the mid-batch enqueue edge — a concurrent submission can fill the
  queue between the up-front capacity check and the enqueue loop, returning `409` after some
  rows committed. Already covered by *Documented trade-offs* above; accepted as best-effort
  enqueue, to be revisited if it bites Epic 10's durable-writer.
- **Review fixes (4b — round 2).** Three findings applied:
  1. *Server-side identity binding (was: identity in the body).* The body's `session_id` and
     `guest_handle` were both client-supplied with no server check, so a caller could submit under
     any handle or rotate `session_id` to dodge the per-session rate limit. New
     `backend/app/services/session_store.py` (`SessionStore`, mirrors `RateLimiter`) persists
     `session_id → {guest_handle, color}` in Redis (`ql:session:{id}`) with a TTL; `POST /api/session`
     now writes it (touches Epic 5's `routers/session.py`), and `submit_batch` derives the trusted
     `guest_handle` from that record — `guest_handle` was dropped from `JobSubmission`. An
     unknown/expired session raises `InvalidSubmissionError` → `422`
     (`[ERR] unknown or expired session — refresh the page`). Adds `session_ttl_seconds` (default
     86400) to config + `.env.example`. Wired a `get_session_store` provider through
     `dependencies.py`/`main.py`; the container-free `test_app.py` session smoke overrides it with a
     no-op store. *Deliberate deviation* from the earlier "stateless identity / handle in body"
     decision — identity is still not authentication, but the handle is now non-spoofable and tied
     to an issued session. Rotation isn't fully closed (a caller can still mint sessions via
     `POST /api/session`, which isn't IP-limited) — left as a known gap.
  2. *Docstring accuracy.* `JobSubmission`'s "deliberately loosely typed" claim was wrong (fields
     are typed `int`/`str`); softened the module + class docstrings to say bad *values* get the
     system-voice `[ERR]` while a wrong *type* falls back to Pydantic's default shape. No code change.
  3. *Capacity before rate limit.* Reordered `submit_batch` guardrails to field → session → capacity
     → rate limit, so a full-queue `409` no longer spends the session's rate-limit token.
- **Review fixes (4b — round 3).** Two residual nits applied:
  1. *Atomic session write.* `SessionStore.save` did `hset` then `expire` as two round-trips, so a
     failed `expire` could leave a session key with no TTL (a leak). The two now go out as one
     `MULTI`/`EXEC` transaction pipeline.
  2. *Session minting throttled per IP.* `POST /api/session` was unthrottled, so a caller could
     mint unlimited sessions and rotate them to dodge the per-session submit limit. Added
     `RateLimiter.check_session(client_ip)` (new action `session`, bucket keyed by IP) and a new
     `session_rate_seconds` setting (default 5, = the submit interval) so sessions can't be rotated
     faster than submits anyway. The route reads the client IP from `X-Forwarded-For` (left-most
     hop, trusting nginx to set/sanitize it — a deploy concern, Epic 19) and falls back to the
     direct peer. `config.py` + `.env.example` gained the setting; the container-free `test_app.py`
     smoke now also overrides the rate limiter with a no-op. New `test_session.py` (2 cases, real
     Redis): the minted identity is bound server-side, and a second immediate mint from one IP is
     `429`. *Note:* the bypass is now bounded, not fully eliminated — a distributed caller across
     many IPs is still possible; accepted for a portfolio app.
- **Verified:** Ruff lint + format clean; `pytest` green (78 tests: 75 Epic-7-original + 1
  unknown-session + 2 session-endpoint) against an auto-spun real Redis + Postgres. No new
  dependencies. Requires a Docker daemon for the integration suite.

## Epic 8a — Simulated work profiles — **COMPLETED**
- **Intent:** Per-type, complexity-scaled duration and failure profiles for simulated
  work — a pure, tested library the worker will call. The thinnest, dependency-free
  slice of the worker.
- **Scope:** `worker/simulate.py` (per-`JobType` duration + failure-rate profiles keyed
  by `type`/`complexity` 1..5; pure functions returning a duration and a pass/fail
  outcome, with injectable randomness). `worker/pyproject.toml` gains pytest config;
  new `worker/tests/test_simulate.py`.
- **Verification:** Pytest covers duration scaling and failure-rate math
  deterministically (seeded/injected randomness — no flakiness); profiles defined for
  all four job types.
- **Depends on:** Epic 7.
- **Implementation notes (plan-time decisions):**
  - **Profile feel = "Snappy"** (user-confirmed). Constants: `BASE_DURATION_MS = {email 300,
    webhook 500, report 800, image 1000}`, `BASE_FAILURE_RATE = {email .02, webhook .03,
    report .04, image .05}`, jitter `uniform(0.85, 1.15)`. Formulas (TDD §5.4):
    `duration_ms = round(base * complexity * jitter)`,
    `fail_prob = clamp(base * complexity + failure_bias, 0, 1)`, `passed = rng.random() >= fail_prob`.
    Ranges ~0.3s–5.8s, max ~25% failure — all comfortably under the 30s lease.
  - **`failure_bias=0.0` included now** (user-confirmed): `simulated_outcome` takes the optional
    bias term today (zero behaviour change when unused) so Epic 12's chaos button plugs in with
    no signature change.
  - **Dependency-free, string-keyed.** No `app.queue` import — profiles keyed by the four literal
    type strings; since `JobType` is a `StrEnum`, Epic 8b can pass `JobType` members straight in.
    Return unit is **integer ms** (matches durable `job.duration_ms`); randomness is an injectable
    keyword-only `rng: random.Random`. Unknown type → `ValueError`; inputs otherwise trusted
    (validation already bounds `type`/`complexity`).
  - **Two-button chaos product intent (user) — recorded for Epic 12, not built here:** a *"break
    something"* button = `POST /api/chaos/destroy-worker` (hard SIGKILL a worker → reaper (Epic 9)
    + autoscaler (Epic 11) recovery; does **not** touch `simulate.py`), and a *"chaos"* button =
    `POST /api/chaos/inject-failures` (biases outcomes via `failure_bias`). Both already in Epic 12's scope.
  - **Phasing:** (1) pytest config in `worker/pyproject.toml` + `simulate.py` duration profile +
    duration tests; (2) failure profile + `simulated_outcome(..., failure_bias=0.0)` + outcome/bias/
    clamp/coverage tests. ~120–160 lines, no `pytest-asyncio` (pure/sync).
  - **As built (implementation):**
    - `worker/simulate.py` (two pure functions `simulated_duration_ms` / `simulated_job_succeeds`
      + the `BASE_DURATION_MS` / `BASE_FAILURE_RATE` / `JITTER_RANGE` constants and a private
      `_require_known_type` guard); `worker/tests/test_simulate.py` (17 tests); `worker/pyproject.toml`
      gained `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`) and ruff
      `src=["."]`. Tests inject a small `FixedRandom` stub (pins jitter + the pass/fail draw) so
      the §5.4 formula is asserted exactly, plus a seeded `random.Random` for the jitter-range band.
    - **Deviation:** under ruff `src=["."]` the local `simulate` import sorts as first-party, so
      isort split it into its own group (cosmetic). Removed the now-stale `worker/.gitkeep`
      placeholder (real worker source now lives there). No new dependencies; `uv.lock` untouched.
    - **Verified:** `ruff check` + `ruff format --check` clean; `pytest` green (17 passed, ~0.02s,
      no Docker/Redis). Ran against `worker/.venv` (`uv` not on PATH on this machine).
  - **Review fixes (8a):**
    - *Outcome function renamed (approach change).* `simulated_outcome` → `simulated_job_succeeds`
      so the name reads as a yes/no and conveys polarity (`True` = the simulated job succeeds),
      per CLAUDE.md's boolean-naming rule. Keeps the `simulated_` pairing with
      `simulated_duration_ms`. Epic 8b/12 call the new name (no callers exist yet; signature is
      otherwise unchanged). Tests updated; supersedes the `simulated_outcome` name used in the
      plan-time bullets above.
    - *`rng` parameter kept (review nit rejected).* CLAUDE.md's "no abbreviations" rule would
      favour a fuller name, but `rng: random.Random` is a near-universal idiom and the type
      annotation removes ambiguity, so the keyword-only `rng` stays as recorded at plan time.

## Epic 8b — Worker claim loop & image — **COMPLETED**
- **Intent:** A genuine container worker that claims a job, runs it via the simulate
  profiles, and acks/nacks — the consumer side of the core flow, draining a real batch.
- **Scope:** `worker/worker.py` (async claim loop: `claim(worker_id, timeout)` → run
  via `simulate` → `ack`/`nack`; worker-id derivation; finite poll timeout).
  `worker/Dockerfile` vendors `backend/app/queue` **and** `backend/app/config.py` and
  sets the `CMD`; `worker/pyproject.toml` gains `pydantic` + `pydantic-settings`.
  Integration test: worker drains a submitted batch through real Redis (in-process
  against testcontainers).
- **Verification:** Build the worker image; run a container against compose Redis with a
  seeded batch → counts move queued→running→completed/failed. Pytest drains a batch
  in-process and asserts terminal states + counts.
- **Depends on:** Epic 8a.
- **Implementation notes:** Worker reuses the backend `Settings` by vendoring
  `backend/app/config.py` — forced, because `app.queue.client` imports
  `from app.config import settings` (not a worker-local config).
  - **As built (8b):**
    - **Vendoring = build-time, single source, repo-root build context** (user-chosen). The
      `worker/Dockerfile` COPYs `backend/app/queue` + `backend/app/config.py` (+ `app/__init__.py`)
      into the image's `app` package — no committed duplicate, so no drift. The build context is
      the **repo root**: `docker build -f worker/Dockerfile -t queuelab-worker:latest .`.
    - **`worker.py` = sequential claim loop.** `run_worker(queue, worker_id, *, poll_timeout=5.0,
      max_idle_polls=None, rng=...)` claims one job at a time (`claim` blocks up to `poll_timeout`,
      a finite wait), runs it via `simulate`, then `ack`s on success / `nack`s on failure. Helpers
      `run_one_job` and `derive_worker_id` (= `socket.gethostname()`, the container short id, legible
      later in `ql:workers`). `main()` runs `JobQueue.from_settings()` forever; `max_idle_polls`
      (finite) is only for the test's bounded drain.
    - **Out of scope here (per plan):** graceful SIGTERM + `ql:workers` registration are Epic 8c;
      hard-kill recovery is Epic 9's reaper. Phase-1 finiteness is only the poll timeout + the
      test's `max_idle_polls`.
    - **`pyproject.toml`:** runtime gains `pydantic` + `pydantic-settings` (back the vendored
      `app.config`/`app.queue`); dev gains `pytest-asyncio` + `testcontainers`; pytest
      `pythonpath = ["../backend", "."]` resolves `app.queue`/`app.config` from the sibling backend
      tree (the same code the image vendors) and `asyncio_mode = "auto"`. `worker/uv.lock`
      regenerated (now 26 packages).
    - **Tests:** `worker/tests/conftest.py` mirrors the backend harness (session Redis 7
      testcontainer, per-test `flushdb`, `queue`, `make_job`, Windows selector-loop switch);
      `test_worker.py` drives the **real** `run_worker` with a small injected `FixedRandom` stub —
      draw `1.0` ⇒ every job `completed`; draw `0.0` + `max_retries=0` ⇒ every job terminally
      `failed` — asserting counts and that leases/processing are cleared.
    - **Deviation (found in verification):** `uv sync` installs into `/app/.venv`, so the CMD's
      bare `python` couldn't see `redis`/`pydantic`. Added `PATH=/app/.venv/bin:$PATH` to the
      Dockerfile `ENV` so `["python", "worker.py"]` runs the venv interpreter (the standard
      uv-Docker pattern). Not in the plan; required to make the image actually run.
    - **No `docker-compose.yml` worker service** — compose deliberately omits workers (the
      autoscaler spawns them at runtime, Epic 11); verification used a manual `docker run`.
    - **Review fix (8b):** *Error boundary in the claim loop.* `run_worker` now wraps
      `run_one_job` in `try/except Exception`: a malformed job (bad payload / unknown type)
      is `nack`ed (logged via `logging.getLogger(__name__)`) and the loop keeps claiming,
      instead of an unhandled exception crashing the process and stranding the job in
      `ql:processing:{worker_id}` until lease expiry (which would crash-loop the next worker
      that claimed it). Inputs are still validated upstream (Epic 7); this is defense-in-depth.
      New test `test_worker_survives_a_malformed_job`. Nacking (not bare logging) settles the
      job the normal way — retry/backoff, or terminal `failed` once retries exhaust.
    - **Review fix (8b):** *Lease renewal during long jobs (new queue surface, scope nudge).*
      The original 8b worker slept the full duration without renewing the lease, relying on
      simulated durations (max ~5.8s) staying under the 30s visibility timeout — the
      at-least-once tradeoff from Epic 3. On review this was hardened to an explicit heartbeat
      so durations can be tuned up safely. Added a new queue primitive in the **backend**
      (vendored into the worker image): `backend/app/queue/scripts/renew.lua` (ownership-fenced,
      re-stamps `ql:leases` from Redis `TIME`; no state change, so counts/pub-sub untouched —
      mirrors `ack.lua`) + `JobQueue.renew_lease(job_id, worker_id)`. `run_one_job` now spawns
      a background `_renew_lease_until_cancelled` task that renews every
      `lease_renewal_seconds` (default = `visibility_timeout_seconds / 2`) and is cancelled the
      moment the work finishes — short jobs never trigger one. `renew.lua` ships in the image
      for free (the Dockerfile already COPYs all of `app/queue/scripts`). Tests:
      `test_renew_lease_extends_the_deadline` + `test_renew_lease_from_superseded_worker_is_ignored`
      (backend, real Redis), `test_worker_renews_the_lease_on_a_long_running_job` (worker,
      spies on `renew_lease` for a ~900ms job at a 50ms interval). *Note:* this reaches into the
      already-reviewed Epic 3 queue module — a deliberate, small expansion of 8b's surface,
      accepted because lease-renewal belongs with the worker that needs it and the reaper
      (Epic 9) already assumes leases can move.
    - **Review fix (8b):** *Best-effort heartbeat.* `_renew_lease_until_cancelled` now catches
      and logs renewal errors and keeps looping, instead of letting a renew exception propagate
      out (which would have `nack`ed a job whose work actually succeeded, burning a retry on a
      transient Redis blip). A failed renewal is now a no-op for the job's outcome; persistent
      failures let the lease lapse so the reaper requeues — the accepted at-least-once path. The
      heartbeat task now ends only via cancellation, so the `finally`'s `suppress(CancelledError)`
      is the only exception it can surface.
    - **Verified:** `ruff check` + `ruff format --check` clean; `pytest` green (19: 17 simulate +
      2 worker drain, ~4s) against an auto-spun real Redis 7. Image builds from the repo root; the
      container's vendored imports resolve and `derive_worker_id()` returns the container id. A
      real container drained a seeded 5-job batch on the compose network: `queued 5 → completed 4
      + retrying 1` (the `retrying` is a genuine ~2% simulated failure nacked into backoff, awaiting
      the Epic 9 reaper to promote it — exactly the real queue mechanics). `uv` was run from
      `backend/.venv/Scripts/uv.exe` (not on PATH on this machine).
    - **Completion gate (8b):** Re-ran the full green gate at completion (the `(19: …)` count
      above predates the review fixes, which added tests). `ruff check` + `ruff format --check`
      clean on both trees. Worker suite **22 passed** = 17 simulate + 5 worker (2 drain +
      `test_worker_survives_a_malformed_job` + `test_worker_renews_the_lease_on_a_long_running_job`
      + `test_worker_completes_job_even_when_lease_renewal_fails`). Backend suite **80 passed** =
      78 prior + the 2 `renew_lease` cases. Both ran against an auto-spun real Redis 7 / Postgres
      16. The worker image rebuilds from the repo root and the container's vendored `app.config` /
      `app.queue` imports resolve with `derive_worker_id()` returning the container short id.

## Epic 8c — Worker heartbeat, registration & graceful shutdown — **COMPLETED**
- **Intent:** Make the worker a well-behaved citizen — registered and heartbeating in
  `ql:workers` (for the autoscaler/chaos to see), with graceful SIGTERM that cleanly
  returns its in-flight job.
- **Scope:** `ql:workers` registration + periodic heartbeat (new `WORKERS_KEY` constant
  + helper in `backend/app/queue`, the shared source of truth the autoscaler reads); a
  dedicated clean requeue (new `requeue` method + `requeue.lua` in `app/queue`);
  graceful SIGTERM handler (stop claiming → requeue in-flight job → exit); hard SIGKILL
  left to lease-expiry recovery (Epic 9). Tests for registration, requeue, and graceful
  shutdown.
- **Verification:** Pytest: SIGTERM (graceful) requeues the in-flight job to
  `ql:queue:ready` as `queued` without consuming a retry; the worker appears in
  `ql:workers` and refreshes its heartbeat; the requeue clears the lease +
  `ql:processing:{worker_id}` entry.
- **Depends on:** Epic 8b.
- **Implementation notes:** Graceful SIGTERM uses a dedicated clean requeue (new
  `requeue` method + `requeue.lua` in `app/queue`) that returns the in-flight job to
  `ql:queue:ready` as `queued` and clears the lease/processing entry **without
  incrementing `attempts`** — graceful drain never burns a retry or fails a
  last-attempt job. Hard SIGKILL is intentionally unhandled here; it relies on
  lease-expiry recovery via the Epic 9 reaper. (Rejected reusing `nack`, which burns a
  retry.)
- **Plan-time decisions (8c):**
  - **Registry = a single `ql:workers` Hash** (TDD §5.4 — `worker_id → JSON {state,
    current_job, last_heartbeat}`), via a new `WORKERS_KEY` constant in
    `app/queue/protocol.py`. Graceful shutdown `HDEL`s its own field; a hard-killed worker
    leaves a stale field the **autoscaler reaps by heartbeat-age (Epic 11)** — the registry
    does not self-clean. (User-confirmed; chosen over per-worker TTL'd `ql:worker:{id}`
    keys, which would self-expire but deviate from the TDD's "Hash" and need `SCAN`.)
  - **Worker `state` vocabulary = `idle` / `busy` / `stopping`** (user-confirmed) — a
    worker-liveness vocab distinct from the job-state enum; `stopping` is set during the
    graceful drain.
  - **Registration is folded into the first heartbeat** — one `heartbeat(worker_id, *,
    state, current_job=None)` upsert, no separate `register_worker` method (a deliberate
    simplification of this epic's "registration + heartbeat" wording). Plus
    `deregister_worker` (`HDEL`) and `list_workers` (`HGETALL` + JSON-decode, for tests now
    / the autoscaler later).
  - **`heartbeat` stamps `last_heartbeat` from Redis `TIME`** (the one authoritative clock,
    so the autoscaler's heartbeat-age check is skew-free), reusing `enqueue`'s
    TIME-then-write pattern — **no new Lua script** (worker-field writes are single-writer,
    so no cross-writer atomicity concern).
  - **`requeue.lua` reuses the `ack`/`nack`/`renew` ownership fence** (no-op `'stale'` for a
    superseded worker) and passes `READY_KEY` in `KEYS` (all keys declared; the worker_id is
    known so `processing_key` is built in Python).
  - **New config `worker_heartbeat_seconds: PositiveInt = 5`** (+ `.env.example`, one-to-one).
  - **Graceful shutdown via an injected `stop_event` seam** on `run_worker` (mirrors the
    existing `max_idle_polls` test seam): the in-flight job runs as a task raced against the
    event, so SIGTERM cancels the simulated work and `requeue`s promptly. The OS signal is
    wired **only in `main()`** (`add_signal_handler` for SIGTERM/SIGINT, suppressing
    `NotImplementedError` on Windows — the worker runs in a Linux container, Windows is
    dev-only), so tests stay OS-agnostic by driving `stop_event` directly.
  - **3-phase build:** (1) queue primitives — `requeue.lua`/`requeue` + registry helpers +
    backend tests; (2) worker registration + periodic heartbeat; (3) graceful SIGTERM
    requeue. Each phase compiles and is independently reviewable.
- **As built (8c):**
  - **Phase 1 — queue surface.** Added `WORKERS_KEY = "ql:workers"` to
    `app/queue/protocol.py`; `app/queue/scripts/requeue.lua` (ownership-fenced clean requeue,
    KEYS include `READY_KEY`, never touches `attempts`); and four `JobQueue` methods —
    `requeue`, `heartbeat` (registration folded in), `deregister_worker`, `list_workers`.
    `heartbeat` stamps `last_heartbeat` from Redis `TIME` via the existing `enqueue`
    timestamp-then-write pattern (no Lua). Tests: requeue clean-return, requeue stale no-op,
    register/refresh/deregister.
  - **Phase 2 — registration + heartbeat.** Added `worker_heartbeat_seconds: PositiveInt = 5`
    (config.py + `.env.example`, new "Worker liveness / registry" group). `run_worker` emits
    an initial heartbeat (registration) and runs a lifetime `_heartbeat_until_cancelled` task
    (mirrors `_renew_lease_until_cancelled`: best-effort, logs, keeps looping) that reads a
    small mutable `_WorkerStatus` dataclass holder, deregistering in a `finally` on exit.
  - **Phase 3 — graceful SIGTERM.** `run_worker` gained a `stop_event` seam; a new private
    `_run_job_until_done_or_stopped` runs the in-flight job as a task raced (`asyncio.wait`,
    `FIRST_COMPLETED`) against the stop event, so a stop mid-job cancels the simulated work
    and `requeue`s the job cleanly. The OS signal is wired **only in `main()`**
    (`add_signal_handler` for SIGTERM/SIGINT, `NotImplementedError` suppressed on Windows).
  - **Deviations / notes:**
    - The worker-test poll helper `_poll_until` uses **PEP 695 inline generics**
      (`def _poll_until[PollResult](...)`) — ruff `UP047`/`UP049` required it over `TypeVar`
      on this py312 tree. It replaces fixed sleeps when observing the concurrently-running
      worker task (registration, claim, heartbeat advance), keeping the tests non-flaky.
    - **No new dependencies** — `signal` and `dataclasses` are stdlib; `worker/pyproject.toml`
      and both `uv.lock`s are untouched. `worker.py` was rewritten in full, so its diff churn
      overstates the logic added (e.g. `run_one_job` is byte-identical).
    - **Idle-shutdown latency** is bounded by `poll_timeout` (the loop checks `stop_event` at
      the top of each cycle; an in-flight job is interrupted promptly via the race). Acceptable
      under Docker's default 10s stop grace; not separately raced to keep the loop simple.
  - **Review fixes (8c):**
    - *`stopping` state made observable (approach refinement).* As first built, `run_worker`'s
      `finally` set `status.state = "stopping"` then cancelled the heartbeat task with no
      intervening `await`, so `stopping` was never published to `ql:workers` before
      `deregister_worker` (`HDEL`) removed the record — the user-confirmed `stopping` vocabulary
      was inert. The `finally` now cancels the periodic heartbeat, publishes **one final
      best-effort `stopping` heartbeat** (logged on failure, mirroring the periodic task), then
      deregisters — so a graceful drain is briefly visible to the autoscaler (Epic 11) before the
      worker disappears. Deviates slightly from the plan's "graceful shutdown `HDEL`s its field":
      it now writes `stopping` then `HDEL`s.
    - *Boolean naming.* Renamed the local `requeued` → `was_requeued` in `run_worker` (CLAUDE.md
      boolean-prefix rule). No behaviour change.
  - **Verified:** ruff lint + format clean on both trees; backend `pytest` **83 passed**
    (80 prior + 3 queue), worker `pytest` **7 passed** (5 prior + 2: registration/heartbeat +
    graceful-shutdown requeue) against an auto-spun real Redis 7 / Postgres 16. The worker
    image rebuilds from the repo root and the container's vendored `app.queue` (incl.
    `requeue.lua`) / `app.config` imports resolve.
  - **Completion gate (8c):** Re-ran the full green gate at completion. ruff `check` +
    `format --check` clean on both trees. Backend suite **83 passed** (80 prior + 3 queue:
    requeue clean-return, requeue stale no-op, register/refresh/deregister). Worker **full
    suite 24 passed** = 17 simulate + 7 `test_worker.py` (the "7 passed" in the Verified
    bullet above counts only `test_worker.py`; the whole worker suite is 24, matching the
    8b convention of reporting the full suite). Both ran against an auto-spun real Redis 7 /
    Postgres 16 via testcontainers.

## Epic 9 — Reaper (delayed promotion & lease recovery) — **COMPLETED**
- **Intent:** The chaos-recovery path — promote due delayed jobs and requeue jobs
  whose lease lapsed (dead worker), making "destroy a worker → job retried" real.
- **Scope:** Reaper background loop in the api process: move `ql:queue:delayed` →
  `ready` when due; scan `ql:leases` for past-deadline entries and requeue
  (respecting `max_retries`). Integration tests (real Redis): expired lease requeues;
  exhausted retries go terminal `failed`.
- **Verification:** Pytest integration: a job whose lease deadline passes is requeued
  as `retrying`; after `max_retries` it becomes `failed`; delayed jobs promote on
  schedule.
- **Depends on:** Epic 8c.

### Implementation notes
- **No new queue mechanics — just the loop.** Epic 3 already built the atomic recovery
  sweep (`reap.lua` + `JobQueue.reap()` returning `(promoted, recovered)`, plus the
  `promote_due_delayed`/`reap_expired_leases` wrappers) and tested it directly. Nothing
  called it on a schedule, so at runtime delayed jobs never promoted and dead-worker leases
  never requeued. Epic 9 adds only the periodic driver.
- **`backend/app/reaper.py` = one module function.** `run_reaper(queue, *, interval_seconds)`
  mirrors the worker's background-task pattern (`_heartbeat_until_cancelled`): sleep-first,
  best-effort (a failed sweep is logged via `logging.exception` and the loop carries on to
  the next tick — a transient Redis blip never stops recovery), and stops only on
  `task.cancel()`. It logs an `info` line only when a sweep actually promoted or recovered
  work (no per-tick noise). Background *loops* in this repo are module functions; only the
  *clients* are classes.
- **Config `reaper_loop_seconds: PositiveInt = 2`** (config.py + `.env.example`, one-to-one),
  mirroring `autoscaler_loop_seconds=2` and the TDD's ~1-2s loops. Env-overridable.
- **Lifespan wiring (main.py).** The reaper task is started right after the datastore clients
  are built and **cancelled before** they are closed (so an in-flight sweep never hits a
  closed Redis client): `reaper_task.cancel()` → `with suppress(asyncio.CancelledError): await
  reaper_task` → the existing `gather(...aclose())`. The task is stashed on
  `app.state.reaper_task` (consistent with the other lifespan-owned resources, and for later
  observability / the boot-smoke assertion). Always-on, no enable/disable flag — single-EC2
  deploy is one api process, and `reap.lua` is atomic so even a double-sweep is safe.
- **Tests are loop-level, not queue-level** (the queue mechanics are already covered in
  `test_queue.py`). `backend/tests/test_reaper.py` (4, real Redis) runs `run_reaper` as a task
  at a 20ms tick and asserts the loop, *on its own*, (a) promotes a due delayed job to
  `queued`, (b) requeues an expired-lease job to `retrying` (attempts++, processing/lease
  cleared), (c) sends a retry-exhausted (`max_retries=0`) expired-lease job terminal `failed`
  — which drives `reap.lua`'s failed branch, previously only reached via `nack`, never via the
  reap path — and (d) keeps ticking after a monkeypatched transient sweep failure. Uses the
  existing score-rewrite time-travel trick (no real sleeps) and a local `_poll_until` helper
  mirroring the worker suite's (PEP 695 inline generic; re-implemented here because `worker` is
  a separate package) to observe the concurrent loop without flaky fixed sleeps. `test_app.py`
  gained a container-free smoke that the lifespan starts the reaper task and cancels it cleanly
  on shutdown.
- **Verified:** ruff lint + format clean on the backend tree; backend `pytest` **88 passed**
  (83 prior + 4 reaper + 1 lifespan smoke) against an auto-spun real Redis 7 / Postgres 16 via
  testcontainers. Ran against `backend/.venv` (`uv` not on PATH on this machine).
- **Completion gate (9):** Re-ran the full green gate at completion — ruff `check` +
  `format --check` clean (42 files), backend suite **88 passed** against an auto-spun real
  Redis 7 / Postgres 16, matching the Verified count. Diff is ~241 non-doc lines / 7 files;
  over the ~150 rule of thumb but the overage is the loop-level integration tests
  (`test_reaper.py`, 157 lines) — production code is ~68 lines for the single reaper-loop
  concern, so kept whole (human-acknowledged at completion).

## Epic 10a — Durable-writer (state events → Postgres outcomes) — **COMPLETED**
- **Goal:** Final job outcomes survive Redis expiry. A background subscriber on the
  `ql:events:state` channel writes the timing/outcome fields (`started_at`, `worker_id`,
  `finished_at`, `duration_ms`, `last_error`, `state`) onto the durable Postgres job rows,
  so completed/failed jobs keep accurate history after the 1-hour Redis TTL lapses.
- **Rough scope:** A new durable-writer subscriber in `backend/app/realtime/` that follows
  the reaper's lifespan-task pattern, maps each state-change event to a Postgres `Job`
  update, and is wired into the app lifespan. Integration test drives a batch through
  claim → ack and asserts the durable row gains `finished_at` and `duration_ms`.
- **Open questions / decisions for stakeholders:** Idempotency / out-of-order events — set
  `started_at` once and compute `duration_ms` from the event epochs; whether `retrying` /
  `failed` events also update `state`/`attempts`/`last_error` (recommend yes — persist every
  state on the row). Settle at epic time.
- **Depends on:** Epic 9.
- **Implementation notes:**
  - **Stakeholder decision — enrich the Lua scripts.** No event carried `last_error`, and
    `failed`/`retrying` events carried no finish timestamp (only the `completed` ack event had
    both epochs). Chose to enrich `nack.lua` + `reap.lua` (over deferring or an HGETALL-from-hash)
    so failed rows get authoritative, complete history: the terminal `failed` branch now publishes
    `started_at` + `finished_at` (= `now_ms`) + `last_error`; the `retrying` branch publishes
    `last_error`. `cjson` omits nil fields, so one publish per branch covers both. Verified no
    existing test pins the event payloads, so the enrichment was safe.
  - **`backend/app/realtime/durable_writer.py` = one module function** (`run_durable_writer`) plus
    a per-message handler and an idempotent `_persist_event` mapper. It mirrors the reaper's
    best-effort/cancel-on-shutdown posture but is a **pub/sub listen loop**, not a sleep-first tick.
  - **Deviation — added an outer re-subscribe loop.** Beyond the plan's single subscribe/listen, a
    dropped subscription (transient Redis blip) is logged and re-subscribed after
    `RESUBSCRIBE_DELAY_SECONDS` (1s). This gives the writer the reaper's "survive a failure and
    carry on" property, and keeps the container-free lifespan smoke non-flaky (the task is always
    mid-flight — never dead — when shutdown cancels it). A bad single message is still logged and
    skipped separately.
  - **`JobQueue.pubsub()` accessor** added so the writer (and Epic 10b's broadcaster) reuse the
    queue's Redis pool instead of a second client. **No new config value** — a pub/sub loop has no
    tick interval.
  - **Mapping:** `_persist_event` applies a field-by-field partial update keyed on which fields the
    event carries (`state` always; `worker_id`/`started_at`/`attempts`/`last_error`/finish-epoch as
    present). `duration_ms` is computed from the event's own epoch pair (finish − start), so it is
    idempotent and order-independent; a missing durable row is logged + skipped. Redis epoch-ms →
    tz-aware `datetime` via `datetime.fromtimestamp(ms/1000, tz=UTC)`.
  - **Verified:** ruff `check` + `format --check` clean (42 files); backend `pytest` **91 passed**
    (88 prior + 2 durable-writer integration + 1 lifespan smoke) against an auto-spun real Redis 7 /
    Postgres 16 via testcontainers. Ran against `backend/.venv` (`uv` not on PATH on this machine).
  - **Size:** ~290 changed lines / 7 non-generated files / 2 phases — over the ~150 rule of thumb,
    but one cohesive behavior; ~116 lines are integration tests and ~60 of `durable_writer.py`'s 105
    lines are the repo's mandated explanatory docstrings/comments. Kept whole (Epic 9 precedent).
  - **Review fix — `ack.lua` also carries `worker_id`.** The `completed` event omitted `worker_id`
    (the script `HDEL`s it before publishing), so the durable row's `worker_id` rode only on the
    earlier `running` event — a writer that started/restarted after the claim would lose it (pub/sub
    has no replay). Now the `completed` event re-publishes the owning `worker_id` (the local the
    ownership fence already matched), so the outcome is self-contained. No writer change — the
    field-by-field mapper already persists `worker_id` when present.
  - **Review fix — `state` ordering caveat.** Clarified in `_persist_event`'s docstring that, unlike
    `duration_ms` (computed from the event's own epochs, truly order-independent), `state` is
    last-write-wins and stays correct only because every event for a job arrives in publish order on
    the single `ql:events:state` channel.
  - **Deferred (review nit, by stakeholder call) — per-event DB session.** `_persist_event` opens one
    session/transaction per message. Acceptable at lab scale; revisit with batching/session reuse
    only if event volume makes per-message commits a bottleneck.
  - **Completion gate (10a):** Re-ran the full green gate at completion — ruff `check` +
    `format --check` clean (42 files), backend `pytest` **91 passed** against an auto-spun real
    Redis 7 / Postgres 16, matching the Verified count. Final diff is ~344 added lines / 8 non-doc
    files — the original Size note (~290 / 7) predates the `ack.lua` review fix, which added the
    eighth file. Overage is the two integration-test files (~161 lines) plus the module's mandated
    docstrings; production is ~183 lines for one cohesive subscriber concern, kept whole
    (human-acknowledged at completion, Epic 9 precedent).

## Epic 10b — Real-time broadcaster & `WS /ws` (snapshot + deltas) — **COMPLETED**
- **Goal:** A browser connects to `WS /ws`, immediately receives a snapshot of current
  queue state, then receives per-job state-change deltas in real time as a batch runs.
- **Rough scope:** A connection manager (track clients, snapshot-on-connect from queue
  counts/state) and a broadcaster (subscribe to `ql:events:state`, fan messages out to every
  connected client) in `backend/app/realtime/`; the `WS /ws` endpoint; broadcaster started
  and stopped in the lifespan. Integration test connects, asserts the snapshot frame, then
  asserts deltas arrive as a batch is claimed/acked.
- **Open questions / decisions for stakeholders:** Message envelope
  (`{type: "snapshot" | "delta", …}`) and snapshot payload shape; broadcast-all vs
  per-session filtering — this is a multiplayer view, so recommend broadcast-all. Settle at
  epic time.
- **Depends on:** Epic 10a.
- **Implementation notes:**
  - **Decisions settled.** Envelope is `{"type": "snapshot" | "delta", …}`. Snapshot carries
    **counts + in-flight jobs** (`queue.counts()` plus every active job). **Broadcast-all**, no
    per-session filtering or auth — a shared multiplayer view. **`session_id` is never
    broadcast**: both the snapshot job projection and the deltas drop it, since it is the
    rate-limit key the REST layer already withholds (`JobResponse`). Test connects to the real
    `/ws` via the small **`httpx-ws`** dev dep on the existing same-event-loop `ASGITransport`
    pattern (the suite deliberately avoids the threaded `TestClient`).
  - **`JobQueue.active_jobs()`** (new read helper) gathers ids from `ready` + `leases` +
    `delayed`, de-dupes, then reads each `ql:job:{id}` hash in **one pipeline**; a hash that
    vanished mid-read (TTL/ack race) is skipped, so the snapshot is best-effort.
  - **`ConnectionManager`** (`backend/app/realtime/connection_manager.py`): `connect` accepts +
    sends the snapshot + registers (in that order); `broadcast` fans a frame to a **copy** of the connection set
    and drops any socket that raises (one dead client can't stop the rest). `_project_job` builds
    the public per-job dict (no `session_id`; lifts `type`/`complexity` out of `payload`).
  - **`run_broadcaster`** (`backend/app/realtime/broadcaster.py`) is the read-many twin of the
    durable-writer: same `queue.pubsub()` loop, re-subscribe-after-`RESUBSCRIBE_DELAY_SECONDS`,
    best-effort per-message handler, cancel-on-shutdown. Started/stopped in the lifespan beside
    the reaper and durable-writer; the `ConnectionManager` lives on `app.state` (no task of its
    own). `get_connection_manager` takes a `WebSocket` (not `Request`) since it is WS-only.
  - **Known limitation (out of scope).** `enqueue()` publishes no `queued` event, so a freshly
    submitted job first appears as a **delta** when it is claimed (`running`); until then it is
    visible only via the **snapshot** to clients that connect after it queued. A live `queued`
    delta would touch the hot producer path / Lua — left to a later epic.
  - **Test deviation.** The WS client is a **factory fixture** (`ws_app_client`) that the test
    opens/closes inside its own task, not a yield-an-open-client fixture: `ASGIWebSocketTransport`
    keeps an anyio cancel scope across the connection, which can't cross pytest-asyncio's
    setup/teardown task boundary. `_poll_until` / `_wait_for_subscriber` / `_running_broadcaster`
    are local copies mirroring the durable-writer suite (per that suite's precedent).
  - **Size.** ~444 changed lines / 10 non-generated files / 2 phases — over the ~150 rule of
    thumb, but **one cohesive concern** (real-time fan-out of one event stream); ~171 lines are
    tests + the conftest fixtures and much of the rest is the repo's mandated module/method
    docstrings. Kept whole — mirrors Epic 10a (human-approved at plan time).
  - **Verified.** ruff `check` + `format --check` clean (47 files); backend `pytest` **93
    passed** (91 prior + 2 realtime integration) against an auto-spun real Redis 7 / Postgres 16
    via testcontainers. Ran against `backend/.venv` (`uv` not on PATH on this machine).
  - **Snapshot vs delta shape (caveat for Epic 10c consumer).** The two frames carry *different*
    per-job shapes: the snapshot's `_project_job` includes `type`/`complexity`/`attempts`/
    `enqueued_at`, but a `delta` forwards the raw Lua state event, which carries only
    `job_id`/`state`/`worker_id`/`started_at`(/`completed_at`). A client must merge a delta into
    the job it already holds from the snapshot, keyed by `job_id`. Intentional — deltas ride the
    existing `ql:events:state` stream unchanged rather than re-reading the hash on the hot path.
  - **Review fixes (Epic 4 round).** Two minor robustness fixes applied: `WS /ws` now deregisters
    in a `finally` so any exit path forgets the socket; `ConnectionManager.connect` sends the
    snapshot *before* registering, so a failed send can't leave a dead socket and the snapshot
    always precedes any delta. Rejected: guarding `active_jobs` against partial hashes (the
    atomic multi-field `HSET` makes a partial `HGETALL` unobservable) and the `pipe`/`ws` naming
    nits (idiomatic redis-py / WebSocket abbreviations).
  - **Completion gate (10b).** Re-ran the full green gate at completion — ruff `check` +
    `format --check` clean (49 files), backend `pytest` **93 passed** against an auto-spun real
    Redis 7 / Postgres 16 via testcontainers, matching the Verified count. Final diff is ~450
    non-doc insertions / 10 non-doc files (501 total over 11 incl. the plan doc), in line with
    the Size note; overage is the integration tests + conftest fixtures plus the module's
    mandated docstrings for one cohesive concern, kept whole (human-acknowledged at completion,
    Epic 10a precedent).

## Epic 10c — Metrics (snapshot & throttled tick) — **COMPLETED**
- **Goal:** The dashboard gets aggregate vitals: a `GET /api/metrics` snapshot of the live
  queue counts plus derived state (queue depth, worker count), and a throttled metrics tick
  pushed over `/ws` so those vitals stay live without re-polling.
- **Rough scope:** `backend/app/services/metrics.py` (compute metrics from `queue.counts()`
  plus derived state), a `GET /api/metrics` endpoint (new `backend/app/routers/metrics.py` +
  a `MetricsResponse` schema), and a throttled metrics-tick task under `backend/app/realtime/`
  broadcasting a `{"type": "metrics", …}` frame over `/ws`, wired into the api lifespan beside
  the reaper/broadcaster. Tests cover the snapshot matching counts and the throttled tick
  fan-out.
- **Open questions / decisions for stakeholders:** Settled at split time — the tick interval is
  a new dedicated `metrics_tick_seconds` setting (default `1`), the timer itself acting as the
  throttle. Nothing else expected.
- **Depends on:** Epic 10b.
- **Implementation notes:**
  - **One shared service feeds both transports.** `backend/app/services/metrics.py` exposes a
    single `compute_metrics(queue) -> dict` returning `{"counts": <queue.counts()>,
    "queue_depth": <queue.queue_depth()>, "worker_count": len(queue.list_workers())}`. The REST
    endpoint and the WS tick both read it, so the pulled snapshot and the pushed tick can never
    disagree. It is a thin read over existing `JobQueue` helpers — no new Redis access.
  - **Worker count = all registered workers** (`len(queue.list_workers())`), settled with the
    stakeholder. Pruning a hard-killed worker by stale heartbeat age is the autoscaler's job
    (Epic 11), so metrics stays a plain count rather than re-deriving liveness here.
  - **Frame/response shape mirrors the snapshot envelope.** REST returns a typed
    `MetricsResponse` (`counts: QueueCounts` + `queue_depth` + `worker_count`); the tick wraps the
    same dict as `{"type": "metrics", "counts": {...}, "queue_depth": N, "worker_count": N}`,
    matching Epic 10b's `{"type": "snapshot", "counts": {...}, "jobs": [...]}`. `queue_depth` is
    read straight from the ready list (`LLEN`), the authoritative depth, distinct from the
    `counts.queued` tally even though they normally agree.
  - **Tick mirrors the reaper loop.** `backend/app/realtime/metrics_tick.py` `run_metrics_tick`
    sleeps first, is best-effort (logs and continues on error so a transient Redis blip never
    stops the feed), and never catches `CancelledError`, so the lifespan cancels it cleanly on
    shutdown. Wired into the lifespan beside the broadcaster, using the new
    `metrics_tick_seconds` setting (default `1`; the timer is itself the throttle).
  - **Phasing.** Phase 1 — service + `MetricsResponse`/`QueueCounts` schema + `GET /api/metrics`
    router (registered in `main.py`) + snapshot test. Phase 2 — `metrics_tick_seconds` setting +
    tick task + lifespan wiring + fan-out test. The tick test is simpler than the broadcaster's
    (no pub/sub, so no wait-for-subscriber) — drain the snapshot, run a fast tick, assert one
    `metrics` frame.
  - **Size.** ~258 changed lines / 8 non-generated files (5 new + 3 edited) / 2 phases — over the
    ~150 rule of thumb, but **one cohesive concern** (queue vitals delivered over REST pull + WS
    push, sharing one service); ~88 lines are the two integration tests and much of the rest is
    the repo's mandated docstrings. Kept whole — well within the Epic 10a/10b precedent.
  - **Verified.** ruff `check` + `format --check` clean (54 files); backend `pytest` **95 passed**
    (93 prior + 2 new: metrics snapshot + metrics tick) against an auto-spun real Redis 7 /
    Postgres 16 via testcontainers. Ran against `backend/.venv` (`uv` not on PATH on this machine).
  - **Completion gate (10c).** Review came back clean (Approve with nits — no fixes required, so no
    review-fixes bullet). Re-ran the full green gate at completion — ruff `check` + `format --check`
    clean (54 files), backend `pytest` **95 passed** against an auto-spun real Redis 7 / Postgres 16
    via testcontainers, matching the Verified count. Final non-doc diff is ~258 changed lines / 8
    files (5 new + 3 edited) — over the ~150 line rule of thumb but at the ~8-file budget; overage is
    the two integration tests plus the module's mandated docstrings for one cohesive concern, kept
    whole (human-acknowledged at completion, Epic 10a/10b precedent).

## Epic 10d — Activity feed — **COMPLETED**
- **Goal:** The dashboard gets a human-readable activity feed: recent job state-changes
  rendered as one-line entries and fanned out over `/ws`, with a freshly-connected client
  seeded with the recent history.
- **Rough scope:** `backend/app/services/activity_feed.py` (format a public state event into a
  readable line; keep a bounded ring buffer of recent lines), a subscriber that fans each new
  line out over `/ws` as a `{"type": "activity", …}` frame, and connect-time seeding of the
  recent lines (mirroring the snapshot). Tests cover the line fan-out and the connect-time
  seeding.
- **Open questions / decisions for stakeholders:** Settled at split time — retention is an
  in-memory ring buffer (length ~50), ephemeral by design (Postgres remains the durable
  record). For epic time: whether the fan-out rides a new dedicated `realtime/` subscriber
  (recommended, matching the durable-writer/broadcaster pattern) or hooks the existing
  broadcaster.
- **Depends on:** Epic 10c.
- **Implementation notes:**
  - **Dedicated subscriber** (settled with stakeholder). The fan-out rides a new
    `backend/app/realtime/activity.py` subscribed to `ql:events:state` — the read-many twin of the
    broadcaster/durable-writer — rather than hooking the existing broadcaster. One subscriber per
    concern, matching the established pattern. (Post-review: the subscribe/re-subscribe/close loop
    itself, previously copied into all three subscribers, was extracted to a shared
    `backend/app/realtime/subscriber.py::run_state_subscriber`; each subscriber is now just its own
    per-message handler — see the post-review note below.)
  - **Seed folds into the snapshot** (settled with stakeholder). The connect-time `snapshot`
    frame gains an `"activity": [recent lines]` key; live updates are a separate
    `{"type": "activity", "line": …}` frame. This mirrors how the snapshot already seeds counts +
    jobs, so a late-joiner gets recent history in the one opening frame (no second seed frame, no
    dual-shape `activity` type).
  - **Lines format the *event*, not the hash.** The public state event on `ql:events:state`
    carries only `job_id`/`state`/`session_id`/`worker_id`/`started_at`(/`completed_at`/
    `finished_at`/`attempts`/`last_error`) — **not** the job's `type`/`complexity` (those live in
    the Redis hash, which the delta path never re-reads). So a line keys on `job_id` + `worker_id`
    + `state`, exactly the fields the broadcaster sees. `session_id` is never used in a line.
  - **Ring buffer.** `ActivityFeed` wraps `collections.deque(maxlen=…)`; length comes from a new
    `activity_feed_max_lines` setting (default 50). Ephemeral by design — Postgres remains the
    durable record (Epic 10a).
  - **Phasing.** Phase 1 — `services/activity_feed.py` (`format_activity_line` + `ActivityFeed`) +
    pure unit test. Phase 2 — `realtime/activity.py` subscriber + setting + lifespan wiring +
    fan-out integration test. Phase 3 — fold recent lines into the snapshot via `ConnectionManager`
    (optional `feed` arg) + conftest fixture + connect-time seeding test.
  - **Subscriber `_handle_message` records before broadcasting.** The line is appended to the ring
    buffer *before* it is fanned out, so the buffer always reflects what has been sent live — a
    client is never handed a live line that is missing from the history it was seeded with. One
    residual window remains (inherent to the Epic 10b connection manager, and shared by `delta`
    frames): the snapshot is built and sent *before* the socket joins the broadcast set, so a line
    published in that brief window reaches neither that client's snapshot nor its live stream.
    Accepted for an ephemeral feed — Postgres remains the durable record.
  - **Size.** ~9 non-generated backend files (5 new — incl. the post-review `realtime/subscriber.py`
    — + 4 edited; the plan doc is the extra edited file) — over the ~150-line rule of thumb but at
    the file budget and **one cohesive concern** (real-time fan-out of one event stream as readable
    lines + connect-time seeding). Roughly half the change is the unit + integration tests and
    conftest fixture, and much of the rest is the repo's mandated module/function docstrings. Kept
    whole — within the human-approved Epic 10a/10b/10c precedent; splitting would ship an incomplete
    feed.
  - **Post-review fixes (Epic 10d review).** Four review nits applied: (1) the duplicated
    subscribe/re-subscribe/close loop was extracted to `realtime/subscriber.py::run_state_subscriber`
    and the broadcaster, durable-writer, and activity subscribers now pass a `functools.partial`
    handler to it (shrinks each `run_*` to a single call; the only behavioural change is the log
    label is now passed as `name=`); (2) the "records before broadcasting" note above was reworded
    to drop the overstated "no gap" and name the residual connect-window race; (3) a
    `test_handle_message_skips_a_malformed_event` unit test now covers the best-effort skip path;
    (4) the unknown-state fallback now renders `"<job> → unknown"` instead of a literal `None`.
  - **Verified.** ruff `check` + `format --check` clean; backend `pytest` green against an
    auto-spun real Redis 7 / Postgres 16 via testcontainers (15 activity tests: 13 unit + 2
    integration, plus the unchanged broadcaster/durable-writer suites confirming the loop
    extraction). Ran against `backend/.venv` (`uv` not on PATH on this machine).

## Epic 11a — Scaling policy core (pure decisions)
- **Goal:** A pure scaling-decision function decides what the autoscaler should do
  from a snapshot of the queue and workers, with no I/O or side effects.
- **Rough scope:** `backend/app/services/autoscaler.py` — a `decide_scaling(...)`
  taking queue depth, the worker registry (state + `last_heartbeat`), the `settings`
  thresholds, and the current time, returning an action (scale up by N / scale down a
  named worker / replace an unhealthy worker / no-op) plus a human-readable reason.
  Covers guardrail caps (`min_workers`/`max_workers`), queue-depth thresholds, idle
  scale-down, and stale-heartbeat (unhealthy) detection. Pure unit tests only — no
  Docker, no Redis, no long-lived process.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 10d.
- **Implementation notes:** _none yet_

## Epic 11b — Docker control
- **Goal:** A thin Docker wrapper can spawn, list, and kill worker containers over the
  mounted Docker socket.
- **Rough scope:** `backend/app/services/docker_control.py` using the Docker SDK
  (`/var/run/docker.sock`): start a worker from `worker_image` (label it, join the
  compose network, pass `redis_url`), list the running worker containers by that label,
  and kill/remove one. Tested with the Docker SDK mocked (or skip-if-no-socket).
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 11a.
- **Implementation notes:** _none yet_

## Epic 11c — Autoscaler process & scaling events
- **Goal:** A long-lived autoscaler process runs the control loop, scaling workers by
  queue depth and recording every step.
- **Rough scope:** `backend/app/autoscaler_main.py` entrypoint (asyncio loop building
  `JobQueue`, `Database`, and the Docker control); the ~1–2s control loop tying the
  policy (11a) to the Docker control (11b), reading depth/workers, applying the caps
  and idle scale-down, and writing a `scaling_event` row to Postgres plus a feed line
  per step; the real `command` for the `autoscaler` compose service. Integration test:
  flood the queue → scale up to cap; idle past `idle_timeout` → scale down to
  `min_workers`.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 11b.
- **Implementation notes:** _none yet_

## Epic 11d — Manual control channel & config API
- **Goal:** Operators can drive scaling manually and adjust the autoscaler thresholds
  at runtime.
- **Rough scope:** a `ql:control` channel consumer folded into the control loop
  (manual scale commands) and `GET/PUT /api/config` endpoints that read and update the
  live autoscaler thresholds. Integration test for the control-channel commands.
- **Open questions / decisions for stakeholders:** none expected.
- **Depends on:** Epic 11c.
- **Implementation notes:** _none yet_

## Epic 12 — Chaos endpoints
- **Intent:** Destroy-worker and inject-failures, wired through the autoscaler and
  reflected in the feed/grid — the "break it on purpose" mechanic.
- **Scope:** `backend/app/services/chaos.py`, `POST /api/chaos/destroy-worker`,
  `POST /api/chaos/inject-failures` (publish on `ql:control`, rate-limited 1/10s),
  failure-bias plumbed into worker `simulate.py`, destroyed-vs-scaled-down marking on
  containers. Integration test: destroy command kills a container and the in-flight
  job recovers via the reaper.
- **Verification:** `POST /api/chaos/destroy-worker` → container killed, lease lapses,
  reaper requeues job, autoscaler may replace; inject-failures biases outcomes toward
  `failed`; rate limit returns 429.
- **Depends on:** Epic 11d.

## Epic 13 — Frontend foundation & style-guide primitives
- **Intent:** The Terminal CLI frontend shell with design tokens and the primitive
  component set, before any live wiring.
- **Scope:** `frontend/` Vite + React + TS + Tailwind; tokens mapped 1:1 from the
  style guide into Tailwind theme (CSS custom properties, no hardcoded hex);
  primitives `<Pane>`, `<Prompt>`, `<BracketButton>`, `<StatusBadge>`, `<AsciiBar>`,
  `<Sparkline>`, `<Counter>`, `<FeedLine>`, `<WorkerCell>`; scanline/effect layer;
  `prefers-reduced-motion` support. Every element carries a unique `id` per CLAUDE.md.
  Vitest unit tests for primitives.
- **Verification:** `vite build` succeeds; Storybook/dev page renders each primitive
  in dark theme; Vitest green; reduced-motion respected; ids present.
- **Depends on:** Epic 1 (can proceed in parallel with backend epics).

## Epic 14 — Live state hook & dashboard panes
- **Intent:** The live multiplayer dashboard — connect the WS, reduce deltas, and
  render the panes that make the mechanics visible.
- **Scope:** `frontend/src/hooks/` (`useLiveState` WS hook, `useSession`,
  `useSubmitJobs`), `frontend/src/lib/` (ws + api clients, formatting),
  `frontend/src/panes/` (QueueDepthPane, WorkersPane with grid + scale/destroy
  controls, SubmitPane CLI form, FeedPane, MetricsPane); `aria-live="polite"` on feed
  and counters; ids + ARIA throughout. Vitest for the reducer; component tests for
  panes.
- **Verification:** Against the running backend: dashboard connects, guest handle
  assigned, submit a batch → counts/feed/grid update live; destroy a worker → grid
  shows recovery; Vitest reducer tests green.
- **Depends on:** Epic 12, Epic 13.

## Epic 15 — In-context architecture content & endpoint
- **Intent:** Surface the explanatory architecture notes where the visitor is looking.
- **Scope:** `GET /api/architecture` (content served to UI), ArchitecturePane in the
  frontend rendering the in-context explanations against live panes. Light tests for
  endpoint shape and pane render.
- **Verification:** Architecture pane renders explanatory copy tied to the relevant
  panes; endpoint returns expected content; ids present.
- **Depends on:** Epic 14.

## Epic 16 — Explainer pages (How It Works & How I Work)
- **Intent:** Two static, narrative explainer pages that earn credibility for the
  product and the builder, per §5.11.
- **Scope:** Routing for `/how-it-works` and `/how-i-work`; static narrative content
  (section order chosen to land each payoff — scaling story / review-loop +
  git-history proof point); Terminal CLI styling; header links; ids + ARIA;
  reduced-motion. No WebSocket state. Vitest/Playwright smoke for navigation.
- **Verification:** Both pages reachable from the header, render the narrative in the
  Terminal CLI system, contain the closing payoff sections; ids present.
- **Depends on:** Epic 13.

## Epic 17 — Test suites wired into CI
- **Intent:** Portfolio-grade, gated test coverage across the stack.
- **Scope:** Consolidate/round out Pytest unit + integration (queue, retry,
  autoscaler policy, guardrails, real Redis/Postgres), Vitest (reducers/primitives),
  Playwright narrative E2E (submit → break → recover → scale); CI workflow running all
  gates with ephemeral Redis/Postgres services.
- **Verification:** CI runs green on all three suites; Playwright drives the full
  narrative against a Compose stack.
- **Depends on:** Epic 14 (and exercises Epics 3–12 backends).

## Epic 18 — Infrastructure (Terraform `/infra`)
- **Intent:** Cheap, fully automated single-EC2 AWS provisioning as IaC.
- **Scope:** `infra/` Terraform: VPC + subnet + security group (80/443), single EC2 +
  Elastic IP, EBS data volume, ECR repos (api, autoscaler, worker, frontend), IAM
  roles (instance profile: ECR pull + SSM + CodeDeploy agent; pipeline roles),
  CodeStar GitHub connection, CodePipeline + CodeBuild + CodeDeploy, Route53 A record
  → EIP.
- **Verification:** `terraform validate` + `terraform plan` succeed against the target
  account; resources match §5.13. (Apply gated/manual.)
- **Depends on:** Epic 1.

## Epic 19 — Deploy plumbing & first live deploy
- **Intent:** The CI/CD shipping path and TLS, then the first live deployment of the
  end-to-end narrative.
- **Scope:** `buildspec.yml` (build images, push to ECR, build React bundle),
  `appspec.yml` + lifecycle scripts (`compose pull && up -d`, Alembic migrate, reload
  Nginx), Nginx config (TLS termination, HTTP + `/ws` upgrade, static bundle), certbot
  issuance/renewal; first deploy: point Route53 A → EIP, issue certs, smoke-test the
  live submit → break → recover → scale narrative.
- **Verification:** Push to `main` → CodePipeline builds/pushes → CodeDeploy runs
  hooks; site serves over HTTPS; WS connects; live narrative works end to end.
- **Depends on:** Epic 17, Epic 18.
