# Automation mockups

Static, browser-openable design mockups for the
[Automation feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_AUTOMATION.md).

These files cover the **MVP scope** spanning all three epics: Event-Driven
Webhooks (Epic 1), Scheduled Jobs & Periodic Tasks (Epic 2), and Workflow
Automation & CI/CD (Epic 3). They are visual references — no API calls, no
auth, no build step.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/automation/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/automation/index.html
```

## Files

| File                  | Maps to roadmap issue                                              |
| --------------------- | ------------------------------------------------------------------ |
| `index.html`          | Mockup hub linking to all screens                                  |
| `dashboard.html`      | 3.5 Unified Configuration UI (Automation overview)                 |
| `timeline.html`       | 3.5 cross-cutting · global activity feed across all sources        |
| `webhooks.html`       | 1.1 Webhook Endpoint Registration · 1.2 Event Subscription Bus     |
| `webhook-test.html`   | 1.3 HMAC-SHA256 Signing · 1.4 Webhook Testing & Debugging Tools    |
| `delivery-logs.html`  | 1.5 Webhook Retry Engine · delivery log + dead-letter queue        |
| `jobs.html`           | 2.1 Scheduler · 2.2 Schema Maintenance · 2.4 Expiration Monitors   |
| `approvals.html`      | 3.1 Approval Workflows for Schema Publishing                       |
| `triggers.html`       | 3.2 CI/CD Pipeline Triggers · 3.4 Automated Code Generation        |
| `integrations.html`   | 3.3 Third-Party Integration Hub (Slack, Teams, Jira, Linear)       |

## Design system

Mockups intentionally mirror the live `objectified-ui` shell and the sibling
`mockups/analytics/` and `mockups/academy/` folders:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, IDs, payloads, and metric values
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280px gradient sidebar, 48px top platform bar, panel cards (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set — `zap` is the Automation product mark
- **Status colors**: emerald (healthy/success), amber (warning/retrying), rose (failed/critical), purple (workflow), cyan (webhooks), indigo (system)
- **Charts**: hand-rolled inline SVG (line, bar, gauge, sparkline) — no chart library, intentionally; final implementation will use Recharts/D3.js per the roadmap tech stack
- **Code samples**: dark `codeblock` panels with token classes (`.k` keyword, `.s` string, `.h` handlebars var, `.c` comment) for HTTP requests, JSON payloads, and template previews
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under `automation-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Conventions matched from production code

The shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`. Notable patterns:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1px border + indigo text + a small dot indicator (animated on `timeline.html` for live state)
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from `dashboard/page.tsx`
- Filter chips use rounded pills with an indigo highlight for the selected source
- Status badges follow the existing `text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded` pattern
- Approval chains, schema diffs, and timelines re-use the colored ring + icon convention from the architect mockups

## What's intentionally faked

- All data is hard-coded (endpoint names, delivery counts, signatures, schema diffs, run histories, integration channels)
- Filters, sort buttons, search inputs, time range pills, and pagination are visual only
- Toggle switches for enabling/disabling jobs and routing rules are CSS-only
- The webhook test console "results" panel shows a static fixture response
- The HMAC signature, cURL block, and verification samples are static — no actual signing or HTTP requests are made
- Slack / Teams / Jira / Linear preview cards are mockups; OAuth flows are not wired
- The "Live" indicator on `timeline.html` is decorative (animated dot only) — events do not stream
- The theme toggle is the only piece of working JS, plus Lucide icon hydration

## Out of scope (not included)

These are part of later issues / epics in the roadmap and were excluded from
the MVP mockup set, or fold into existing screens as preview-only sections:

- **Epic 1**: Per-event delivery analytics dashboards beyond the simple status counts on `delivery-logs.html`; webhook secret rotation flow (referenced inline on `webhook-test.html` only)
- **Epic 2**: 2.3 Notification Digest builder UI (only an inline run record on `jobs.html` represents it); custom job authoring UI beyond the inline edit dialog mockup; SLA/expiration policy editor (the monitors panel on `jobs.html` is read-only)
- **Epic 3**: 3.1 reviewer-group management UI (only the assigned-reviewers list is shown); workflow editor (the "Edit workflow →" link on `approvals.html` is inert); rule builder for `integrations.html` routing rules (only the configured table is shown)

Sidebar items marked `Soon` are intentional placeholders showing the eventual
nav surface area without committing to a screen design.
