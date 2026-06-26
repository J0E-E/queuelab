# How-It-Works Stack Narrative — Epic Plan

Source: direct (right-sized — no BRD/TDD)

Make the public `/how-it-works` page ([frontend/src/pages/HowItWorks.tsx](../../frontend/src/pages/HowItWorks.tsx))
describe the whole VM + Docker stack QueueLab runs on, so the page concretely shows the
system is a genuinely running, deployed thing — not a mockup.

## Epic 1 — "The machine it runs on" stack section — **COMPLETED** (28m22s)

- **Build strategy:** Tracer bullet — pure copy change to one static page; no architecture or
  integration risk to skeleton out.
- **Intent:** Give the `/how-it-works` narrative a concrete, honest account of the real stack
  so a reader trusts that the queue/workers/chaos they just read about actually run. Today the
  page describes the mechanics but never says *where* or *on what* they run.
- **Scope:**
  - Add **one new section** keyed `stack` (heading e.g. "The machine it runs on") to the
    `SECTIONS` array, positioned **between `chaos` and `payoff`**. Leave `queue`, `workers`,
    `chaos`, `payoff` keys and the existing four bodies intact.
  - New section body, concrete and brand-named (human prose, not a config dump), covering the
    real stack as built: it runs as a **Docker Compose stack** — Postgres, Redis, the api, the
    **autoscaler that holds the Docker socket and spawns/kills real worker containers**, and
    **Nginx** out front (TLS + WebSocket + static bundle) — all on a **single EC2 cloud VM**,
    shipped by a **CI/CD pipeline** (build → push images → deploy). Tie it back: this is why the
    containers you watch appear and disappear for real.
  - **Voice:** present-tense and live — "it runs / it's deployed." Honest because Epic 19
    (live deploy) ships in parallel and will be done before this page goes public.
  - Tighten the `payoff` body's close to land the "and it's all genuinely live" note (keep the
    `payoff` key and heading "The point").
  - Match existing section rendering (no new components, IDs auto-derive from the section key —
    confirm `how-it-works-section-stack*` ids render).
  - **No live URL/link** — the page already sits beside a Dashboard nav link in
    [Layout.tsx](../../frontend/src/Layout.tsx); a "see it live" link is redundant.
- **Verification:** Page renders 5 sections in order (queue → workers → chaos → **stack** →
  payoff); existing `HowItWorks.test.tsx` stays green (landmark + heading + `payoff` section
  still present). Frontend gate green (build · test · lint · format). Eyeball: stack section
  reads as honest present-tense, names the real pieces, no claim of a clickable public URL.
- **Depends on:** none (copy-only; Epic 19 lands the live deploy in parallel but is not a
  blocker for this page change).
- **Open questions / decisions for stakeholders:** none open — voice (live present-tense),
  concreteness (name real pieces), and structure (new `stack` section before `payoff`) all
  settled in the grill. If a public domain is finalized later, a one-line copy tweak can name it.
- **Implementation notes:** none — copy-only change, exactly per plan; no deviations or cross-epic handoffs.
