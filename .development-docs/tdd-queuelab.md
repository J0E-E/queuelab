# QueueLab — Technical Design Document

## 1. Summary

QueueLab is a live, multiplayer distributed job-processing lab: visitors submit
configurable background jobs, watch them flow through a real Redis-backed queue, break
the system on purpose (destroy workers, inject failures), and watch it retry, recover,
and autoscale — all on one shared, global, live instance. This TDD specifies a
**FastAPI** backend exposing REST + a **WebSocket** real-time channel, a **custom
Redis-primitive job queue** with real worker-claiming semantics, **Docker
container-per-worker** workers managed by an autoscaler via the Docker socket, durable
records in **Postgres** with hot live state in **Redis**, a **Vite + React +
TypeScript + Tailwind** terminal-CLI dashboard, and a **single AWS EC2** deployment
provisioned with **Terraform** and shipped by a **CodePipeline + ECR + CodeDeploy**
pipeline triggered on GitHub pushes. The mechanics are real (genuine separate
processes/containers, real queue claiming, real retries); only the work each job
performs is simulated (complexity-scaled sleep + failure).

## 2. Business Requirements

Lifted from [QueueLab_BRD.md](QueueLab_BRD.md):

- **Shared live instance.** One global system all visitors observe and interact with
  simultaneously; no per-user sandbox. Multiplayer must be visibly apparent.
- **Anonymous ephemeral identity.** Per-session handle + color (e.g. `guest-amber`),
  no login, used purely for attribution in the activity feed.
- **Job submission** with configurable Job Count, Complexity, Maximum Retries, Retry
  Delay, and Job Type (Email, Report Generation, Image Processing, Webhook Delivery).
- **Real-time monitoring dashboard** of job state counts/flow: queued, running,
  completed, failed, retrying.
- **Worker scaling controls:** Min/Max Workers, Scale-Up/Scale-Down Thresholds, Idle
  Timeout, Scaling Strategy (Manual | Queue Depth).
- **Chaos controls:** destroy a worker (in-flight job is retried, autoscaler may
  replace it); inject failures (bias jobs toward failure).
- **Live activity feed** attributing actions to handles in real time.
- **Job validation:** a verifiable record of outcomes, not just moving numbers.
- **Real processes, simulated work.** Workers are genuine separate processes competing
  for jobs from a real queue; each job sleeps for a complexity-scaled duration and
  fails at a complexity-scaled rate. No real side effects.
- **Autoscaling service** monitoring queue depth, active jobs, worker count, average
  job duration, worker health; adds/removes workers; records scaling events; enforces
  guardrails.
- **Observability:** queue depth, running jobs, failed jobs, retry rate, average job
  duration, worker count (visual grid: offline/running/broken), scaling events.
- **Guardrails:** caps (jobs/submission, total queued, max workers), per-session rate
  limiting, auto-reset/drain toward a clean baseline, graceful saturation (clear
  rejection at capacity, not degradation).
- **In-context architecture explanations** rendered where the visitor is looking.
- **Publicly deployed and accessible**, pragmatic and cheap.

## 3. Goals / Non-Goals

**Goals**

- Real distributed mechanics: a real queue with real claiming, real separate worker
  containers, real retries, real autoscaling driven by live queue depth.
- A real-time terminal-CLI dashboard that makes the invisible mechanics visible within
  ~60 seconds, following the narrative submit → break → recover → scale.
- A coherent shared multiplayer experience with anonymous attribution and guardrails.
- A durable, verifiable record of job outcomes and scaling events.
- A fully automated, cheap AWS deployment (Terraform + CodePipeline) on a single EC2.
- In-context architecture/tradeoff explanations surfaced in the UI.
- Portfolio-grade test coverage (Pytest, Vitest, Playwright).

**Non-Goals**

- No real job side effects (no real emails/images/webhooks).
- No multi-region, HA, or strong durability guarantees.
- No user accounts, login, or persistence of personal history.
- No horizontal scaling of the backend itself (single instance is acceptable).
- No managed AWS data stores (RDS/ElastiCache) — Postgres/Redis run as local
  containers on the instance (cost decision, §6).

## 4. Current State

Greenfield repository. Only documentation exists today:

- [QueueLab_BRD.md](QueueLab_BRD.md) — the business requirements (source of §2).
- [ui-ux-style-guide.md](ui-ux-style-guide.md) — the binding **Terminal CLI** design
  system: dark-only multi-phosphor palette, `JetBrains Mono`, `0px` radius, ASCII
  panes, raw ASCII data-viz (`[||||||||..]`, sparklines, worker grid), restrained
  reduced-motion-aware effects, and a primitive component set (`<Pane>`, `<Prompt>`,
  `<BracketButton>`, `<StatusBadge>`, `<AsciiBar>`, `<Sparkline>`, `<Counter>`,
  `<FeedLine>`, `<WorkerCell>`).
- [design-prompt.md](design-prompt.md) — the upstream design-system brief.
- [.claude/CLAUDE.md](.claude/CLAUDE.md) — **binding project rules**: every rendered
  HTML element must carry a unique descriptive `id`; prefer many small focused React
  components; descriptive non-abbreviated names; natural-language naming over jargon;
  boolean names read as yes/no (`is`/`has`/`can`/`should`/`did`); consult the style
  guide before any UI change.

No source, build config, package manifests, or infrastructure exist yet — this design
starts from zero and is unconstrained except by the documents above.

## 5. Proposed Design

### 5.1 High-level approach

A monorepo with four services composed by Docker Compose, fronted by Nginx for TLS:

```txt
                 Route53 (A → EIP)
                        |
                   Nginx + certbot         (TLS termination, HTTP+WS reverse proxy)
                        |
   ┌────────────────────┴───────────────────────────────────────────┐
   |                         single EC2 instance (Docker)             |
   |                                                                  |
   |  React static (served by Nginx)                                  |
   |                                                                  |
   |  FastAPI api  ──REST──  submit / config / chaos / metrics / docs |
   |      │        ──WS────  /ws live state + activity feed           |
   |      │                                                           |
   |      ├── Postgres (durable: job records, scaling events)         |
   |      └── Redis (queue, hot live state, pub/sub, rate limits)     |
   |                                                                  |
   |  Autoscaler service ── Docker socket ──▶ spawn/kill worker       |
   |      │  (watches queue depth + worker health)        containers  |
   |      │                                                           |
   |  Worker container ×N  ── claim & run simulated jobs from Redis ──┤
   |      (siblings via /var/run/docker.sock)                         |
   └──────────────────────────────────────────────────────────────────┘
```

The `api`, `autoscaler`, Postgres, Redis, and Nginx are long-lived Compose services.
**Worker containers are NOT in the Compose file** — they are created and destroyed at
runtime by the autoscaler through the mounted Docker socket, so scaling and chaos are
genuinely visible as containers appearing and disappearing.

### 5.2 Components / modules

**Monorepo layout** (`/backend /frontend /worker /infra`):

```txt
queuelab/
  backend/                FastAPI app (api + autoscaler entrypoints)
    app/
      main.py             FastAPI app, routers, WS endpoint, lifespan
      config.py           settings (env-driven: guardrails, TTLs, thresholds)
      queue/              the custom Redis queue (shared protocol)
        protocol.py       key names, payload schema, state machine
        client.py         enqueue/claim/ack/nack/requeue (Lua-script wrappers)
        scripts/          atomic Lua scripts (claim, reap, ack)
      models/             Pydantic DTOs + SQLAlchemy ORM (jobs, scaling_events)
      services/
        submission.py     validate + enqueue a batch
        chaos.py          destroy-worker / inject-failure
        metrics.py        aggregate live metrics snapshot
        autoscaler.py     queue-depth scaling loop + Docker control
        docker_control.py thin wrapper over the Docker SDK
        identity.py       ephemeral guest handle + color assignment
        rate_limit.py     per-session token-bucket on Redis
        activity_feed.py  append + publish feed events
      realtime/
        broadcaster.py    Redis pub/sub → WebSocket fan-out
        ws.py             connection manager, snapshot-on-connect
      db/                 engine, session, migrations (Alembic)
      autoscaler_main.py  separate process entrypoint for the autoscaler
    tests/                pytest (unit + integration w/ real Redis + Postgres)
  worker/
    worker.py             claim loop: claim → run simulated job → ack/nack
    simulate.py           per-type duration + failure profiles
    Dockerfile            the image the autoscaler launches
  frontend/
    src/
      components/         primitives from the style guide (§13 of style guide)
      panes/              QueueDepthPane, WorkersPane, SubmitPane, FeedPane, ...
      hooks/              useLiveState (WS), useSession, useSubmitJobs
      lib/                ws client, api client, formatting
      theme/              tokens → Tailwind config (CSS custom properties)
    index.html
  infra/                  Terraform (VPC, EC2, EIP, ECR, CodePipeline, Route53, IAM)
  docker-compose.yml      api, autoscaler, postgres, redis, nginx
  appspec.yml             CodeDeploy lifecycle hooks
  buildspec.yml           CodeBuild build/push to ECR
```

> Per the user's "plain monorepo" choice, the queue protocol is **not** split into a
> separately published package. `worker/` imports the queue protocol from `backend`
> via a small copied/vendored module (the `worker` Dockerfile copies `backend/app/queue`
> in). The protocol (key names, payload shape, Lua scripts) is the single source of
> truth to prevent drift between producer (api) and consumer (worker).

### 5.3 The custom Redis queue (the core mechanic)

State machine per job: `queued → running → (completed | failed | retrying → queued)`.

Redis structures:

- `ql:queue:ready` — a **List** of job IDs (FIFO). Producers `LPUSH`; workers claim.
- `ql:queue:delayed` — a **Sorted Set** scored by "ready-at" epoch ms, for retry
  backoff. A reaper moves due jobs back to `ready`.
- `ql:job:{id}` — a **Hash** with the full job payload + state + attempt counters.
- `ql:processing:{worker_id}` — a **List** holding the single job a worker is
  currently running (its in-flight claim), enabling crash recovery.
- `ql:leases` — a **Sorted Set** of in-flight job IDs scored by lease deadline (epoch
  ms): the **visibility timeout**. The reaper finds entries past their deadline to
  detect a dead worker's job and requeue it. (A TTL key can't be enumerated once it
  expires, so leases are tracked here explicitly rather than as per-job TTL keys.)
- `ql:counts` — a Hash of live state counts (queued/running/completed/failed/retrying)
  for O(1) dashboard reads.

**Claiming** uses `BLMOVE ql:queue:ready ql:processing:{worker_id} RIGHT LEFT` (blocking
pop + atomic move into the worker's processing list), then a Lua script sets the job
to `running`, stamps `started_at`, and adds the job to `ql:leases` scored
`now + visibility_timeout`. This is the
real, explainable claiming mechanic the lab exists to show — atomic, at-least-once,
with a visibility timeout.

**Acknowledge (success):** a Lua script removes the job from `ql:processing:{worker}`,
removes it from `ql:leases`, sets state `completed`, decrements `running`/increments
`completed`, sets a **1h Redis TTL** on `ql:job:{id}`, and publishes a state-change
event carrying the final timing. A single **durable-writer** (api-side, subscribed to
state-change events) persists the outcome to Postgres — the worker stays lean and never
touches the DB (it vendors only the queue protocol).

**Negative-ack (failure):** Lua script increments `attempts`. If `attempts <= max_retries`,
state → `retrying`, job re-added to `ql:queue:delayed` with score `now + retry_delay`;
else state → `failed` (terminal). Either path removes the processing entry and the
`ql:leases` entry, then publishes the change.

**Reaper / lease recovery (how chaos recovers):** a background loop in the api process
(a) moves due jobs from `delayed` to `ready`; (b) re-queues jobs whose `ql:leases`
deadline has passed — when a worker is destroyed mid-job, its lease deadline lapses, the
job is treated as a failed attempt and re-queued (respecting `max_retries`). This is what makes "destroy a worker
→ job is retried" real rather than animated.

### 5.4 Workers & simulated work

- A worker is a **Docker container** running `worker.py`, launched by the autoscaler
  with a unique `worker_id`. It registers itself in `ql:workers` (a Hash:
  `worker_id → {state, current_job, last_heartbeat}`) and emits a heartbeat.
- Claim loop: claim one job → look up its type/complexity → `simulate.py` sleeps
  `base_duration[type] * complexity` (with jitter) and fails with probability
  `base_failure_rate[type] * complexity` (plus any global inject-failure bias) → ack or
  nack. Concurrency = one job per worker (so the worker grid maps 1:1 to in-flight jobs
  and the mechanics stay legible).
- Graceful shutdown (SIGTERM) nacks/requeues the in-flight job; **hard destroy**
  (SIGKILL via Docker) does not — that path exercises the lease-expiry reaper, which is
  the more impressive chaos demo.

### 5.5 Autoscaler

A separate long-lived process (`autoscaler_main.py`) running a control loop (~1–2s):

- Reads queue depth, running count, worker count, avg duration, and worker
  heartbeats/health from Redis.
- **Manual strategy:** drives toward the target worker count the user set.
- **Queue-depth strategy:** if `queue_depth / max(worker_count,1) > scale_up_threshold`
  → add a worker (up to `max_workers` / guardrail cap of 10); if a worker has been idle
  beyond `idle_timeout` and depth is below `scale_down_threshold` → remove it (down to
  `min_workers`).
- Adds/removes workers by calling the **Docker SDK** (`docker_control.py`) against the
  mounted `/var/run/docker.sock` to run/stop sibling worker containers from the
  `worker` image.
- The api never touches the Docker socket; chaos (`destroy-worker`) and manual-scale
  requests reach the autoscaler over a Redis **control channel** (`ql:control`), and
  only the autoscaler acts on them.
- Detects dead/unhealthy workers (missed heartbeats) and may replace them.
- Records every action as a **scaling event** in Postgres and publishes it to the feed.
- Marks containers it kills as "destroyed (chaos)" vs "scaled-down" so the worker grid
  can color them correctly.

### 5.6 Real-time layer

- **Transport: WebSocket** at `/ws`. On connect the server sends a full **snapshot**
  (counts, workers, recent feed, config) so a late joiner is immediately consistent;
  thereafter it streams deltas.
- **Broadcaster:** all state mutations (job state changes, scaling events, feed lines)
  are published to Redis **pub/sub** channels by whichever process caused them (api,
  worker, autoscaler). The api's broadcaster subscribes and fans messages out to all
  connected WebSocket clients. This decouples producers from the socket layer and works
  across the separate processes/containers.
- Client actions (submit, chaos, config) go over **REST** (simpler validation,
  rate-limit headers, idempotency keys); only live state flows back over the socket.
- A periodic throttled "metrics tick" (counts + sparkline sample) is published so
  derived metrics (retry rate, avg duration, queue-depth sparkline) update smoothly
  without a message per job.

### 5.7 Data model

**Redis** (live/hot, §5.3) — ephemeral, all keys carry a **1h TTL** where applicable.

**Postgres** (durable record):

```sql
-- jobs: the verifiable outcome record
job (
  id            uuid primary key,
  session_id    text not null,            -- ephemeral guest handle owner
  guest_handle  text not null,
  type          text not null,            -- email|report|image|webhook
  complexity    smallint not null,        -- 1..5
  max_retries   smallint not null,
  retry_delay_ms integer not null,
  state         text not null,            -- queued|running|completed|failed|retrying
  attempts      smallint not null default 0,
  worker_id     text,
  submitted_at  timestamptz not null,
  started_at    timestamptz,
  finished_at   timestamptz,
  duration_ms   integer
)
-- index on (submitted_at), (state) for metrics + pruning

scaling_event (
  id           bigserial primary key,
  at           timestamptz not null,
  action       text not null,             -- scale_up|scale_down|destroy|replace|manual
  worker_id    text,
  reason       text,                       -- e.g. "queue_depth 142 > threshold"
  worker_count_after smallint not null
)
-- index on (at) for feed + pruning
```

Migrations via **Alembic**. A periodic **prune** job deletes `job` rows with
`finished_at < now() - 24h` and `scaling_event` rows older than 24h (retention
decision §6) so the DB stays bounded on a small instance.

### 5.8 API surface (REST + WS)

```txt
POST /api/session                 → { session_id, guest_handle, color }   (ephemeral)
POST /api/jobs                    → submit batch
       body { count, type, complexity, max_retries, retry_delay_ms }
       201 { batch_id, accepted } | 422 validation | 429 rate-limited
                                     | 409 at-capacity (graceful saturation)
GET  /api/metrics                 → current metrics snapshot (also pushed via WS)
GET  /api/jobs?session=&state=    → paged job records (job validation)
GET  /api/config                  → autoscaler config
PUT  /api/config                  → update Min/Max/thresholds/idle/strategy
POST /api/chaos/destroy-worker    → { worker_id? }  (random if omitted)  429-limited
POST /api/chaos/inject-failures   → { enabled, bias }                    429-limited
GET  /api/architecture            → in-context explanation content (served to UI)
WS   /ws                          → snapshot then deltas:
       {type:"snapshot"|"counts"|"job"|"worker"|"scaling"|"feed"|"saturation", ...}
```

All write endpoints accept an idempotency key header and enforce per-session rate
limits (§5.9). Validation errors are returned in the system voice the UI renders
(`[ERR] --count exceeds cap (max 100)`).

### 5.9 Guardrails (concrete)

- **Caps:** ≤ **100 jobs/submission**, ≤ **1000 total queued** system-wide, ≤ **10**
  worker containers.
- **Rate limits (per session, token bucket in Redis):** **1 submission / 5s**,
  **1 chaos action / 10s**. Exceeding → `429` with a `Retry-After`, surfaced as
  `[WARN] rate limit ...`.
- **Graceful saturation:** at the queued cap, `POST /api/jobs` returns `409` with a
  clear `[ERR] queue at capacity` rather than partially accepting; the UI shows a
  `[ DRAINING ]`/`[ AT CAPACITY ]` pane state.
- **Auto-reset / drain:** idle workers scale down to `min_workers`; completed/failed
  jobs age out of Redis at 1h and are pruned from Postgres at 24h, so the system trends
  back to a clean baseline.

### 5.10 Frontend

- Vite + React + TypeScript + Tailwind, dark-only, tokens mapped 1:1 from the style
  guide into the Tailwind theme (CSS custom properties; no hardcoded hex).
- Panes (tmux-split layout): **Queue Depth**, **Workers** (the worker grid + scale /
  destroy controls), **Submit Jobs** (CLI-style faux command form), **Activity Feed**,
  **Metrics/Observability**, **Architecture** (in-context explanations).
- A single `useLiveState` hook owns the WebSocket connection, applies the snapshot, and
  reduces deltas into client state; counters/bars/sparklines/worker grid read from it.
- Every rendered element gets a unique descriptive `id`; `aria-live="polite"` on the
  feed and live counters; full `prefers-reduced-motion` support; built from small
  focused primitives per CLAUDE.md and the style guide.
- **Routing:** the live dashboard is the primary route (`/`); two standalone, static
  **explainer pages** (`/how-it-works`, `/how-i-work`, §5.11) are reachable from the
  site header. These are content pages, not live panes — they share the Terminal CLI
  visual system but carry no WebSocket state.

### 5.11 Explainer pages — How It Works & How I Work

The site has two matched explainer pages: **How It Works** (how the *system* works) and
**How I Work** (how *you*, the builder, work). They are a deliberate pair — one earns
technical credibility for the **product**, the other for the **person** who built it.

**Shared characteristics**

- **Static and information-dense**, written for a **technical visitor**. No live state,
  no WebSocket — pure content baked into the frontend bundle (distinct from the
  dashboard's `/api/architecture` in-context notes, which annotate live panes).
- Each page is a **linear narrative with a payoff**, not a feature list. The reader is
  carried from premise to a single landing point.
- Both follow the **Terminal CLI** design system (multi-phosphor palette,
  `JetBrains Mono`, ASCII panes/dividers, reduced-motion-aware). Every rendered element
  carries a unique descriptive `id` per CLAUDE.md; headings/sections/paragraphs/lists
  all included.

**Section order is the argument.** Each page is structured so the *order of sections* is
itself the persuasive case — when (re)building a page, decide the section order by the
**point you want to land**, then arrange the narrative to climax there.

**How It Works** — argues *"this looks simple but is built to scale."* The narrative
walks from the visible, simple surface (submit a job, watch it run) down through the
real mechanics (custom Redis queue, claiming + visibility timeout, retries/recovery,
container-per-worker, autoscaling) and **ends on the scaling story** — that is the
payoff the page lands.

**How I Work** — argues *"the value is design and review, not code generation."* The
narrative **climaxes at the review-loop** (how work is scoped, designed, generated, and
critically reviewed), then **closes on a proof point: this site itself is the receipts —
check the git history.** The last section points the visitor at the repo's commit
history as evidence of the process the page describes.

### 5.12 Primary flows (sequences)

**Submit batch:** `POST /api/jobs` → api validates (caps/rate/capacity), writes job rows
(Postgres), enqueues to `ql:queue:ready` (Redis), publishes `feed` ("guest-amber +50")
and `counts` → workers `BLMOVE`-claim → run sim → ack → `counts`/`job` deltas + durable
record. Counters tick live throughout.

**Destroy worker (chaos):** `POST /api/chaos/destroy-worker` → api rate-checks and
publishes a destroy command on `ql:control` → autoscaler (sole Docker-socket holder)
`kill`s the container → in-flight job's lease lapses → reaper requeues it (`retrying`)
→ queue-depth policy may spawn a replacement → feed: `destroyed worker-3`, `scale-up +1`,
`worker-4 online`.

**Autoscale under load:** rising `ready` depth crosses `scale_up_threshold` → autoscaler
runs a worker (`[·]` spawning → `[R]` running) → depth drains → idle workers pass
`idle_timeout` → scaled down → each step a `scaling_event` + feed line.

### 5.13 Deployment & CI/CD (AWS)

- **Terraform (`/infra`)** provisions: VPC + subnet + security group (80/443 in),
  **single EC2** instance with an **Elastic IP**, an **EBS** data volume for
  Postgres/Redis persistence, **ECR** repositories (api, autoscaler, worker, frontend
  build), **IAM** roles (EC2 instance profile w/ ECR pull + SSM + CodeDeploy agent;
  pipeline roles), **CodePipeline + CodeBuild + CodeDeploy**, a **CodeStar GitHub
  connection** (trigger on push to `main`), and the **Route53 A record → EIP**.
- **Pipeline:** GitHub push → CodePipeline → **CodeBuild** (`buildspec.yml`: build
  images, push to ECR, build the React static bundle) → **CodeDeploy** (agent on the
  EC2 instance runs `appspec.yml` hooks: `docker compose pull && docker compose up -d`,
  run Alembic migrations, reload Nginx).
- **TLS:** **Nginx + certbot** on the instance terminates HTTPS for the Route53 domain
  (Let's Encrypt, auto-renew) and reverse-proxies HTTP + the `/ws` WebSocket upgrade to
  the api container; serves the React static bundle.
- **Worker control:** the autoscaler container mounts `/var/run/docker.sock` to run/kill
  sibling worker containers from the ECR `worker` image on the host daemon.

## 6. Decisions

| # | Decision | Chosen | Alternatives considered | Rationale |
|---|----------|--------|--------------------------|-----------|
| 1 | Backend framework | **FastAPI** | Flask; Django + Channels | Async-native, first-class WS + SSE, Pydantic + auto OpenAPI; best fit for a live real-time API and impressive to reviewers. |
| 2 | Frontend stack | **Vite + React + TS + Tailwind** | Next.js; Vite + plain CSS | App is a client-side live dashboard with no SSR/SEO need; Vite SPA is cheap to host as static files; Tailwind maps the design tokens directly. |
| 3 | Real-time transport | **WebSocket** | SSE; polling | Full-duplex, lowest latency, naturally multiplayer; most impressive for a "live system" and standard in FastAPI. |
| 4 | Queue mechanics | **Custom queue on Redis primitives** | Arq; RQ / Dramatiq | Maximum teaching value — claiming, visibility timeout, retries, recovery are real and explainable in-context, which is the point of the lab. |
| 5 | Worker model | **Container-per-worker via Docker API** | Subprocesses; async tasks | User-selected; most production-like, genuinely separate containers; scaling/chaos visible as containers appearing/disappearing. |
| 6 | Container control | **Sibling containers via mounted Docker socket** | Docker-in-Docker | Standard single-host pattern; real separate containers without DinD overhead/fiddliness on a trusted EC2. |
| 7 | Deployment target | **Single AWS EC2 + EIP, Terraform, CodePipeline from GitHub** | Fly.io; Railway; Render; Compose-only | User-owned AWS account + existing Route53 domain; wants a fully automated IaC + pipeline showcase. |
| 8 | Deploy mechanism | **ECR + CodeDeploy agent on EC2** | ECR + SSM Run Command; instance self-pull | AWS-native, visible in console, supports gated/rollback lifecycle hooks (`appspec.yml`). |
| 9 | TLS / reverse proxy | **Nginx + certbot** | Caddy auto-TLS; ALB + ACM | User-selected; familiar/flexible, no ALB cost, free Let's Encrypt certs, proxies HTTP + WS on the single instance. |
| 10 | Data stores | **Postgres + Redis as containers on the EC2 host** | RDS + ElastiCache; RDS + Redis container | Cheapest, self-contained, matches single-EC2 intent; data on an EBS volume; managed stores are heavier/cost more than a portfolio lab needs. |
| 11 | Persistence roles & retention | **Postgres durable record + Redis live state, auto-age (Redis 1h TTL, prune Postgres > 24h)** | Redis-only; Postgres-for-everything | Matches BRD; keeps the verifiable outcome record while bounding growth on a small instance. |
| 12 | Caps | **100 jobs/submit, 1000 queued, 10 workers** | 50/500/6; 200/2000/16 | Sane for a small EC2 + Docker daemon; matches the style guide's `max 100` example; still dramatic to watch scale. |
| 13 | Rate limits | **1 submit / 5s, 1 chaos / 10s** | 1/3s & 1/5s; 1/1s & 1/2s | User-selected (most protective); guards the budget and keeps the shared feed legible under multiplayer load. |
| 14 | Repo structure | **Monorepo: `/backend /frontend /worker /infra`** | Monorepo + shared package; separate repos | Simplest for one author + one pipeline; queue protocol kept single-source and vendored into the worker image to avoid drift. |
| 15 | Testing | **Pytest (unit+integration) + Vitest + Playwright** | Backend-only; light smoke only | Broad, portfolio-grade: real-Redis/Postgres integration for queue/retry/autoscaler, Vitest for React units, Playwright for the core narrative. |

## 7. Risks and Open Questions

- **Docker socket = host control.** Mounting `/var/run/docker.sock` grants the
  autoscaler effective host root. Acceptable on a single trusted instance; mitigate by
  running only first-party images, capping worker count (10), and not exposing the
  socket beyond the autoscaler container.
- **Single instance = single point of failure** and limited capacity. Explicitly a
  non-goal to solve (no HA); guardrails + saturation keep a small instance coherent.
- **Container spawn latency.** Starting a worker container is slower than a subprocess;
  scaling may look laggy. Mitigate by pre-pulling the worker image on the host and
  keeping `min_workers ≥ 1` warm.
- **At-least-once delivery.** The lease/visibility-timeout model can run a job twice
  (worker dies after finishing, before ack). Acceptable for simulated work; document it
  as an intentional, explained tradeoff in the in-context architecture notes.
- **Rate limits feel slow (1/5s, 1/10s)** for a solo evaluator. If the demo feels
  sluggish, revisit; these are env-configurable, not hardcoded.
- **certbot on a single host** needs the domain pointed at the EIP before issuance and
  port 80 reachable for the HTTP-01 challenge; renewal must be wired (cron/systemd
  timer or certbot container).
- **EBS persistence + redeploys.** Ensure Postgres/Redis volumes survive
  `docker compose up` and instance reboots; document backup expectations (none beyond
  the EBS volume — durability is a non-goal).
- **Open:** exact per-type duration/failure profiles (tunable constants); the source of
  truth for *average job duration* (rolling Redis stat vs Postgres aggregate);
  metrics-tick cadence vs per-event deltas balance.

## 8. Rollout / Verification

**Local (Docker Compose) verification — the narrative end to end:**

1. `docker compose up` brings up api, autoscaler, Postgres, Redis, Nginx; build the
   worker image so the autoscaler can launch it.
2. Open the dashboard → confirm WS connects, a guest handle/color is assigned, panes
   render with honest empty/idle states.
3. Submit a batch → watch counts move queued→running→completed/failed; verify durable
   rows in Postgres and the feed line.
4. Destroy a worker mid-job → confirm the in-flight job is retried (lease expiry), a
   replacement may spawn, and the queue drains.
5. Flip to queue-depth strategy and flood jobs → watch workers scale up; idle → scale
   down after `idle_timeout`; each step recorded as a scaling event.
6. Hit caps/rate limits/capacity → confirm `422`/`429`/`409` render in system voice.
7. Reduced-motion + accessibility pass; `aria-live` regions announce updates.

**Test gates:** Pytest unit (queue state machine, retry math, autoscaler policy,
guardrails) + integration (real Redis + Postgres: claim/ack/nack/reaper, end-to-end
submit→complete); Vitest for React reducers/primitives; Playwright for the submit →
break → recover → scale narrative.

**Rollout:** push to `main` → CodePipeline builds/pushes to ECR → CodeDeploy runs
`appspec.yml` (pull, migrate via Alembic, `compose up`, reload Nginx). First deploy
also: point Route53 A record at the EIP, then issue certs via certbot. No feature
flags needed (single greenfield instance); rollback by redeploying the prior ECR image
tags through CodeDeploy. No backwards-compatibility constraints (no existing data or
clients).

## 9. Work Breakdown

1. **Repo & tooling scaffold** — monorepo dirs, `docker-compose.yml`, base Dockerfiles,
   linting/formatting, env/config conventions.
2. **Custom Redis queue** — protocol (keys/payload/state machine), Lua scripts
   (claim/ack/nack/reap), client wrappers; unit + integration tests against real Redis.
3. **Postgres + models** — SQLAlchemy models, Alembic migrations, prune job; durable
   record writes.
4. **FastAPI core** — app skeleton, config/settings, session/identity, REST endpoints
   (submit, jobs, config, metrics), validation + guardrails (caps, rate limits,
   saturation).
5. **Worker image** — claim loop, per-type simulate profiles, heartbeats, graceful vs
   hard shutdown behavior.
6. **Autoscaler** — control loop, manual + queue-depth strategies, Docker SDK control
   (`docker_control.py`), worker health/replacement, scaling-event recording.
7. **Reaper** — delayed→ready promotion and lease-expiry recovery (the chaos-recovery
   path).
8. **Real-time layer** — Redis pub/sub broadcaster, WS endpoint, snapshot-on-connect,
   delta protocol, metrics tick.
9. **Chaos endpoints** — destroy-worker, inject-failures, wired to autoscaler/Docker +
   feed.
10. **Frontend foundation** — Vite/React/TS, Tailwind token mapping, the style-guide
    primitives (`<Pane>`, `<Prompt>`, `<BracketButton>`, `<StatusBadge>`, `<AsciiBar>`,
    `<Sparkline>`, `<Counter>`, `<FeedLine>`, `<WorkerCell>`), scanline/effect layer.
11. **Dashboard panes** — `useLiveState` WS hook; Queue Depth, Workers (grid + scale/
    destroy), Submit (CLI form), Activity Feed, Metrics, Architecture panes; ids + ARIA
    + reduced-motion.
12. **In-context architecture content** — the explanatory copy surfaced where relevant.
13. **Explainer pages** — `/how-it-works` and `/how-i-work` (§5.11): routing, static
    narrative content, Terminal CLI styling, ids + ARIA; section order chosen to land
    each page's payoff (scaling story / review-loop + git-history proof point).
14. **Tests** — Pytest unit+integration, Vitest, Playwright narrative E2E; wire into CI.
15. **Infrastructure (Terraform `/infra`)** — VPC/EC2/EIP/EBS, ECR, IAM, CodeStar GitHub
    connection, CodePipeline/CodeBuild/CodeDeploy, Route53 A record.
16. **Deploy plumbing** — `buildspec.yml`, `appspec.yml` + lifecycle scripts, Nginx
    config + certbot issuance/renewal, first deploy + smoke test of the live narrative.
