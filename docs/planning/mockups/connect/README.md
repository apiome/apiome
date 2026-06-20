# Connect mockups

Static, browser-openable design mockups for the
[Connect feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_CONNECT.md).

These files cover the full roadmap surface area across all four epics:
Connector Framework &amp; Registry (Epic 1), Schema Mapping &amp; Transformation
(Epic 2), Real-Time Data Sync &amp; CDC (Epic 3), and Event-Driven &amp;
Messaging Integration (Epic 4). They are visual references — no API calls,
no auth, no Docker runtime, no real gRPC streams, no build step.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/connect/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/connect/index.html
```

## Files

| File                     | Maps to roadmap issue                                                                    |
| ------------------------ | ---------------------------------------------------------------------------------------- |
| `index.html`             | Mockup hub linking to all screens, grouped by epic                                       |
| `dashboard.html`         | Connect overview — connection health, sync throughput, event volume, recent activity     |
| `marketplace.html`       | 1.3 Connector Marketplace UI — categories, tiles, install/uninstall                      |
| `connection-wizard.html` | 1.4 Connection Configuration Wizard — multi-step OAuth / API key / settings / test       |
| `connections.html`       | 1.5 Connector Health &amp; Monitoring — status grid, uptime, alerts                      |
| `sdk.html`               | 1.6 Community Connector SDK — CLI, manifest, testing harness, publish flow               |
| `mapping-editor.html`    | 2.1 Schema Discovery + 2.2 Visual Field Mapping — two-panel mapper with connection lines |
| `transforms.html`        | 2.3 Transformation Rules Engine — pipeline builder, live preview, custom expressions     |
| `templates.html`         | 2.4 Mapping Templates &amp; Presets — platform / community / tenant templates             |
| `sync-jobs.html`         | 3.1 Sync Job Configuration + 3.2 Batch Sync Engine — schedule, direction, in-flight runs |
| `sync-logs.html`         | 3.5 Sync Execution Log — runs list, per-record drill-down, retry from DLQ                |
| `conflicts.html`         | 3.4 Conflict Resolution Engine — side-by-side diff, manual review queue                  |
| `webhooks.html`          | 4.1 Webhook Orchestration — inbound endpoints, outbound deliveries, retries, replay      |
| `event-router.html`      | 4.4 Event Router &amp; Fan-Out + 4.5 Schema Validation &amp; DLQ — rules, throughput, DLQ  |

## Design system

Mockups intentionally mirror the live `objectified-ui` shell and align with the
sibling `mockups/academy`, `mockups/analytics`, `mockups/architect`,
`mockups/automation`, `mockups/code-gen`, and `mockups/collaboration` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for table IDs,
  field paths, connector names, channel names, cron expressions, and stats
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `connect-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Connect-specific visual language

Beyond the shared shell, the Connect mockups introduce a few conventions
that the production build is expected to honor:

- **Connector tiles**: 12×12 (48 px) rounded brand-coloured square with
  the connector's letter or glyph (Slack `#`, Stripe `S`, Postgres elephant,
  Kafka `Kf`, Salesforce `SF`, Snowflake `❄`, etc.). Hover highlights the
  border in indigo and reveals the install / configure CTA.
- **Health status pills**: traffic-light language consistent with
  `mockups/automation` — `Healthy` = emerald, `Degraded` = amber,
  `Unhealthy` = rose, `Disconnected` = gray, `Token expiring` = amber.
  Each pill is paired with a 1.5 × 1.5 px coloured dot.
- **Capability icons**: `book-open` = read-only, `pencil` = write-only,
  `repeat-2` = bi-directional, `radio-tower` = subscribe / streaming.
  These appear on every connector tile and on each sync job row.
- **Sync direction**: `arrow-down-to-line` = inbound (external → Objectified),
  `arrow-up-from-line` = outbound (Objectified → external), `repeat-2` =
  bi-directional. Always paired with a connector logo on each side.
- **Mapping lines (mapping editor)**: solid indigo line = direct copy,
  dashed indigo line with `[T]` icon = transformation applied, rose dot on
  the target side = unmapped required field, amber dot = type mismatch.
- **Conflict diff**: emerald background = source-side change, rose
  background = target-side change, amber underline on the field name when
  both sides changed since the last sync watermark.
- **Run status badges (sync logs)**: `Success` = emerald, `Partial` = amber,
  `Failed` = rose, `Running` = indigo (with pulsing dot), `Queued` = gray,
  `Retried` = blue.
- **Event throughput chart**: small inline sparkline using indigo gradient,
  shown on the dashboard, the event router, and per-connection cards.
- **Marketplace tier ribbon**: corner ribbon on connector tiles —
  `Free` = emerald, `Pro` = indigo, `Enterprise` = purple, `Beta` = amber.

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10 % indigo fill + 1 px border + indigo text + a small
  dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- Status pills mirror those in `mockups/automation/integrations.html`

## What's intentionally faked

- All connectors, connections, sync jobs, runs, mappings, transforms,
  templates, conflicts, webhooks, deliveries, events, routing rules, and DLQ
  entries are hard-coded
- Sync progress bars, charts, sparklines, and live event counters are static SVG
- The mapping canvas connection lines are static SVG paths — no real
  drag-and-drop, no auto-layout
- The transformation pipeline preview output is pre-computed
- The OAuth wizard does not redirect anywhere; "Test connection" always
  succeeds in the mockup
- The event router throughput meter is a fixed gradient
- The theme toggle and Lucide icon hydration are the only working JS

## Out of scope (not included)

These belong to later phases of the roadmap and were excluded from the mockup
set in favour of the screens above:

- 1.1 Connector Plugin Architecture — surfaces in `sdk.html` as the
  `ConnectorInterface` reference, but the runtime container view is omitted
- 1.2 Connector Registry &amp; Metadata Store — visible to the user only via
  the marketplace; the registry admin view is not mocked
- 2.5 Mapping Validation &amp; Preview — the "Test with sample data" results
  panel is integrated into `mapping-editor.html` rather than a separate page
- 3.3 CDC Listener Configuration — non-MVP; would extend `sync-jobs.html`
  with a third sync mode (`streaming`) and a CDC position viewer
- 4.2 Kafka Connector / 4.3 RabbitMQ &amp; NATS Connectors — non-MVP; would
  appear as additional connector tiles in `marketplace.html` and a topology
  viewer panel in `connections.html`
