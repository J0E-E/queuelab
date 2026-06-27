# Stack Screenshot — Proof It's Running — Epic Plan

Source: direct (right-sized — no BRD/TDD)

Add the real compose-stack screenshot to the public `/how-it-works` page
([frontend/src/pages/HowItWorks.tsx](../../frontend/src/pages/HowItWorks.tsx)) as a dedicated
section, so the page doesn't just *describe* the running stack — it *shows* it. The screenshot
([.development-docs/compose-stack/image.png](../compose-stack/image.png)) is a Docker-desktop view
of the live `queuelab` Compose project: `redis-1`, `postgres-1`, `api-1`, `autoscaler-1`,
`frontend-1`, and `inspiring_chatelet` (a worker container the autoscaler spawned on its own) —
all running, with real image tags and container IDs. It is visual proof the architecture is a
genuinely running thing, not a mockup.

## Epic 1 — "Here it is, actually running" screenshot section — **COMPLETED** (23m · 10.2M tok · 436k tok/min)

- **Build strategy:** Tracer bullet — a single static-page addition plus one served image asset;
  no architecture or integration risk to skeleton out.
- **Intent:** The `/how-it-works` page already describes the real Docker Compose stack in prose
  (the `stack` section, "The machine it runs on"). Give the reader the receipt: a screenshot of
  the actual running containers, captioned so the rows map back to the architecture just described.
  Turns a claim into evidence.
- **Scope:**
  - **Asset:** Copy [.development-docs/compose-stack/image.png](../compose-stack/image.png) into
    `frontend/public/compose-stack.png` (the served asset, alongside `queuelab-logo.svg`). Leave
    the original in `.development-docs/compose-stack/` as the doc source. Reference it from the
    app as `/compose-stack.png`.
  - **New section** keyed `proof`, heading **"Here it is, actually running"**, positioned
    **between the `stack` and `payoff` sections** (final order: queue → workers → chaos → stack →
    **proof** → payoff). Leave the existing `queue`, `workers`, `chaos`, `stack`, `payoff` keys,
    headings, and bodies intact.
  - The new section renders the screenshot `<img src="/compose-stack.png">` followed by a short
    caption that names the pieces and calls out the autoscaler-spawned worker as the honesty hook,
    e.g.: *"The live `queuelab` stack: Redis, Postgres, the API, the autoscaler, and the frontend
    — plus `inspiring_chatelet`, a worker container the autoscaler spawned on its own (the random
    name is Docker's, not ours)."* (Implementer may tighten wording; keep the named-pieces +
    spawned-worker call-out.)
  - **Accessibility:** the `<img>` gets descriptive **alt text** naming what it shows, e.g.
    "Screenshot of the running queuelab Docker Compose stack: redis, an autoscaler-spawned worker,
    postgres, the autoscaler, the api, and the frontend — all running."
  - **IDs (project rule — every rendered element gets a unique descriptive id):** the new
    `<section>` → `how-it-works-section-proof`; its heading → `how-it-works-section-proof-heading`
    (match the existing heading classes/markup); the image → `how-it-works-stack-screenshot`; the
    caption → `how-it-works-stack-screenshot-caption`.
  - Keep the existing text `SECTIONS` map uniform (heading + body paragraph). The `proof` section
    carries an image + caption, not a body paragraph, so render it as a distinct `<section>`
    inserted between the `stack` and `payoff` text sections — implementer picks the tidy mechanism
    (split the map, or render it explicitly in order). No backend change; no new route or nav item.
  - **Tests:** extend [frontend/src/pages/HowItWorks.test.tsx](../../frontend/src/pages/HowItWorks.test.tsx)
    to assert the `proof` section renders and the screenshot `<img>` is present with its alt text.
    Existing assertions (landmark, heading, `payoff` section) must stay green. **Also add an
    asset-existence guard** (approved at plan time, mirroring
    [frontend/src/brandLogo.test.ts](../../frontend/src/brandLogo.test.ts)): `readFileSync` the
    served `public/compose-stack.png` and assert it is non-empty and carries the PNG signature
    bytes (`\x89PNG`) — the jsdom `<img>` test never loads the file, so this catches a missing or
    empty asset at gate time. Same file or a sibling `composeStackAsset.test.ts` — implementer's call.
- **Verification:** Page renders six sections in order (… → stack → **proof** → payoff); the
  screenshot loads from `/compose-stack.png` and displays with alt text and caption; new + existing
  `HowItWorks.test.tsx` assertions pass; frontend gate green (build · test · lint · format).
  Eyeball: caption reads honest, names the real pieces, calls out the spawned worker.
- **Depends on:** none. (Complements the prior `stack` prose section from
  [.development-docs/how-it-works-stack/](../how-it-works-stack/epic-plan-how-it-works-stack.md),
  but does not block on it.)
- **Open questions / decisions for stakeholders:** none open — placement (own section on
  `/how-it-works`, after `stack`), heading ("Here it is, actually running"), caption (names the
  pieces + spawned-worker hook), asset handling (copy to `frontend/public/compose-stack.png`), and
  test coverage (assert section + img alt) all settled in the grill.
- **Implementation notes:** Epic 1 — frontend repo-wide `format:check` is **already red on `main`**
  (6 files: FeedLine.test.tsx, useSubmitJobs.test.tsx, FeedPane.test.tsx, FeedPane.tsx,
  WorkersPane.tsx, vite.config.ts) — pre-existing drift, untouched by this epic; any future
  frontend epic's gate sees the same. This epic's own files are Prettier-clean.
