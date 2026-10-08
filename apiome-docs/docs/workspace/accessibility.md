---
title: "Accessibility"
description: "The WCAG 2.2 AA contract, the CI axe gate and screen-reader checklist."
sidebar_position: 11
tags: [accessibility]
---

Apiome's web app (`apiome-ui`) targets **WCAG 2.2 AA** everywhere and **AAA text contrast in the
High contrast theme** (`docs/mockups/DESIGN.md` §9). This page is the contract, how it is
checked, and the manual screen-reader checklist.

For using the app without a mouse, see [Keyboard](./keyboard.md).

## The contract

| Promise | How it is held |
|---|---|
| Zero serious/critical axe violations on every redesigned page, in light, dark and High contrast | The CI axe gate (below) |
| Text at 4.5:1 (7:1 in High contrast), large text and marks at 3:1, in every theme | `apiome-ui/tests/a11y-token-contrast.test.ts` — the token contrast gate |
| Every overlay traps focus while open and returns it on close; no keyboard trap anywhere | `apiome-ui/e2e/a11y/keyboard.spec.ts` |
| Pointer targets of at least 44 px in comfortable density (24 px in compact) | `.hit-target` in `globals.css`; `tests/a11y-hit-target.test.ts` and the gate's in-browser probe |
| Save state, async jobs and bulk results are announced | `ui/LiveRegion` + `lib/a11y/announcements.ts` |
| Motion follows `DESIGN.md` §3.4: 120 / 180 / 260 ms, one easing, nothing longer than 260 ms but the mockups' own loading loops; no animation blocks a click | `apiome-ui/tests/motion-pass.test.ts`; `e2e/a11y/motion.spec.ts` measures what the browser runs |
| Reduced motion is respected, in CSS and in script — state changes are instant and loops stop | the `data-motion` / `prefers-reduced-motion` rules in `globals.css` (zero durations, one iteration); `lib/motion.ts` for scroll and canvas animation |

## The axe gate (CI)

`.github/workflows/apiome-ui-a11y.yml` runs `yarn test:e2e:a11y` (`apiome-ui/playwright.a11y.config.ts`)
on every change to `apiome-ui/`. It needs no database and no session:

- **`e2e/a11y/routes.ts`** is the ledger: every redesigned page mockup names how it is checked —
  committed **fixtures** (jsdom dumps mounted into `/login`, every file in the directory gated),
  a signed-out **route** (`/login`, the `/design-system` galleries), or an inline-markup **spec**
  file. `tests/a11y-routes.test.ts` fails if a redesigned mockup has no entry.
- **`e2e/a11y/gate.spec.ts`** runs axe (WCAG 2.0/2.1/2.2 A + AA tags, including `target-size`)
  over each fixture and route in light, dark and High contrast, at comfortable density and the
  default font scale, and probes the 44 px hit areas.
- **`e2e/a11y/keyboard.spec.ts`** walks every live route with Tab and opens the drawer, a dialog and
  the command palette from the keyboard.
- **`e2e/a11y/sr-smoke.spec.ts`** pins what a screen reader is given on login, home and a
  dialog (projects is pinned in `e2e/hive-projects.spec.ts`).

### Running it locally

`next dev` can serve a stale CSS chunk after a `globals.css` edit, which makes axe pass or fail
for the wrong reason. Run the gate against a production build:

```bash
cd apiome-ui
yarn build
npx next start -p 3200 &          # the a11y config reuses a server already on :3200
yarn test:e2e:a11y                # or: npx playwright test -c playwright.a11y.config.ts e2e/a11y
```

### Adding a page

1. Dump fixtures from the page's Jest suite (the `*_FIXTURE_DUMP=1` pattern, or
   `writeA11yFixture()` from `tests/helpers/a11y-fixture-dump.ts`), **or** give the page a
   signed-out route, **or** keep its markup in its own spec and import `WCAG_TAGS` /
   `GATE_THEMES` from `e2e/support/a11y.ts`.
2. Add one entry to `A11Y_ROUTES` in `e2e/a11y/routes.ts`.
3. When a shared primitive changes, re-dump the fixtures so the gate checks today's markup.

## The token contrast gate

`tests/a11y-token-contrast.test.ts` resolves every token pair under all eight palettes (the ninth
theme, *System*, resolves to one of them) and checks it the way a reader sees it — translucent
chips composited over the card, page, toolbar and footer backgrounds they sit on — with a small
margin above each threshold so it never passes a pair the browser would fail.

- **Text tokens** — `--fg`, `--fg-muted`, `--fg-subtle`, every `-fg` ink, `--accent-fg` (link text),
  `--ink-fg`, `--honey-ink`, `--fg-on-accent` on a danger button: 4.5:1, 7:1 in High contrast.
- **Marks** — `--accent`, `--ok`, `--warn`, `--danger`… (dots, bars, icons, the solid edge of the
  focus ring): 3:1.
- **`--fg-faint`** is the disabled/decorative tier and is not used for text a reader needs.
- **Deviations** — a pair that cannot move without breaking the design goes in `DEVIATIONS` with
  a reason. The ledger is exact both ways: a new failure fails, and so does an entry that now
  passes. High contrast text can never be excused.
- **Mark hues as small text** (`text-warn`, `color: var(--accent)`) are counted against a locked
  baseline that may only go down; new small text uses the `-fg` ink.

## Screen-reader checklist (manual)

Run before a release with VoiceOver (macOS: `⌘ F5`) or NVDA (Windows), in a production build.
The automated smoke pins the structure; this pass is about what is *heard*.

| Page | Check |
|---|---|
| **Login** (`/login`) | One `main` landmark; “Welcome back, heading level 1”; the sign-in buttons by name (“Continue with GitHub”…); a failed sign-in is announced as an alert. |
| **Home** (`/ade`) | Heading “Your API specification workspace”, level 1; regions “Applications” and “Resources” with level-2 headings; each application link names its destination; “Opens in a new tab” is read for external links. |
| **Projects** | Heading “Projects”; the “Show soft-deleted projects” switch reads its state; the search box is “Filter projects”; the table is “Projects in this workspace” with column headers; row checkboxes are “Select \<project\>”; typing in the filter announces the result count in the palette. |
| **A dialog** (e.g. delete a role) | Announced as an alert dialog with its question as the name; focus starts on **Cancel**; `Esc` closes it and focus returns to the button that opened it. |

Also confirm on any page: the skip link is the first `Tab` stop; status changes (“Import running:
step 3 of 8”, “All changes saved”, “acme/api is ready”) are spoken without moving focus.
