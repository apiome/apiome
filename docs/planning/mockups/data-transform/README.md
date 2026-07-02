# Data Transform mockups

Static, browser-openable design mockups for the
[Data Transform &amp; Schema Migration roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_DATA_TRANSFORM.md).

These files cover the full MVP surface area across all six epics:
Schema Comparison &amp; Compatibility (Epic 1), Data Translation Rules
(Epic 2), Major Version Safeguards (Epic 3), Visual Migration Step Plans
(Epic 4), MongoDB as Interim Store (Epic 5), and Apache Spark for Parallel
Migration (Epic 6). They are visual references — no API calls, no auth,
no Spark cluster, no real MongoDB, no schema diffing engine, no build step.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/data-transform/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/data-transform/index.html
```

## Files

| File                          | Maps to roadmap issue                                                                          |
| ----------------------------- | ---------------------------------------------------------------------------------------------- |
| `index.html`                  | Mockup hub linking to all screens, grouped by epic                                              |
| `dashboard.html`              | Transform overview — active migrations, throughput, blocking conditions, recent runs            |
| `compatibility-report.html`   | 1.1 Schema Diff Engine — class &amp; property-level diff between two captures                   |
| `deletion-policy.html`        | 1.2 Property Deletion Policy — strict, report-only, allow-list with unresolved drops queue      |
| `blocking-conditions.html`    | 1.3 Blocking Conditions + 3.2 Blocking Resolutions — list and resolve conditions blocking a run |
| `rule-sets.html`              | 2.2 Rule Set list &amp; versioning — published, draft, and reusable templates                  |
| `rule-editor.html`            | 2.1 Translation Rule Definition + 2.2 Rule authoring — per-class rule editor with live preview  |
| `migration-plans.html`        | 4.1 Migration Plan list — capture pair, rule set, engine, state, last run                       |
| `migration-plan-detail.html`  | 4.2 Step plan + 4.3 Visual flow — export → transform → load → verify with running step drawer   |
| `version-policy.html`         | 3.1 Major Version Safeguards — transition matrix, approver requirements, audit                  |
| `interim-store.html`          | Epic 5 — MongoDB raw / transformed / errors collections, retention, sample document             |
| `spark-jobs.html`             | Epic 6 — submitted jobs, executor heatmap, DAG, submission form, when-to-use guidance           |

## Design system

Mockups intentionally mirror the live `apiome-ui` shell and align with
the sibling `mockups/academy`, `mockups/analytics`, `mockups/architect`,
`mockups/automation`, `mockups/code-gen`, `mockups/collaboration`, and
`mockups/connect` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for plan IDs,
  rule set IDs, capture versions, collection names, app IDs, sample
  documents, and stats
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set —
  brand mark is `git-compare-arrows` for the Transform feature
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `data-transform-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Data Transform-specific visual language

Beyond the shared shell, the Data Transform mockups introduce a few
conventions that the production build is expected to honor:

- **Compatibility classification pills**: `additive` = emerald,
  `breaking` = rose, `requires-rule` = amber, `unchanged` = gray. Used on
  every diff row in `compatibility-report.html` and on the per-class summary
  table on the same page.
- **Rule type chips**: `copy` = slate, `expression` = indigo,
  `type-coerce` = purple, `default` = sky, `null` = gray,
  `accepted-drop` = amber. Shown in `rule-editor.html` and in the rule
  count breakdown on `rule-sets.html`.
- **Stage badges (interim store / step plans)**: `raw` = sky,
  `transformed` = purple, `errors` = rose. Used wherever an interim
  collection is referenced.
- **Plan / run state badges**: `Draft` = gray, `Queued` = blue,
  `Executing` / `Running` = indigo (with pulsing dot), `Paused` = amber,
  `Verified` = emerald, `Rolled back` = rose, `Failed` = rose,
  `Blocked` = rose with `shield-alert` icon.
- **Step nodes (visual flow)**: each step renders as a rounded card with a
  coloured top stripe matching its state — completed steps use emerald,
  the active step uses indigo with a 2 px ring, pending steps use gray.
  Connector arrows are SVG with state-coloured strokes; running edges are
  dashed and indigo.
- **Engine icons**: `cpu` = in-process engine, `zap` = Spark engine.
  Shown beside every plan and every job.
- **Sync direction inside a plan**: `arrow-down` is used to indicate the
  data flow between source PostgreSQL → MongoDB → target PostgreSQL on
  the interim store schematic.
- **Approval state pills (version policy)**: `allow` = emerald,
  `review` = amber, `approval` = rose, `blocked` = gray. Cells with an
  override are rendered with a 2 px indigo ring and a trailing `*`.
- **Executor heatmap (Spark)**: 14 × 14 px squares per executor, coloured
  `#e2e8f0` idle, `#a5b4fc` active, `#6366f1` hot, `#f43f5e` failing.
- **Health status pills**: traffic-light language consistent with
  `mockups/connect` and `mockups/automation` — `Healthy` = emerald,
  `Degraded` = amber, `Unhealthy` = rose, paired with a 1.5 × 1.5 px dot.

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10 % indigo fill + 1 px border + indigo text + a small
  dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- Status pills mirror those in `mockups/automation/integrations.html` and
  `mockups/connect/connections.html`

## What's intentionally faked

- All captures, classes, properties, rule sets, rules, plans, runs, blocking
  conditions, version policy entries, audit events, MongoDB collections,
  sample documents, and Spark jobs are hard-coded
- Diff counts, KPI numbers, progress bars, throughput counters, executor
  heatmap cells, replica lag, and DAG state are static
- The visual flow page connectors, ring states, and pulsing dot are static
  CSS / SVG — there is no live polling
- The "Save policy", "Approve", "Submit job", and "Resume" buttons do not
  trigger anything
- The matrix overrides on `version-policy.html` are visual only
- The theme toggle and Lucide icon hydration are the only working JS

## Out of scope (not included)

These either belong to later phases of the roadmap or are admin surfaces
that don't need a dedicated screen in the MVP mockup set:

- The schema diff engine internals (graph traversal, AST output) — surfaced
  only via the rendered report on `compatibility-report.html`
- The rule set publish / signing pipeline UI — represented as a single
  `Publish` CTA on `rule-sets.html` and `rule-editor.html`
- Kubernetes operator + autoscaler UIs for the Spark cluster — the
  `spark-jobs.html` page assumes the cluster is already running
- MongoDB shard topology, oplog tail, and backup / restore admin views —
  the `interim-store.html` page focuses on the migration-facing usage
- Source / target connection settings (PostgreSQL credentials, vault
  binding) — assumed inherited from existing platform settings
