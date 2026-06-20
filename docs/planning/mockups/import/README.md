# Import mockups

Static, browser-openable design mockups for the
[Import feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_IMPORT.md).

These files cover the full roadmap surface area across all eight epics:
Import History &amp; Audit (Epic 1), Access Control &amp; Approval Workflows
(Epic 2), Headless Import API &amp; CI/CD Integration (Epic 3), Import
Templates &amp; Presets (Epic 4), Scheduled Import &amp; Automated Sync
(Epic 5), Conflict Resolution &amp; Intelligence (Epic 6), Data
Transformation Pipeline (Epic 7), and Large-Scale Performance &amp; Database
Reverse-Engineering (Epic 8). They are visual references — no API calls, no
auth, no Docker runtime, no real file uploads, no build step.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/import/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/import/index.html
```

## Files

| File                   | Maps to roadmap issue                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------- |
| `index.html`           | Mockup hub linking to all screens, grouped by epic                                          |
| `dashboard.html`       | Import overview — throughput, in-flight jobs, pending approvals, recent imports, error mix  |
| `history.html`         | 1.2 Import History Table + 1.4 Re-Import + 1.5 Run-to-Run Compare + 1.6 Audit Export        |
| `import-detail.html`   | 1.3 Import Detail View + 1.7 User Attribution + 1.8 Retention policy                        |
| `approvals.html`       | 2.3 Approval Workflow + 2.4 Multi-Approver + 2.5 Notifications + 2.6 SLA &amp; Auto-Rollback |
| `governance.html`      | 2.1 RBAC + 2.2 Project Lock + 2.7 Quotas + 2.8 IP Allowlist                                 |
| `api.html`             | 3.1 REST API + 3.2 Status API + 3.3 Commit/Rollback + 3.5 CLI + 3.6 GHA + 3.7 GitLab + 3.8  |
| `multi-source.html`    | 3.9 Multi-File Upload + #350 AWS API Gateway + #800 Cross-Tenant Objectified Registry       |
| `presets.html`         | 4.1 Built-In Templates + 4.2 Custom + 4.3 Org Sharing + 4.5 Variables + 4.6 Import/Export   |
| `schedules.html`       | 5.1 Schedule Configuration + 5.2 Change Detection + 5.3 Differential + 5.5 Pause + 5.6 Git  |
| `conflicts.html`       | 6.1 Conflict Panel + 6.2 Strategies + 6.3 Property Diff + 6.5 AI Suggestion + 6.7 3-Way     |
| `transforms.html`      | 7.1 Rules Engine + 7.2 Renaming + 7.3 Type Coercion + 7.4 Metadata + 7.5 Strip + 7.6 Diff   |
| `ddl-import.html`      | 8.5 SQL DDL + 8.6 Live Database + 8.8 DBML/Prisma + 8.9 Dependency Graph                    |
| `sandbox.html`         | 8.10 Validation Rules + 8.11 Sandbox/Staging + 8.12 Importer Plugin Registry                |

## Design system

Mockups intentionally mirror the live `objectified-ui` shell and align with
the sibling `mockups/academy`, `mockups/analytics`, `mockups/architect`,
`mockups/automation`, `mockups/code-gen`, `mockups/collaboration`, and
`mockups/connect` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for job IDs,
  source URIs, schema names, cron expressions, file sizes, durations
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set —
  `file-input` is the Import product mark
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `import-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Import-specific visual language

Beyond the shared shell, the Import mockups introduce a few conventions that
the production build is expected to honor:

- **Job status pills**: `Pending` = gray, `Analyzing` = indigo (pulsing dot),
  `Previewing` = purple, `Awaiting Approval` = amber, `Committing` = blue
  (pulsing dot), `Complete` = emerald, `Failed` = rose, `Rolled Back` =
  slate, `Cancelled` = neutral. Each pill is paired with a 1.5 × 1.5 px
  coloured dot.
- **Source-type icons**: `link` = URL, `file-up` = file upload, `git-branch`
  = Git repository, `cloud` = AWS API Gateway / cloud provider,
  `package` = cross-tenant Objectified registry, `database` = live database,
  `file-code-2` = SQL DDL, `boxes` = Postman collection.
- **Format chips**: `OpenAPI 3.1`, `Swagger 2.0`, `JSON Schema`,
  `GraphQL`, `Postman v2.1`, `DBML`, `Prisma`, `SQL DDL`, `Avro`, `Protobuf`
  — small rounded `bg-gray-100` chips with a colored dot per family
  (REST = indigo, GraphQL = pink, schema-only = teal, RPC = orange).
- **Quality score bar**: 0–100 scale, gradient from rose (&lt; 50) →
  amber (50–69) → emerald (≥ 70). Threshold = 70 by default; below that,
  Quality Gate blocks commit.
- **Diff highlighting**: emerald background = added, rose background =
  removed, amber underline = property changed both sides since last import
  watermark.
- **Conflict resolution badges**: each conflict carries a strategy badge —
  `Keep Existing` = slate, `Replace` = rose, `Merge Additive` = emerald,
  `Merge Override` = amber, `Rename` = blue, `New Version` = purple. AI
  suggestions are marked with a sparkle icon and a soft purple ring.
- **Approval chain pill**: 1 of 3 / 2 of 3 / etc., with avatars stacked
  left-to-right; each avatar is wrapped in an emerald ring once that
  reviewer has approved.
- **Sandbox vs. Live banner**: when a job lands in the sandbox, a
  purple banner appears at the top of the import detail with a
  `Promote to Live` CTA. Live commits use the standard indigo banner.
- **Event log row**: timestamp · actor avatar · event type pill · short
  description. Actors are users (initials avatar) or system events
  (gear icon avatar).

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1
  indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10 % indigo fill + 1 px border + indigo text + a
  small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- Status pills mirror those in `mockups/automation/integrations.html` and
  `mockups/connect/dashboard.html`
- Wizard steppers reuse the numbered ring + connecting line pattern from
  `mockups/connect/connection-wizard.html`

## What's intentionally faked

- All import jobs, sources, schemas, conflicts, presets, transforms, audit
  events, approvers, schedules, plugins, and validation rules are
  hard-coded
- Progress bars, throughput sparklines, dependency graphs, and quality
  score arcs are static SVG
- The DDL parser preview, Postman import preview, and DBML preview are
  pre-computed
- The "Run dry import", "Apply preset", "Approve", "Promote to live", and
  "Re-import" buttons are inert
- The git branch tracking widget shows static commit history; no real polling
- The plugin sandbox console is a static fixture; no actual plugin runtime
- The CLI block, GitHub Actions YAML, and GitLab CI YAML are syntax-coloured
  text — no commands actually run
- The theme toggle and Lucide icon hydration are the only working JS

## Out of scope (not included)

These belong to later phases of the roadmap and were excluded from the mockup
set in favour of the screens above:

- 1.1 Import History Data Model — surfaces in `import-detail.html` as the
  serialized event log + diff snapshot, but the schema itself is a docs
  concern
- 4.4 Preset Auto-Apply per Project — appears as a sidebar settings toggle
  on `presets.html` rather than a dedicated screen
- 6.4 Bulk Conflict Resolution — exposed as the "Apply to all similar"
  action on `conflicts.html` rather than its own page
- 6.6 Conflict Memory — appears as the "Remembered choices" panel on
  `conflicts.html`
- 7.7 Reusable Transformation Profiles — surfaces in `transforms.html` as
  the saved profiles drawer
- 8.1 Chunked File Upload with Resume / 8.2 Background Processing /
  8.3 WebSocket Progress / 8.4 Parallel Processing — internal mechanics,
  visible to users only as the in-flight progress UI on `dashboard.html`
  and `import-detail.html`
- 8.7 Postman Collection Import — would extend `multi-source.html` with a
  Postman tab; for the mockup set the visible surface area is covered by
  the existing source picker

Sidebar items marked `Soon` are intentional placeholders showing the
eventual nav surface area without committing to a screen design.
