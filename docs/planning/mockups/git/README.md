# Git-like mockups

Visual preview of the Objectified Git-like workflow, drawn from the two
roadmaps:

- `docs/FUTURE_FEATURE_ROADMAP_GITLIKE.md` (P0 → P2 — commit, push,
  pull, merge, history, rollback, audit, branch protection, draft
  locking, webhooks, compatibility checks)
- `docs/FUTURE_FEATURE_ROADMAP_GITLIKE_IMPROVEMENTS.md` (GLI-01 → GLI-10 —
  default branch, branch picker chip, divergence chip, prominent commit
  button, sync-from-main, branch status popover, branch protection UI,
  recent activity ticker, command palette)

These are static HTML mockups — no React, no API calls — used to align
on UI direction before coding production components in
`objectified-ui/src/app/components/ade/...`.

## Stack

- Tailwind via CDN (`tailwind.config = { darkMode: 'class' }`)
- Inter (UI) + JetBrains Mono (`.mono`) from Google Fonts
- Lucide icons via `<i data-lucide="…">` + `lucide.createIcons()`
- Theme toggle persists to `localStorage` under `git-mockup-theme`

Match the existing `mockups/devex/` style: indigo accent, slate gray
scale, gradient sidebars, panel cards, dark-mode-first.

## Running locally

Open any file directly in a browser, e.g.:

```bash
xdg-open objectified-ui/public/mockups/git/index.html
```

…or visit `http://localhost:3000/mockups/git/` once the Next.js dev
server is up — `public/` is served as static assets.

## Pages

| File              | Roadmap items                                   | What it shows                                                                 |
|-------------------|-------------------------------------------------|-------------------------------------------------------------------------------|
| `index.html`      | hub                                             | Cards grouped by epic, links to every page below.                            |
| `canvas.html`     | GLI-03/04/05/07/09                              | Designer canvas chrome: branch picker chip, divergence chip, prominent commit button, branch status popover, recent activity ticker. |
| `commit.html`     | P0-01/02, P2-08                                 | Commit dialog with message + body + reference + version bump, policy checks, compatibility report with breaking-change override. |
| `conflict.html`   | P0-03, P2-02/03                                 | Stale-head push rejection, draft lock takeover modal, active locks ledger, live presence on canvas. |
| `branches.html`   | GLI-01/02/08, P2-01                             | Default branch hero, protection badges, branch table with divergence + lock states, side panel for protection settings. |
| `merge.html`      | P1-01/02/03/04, GLI-06                          | Sync-from-main flow: merge preview summary, conflict list with bulk mine/theirs/manual, side-by-side diff, gated "Apply merge". |
| `history.html`    | P1-07/08, P0-09                                 | Revision timeline graph + filterable table, compare-with-current preview, context menu (branch from here, rollback to here). |
| `rollback.html`   | P1-09/10                                        | Preview impact (+/~/-), required reason, AlertDialog confirmation, resulting audit event. |
| `audit.html`      | P1-05/06                                        | Workflow audit ledger with action/actor/outcome filters, summary stats, paginated table + JSON payload drawer. |
| `webhooks.html`   | P2-05/06                                        | Push subscriptions list, dead-letter queue with replay, retry policy timeline, delivery attempts table, signed payload sample. |
| `palette.html`    | GLI-10, P2-09/10                                | ⌘K command palette overlay, headless pull preview (diff-only), conditional fetch with ETag, recent palette runs. |

## Conventions

- **Top bar**: 48px tall, breadcrumb + theme toggle + avatar.
- **Sidebar**: 260px wide, gradient background, four sections (Workflow,
  Branches, History, Enterprise). Active item gets indigo border + dot.
- **Page header**: 24px title with a Lucide icon, one-line subtitle.
- **Panel cards**: `rounded-lg border bg-white/dark:bg-gray-800` with a
  gray header row containing an indigo icon.
- **Mono spans** (`.mono`) for IDs (`r-91a2c4e`), API paths
  (`POST /v1/...`), branch names, audit action names.
- **Status colors**: emerald = success/active, indigo = primary/info,
  amber = warning/degraded, rose = error/breaking, cyan = modified, slate
  = neutral/disabled.
- **Roadmap tags**: small uppercase pills like `P2-08` or `GLI-10`
  next to features so reviewers can map mockup → ticket quickly.

## Updating

When a roadmap item ships, either:

- update the matching mockup so it reflects the final design (and tag
  the heading `Shipped`), or
- delete the mockup if it has been superseded by a newer screen.

Don't let mockups go stale — they are reference material for review and
onboarding, not historical artifacts.
