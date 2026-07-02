# Database mockups

Static, browser-openable design mockups for the
[Database feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_DATABASE.md).

These files cover the full roadmap surface area across all six epics:
Schema Capture &amp; Storage Foundation (Epic 1), Instance Lifecycle &amp;
Event-Sourced Writes (Epic 2), Read &amp; Query API (Epic 3), Search &amp; AI
Augmentation (Epic 4), Bulk &amp; Batch Operations (Epic 5), and Governance,
Tenancy &amp; Tiered Storage (Epic 6). They are visual references — no API
calls, no auth, no Docker runtime, no real Postgres or Redis or MongoDB.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/db/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/db/index.html
```

## Files

| File                       | Maps to roadmap issue                                                                                |
| -------------------------- | ---------------------------------------------------------------------------------------------------- |
| `index.html`               | Mockup hub linking to all screens, grouped by epic                                                   |
| `dashboard.html`           | Database overview — instance count, write volume, read latency, conflict rate, tier distribution     |
| `instance-browser.html`    | 3.1 List / Filter API + 6.4 Column Masking — JSONB filter sidebar, paginated table, masked PII rows  |
| `instance-detail.html`     | 2.1 CREATE + 2.2 UPDATE + 2.4 Optimistic Locking — snapshot view, ETag, event timeline, JSON Patch   |
| `schema-capture.html`      | 1.1 Schema Capture + 1.2 JSON Schema Validation — class registry, properties, indexing, sensitivity  |
| `query-builder.html`       | 3.4 Visual Query Builder — drag-drop class canvas, joins, generated DSL, results pane                |
| `nl-query.html`            | 4.3 Natural-Language Query — prompt input, plan / reasoning, generated DSL, guardrails               |
| `time-travel.html`         | 3.5 Time-Travel Query — AS OF slider, snapshot reconstruction, diff viewer, schema migration trail   |
| `relationship-graph.html`  | 4.2 Relationship Graph Explorer — force-directed graph, depth controls, outgoing / incoming panel    |
| `vector-search.html`       | 4.1 Semantic Search (pgvector) — hybrid query, top-k results, UMAP scatter, index health             |
| `batch-jobs.html`          | 5.1 Bulk Import + 5.2 Bulk Export + 5.3 Async Job Runner — queue stats, active jobs, history         |
| `storage-tiers.html`       | 6.5 Tiered Storage + 6.6 Redis / 6.7 MongoDB Offload — hot / primary / warm / cold flow, policy YAML |
| `audit-log.html`           | 6.2 Audit Log — tamper-evident hash chain, sensitive event filtering, activity histogram             |
| `api-keys.html`            | 6.1 Tenant Isolation + 6.3 API Key Management — keys table, scope picker, rate limits, IP allowlist  |

## Design system

Mockups intentionally mirror the live `apiome-ui` shell and align with
the sibling `mockups/academy`, `mockups/analytics`, `mockups/architect`,
`mockups/automation`, `mockups/browser`, `mockups/code-gen`,
`mockups/collaboration`, and `mockups/connect` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for instance IDs,
  ETags, JSON paths, hash digests, schema IDs, version numbers, and stats
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `db-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Database-specific visual language

Beyond the shared shell, the Database mockups introduce a few conventions
that the production build is expected to honor:

- **Instance ID pills**: monospace, indigo-500 text on a transparent
  background (e.g. `cus_01HK2BR41XF8H`). When truncated, ellipsis goes in
  the middle so the suffix remains visible (`cus_01HK2…XF8H`).
- **Write-action badges**: `CREATE` = emerald, `UPDATE` = indigo,
  `DELETE` = rose, `MIGRATE` = purple, `MERGE` = amber. Matches the colour
  used in event timelines, audit logs, and the dashboard write breakdown.
- **Storage tier pills**: `HOT` = rose, `PRIMARY` = indigo, `WARM` = amber,
  `COLD` = slate. Shown on every storage card, the storage distribution
  table, and the policy YAML preview.
- **Sensitivity tags**: `PII` = amber, `PCI` = rose, `Internal` = gray,
  `Public` = emerald. Appear next to property names in `schema-capture.html`
  and as a column in `instance-browser.html`.
- **Optimistic-lock conflicts**: 409 conflicts show a small amber dot and
  the version pair (`v15 → v16`) so reviewers can spot auto-merged updates.
- **Event timeline (instance-detail)**: vertical bar with one circle per
  version. Circle colour mirrors the write-action badge for that event.
  The current version's row is rendered in indigo + bold.
- **JSON Patch diff colouring**: green = `add`, amber = `replace`,
  rose = `remove`. Used identically in `instance-detail.html` and
  `time-travel.html`.
- **Vector results**: each match shows a cosine-similarity float with a
  thin progress bar. ≥ 0.90 = emerald, 0.80–0.90 = indigo, &lt; 0.80 = amber.
- **Audit chain status**: when the hash chain is verified, the chip reads
  `OK` in emerald + `root <hash>`. A failed verification flips it to rose.
- **Tier flow diagram (storage-tiers)**: four cards left-to-right —
  hot → primary → warm → cold — with a horizontal gradient line behind
  them showing lifecycle direction.

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

- All instances, schema captures, events, queries, search results, batch
  jobs, audit events, API keys, and storage stats are hard-coded
- Charts, sparklines, the UMAP scatter, the relationship-graph layout, and
  the time-travel slider position are static SVG
- The visual query builder canvas does not perform real drag-and-drop or
  auto-layout — class nodes are positioned absolutely
- Generated DSL / SQL / JSON Patch blobs are pre-computed
- The natural-language query "Re-run" button does not call any LLM
- The audit-log chain verification status always reads `OK`
- The "Reveal" button on a freshly created API key does not actually
  reveal a secret
- The theme toggle and Lucide icon hydration are the only working JS

## Out of scope (not included)

These belong to later phases of the roadmap and were excluded from the
initial mockup set in favour of the screens above:

- 1.3 Schema Versioning &amp; Migration Tooling — surfaces in
  `time-travel.html` (the migration trail panel) and in `schema-capture.html`
  (capture metadata), but the migration authoring UI is not mocked
- 2.3 DELETE / Soft-Delete Tooling — accessible from the row-action menu in
  `instance-browser.html`; no dedicated screen
- 2.5 Snapshot &amp; Replay Engine — exercised implicitly by `time-travel.html`
- 3.2 Single Read API + 3.3 Cursor Pagination — visible in
  `instance-browser.html` and `instance-detail.html`; no separate API
  console screen
- 4.4 Embedding Pipeline Monitor — collapsed into the "Embedding queue" KPI
  on `vector-search.html`
- 5.4 Job Templates &amp; Validators — the template selector appears inline
  in `batch-jobs.html`; no dedicated authoring page
- 6.8 Backup &amp; PITR — would extend `storage-tiers.html` with a
  point-in-time-recovery picker; out of MVP scope
