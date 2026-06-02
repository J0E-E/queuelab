# Business Requirements Document (BRD)

# Project: QueueLab

**An interactive distributed systems lab.**

QueueLab is a live, multiplayer distributed job-processing platform built to make
invisible backend concepts *visible and interactive*. Visitors submit configurable
background jobs, watch them flow through a real queue, deliberately break the system,
and observe how it retries, recovers, and scales workers in real time.

It is a working application first and a teaching instrument second: every concept it
demonstrates (queueing, retries, backpressure, autoscaling, chaos resilience) is
backed by real mechanics, not animations.

---

# Audience & Purpose

This is a **portfolio project**. Its job is to convince an evaluator — a recruiter,
hiring manager, or senior engineer spending a couple of minutes — that the author
can design, build, ship, and *explain* a non-trivial distributed system.

It is meant to prove three things:

1. **Distributed systems depth** — real queues, retries, backpressure, autoscaling,
   and chaos resilience, not a CRUD app in disguise.
2. **Full-stack polish** — a clean, real-time React experience sitting on top of a
   real backend.
3. **System-design communication** — the architecture and its tradeoffs are
   explained *in context*, where the visitor is looking, not buried in a README.

Production/DevOps maturity (real deployment, observability) is a supporting goal, not
the headline — deployment stays pragmatic and cheap.

---

# The Demonstrational Narrative

A first-time visitor with no prior context should be able to, within ~60 seconds and
without reading documentation:

1. Land on the dashboard and immediately understand they are watching a *live* system.
2. Submit a batch of jobs with varying complexity (simulated time and failure rate) and 
   watch them move: queued → running → completed/failed.
3. Destroy a worker, and *see the system recover* (retries fire,replacement worker 
   comes up, queue drains).
4. Watch the autoscaler add or remove workers as load changes.
5. Walk away understanding what a job queue is and why resilience and scaling matter.

This narrative is the north star. Every feature should make some part of this story
clearer or more impressive.

---

# Personas

- **The Evaluator** (primary) — recruiter or engineer assessing the author. Wants to
  understand the system fast and judge its depth. Low patience, high signal needs.
- **The Curious Engineer** — peer who wants to play with the mechanics, push the
  system, and read the architecture explanations.
- **The Author** (you) — uses it as a living artifact to talk through in interviews
  and as a reference implementation of distributed patterns.

---

# Concurrency Model — A Shared Live Instance

QueueLab runs as **one shared, global, live system** that all visitors observe and
interact with simultaneously. There is no per-user sandbox. This makes the lab feel
alive and genuinely multiplayer — you see other people's jobs flowing alongside yours.

Implications this introduces (addressed in later sections):

- **Anonymous identity** — each visitor gets an ephemeral session identity (a handle
  and color) so their actions are attributable in the shared view without requiring
  login.
- **A live activity feed** — a shared, real-time stream of events ("guest-amber
  submitted 50 jobs", "guest-teal destroyed worker-3") so the shared system stays
  legible and the multiplayer aspect is visible.
- **Guardrails are mandatory** — because anyone can act on the shared system, caps and
  rate limits are required to keep the experience coherent (see Guardrails).

---

# Authentication

**Anonymous and ephemeral.** No sign-up, no login. Identity is a per-session handle
assigned on arrival (e.g. `guest-amber`) and is used purely for attribution in the
shared activity feed. Lowest possible friction — a visitor can play instantly.

---

# Core Features

## Job Submission

Visitors submit a batch of jobs with configurable parameters:

- **Job Count** (capped — see Guardrails)
- **Job Complexity** — scales simulated job duration and failure rate
- **Maximum Retries**
- **Retry Delay**
- **Job Type** (see Job Types)

## Real-Time Monitoring Dashboard

Live counts and visual flow of jobs by state:

- Queued
- Running
- Completed
- Failed
- Retrying

The dashboard is the centerpiece and must update in real time as the shared system
changes.

## Worker Scaling Controls

Configuration of the autoscaler:

- Minimum Workers
- Maximum Workers
- Scale-Up Threshold
- Scale-Down Threshold
- Idle Timeout
- Scaling Strategy (Manual | Queue Depth)

## Chaos Controls

The "lab" interactions that demonstrate resilience:

- **Destroy a worker** — kill a worker on demand and watch the system rebound
  (in-flight job is retried, autoscaler may replace the worker).
- **Inject failures** — bias jobs toward failure to demonstrate retry behavior.
- (Future) other fault injections such as slow workers or queue backpressure.

## Live Activity Feed

A shared, real-time event stream attributing actions to ephemeral visitor handles, so
the multiplayer nature of the shared instance is visible and the system stays legible.

## Job Validation

A visitor can confirm that submitted jobs completed as expected — i.e. the system
provides a verifiable record of outcomes, not just moving numbers.

---

# Worker Model & Job Types

**Real processes, simulated work.** Workers are genuine, separate processes that
compete for jobs from a real Redis-backed queue — so the distributed mechanics
(queueing, claiming, concurrency, failure, recovery) are real. The *work itself* is
simulated: each job type sleeps for a complexity-scaled duration and fails at a
complexity-scaled rate. No real emails are sent, no real images processed.

Job types (flavor that ties into complexity and failure characteristics):

- Email Job
- Report Generation
- Image Processing
- Webhook Delivery

Each type can carry a characteristic duration/failure profile so different workloads
behave distinctly.

---

# Scaling Strategies

### Manual Scaling

Visitors set the worker count directly.

### Queue Depth Scaling

The autoscaler adjusts worker count based on queue depth against the configured
scale-up / scale-down thresholds.

---

# Autoscaling Service

Monitors:

- Queue Depth
- Active Jobs
- Worker Count
- Average Job Duration
- Worker Health

Responsibilities:

- Add workers (up to the configured/guardrail maximum)
- Remove idle workers (after idle timeout)
- Track and surface scaling events
- Enforce scaling policies and guardrails

---

# Observability

Surfaced metrics:

- Queue Depth
- Running Jobs
- Failed Jobs
- Retry Rate
- Average Job Duration
- Worker Count - (visual display of all possible workers, greyed out if offline, green if running, red if broken/down, etc)
- Scaling Events

These feed both the dashboard and the in-context explanations of what the system is
doing and why.

---

# Guardrails & Abuse Prevention

Because the instance is **shared and anonymous**, guardrails are required to keep the
experience coherent and to protect a small hosting budget:

- **Caps** — maximum jobs per submission, maximum total queued jobs, maximum workers.
- **Rate limiting** — per-session limits on submissions and chaos actions.
- **Auto-reset / drain** — the system trends back toward a clean baseline (e.g. idle
  workers scale down, completed jobs age out) so it never accumulates indefinitely.
- **Graceful saturation** — when at capacity, the system rejects new work clearly
  rather than degrading for everyone.

---

# Non-Goals (Out of Scope)

Stating these deliberately, as a portfolio reviewer should know what was intentionally
excluded:

- No real job side effects (no real emails, image processing, or webhooks).
- No multi-region, high-availability, or durability guarantees.
- No user accounts, persistence of personal history, or per-user data.

---

# Architecture (High-Level)

```txt
            React Frontend (real-time dashboard + lab controls)
                          |
                          v
              Python Backend (API + WebSocket/SSE)
                          |
              +-----------+-----------+
              |                       |
              v                       v
          Postgres                  Redis  <----------------+
       (job records,             (job queue,                |
        scaling events)           live state)               |
                                     ^                       |
                                     |                       |
                          +----------+----------+            |
                          |                     |            |
                          v                     v            |
                    Worker Process        Worker Process     |
                   (claims & runs        (claims & runs      |
                    simulated jobs)       simulated jobs)     |
                                                             |
                              Autoscaler Service  -----------+
                       (watches queue depth & health,
                        adds/removes worker processes,
                        records scaling events)
```

*Framework and infrastructure choices are deferred to the TDD; this diagram is the
high-level shape only.*

---

# Success Criteria

## Functional

- Jobs can be submitted and are executed asynchronously by real worker processes.
- Failure scenarios (job failures, worker destruction) can be simulated on demand.
- Retries function correctly per configuration.
- Workers scale dynamically under the queue-depth strategy and recover from chaos.
- Metrics and the live activity feed are visible and update in real time.
- Multiple simultaneous visitors can interact with the shared instance coherently.
- The system is publicly deployed and accessible.

## Demonstrational

- A first-time visitor can follow the core narrative (submit → break → recover →
  scale) within ~60 seconds without reading docs.
- Architectural decisions and tradeoffs are explained *in context* within the app, not
  only in external documentation.
- The shared, multiplayer nature of the lab is immediately apparent.
- Architecture documentation is complete and interview-ready.

---

# Open Questions (to resolve before / during TDD)

- **Job/event retention** — how long do completed jobs and scaling events persist
  before aging out?
- **Real-time transport** — WebSocket vs SSE vs polling (defer to TDD, but it affects
  the live-feed UX).
- **Worker "processes" in deployment** — separate containers vs processes on one host,
  given the cheap-hosting constraint (defer to TDD).
- **Exact guardrail numbers** — concrete caps and rate limits.
