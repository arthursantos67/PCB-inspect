# Accessibility Audit — FE-10, Issue #24

Full accessibility pass across all Phase-1 screens (login, dashboard, ingestion, inspection
detail, search/history), verifying the cross-cutting FE-10 requirement holistically rather than
per-screen. Scope and acceptance criteria: see the issue body ("[Feature] Full accessibility pass
across Phase-1 screens (FE-10)"). This document records what was found, what was fixed, and what
was verified as already correct, plus the automated regression guards added to CI.

## Method

- Manual read-through of every Phase-1 screen and shared component (`AppShell`, `FilterBar`,
  `InspectionTable`, `AnnotatedImageViewer`, `DetectionsPanel`, badges, charts).
- Automated scans via `@axe-core/playwright` (WCAG 2.1 A/AA rule set) wired into the existing
  Playwright e2e suite, which already drives every Phase-1 screen through the real app.
- A dedicated keyboard-only run of the golden path (login → ingest → dashboard →
  search/filter → detail) using `.focus()` + `keyboard.press(...)` instead of `.click()`
  throughout, so reachability and operability are both exercised, not just visual appearance.
- Manual viewport sweep at desktop (1280×800) and two tablet sizes (834×1194 portrait,
  1024×768 landscape) across all five screens, screenshotted and checked for horizontal
  document overflow (`scrollWidth > clientWidth`).

## Findings and fixes

### 1. No skip link / no way to bypass the sidebar nav (AppShell)
Keyboard and screen-reader users had to tab through all 6 nav items on every single page before
reaching page content. Added a "Skip to main content" link as the first focusable element
(visually hidden until focused), landing on a newly-added `id="main-content"` /
`tabIndex={-1}` on `<main>`. Verified as the very first Tab stop after login in
`e2e/accessibility-keyboard.spec.ts`.

### 2. No indication of the current page in the nav
The active nav item was styled identically to the rest (`text-muted-foreground`), with no
`aria-current`. Fixed: active link now gets `aria-current="page"` plus a visible
background/text treatment, computed from `usePathname()`.

### 3. Nav landmark had no accessible name
Added `aria-label="Primary"` to the `<nav>` in `AppShell` — there's no `<header>`-level nav
elsewhere, but a named landmark still helps screen-reader users jump directly to navigation.

### 4. Live-updates connection badge wasn't announced
The "live updates: connecting/connected/reconnecting/not connected" badge in the header changes
state without user action; added `aria-live="polite"` so a screen-reader user is told when the
connection drops or recovers, not just sighted users watching the badge color/text change.

### 5. Missing page-level headings (Dashboard, Ingestion, Login)
`Inspections` and the inspection detail screen already had a visible `<h1>`; Dashboard and
Ingestion had none (content started directly with cards), and Login relied entirely on a
`CardTitle` (renders as a `<div>`, not a heading). Screen-reader users navigating by heading
have no way to identify these pages. Fixed:
- Dashboard and Ingestion: added a visible `<h1>` + one-line description, matching the existing
  pattern on `Inspections`/detail.
- Login: added a visually-hidden `<h1>PCB-Inspect</h1>` (kept the visible `CardTitle` as-is,
  since "Sign in" / "Set up PCB-Inspect" already reads correctly for sighted users and a second
  visible heading would just duplicate it).

### 6. Ad hoc import dropzone was mouse/pointer-only
`frontend/src/app/(app)/ingestion/page.tsx` — the "Drop image files here, or click to choose"
box was a bare `<div onClick>` with no `tabindex`, `role`, or key handling: a keyboard user
could never reach it, let alone open the file picker. This is a real gap in the "every
interactive element... reachable and operable via keyboard alone" acceptance criterion. Fixed:
added `role="button"`, `tabIndex={0}`, an `aria-label` (the accessible name now used in the new
keyboard e2e test), a focus-visible ring, and an `onKeyDown` handler for Enter/Space.

### 7. Annotated image viewer: zoom had no keyboard-reachable pan
`AnnotatedImageViewer` already had fully keyboard-operable zoom in/out/reset buttons and
per-detection bounding-box buttons (both pre-existing and correct), but panning was
pointer-drag only. Once zoomed in, a keyboard-only user had no way to see the parts of the image
that scrolled out of the visible frame — a real dead end for exactly the interaction this
issue's scope calls out by name ("image viewer zoom/pan"). Fixed: the viewer's group container
is now focusable (`tabIndex={0}`) and handles arrow keys (pan in 40px steps) and Home (reset
zoom/pan) whenever `scale > 1`; the container's `aria-label` grows a
"— use arrow keys to pan, Home to reset" suffix in that state so screen-reader/keyboard users
discover the capability without needing sighted trial-and-error.

### 8. Charts had no accessible summary
`DefectTrendChart` and `DefectDistributionChart` render an SVG via Recharts with no text
alternative for screen-reader users — the legend/tooltip/bar labels are all real DOM text (good,
verified in finding #10), but a screen reader landing on the chart region itself got nothing.
Added `role="img"` + a descriptive `aria-label` to each chart's container div.

## Verified as already correct (no fix needed)

- **Text labels for color-coded indicators (AC3):** `DefectBadge`, `SeverityBadge`,
  `StatusBadge` all already pair a color swatch (or badge variant) with a plain-text label —
  color is never the sole carrier of meaning. The `ClassLegend` in the image viewer does the
  same. Verified comprehensively across dashboard, table, viewer, and detections panel; no
  color-only indicator found anywhere in the Phase-1 surface.
- **Bounding-box overlay ARIA (AC4):** each detection box is a real `<button>` with a
  descriptive `aria-label` ("Detection N: <class>, X% confidence"), `aria-describedby` pointing
  at a `role="tooltip"` element, and visible focus styling. Screen-reader spot check (VoiceOver
  via macOS-style AT walkthrough is not available in this Linux dev environment; verified
  instead via the accessibility tree exposed to Playwright/axe, which resolves each box's
  accessible name and role exactly as an AT would) confirmed each box announces correctly.
- **`FilterBar` (AC4):** the defect-type checkbox group already uses `role="group"` +
  `aria-labelledby`; every text/select/date field has a proper `<Label htmlFor>`. No gaps.
- **Processing stepper (AC4):** the inline stepper on the detail screen (`ProcessingStepper` in
  `inspections/[id]/page.tsx`) already uses an `<ol>` with `aria-current="step"` on the active
  step — correct semantics, no fix needed.
- **Tables (AC4):** `InspectionTable` renders a real `<table>`/`<thead>`/`<tbody>` via the
  shared `Table` primitives (not styled `div`s), so row/cell semantics are correct for free.
  The whole-row `onClick` navigation has no keyboard handler of its own, but the board number in
  every row is a real `<Link>` reachable and operable by keyboard to the same destination — the
  row click is a mouse-only convenience layered on top of an already-keyboard-complete path, not
  a dead end.
- **Color contrast (AC2):** theme tokens (`globals.css`) use near-maximum-contrast
  foreground/background pairs in both light and dark mode; the categorical/status color palettes
  are only ever used as small decorative swatches (`aria-hidden`) next to text, never as text
  color or as the sole background behind body text. The automated axe scan (WCAG AA tag) found
  no contrast violations on any screen.
- **Native form controls:** `<select>`, `<input type="date">`, checkboxes, and all shadcn
  `Button`/`Input`/`Label` primitives already carry correct implicit roles, labels, and
  `focus-visible` treatment from the design system — no per-screen gaps found.

## Automated regression guards added to CI

All added to the existing `e2e` CI job (`.github/workflows/ci.yml`) — no new job needed, since
it already brings up the full stack (Postgres, Redis, API, fake-backend inference worker,
frontend) that these checks need.

1. **`frontend/e2e/a11y.ts`** — shared `assertNoA11yViolations(page, screenName)` helper,
   scans with `@axe-core/playwright` against the WCAG 2.1 A/AA rule set, fails on any
   `critical`- or `serious`-impact violation (stricter than the AC's "no critical violations"
   floor, since most real WCAG AA failures surface as "serious").
2. Wired into the existing golden-path specs at the point each screen is reached:
   `e2e/inspection-flow.spec.ts` (login, dashboard, ingestion, inspection detail) and
   `e2e/inspection-search.spec.ts` (search/history).
3. **`frontend/e2e/accessibility-keyboard.spec.ts`** (new) — the AC1 golden path
   (login → ingest → dashboard → search/filter → detail) driven entirely via `.focus()` +
   `keyboard.press(...)`, never `.click()`. Explicitly asserts: the skip link is the first Tab
   stop after login, the ad hoc-import dropzone is keyboard-focusable (regression guard for
   finding #6), the annotated-image bbox button and zoom/pan controls are keyboard-operable
   (regression guard for finding #7), and the full path reaches the detail screen with no dead
   end.

Together these run on every PR and push to `main`, so a future regression in contrast, missing
labels, or keyboard-reachability on any Phase-1 screen fails CI rather than shipping silently.

## Not fixed (explicitly out of scope)

The primary nav (`AppShell`) includes `Chat`, `Reports`, and `Settings` links that route to
pages not yet built (Phase 2/3 per the PRD roadmap, section 15). A keyboard or screen-reader
user tabbing to one of those today reaches a 404 — a real dead end, but not a Phase-1
regression: the golden path this issue's AC1 defines (login → ingest → dashboard →
search/filter → detail) never touches them, and disabling/hiding them now is a product
decision for whoever picks up those issues, not an accessibility fix. Flagging here so it isn't
lost.
