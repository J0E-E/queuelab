# Sparkline Trend Fix — Epic Plan

Source: direct (right-sized — no BRD/TDD)

> **Build strategy:** Tracer bullet

Fix the queue-depth trend sparkline so its time buckets are visually distinct and it
never spills past its pane. Two settled decisions from the off-ramp grill:

1. **Separation** — add CSS letter-spacing (tracking) to the block glyphs so each time
   bucket reads as its own unit instead of one smear. Characters and logic unchanged.
2. **Overflow** — display-only cap of the **last 30** buckets (stored `DEPTH_CAP = 40`
   stays untouched) **plus** a hard container constraint (`overflow-hidden`, newest-anchored
   so the most recent buckets stay visible) as a backstop on narrow viewports.

---

## Epic 1 — Spaced, non-overflowing trend sparkline

- **Goal:** The queue-depth trend renders with clear separation between time buckets and
  always stays within its pane. Buckets are spaced via CSS tracking; the sparkline shows the
  last 30 samples and is clipped to the container (newest-anchored) so a long-running session
  never overflows to the right.
- **Rough scope:** `frontend/src/components/Sparkline.tsx` (spacing + display-cap slice),
  its wrapper in `frontend/src/panes/QueueDepthPane.tsx` (container width/overflow constraint),
  and the related component tests (`Sparkline`/`QueueDepthPane`). `liveState.ts` `DEPTH_CAP`
  is **not** changed — the cap here is display-only.
- **Open questions / decisions for stakeholders:** none expected — separation method (CSS
  letter-spacing), overflow handling (display cap + container clip), N (30), and clip anchor
  (newest) are all settled.
- **Depends on:** none.
- **Implementation notes:** _none yet_
