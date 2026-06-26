# How I Work — Pipeline Overhaul — Epic Plan

Source: direct (right-sized — no BRD/TDD)

Overhaul the public `/how-i-work` explainer page so it concretely describes the real
Claude build pipeline, instead of stating abstract principles. The work is a single
content/structure edit to one React page (and its test), preserving §5.11's narrative
arc — the page must still **climax at the review-loop** and **close on the git-history
proof point** — and the matched section-card styling shared with the sibling
`/how-it-works` page.

**Grilled decisions (the only grill — off-ramp from `1-prompt-to-brd`):**
- **Concreteness (B):** describe the pipeline's real *shape* in plain terms (brief →
  design → sliced epics → generate → adversarial review → green gate → one commit).
  Light on tool brand-names so the page reads cold and doesn't rot when tooling is
  renamed; one or two real names (e.g. "green gate") are fine as flavor.
- **Granularity (B):** ~6 sections (up from 4), reading as a real sequence. Keep the
  `spec-driven` and `git-history` section keys as the arc's bookends so the climax/close
  anchors — and the existing test — stay stable.
- **Close links out (A):** the `git-history` section is the "check the receipts" payoff
  and should point the visitor at the repo's commit history. No public repo URL /
  git remote exists yet, so build the section **link-ready** (optional href) and ship
  copy-only until a URL exists. See Open questions.

---

## Epic 1 — Rewrite the How-I-Work page as the real pipeline narrative

- **Build strategy:** Tracer bullet — one customer-visible page edit through the only
  layer it touches (the static React page + its test); no architecture or integration
  risk that would warrant a walking skeleton.
- **Intent:** Make `/how-i-work` concretely describe how the builder actually works —
  a spec-driven, gated, review-first pipeline — so the page earns credibility for the
  *person*, landing the §5.11 thesis "the value is design and review, not code
  generation."
- **Scope:** Edit [HowIWork.tsx](frontend/src/pages/HowIWork.tsx) `SECTIONS` from 4 to
  6 entries, in narrative order (keys fixed where noted):
  1. `spec-driven` *(keep key)* — **Spec before code.** Brief → technical design →
     small, independently-reviewable epics with explicit dependencies; ambiguity closed
     on paper.
  2. `sliced-epics` *(new)* — **Sliced into shippable epics.** Each epic is one small,
     gated unit with deliverables defined up front.
  3. `thin-thread` *(keep)* — **A thin thread, end to end.** Walking-skeleton /
     tracer-bullet first slice; real behavior layers onto a structure that already holds.
  4. `generate` *(new)* — **Generation is the cheap part.** Code is generated against a
     locked spec; the leverage is the spec and the gate around it, not the typing.
     (Carries the §5.11 "design & review over code generation" thesis explicitly.)
  5. `review-loop` *(keep — climax)* — **A review loop with teeth.** Plan → implement →
     adversarial review against deliverables + a green gate (build, lint, tests);
     findings triaged and fixed before it lands.
  6. `git-history` *(keep — close)* — **The proof is in the history.** Every epic = one
     small titled commit; the log reads as the build narrative — this site is the
     receipts. Render **link-ready**: support an optional commit-history href (rendered
     as a "view the commit history →" link only when a URL is present); ship without the
     URL for now.
  Keep all existing ids/ARIA, the `glow`/`text-fg`/`text-fg-dim` styling, the
  `space-y-6` section rhythm, and the per-CLAUDE.md unique-`id` rule (any new link/element
  gets a descriptive `id`). Update [HowIWork.test.tsx](frontend/src/pages/HowIWork.test.tsx)
  to cover the new sections while keeping the existing `git-history` proof-point assertion.
- **Verification:** Green gate (frontend build + lint + Vitest). The page renders 6
  sections in order; `how-i-work-section-spec-driven` and
  `how-i-work-section-git-history` headings are present (bookends intact); the
  git-history proof-point assertion still passes; no console/ARIA regressions; copy stays
  in plain language with no hard dependency on tool brand-names.
- **Depends on:** Epic 13 / §5.11 (the existing `/how-i-work` page and its routing) —
  already built.
- **Open questions / decisions for stakeholders:**
  - **Commit-history URL** — the close is built link-ready but no public repo URL / git
    remote exists yet. When a public repo is published, supply the URL to wire the
    "view the commit history →" link. Until then it ships copy-only. *(Confirm at
    `4-plan-epic`.)*
