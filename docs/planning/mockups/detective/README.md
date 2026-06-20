# Detective mockups

Static, browser-openable design mockups for the
[Detective feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_DETECTIVE.md).

These files cover the **Detective MVP and key post-MVP investigation surfaces**
across all six epics: Foundations & Correlation Fabric (Epic 1), Database
Instance Forensics (Epic 2), ETL & Migration Forensics (Epic 3), Investigation
Experience (Epic 4), Integrity, Anomalies & Policy Signals (Epic 5), and
Exports, Compliance & Operations (Epic 6). They are visual references — no
API calls, no auth, no build step.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/detective/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/detective/index.html
```

## Files

| File                       | Maps to roadmap issue                                            |
| -------------------------- | ---------------------------------------------------------------- |
| `index.html`               | Mockup hub linking to all screens                                |
| `dashboard.html`           | Detective home · open critical alerts, integrity summary (5.1, 6.2) |
| `instance-timeline.html`   | 4.1 Detective Panel · 2.1 enrichment · 2.3 history filters       |
| `version-compare.html`     | 4.2 Side-by-Side Version Compare                                 |
| `lineage-graph.html`       | 4.3 Lineage Mini-Graph · 3.2 file fingerprinting & provenance    |
| `pipeline-runs.html`       | 3.1 Pipeline Run Registry · 3.3 Migration↔Instance · 3.4 Handoff |
| `investigations.html`      | 4.4 Saved Investigations & Annotations                           |
| `reconciliation.html`      | 5.1 Reconciliation Reports · 5.2 Anomaly Hints · 2.4 Replay      |
| `exports.html`             | 5.3 Integrity Checksums · 6.1 Auditor Export API · 6.2 Permissions |

## Design system

Mockups intentionally mirror the live `objectified-ui` shell and align with the
sibling `mockups/architect`, `mockups/academy`, and `mockups/analytics` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, IDs, hashes,
  correlation IDs, and JSON Pointer paths
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 260 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `detective-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Detective-specific visual language

Beyond the shared shell, the Detective mockups introduce a few forensic-UI
conventions that the production build is expected to honor:

- **Brand mark**: `fingerprint` lucide icon in indigo-to-purple gradient — used
  in the platform bar and the index hub.
- **Action badges**: `CREATE` (emerald), `UPDATE` (sky), `DELETE` (rose),
  `BULK_IMPORT` (purple), `MIGRATION_STEP` (indigo), `ROLLBACK` (amber). All
  appear as small uppercase JetBrains-Mono pills in the timeline.
- **Actor chips**: avatar + display name + actor type badge. `user` gets a
  filled circle, `api_key` gets a 🔑 with a masked `…7e3f` suffix, `system`
  gets a ⚙ glyph, `service` gets a server glyph. Deleted actors render in
  italic gray as "Deleted user".
- **Anomaly hints**: yellow ⚠ chips next to flagged events with `low | medium`
  confidence — never `high`, per the roadmap copy guidance (Epic 5.2).
- **Integrity dots**: emerald `verified`, amber `warn`, rose `critical`; gray
  `unverified` for instances never replayed.
- **Source-file hash status**: emerald `verified`, rose `modified`, slate
  `unknown`. Always rendered alongside the truncated SHA-256.
- **Diffs**: Monaco-style green-add / red-remove rails, with JSON Pointer
  breadcrumbs above each changed key.
- **Lineage canvas**: `instance` nodes (rounded-lg), `pipeline_run` nodes
  (rounded-lg with workflow icon), `source_file` nodes (rounded-md, dashed
  violet border for "modified" status), `migration_run` nodes (rounded-lg
  with route icon).

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1 px border + indigo text + a small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from `dashboard/page.tsx`

## What's intentionally faked

- All instances, audit events, pipeline runs, hashes, and correlation IDs are
  hard-coded
- Time pickers, actor search, and path autocompletes are visual only
- The lineage graph nodes are absolutely positioned — no React Flow runtime
- The Monaco diff is hand-drawn HTML, not the real editor
- The reconciliation sparkline uses inline SVG with static points
- The theme toggle is the only piece of working JS (plus Lucide icon hydration)

## Out of scope (not included)

These belong to backend-only work or to later phases of the roadmap and were
excluded from the mockup set:

- 1.1 Detective Audit Event Model (DDL + OpenAPI components — schema-only)
- 1.2 Correlation & Tracing Standards (middleware-only; surfaces in timeline)
- 1.3 Append-Only Audit Storage (DB role policy; surfaced as retention card on
  reconciliation page)
- 1.4 Actor Resolution & Display Policy (resolver — every actor chip in the set
  shows the result)
- 2.2 Field-Level Change Index (storage layer — surfaces as the path filter on
  the timeline)
- 2.3 Instance History API contract (the timeline page is the consumer)
