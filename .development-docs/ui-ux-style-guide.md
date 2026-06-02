# QueueLab — UI/UX Design Style Guide

> The single source of truth for how QueueLab looks, feels, and behaves on screen.
> Consult this **before** adding or changing any frontend UI. When a decision isn't
> covered here, choose the option most faithful to the **Terminal CLI** philosophy
> below, then add it back to this guide.

---

## 1. Design Philosophy

QueueLab is a live, multiplayer distributed-systems lab. Its job is to make
**invisible backend mechanics visible** — queues filling, workers claiming jobs,
retries firing, the autoscaler reacting. The interface should feel like you're
**looking straight into the system**, not at a polished abstraction over it.

The aesthetic is **Terminal CLI**: brutally functional, high-contrast, authentically
retro. It reads like a ZSH/BASH shell or a `tmux` session into a mainframe — not
"Matrix rain." Every pixel earns its place; there is no decoration that isn't also
information.

This aesthetic is not a costume. It is *thematically true* to the product: QueueLab is
about systems internals, so the UI speaks the language of systems internals — prompts,
status codes, monospaced columns, raw data bars.

**Key signatures**
- **Monospace supremacy** — every character, headline to footnote, is monospaced.
- **The cursor** — a blinking block `█` / underscore `_` is the heartbeat of the UI.
- **Shell metaphors** — prompt characters (`>`, `$`, `~`), flags (`--max-retries`),
  status codes (`[OK]`, `[ERR]`, `[RUNNING]`).
- **Raw data viz** — stats render as ASCII bars `[||||||||..]`, never pie charts.
- **Restrained CRT** — faint scanlines and a soft phosphor glow on headings give depth
  without ever fighting the data. Readability wins every tie.

**Decisions locked for this project**
- **Color model:** multi-phosphor (green base UI + a distinct phosphor hue per job
  state). See §3.
- **Typeface:** `JetBrains Mono`. See §4.
- **Effect intensity:** restrained / tasteful, fully reduced-motion aware. See §9.

---

## 2. Design Principles (apply these when in doubt)

1. **Legibility beats immersion.** People stare at this dashboard for minutes. If an
   effect makes a number harder to read, the effect loses.
2. **Color is data, not decoration.** Every hue means something specific (§3). Never
   use a state color for a non-state purpose.
3. **Everything is on a character grid.** Align to the monospace cell. Columns line up.
   Numbers are right-aligned. Labels are fixed-width.
4. **Show the mechanism.** Prefer UI that exposes what the system is doing (a draining
   bar, a worker claiming a job) over UI that merely reports a final number.
5. **Honest states.** Loading, empty, error, and saturated (at-capacity) states are
   designed, not afterthoughts — the system should narrate itself even when idle.
6. **One pane, one job.** Lay the screen out like `tmux` splits — each pane owns a
   single concern (queue, workers, feed, controls).

---

## 3. Color Tokens (Dark Mode Only)

The palette mimics a phosphor monitor on near-black glass. High contrast is
non-negotiable; all foreground colors clear WCAG AA (4.5:1) on the background.

### 3.1 Core / UI

| Token | Hex | Use |
|---|---|---|
| `--color-bg` | `#0a0a0a` | App background (deep black, not OLED-pure, so scanlines read) |
| `--color-bg-raised` | `#101410` | Pane/card interior, one step off the floor |
| `--color-fg` | `#33ff00` | Primary terminal green — default text, prompts, primary actions |
| `--color-fg-dim` | `#6f9f6f` | Secondary text, captions, helper copy |
| `--color-muted` | `#1f521f` | Borders, inactive text, dividers, disabled |
| `--color-accent` | `#33ff00` | Cursor, active/focus, selection (same phosphor as `fg`) |
| `--color-bg-invert` | `#33ff00` | Inverted-video fill (button hover, title bars) — text becomes `--color-bg` |

### 3.2 Job-State Phosphors (semantic — never reuse off-purpose)

Each job state gets its own phosphor hue **and** a glyph/status-code, so state is
never carried by color alone (accessibility — §10).

| State | Token | Hex | Glyph | Status code |
|---|---|---|---|---|
| Queued | `--state-queued` | `#36c5ff` (cyan) | `░` / `[ ]` | `[QUEUED]` |
| Running | `--state-running` | `#ffb000` (amber) | `▓` / `►` | `[RUN]` |
| Completed | `--state-completed` | `#33ff00` (green) | `█` / `✓` | `[DONE]` |
| Failed | `--state-failed` | `#ff3333` (red) | `✗` / `×` | `[FAIL]` |
| Retrying | `--state-retrying` | `#b46bff` (violet) | `↻` / `@` | `[RETRY]` |

> Mnemonic: **cold→hot→done.** Cyan is cold storage (waiting), amber is hot (working),
> green is settled (done), red is broken, violet is cycling back around.

### 3.3 System / Semantic

| Token | Hex | Use |
|---|---|---|
| `--color-error` | `#ff3333` | Errors, destructive actions, `[ERR]` |
| `--color-warn` | `#ffb000` | Warnings, near-capacity, rate-limit notices |
| `--color-ok` | `#33ff00` | Success, `[OK]`, healthy |
| `--color-info` | `#36c5ff` | Neutral system notices, scaling info |
| `--color-scale-up` | `#33ff00` | Autoscaler adding workers |
| `--color-scale-down` | `#ffb000` | Autoscaler removing idle workers |

### 3.4 Guest-handle colors (activity feed)

Ephemeral visitor handles (`guest-amber`, `guest-teal`) are attributed by color. Pull
from a fixed, named, phosphor-safe set so handles stay stable and legible against
`--color-bg`. Keep this set **distinct from the job-state hues** to avoid confusion —
e.g. `teal #2dd4bf`, `pink #ff5fd2`, `lime #aaff00`, `sky #5ab0ff`, `orange #ff8c42`,
`lavender #c77dff`. Each handle is rendered as `guest-<colorname>` in its own color.

### 3.5 Color usage rules
- Body text is `--color-fg` or `--color-fg-dim`. Don't tint body text with state hues.
- A state hue may color: a status badge, that state's count/bar, its row accent, its
  glyph. Nothing else.
- Red is reserved. It means failure or destruction — never use it for emphasis.
- Maximum one inverted-video block competing for attention per pane.

---

## 4. Typography

### 4.1 Family
- **Primary:** `JetBrains Mono` (weights 400 / 500 / 700). Highly legible at small
  sizes and for dense numerics — the right anchor for a live dashboard.
- **Fallback stack:** `'JetBrains Mono', 'Fira Code', 'SF Mono', ui-monospace, Menlo, Consolas, monospace`.
- Load `tabular-nums` everywhere numbers change in real time so digits don't jitter.

### 4.2 Case & voice
- **Headers / section titles / labels:** `ALL CAPS`, often bracketed: `[ QUEUE DEPTH ]`.
- **Body, logs, code, feed lines:** lowercase or natural case — reads like shell output.
- **Status codes:** uppercase in brackets — `[OK]`, `[ERR]`, `[RUN]`, `[RETRY]`.
- Voice is terse and systemic: `> 50 jobs queued` not `You have queued 50 jobs!`.

### 4.3 Modular scale (snaps to grid — no fluid in-between sizes)

| Token | Size / line-height | Use |
|---|---|---|
| `--text-hero` | `2.5rem / 1.1` | Landing/ASCII hero only |
| `--text-xl` | `1.75rem / 1.2` | Big live counters (queue depth, worker count) |
| `--text-lg` | `1.25rem / 1.3` | Pane titles, section headers |
| `--text-base` | `0.9375rem / 1.5` | Body, form fields, feed lines |
| `--text-sm` | `0.8125rem / 1.45` | Captions, helper text, metadata |
| `--text-xs` | `0.6875rem / 1.4` | Dense table cells, footnotes |

Letter-spacing: `0.02em` on ALL-CAPS headers; `0` elsewhere (monospace already breathes).

---

## 5. Spacing, Grid & Layout

### 5.1 The character grid
Everything aligns to a monospace cell. Use a base unit of **`0.25rem` (4px)** and a
character column width derived from the font. Tabular columns (job lists, metrics)
align on the cell; numbers right-align, labels left-align to fixed widths.

Spacing scale: `--space-1: 4px`, `-2: 8px`, `-3: 12px`, `-4: 16px`, `-6: 24px`,
`-8: 32px`, `-12: 48px`. Prefer these over arbitrary values.

### 5.2 Pane layout (tmux/vim splits)
The screen is a grid of bordered **panes**, each owning one concern. A representative
desktop layout for the main lab:

```txt
+== QUEUELAB ============================== guest-amber ===+ [ live ● ]
|                                                          |
| +--[ QUEUE DEPTH ]------+  +--[ WORKERS ]--------------+ |
| | queued   ░░░ 0142     |  | worker-1  [RUN]  job#8821 | |
| | running  ▓▓▓ 0018     |  | worker-2  [RUN]  job#8822 | |
| | done     ███ 4096     |  | worker-3  [IDLE] --       | |
| | failed   ✗   0007     |  | [+] scale   [x] destroy   | |
| | retry    ↻   0003     |  +---------------------------+ |
| +----------------------+                                 |
|                                                          |
| +--[ SUBMIT JOBS ]------+  +--[ ACTIVITY FEED ]--------+ |
| | $ submit --count 50 \ |  | 12:04:02 guest-teal +50   | |
| |   --type email \      |  | 12:04:05 guest-amber kill | |
| |   --complexity 3      |  | 12:04:06 sys  scale-up +1 | |
| | [ EXECUTE ]           |  | 12:04:07 worker-4 online  | |
| +----------------------+  +---------------------------+ |
+==========================================================+
```

- **Separators:** ASCII rules — `----------------`, `================`, `//`. Pane
  borders are `1px solid var(--color-muted)`; the active pane border brightens to
  `--color-fg`.
- **Title bars:** either `+--[ TITLE ]--------+` ASCII style or a solid inverted-video
  bar (`--color-bg-invert` background, `--color-bg` text). Pick one per surface and
  stay consistent.
- **Density:** comfortable but tight. Pane padding `--space-4`; row height tuned to the
  line-height, not inflated.

---

## 6. Radius, Borders & Surfaces

- **Radius:** `0px`. Absolutely no rounded corners, anywhere, ever.
- **Borders:** `1px solid` (or `1px dashed` for provisional/placeholder regions, e.g.
  an empty drop target or a not-yet-configured pane).
- **Borders define windows.** Panes, cards, inputs-on-focus, and dialogs are delineated
  by borders, not shadows.
- **Shadows:** none. No drop shadows, no elevation. Depth comes from borders, the
  scanline texture, and the phosphor glow — never from blur.

---

## 7. Components

> All frontend elements must carry a unique, descriptive `id` (see project CLAUDE.md).
> The `id` examples below are suggestions; keep them stable for E2E/automation/ARIA.

### 7.1 Buttons
- **Default:** bracketed label — `[ EXECUTE ]`, `[ DESTROY WORKER ]`, `[ + SCALE UP ]`.
- **Hover:** inverted video — background fills with the relevant color, text becomes
  `--color-bg`. (Primary actions invert to green; destructive to red.)
- **Active/pressed:** text nudges `1px` down, or a single rapid blink.
- **Disabled:** `--color-muted` text, no fill, no invert; often shown as `[ ----- ]`.
- **Destructive** (`destroy worker`, `inject failures`): red border + red invert on
  hover. Always reads as a deliberate chaos action.

### 7.2 Cards / Panes (Windows)
- Black-on-near-black box, `1px` border, ASCII or inverted-bar title (§5.2).
- Content is padded monospaced text/columns.
- A pane may show a live status chip in its title bar (`● live`, `[ DRAINING ]`).

### 7.3 Inputs & Forms
Submission and config forms read like typing a command, not filling a web form.

- **Style:** no boxy field. A prompt precedes the input: `guest-amber@queuelab:~$ `.
- **Caret:** a blinking block `█` at the caret. Focus = the cursor, no focus ring box;
  the field's prompt brightens to `--color-fg`.
- **Composite/CLI form:** render the job-submission form as a faux command being built,
  with each control as a flag:
  ```txt
  $ submit \
      --count 50          ▸ [slider/stepper, capped per Guardrails]
      --type email        ▸ [select: email|report|image|webhook]
      --complexity 3      ▸ [1–5]
      --max-retries 3     ▸ [stepper]
      --retry-delay 2s    ▸ [stepper]
  [ EXECUTE ]   [ --help ]
  ```
- **Validation:** inline, terse, system-voiced — `[ERR] --count exceeds cap (max 100)`
  in `--color-error` directly beneath the offending flag.
- **Selects/toggles:** render as bracketed option groups — `[ MANUAL ] queue-depth` /
  `manual [ QUEUE-DEPTH ]` where the chosen option is inverted-video.

### 7.4 Status badges
`[QUEUED]` `[RUN]` `[DONE]` `[FAIL]` `[RETRY]` — bracketed, uppercase, in the state
phosphor (§3.2), paired with the state glyph. Never color-only.

### 7.5 Tables / Lists (jobs, workers)
- Fixed-width columns, header row in ALL CAPS, `1px` rule under the header.
- Right-align numbers (`tabular-nums`), left-align labels, state badge in its own column.
- Row hover: faint `--color-bg-raised` fill or a `>` gutter marker on the active row.
- Long lists scroll within the pane; the pane title shows a count (`[ JOBS · 4231 ]`).

### 7.6 Activity feed
- Append-only, newest at bottom (like a tailing log) or top — pick one, stay consistent.
- Line format: `HH:MM:SS  guest-teal  destroyed worker-3`. Timestamp dim, handle in its
  guest color, action in body color, any state word in its state color.
- New lines fade/type in once (§9), then stay static. Never animate the whole log.

### 7.7 Toasts / system notices
- Slide in as a bordered strip, not a rounded bubble. Prefixed with a status code:
  `[OK] 50 jobs queued`, `[WARN] rate limit: 1 submission / 3s`, `[ERR] queue at capacity`.

### 7.8 Dialogs / confirms
- Centered bordered pane with an ASCII title bar and a backdrop of intensified
  scanlines (dimmed, not blurred). Confirm/cancel as bracketed buttons.
- Chaos confirmations spell out the consequence in system voice:
  `> destroy worker-3? in-flight job#8821 will be retried. [ CONFIRM ] [ CANCEL ]`.

---

## 8. Data Visualization (raw, not chart-library)

This is where QueueLab earns its theme. Stats render as **ASCII/terminal viz**, not
glossy charts.

- **Progress / proportion bars:** `[||||||||||......]  62%`. Fill char `|` or `█`,
  empty char `.` or ` `, bracketed ends. Color the fill with the relevant state hue.
- **Queue depth over time:** a braille/block **sparkline** — `▁▂▃▅▇▆▃▂` — in
  `--color-fg`, with the current value printed beside it.
- **Stacked state bar:** a single horizontal bar segmented by state color showing the
  mix of queued/running/done/failed/retry — the at-a-glance system snapshot.
- **Worker grid:** each worker a cell — `[R]` running (amber), `[I]` idle (dim),
  `[·]` spawning, ` ✗ ` destroyed (red, briefly) — so scaling is *visible* as cells
  appearing/disappearing.
- **Counters:** large `--text-xl`, `tabular-nums`, with a tick animation (§9) when the
  value changes. Show delta inline when useful: `0142  (+12)`.
- **Gauges (thresholds):** the autoscaler's scale-up/down thresholds drawn as marks on
  the queue-depth bar — `[||||||||^.....v..]` where `^`=scale-up, `v`=scale-down — so
  *why* the autoscaler acts is legible in context.

> Rule: if a metric in the BRD (queue depth, running jobs, failed jobs, retry rate,
> avg duration, worker count, scaling events) needs a visual, it gets a terminal-native
> one from this section — never a third-party chart widget.

---

## 9. Motion & Effects (restrained, reduced-motion aware)

Effects are tasteful and serve comprehension. **All of the below must be disabled or
reduced under `@media (prefers-reduced-motion: reduce)`.**

- **Cursor blink** (`animate-blink`): the signature `█`/`_` blink (~1s step). Always on
  in inputs; decorative elsewhere.
- **Scanlines:** a single `pointer-events-none` fixed overlay, `~3%` opacity, repeating
  linear-gradient. Subtle enough that data stays crisp.
- **Phosphor glow:** `text-shadow: 0 0 5px rgba(51,255,0,0.45)` on headings, the cursor,
  and active counters **only** — not on body text or tables.
- **Typewriter:** the landing hero / ASCII logo types in character-by-character, once.
  Do **not** typewrite live data or feed lines beyond a quick fade.
- **Counter tick:** when a live number changes, a fast (~120ms) color flash to the
  relevant state hue, then settle. Communicates "this is live."
- **Glitch:** reserved and rare — a subtle 1–2px text offset on hover of a logo/hero
  element, or on a chaos/error event. Never on data the user is reading.
- **New-worker / job transitions:** brief fade or a single-cell appear; never slide
  large blocks around the dashboard.

Boot flourish (optional, once per session, skippable): a short fake boot line
`queuelab v1.0 :: connecting to shared instance... [OK]` before the dashboard resolves.
Keep it under ~1.2s and skippable on any keypress/click.

---

## 10. Iconography

- **Library:** Lucide, `stroke-width: 2`, sharp (no rounded line caps where avoidable),
  sized to the text cell. Keep them sparse — glyphs and status codes do most of the work.
- **Color:** icons are `--color-fg` by default; a state-scoped icon may take its state
  hue. No multicolor icons.
- **Prefer ASCII/Unicode glyphs** (`>`, `$`, `~`, `█`, `░`, `↻`, `✗`, `▸`) over drawn
  icons wherever a glyph reads clearly — it's more on-theme and lighter.

---

## 11. Responsive Strategy

- **Breakpoints (guidance):** `sm < 640`, `md 640–1024`, `lg > 1024`. Desktop-first —
  the lab is richest on a wide screen, but must stay fully usable on mobile.
- **Stacking:** panes are a grid on desktop and **stack vertically** on mobile, in
  narrative order: live counters → submit → workers/chaos → feed.
- **Overflow:** monospace runs wide — guard against horizontal scroll. Wrap long shell
  lines with a trailing `\` continuation indicator, mirroring real shell wrapping.
- **Touch targets:** bracketed buttons get a minimum `44px` tap height on touch via
  padding, without breaking the character-grid look.
- **Keep numbers legible:** never shrink live counters below `--text-base` on mobile;
  drop secondary columns from tables before shrinking type.

---

## 12. Accessibility

- **Contrast:** all foreground hues clear WCAG AA on `--color-bg`. Verify any new color
  before adding it.
- **Never color-only:** every job state is conveyed by **glyph + status code + label**
  in addition to color (§3.2). A colorblind or monochrome user loses nothing.
- **Focus:** highly visible by nature — the inverted-video / brightened-prompt focus
  state is the focus indicator. Ensure every interactive element has a clear, distinct
  focus style (don't rely on the blinking cursor alone for non-input controls; give
  buttons/links a visible inverted or outlined focus state).
- **Reduced motion:** honor `prefers-reduced-motion` — disable scanline shimmer, glitch,
  typewriter, counter flashes; keep the static layout fully functional.
- **Semantics & ARIA:** real landmarks (`header`/`main`/`nav`/`footer`), labelled form
  controls (`htmlFor` ↔ input `id`), and `aria-live="polite"` on the activity feed and
  on live counters so screen readers hear the system update.
- **Don't encode meaning in the scanline/CRT layer** — it's decorative and
  `aria-hidden`.

---

## 13. Implementation Reference

Token names map 1:1 to CSS custom properties / Tailwind theme keys. Centralize them;
never hardcode a hex in a component.

```css
:root {
  /* core */
  --color-bg: #0a0a0a;
  --color-bg-raised: #101410;
  --color-fg: #33ff00;
  --color-fg-dim: #6f9f6f;
  --color-muted: #1f521f;
  --color-accent: #33ff00;

  /* job states */
  --state-queued: #36c5ff;
  --state-running: #ffb000;
  --state-completed: #33ff00;
  --state-failed: #ff3333;
  --state-retrying: #b46bff;

  /* system */
  --color-error: #ff3333;
  --color-warn: #ffb000;
  --color-ok: #33ff00;
  --color-info: #36c5ff;

  /* type */
  --font-mono: 'JetBrains Mono', 'Fira Code', ui-monospace, Menlo, Consolas, monospace;

  /* radius / border */
  --radius: 0px;
  --border-width: 1px;

  /* effects */
  --glow-fg: 0 0 5px rgba(51, 255, 0, 0.45);
  --scanline-opacity: 0.03;
}

@keyframes blink { 0%, 49% { opacity: 1 } 50%, 100% { opacity: 0 } }
.animate-blink { animation: blink 1s steps(1) infinite; }

@media (prefers-reduced-motion: reduce) {
  .animate-blink, .animate-typing, .animate-glitch, .scanlines { animation: none; }
  .scanlines { opacity: 0; }
}
```

**Tailwind note:** if using Tailwind, register the above as `theme.extend.colors`,
`fontFamily.mono`, set `borderRadius.DEFAULT: '0px'`, and disable the default rounded
utilities by convention. Expose state colors as `text-state-queued`,
`border-state-failed`, etc.

**Component architecture (per project React philosophy):** build small, focused,
well-named primitives first — `<Pane>`, `<PaneTitle>`, `<Prompt>`, `<BracketButton>`,
`<StatusBadge>`, `<AsciiBar>`, `<Sparkline>`, `<Counter>`, `<FeedLine>`,
`<WorkerCell>` — then compose screens from them. No one-off inline styles; if a style
recurs, it becomes a token or a primitive.

---

## 14. Quick "Definition of Done" for any new UI

- [ ] Monospace only; aligned to the character grid.
- [ ] `0px` radius; borders (not shadows) define every surface.
- [ ] Colors come from tokens; state hues used only for their state.
- [ ] Every state shown with glyph + status code + label, not color alone.
- [ ] Live numbers use `tabular-nums` and an `aria-live` region.
- [ ] Effects honor `prefers-reduced-motion`.
- [ ] Every element has a unique, descriptive `id` (project CLAUDE.md rule).
- [ ] Contrast checked AA; focus state visible on every interactive element.
- [ ] Reads like the system narrating itself — terse, shell-voiced, honest about
      loading/empty/error/at-capacity states.
```
