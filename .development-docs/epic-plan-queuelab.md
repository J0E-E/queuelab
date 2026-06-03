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

## Epic 6 — Guardrails: rate limiting & validation
- **Intent:** Per-session token-bucket rate limiting and reusable validation/cap
  enforcement, surfaced in the system voice.
- **Scope:** `backend/app/services/rate_limit.py` (Redis token bucket: 1 submit/5s,
  1 chaos/10s), shared validation helpers (caps, capacity), error shaping
  (`[ERR]`/`[WARN]` messages, `429` + `Retry-After`, `409` at capacity). Unit +
  integration tests (real Redis) for bucket refill and limit responses.
- **Verification:** Pytest: bucket allows/denies on schedule; over-cap and
  at-capacity produce 422/429/409 with correct messages.
- **Depends on:** Epic 5.

## Epic 7 — Job submission & job-records endpoints
- **Intent:** Submit a validated batch into the queue and read back durable job
  records — the producer side of the core flow.
- **Scope:** `backend/app/services/submission.py` (validate caps/rate/capacity, write
  job rows to Postgres, enqueue to `ql:queue:ready`), `POST /api/jobs`,
  `GET /api/jobs?session=&state=` (paged). Integration tests (real Redis + Postgres).
- **Verification:** `POST /api/jobs` returns `201 {batch_id, accepted}`, rows appear
  in Postgres, IDs land on `ql:queue:ready`; over-limit paths return 422/429/409;
  `GET /api/jobs` pages records.
- **Depends on:** Epic 6.

## Epic 8 — Worker image & simulated work
- **Intent:** A genuine container worker that claims jobs and runs simulated work —
  the consumer side of the core flow.
- **Scope:** `worker/worker.py` (claim loop: BLMOVE-claim → run → ack/nack,
  heartbeat, register in `ql:workers`, graceful SIGTERM requeue vs hard SIGKILL),
  `worker/simulate.py` (per-type duration + failure profiles), `worker/Dockerfile`
  (vendors `backend/app/queue`). Unit tests for simulate profiles; integration test:
  worker drains a submitted batch through real Redis.
- **Verification:** Build worker image; run a container against compose Redis with a
  seeded batch → counts move queued→running→completed/failed; SIGTERM requeues
  in-flight job; Pytest for simulate duration/failure math.
- **Depends on:** Epic 7.

## Epic 9 — Reaper (delayed promotion & lease recovery)
- **Intent:** The chaos-recovery path — promote due delayed jobs and requeue jobs
  whose lease lapsed (dead worker), making "destroy a worker → job retried" real.
- **Scope:** Reaper background loop in the api process: move `ql:queue:delayed` →
  `ready` when due; scan `ql:leases` for past-deadline entries and requeue
  (respecting `max_retries`). Integration tests (real Redis): expired lease requeues;
  exhausted retries go terminal `failed`.
- **Verification:** Pytest integration: a job whose lease deadline passes is requeued
  as `retrying`; after `max_retries` it becomes `failed`; delayed jobs promote on
  schedule.
- **Depends on:** Epic 8.

## Epic 10 — Durable-writer & real-time broadcaster
- **Intent:** Decouple producers from the socket: persist final outcomes and fan
  state changes out to WebSocket clients.
- **Scope:** `backend/app/realtime/broadcaster.py` (Redis pub/sub → WS fan-out),
  `backend/app/realtime/ws.py` (connection manager, snapshot-on-connect), `WS /ws`
  endpoint, durable-writer subscriber (state-change events → Postgres outcome
  updates), throttled metrics tick, `GET /api/metrics`,
  `backend/app/services/metrics.py`, `backend/app/services/activity_feed.py`.
  Integration tests for snapshot + delta protocol and durable-writer persistence.
- **Verification:** Connect to `/ws` → receive snapshot then deltas as a batch runs;
  metrics snapshot matches counts; completed jobs get durable `finished_at`/duration
  in Postgres; Pytest covers fan-out and snapshot-on-connect.
- **Depends on:** Epic 9.

## Epic 11 — Autoscaler (control loop & Docker control)
- **Intent:** A separate long-lived process that scales worker containers by manual
  and queue-depth strategies, records scaling events, and replaces unhealthy workers.
- **Scope:** `backend/app/autoscaler_main.py` entrypoint,
  `backend/app/services/autoscaler.py` (control loop ~1–2s: manual + queue-depth
  strategies, guardrail caps, idle scale-down), `backend/app/services/docker_control.py`
  (Docker SDK over `/var/run/docker.sock`), `ql:control` channel consumer, scaling
  events to Postgres + feed, config endpoints `GET/PUT /api/config`. Unit tests for
  scaling policy math; integration test for control-channel commands.
- **Verification:** Flood queue → autoscaler spawns workers up to cap; idle past
  `idle_timeout` → scale down to `min_workers`; each step writes a scaling_event +
  feed line; Pytest for threshold/idle policy decisions.
- **Depends on:** Epic 10.

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
- **Depends on:** Epic 11.

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
