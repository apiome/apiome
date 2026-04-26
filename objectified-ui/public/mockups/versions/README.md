# Versions mockups

A polished, opinionated redesign of the **Versions** surface. Today
versions are reachable only as a sub-tab of a project's detail page
([`VersionsTab.tsx`](../../../src/app/components/ade/dashboard/projectDetail/VersionsTab.tsx))
and there is no top-level entry from the dashboard sidebar.

This set proposes a top-level **Versions** entry in the sidebar that
forces the user to **pick a project first** (versions only exist in the
context of a project), then drops them into a polished per-project
versions view.

These mockups live inside the same dashboard chrome as `mockups/projects/`
(top bar, 280 px sidebar, project header for the per-project view).

> **Note.** Anything git-like (branches, side-by-side diff, version
> compare, reviewer/PR workflow, channels-as-tags) is intentionally
> deferred. The mockups focus on what's intrinsic to a single version:
> **lifecycle, quality, history.**

## Files

| File             | Status   | What it covers |
| ---------------- | -------- | -------------- |
| `dashboard.html` | ✅ done | **Project picker (entry point).** Renders when the user clicks `Versions` in the sidebar with no project selected. Page header (title + description + cards/table view switcher + ⌘K filter). Portfolio KPI band (Total versions across all projects · Drafts in flight · Published in 30d · Sunset risks). Filter chips (All · Mine · Starred · Has drafts · Sunset risk · Lint regression) + sort. 3-column project picker grid: each card shows project avatar + name + domain + contributors, a "headline" status chip (`sunset 14d`, `3 drafts`, `lint −1`, `stable`, `idle`), latest semver + age, quality ring, a 4-cell mini-grid (Total/Drafts/Pub/Dep counts), a tone-coded sparkline, and a `View versions →` CTA that fills indigo on hover. The whole card links to `detail.html`. |
| `detail.html`    | ✅ done | **Per-project versions.** Reached after picking a project from `dashboard.html` (or via the project's Versions tab). Sub-page header (counts + actions: Export bundle · New version). 4-card KPI band: Latest published · Drafts in flight · Avg quality (with sparkline) · Sunset risk (countdown). 4-column lifecycle pipeline: Draft → Published → Deprecated → Sunset, with rich version cards (semver · message · quality ring · author · sunset progress bar). Quality trajectory chart. Filter chips toolbar. Versions table (Version · Status · Schema size · Quality · Lint · Author · Updated · row actions). Right rail: selected-version compact (metadata · quality+lint scorecards · changelog · View detail / Deprecate actions), lifecycle alerts (sunset countdown · lint regression), recent activity timeline. Kanban cards, table rows, and the "View detail" CTA all drill into `version.html`. |
| `version.html`   | ✅ done | **Single version detail.** Reached by clicking a kanban card, table row, or "View detail" on `detail.html`. Version sub-page header (semver, status pill, lineage chip, schema-size chip, summary, actions: Export · Edit notes · Deprecate · Schedule sunset). 6-cell hero metadata strip (Author · Created · Published · Lineage · Sunset · Quality at-a-glance). Two-column body: **left** has Quality scorecard (ring + sub-scores: completeness/consistency/descriptions/examples + delta vs. parent), Lint scorecard (grade + E/W/I counts + top findings), Schema scope (Classes/Properties switcher + change-tag chips + table with `added`/`modified`/`unchanged`), and full Release notes (markdown look). **Right rail** has Lineage rail (parent → this → child draft), Lifecycle history timeline (Draft created → Lint passed → Published), and Activity scoped to this version. |

## Open

```
open objectified-ui/public/mockups/versions/dashboard.html
```

Or, with the Next.js dev server running:

```
http://localhost:3000/mockups/versions/dashboard.html
```

## Flow

```
sidebar "Versions"  →  dashboard.html  →  pick a project  →  detail.html  →  version.html
                                                         ↘                ↘
                          projects/detail.html → Versions tab    ↑ kanban card / row / "View detail"
```

The detail view is the same surface whether you arrive via the picker
or via the per-project tab. The only difference is which sidebar item is
highlighted on the way in. From `detail.html`, every version card on the
kanban, every row in the table, and the right-rail "View detail" button
all drill into `version.html`.

## Mental model

A **version** is a snapshot of the project's schema at a point in time.
Versions move through a simple **lifecycle**:

```
Draft  →  Published  →  Deprecated  →  Sunset
```

- **Draft.** Work in progress; not yet visible to consumers.
- **Published.** Live and consumable. Multiple Published versions can
  coexist (e.g. v2.4.x patch line + v2.5.0).
- **Deprecated.** Still consumable but discouraged; consumers should
  migrate. Schema is frozen.
- **Sunset.** Scheduled for removal on a specific date. The workspace
  surfaces a countdown and the list of consumers still pinned to it,
  with a "Notify consumers" affordance.

Versions belong to a **project** by relation — there is no global
versions list. The picker enforces this: pick a project, then look at
its versions.

## Visual language

Inherits from `mockups/projects/`:

- **Status pills:** Draft = slate · Published = emerald · Deprecated =
  orange · Sunset = rose.
- **Quality ring:** ≥ 90 emerald · 75–89 indigo · 60–74 amber · &lt; 60
  rose. Drafts without a score show `—`.
- **Lint grade:** single letter (A · B · C · D) with `0E · 2W` count next
  to it. Tone matches the ring tier.
- **Sunset:** rose progress bar on the kanban card, rose 3px inset bar
  on the table row, rose lifecycle-alert tile, rose-bordered project
  card on the picker.
- **Project avatar:** deterministic gradient (indigo→purple,
  emerald→cyan, amber→orange, etc.) — matches the convention used in
  `projects/dashboard.html`.

## What's intentionally faked

- All projects, versions, scores, consumers, and activity are
  hard-coded.
- Trajectory and sparkline SVGs are static — no live history.
- The lifecycle pipeline implies drag-to-promote, but no JS is wired up;
  the action menu (`…`) is the real path for now.
- Filter chips, search inputs, sort dropdown, and view switchers do not
  filter the rendered set.
- Theme toggle (persisted under `versions-mockup-theme`) and Lucide icon
  hydration are the only working JS.

## Out of scope (for now, by request)

- **Anything git-like** — no branches, no version compare/diff, no
  reviewer/approver workflow, no channels-as-tags, no breaking-change
  detector. These will be added in a later iteration.
- The **publish flow** modal (target audience, dry-run lint, schedule).
- The **schedule sunset** modal (date picker, consumer notification
  draft, migration-guide link).
- A **table view** for the picker — only the cards view is mocked.
