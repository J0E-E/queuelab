# QueueLab Brand & Portfolio Entry — Epic Plan

**Source:** direct (right-sized — no BRD/TDD)
**Build strategy:** Tracer bullet — thinnest customer-visible thread first (one logo asset that renders in the navbar), then reuse it across favicon and portfolio.

Spans two repos: **QueueLab** (`c:\Development\QueueLab`, the logo + app wiring) and **joeys-hub** (`c:\Development\joeys-hub`, the portfolio entry). Both are accessible as working dirs.

Settled in grilling (2026-06-26):
- Off-ramp: direct epic plan, no BRD/TDD.
- Logo: hand-authored SVG matching QueueLab's CRT/terminal look — **phosphor green `#33ff00` on near-black `#0a0a0a`**, bracketed-monogram + queue/scanline motif, hard corners (palette is the app's own, per `frontend/src/index.css` + `ui-ux-style-guide.md`). One asset reused as navbar mark, favicon, and portfolio image.
- Navbar: logo mark to the **left** of the existing `[ QUEUELAB ]` text; **also** add an external GitHub link (`https://github.com/J0E-E/queuelab`) to the right-side nav.
- Portfolio entry: joeys-hub `projectsDataset.js`, category `scalable-system-design-mvps`, beside LinkShrink. Copy short and fun; system-design framing; the demo is fully simulated (no real data) — **no** "data is public" caveat. Links: live app `https://queuelab.joeyshub.com` + repo `https://github.com/J0E-E/queuelab`.

---

## Epic 1 — QueueLab logo & app brand wiring

- **Goal:** QueueLab gets a real visual identity: a hand-authored SVG logo in the app's CRT-green palette, shown in the navbar beside `[ QUEUELAB ]`, set as the browser favicon, and with a GitHub repo link added to the nav.
- **Rough scope:** QueueLab `frontend/` — a new logo SVG asset, `src/Layout.tsx` (navbar mark + GitHub nav link), `index.html` (favicon `<link>`, currently absent). Keep within the existing Tailwind token system (`text-accent`, no hardcoded hex in components, no rounded corners).
- **Open questions / decisions for stakeholders:** none expected — palette, placement, and the GitHub URL are settled above.
- **Depends on:** none.
- **Implementation notes:** _none yet_

## Epic 2 — Portfolio entry on joeys-hub

- **Goal:** A QueueLab card appears on the joeys-hub portfolio under "Scalable System Design MVPs" beside LinkShrink, with the Epic-1 logo as its image, short/fun system-design copy, and links to the live app and the repo.
- **Rough scope:** joeys-hub `joeyshub/src/data/projectsDataset.js` (new project object in the `scalable-system-design-mvps` category) and `joeyshub/public/images/` (the logo-derived square image). Follows the existing project-object shape (`imageSrc`, `header`, `paragraph1-3`, `links[]`).
- **Open questions / decisions for stakeholders:** none expected — category, copy angle, links, and "no demo caveat" are settled.
- **Depends on:** Epic 1 — reuses the same logo asset as the card image (`imageSrc`), so the asset must exist first.
- **Implementation notes:** _none yet_
