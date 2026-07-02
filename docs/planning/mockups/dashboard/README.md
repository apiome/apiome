# Dashboard / Control Panel mockups

Static, browser-openable design mockups proposing an enterprise-grade
redesign of the Apiome **control panel** (the surface mounted at
[`/ade/dashboard`](../../../src/app/ade/dashboard/page.tsx) in the live
app).

Today's control panel is a five-card stat grid + a recent-activity list.
This set proposes a richer operator-and-owner surface that blends:

- **KPIs** the platform owner wants to see at a glance (tenants,
  projects, versions, published surface area, write throughput, lint
  health, error budget, MTTR)
- **Governance** signals the security / platform team needs front and
  centre (audit trail, RBAC, key rotation status, primitive drift,
  data-residency, quotas, deprecation timers)
- **Portfolio** signals the engineering org needs to triage day-to-day
  (project quality scores, version pipeline, sunset timeline, consumers
  per published version, change-request volume)

These files are visual references — no API calls, no auth, no real
runtime. The theme toggle and Lucide icon hydration are the only working
JS.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/dashboard/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/dashboard/index.html
```

## Files

| File                    | Maps to current screen                                 | Proposed enterprise additions                                                        |
| ----------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `index.html`            | —                                                      | Mockup hub linking to all 9 screens, grouped by capability                           |
| `overview.html`         | `/ade/dashboard` (the page itself)                     | KPI band, schema-health donut, version pipeline, alerts, system status, quick acts   |
| `profile.html`          | `/ade/dashboard/profile`                               | Identity card, preferences, MFA, active sessions, recovery codes, recent sign-ins    |
| `linked-accounts.html`  | `/ade/dashboard/linked-accounts`                       | SSO/OIDC providers, SCIM, GitHub/GitLab/Bitbucket, Slack, PagerDuty, last-sync state |
| `tenants.html`          | `/ade/dashboard/tenants`                               | Tenant cards, plan + seats, residency, members preview, audit pulse, billing health  |
| `api-keys.html`         | `/ade/dashboard/api-keys`                              | Keys table with scopes, rotation timer, IP allowlist, usage sparkline, revoke flow   |
| `primitives.html`       | `/ade/dashboard/primitives`                            | Primitive registry, usage map across versions, drift report, deprecation queue       |
| `projects.html`         | `/ade/dashboard/projects`                              | Portfolio grid + table, quality score, lint score, contributors, last activity       |
| `versions.html`         | `/ade/dashboard/versions`                              | Version pipeline (draft → review → published), branch DAG, publish gates, sunset row |
| `published.html`        | `/ade/dashboard/published`                             | Published surface area, runtime endpoints, consumer count, traffic, deprecation eta  |

## Design system

These mockups reuse and extend the conventions already established in
the sibling sets (`mockups/db`, `mockups/designer`, `mockups/connect`,
`mockups/architect`, etc.) and align with the live shell:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for tenant
  IDs, key prefixes, ETags, version numbers, hash digests, counts
- **Accent**: indigo-500 / 600 (matches Radix `accentColor="indigo"`)
- **Gray scale**: slate (matches Radix `grayColor="slate"`)
- **Layout**: 280 px gradient sidebar, 48 px top platform bar, panel
  cards with `bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`
- **Icons**: Lucide via CDN, mirroring the live `lucide-react` set
- **Theme**: class-based dark mode toggle, persisted to `localStorage`
  under `dashboard-mockup-theme`. Honors `prefers-color-scheme` on
  first load.

## Sidebar reorganization

The current sidebar groups things by an awkward mix of concerns
(Account · Administration · Data Management · Specifications). The
proposed sidebar reorganizes around what the user is *trying to do*:

```
OVERVIEW          → Control panel
IDENTITY          → Profile, Linked accounts
WORKSPACE         → Tenants, API keys
SPECIFICATIONS    → Projects, Versions, Published
GOVERNANCE        → Primitives
```

Each group still uses the existing `text-[0.65rem]` uppercase header
with the 1×1 indigo dot (`DashboardSideNav.tsx` convention). Active
items keep the 10 % indigo fill + 1 px border + indigo text + dot
indicator.

## Control-panel-specific visual language

A few new conventions introduced by this mockup set that the production
build is expected to honor:

- **Health pills**: `OK` = emerald, `WARN` = amber, `DEGRADED` = orange,
  `DOWN` = rose. Used on the system status row and per-tier indicators.
- **Lifecycle pills**: `DRAFT` = slate, `REVIEW` = amber,
  `PUBLISHED` = emerald, `DEPRECATED` = orange, `SUNSET` = rose.
- **Plan pills**: `FREE` = slate, `TEAM` = indigo, `ENTERPRISE` = purple.
- **Residency pills**: `US` / `EU` / `APAC` in slate with a flag-style
  monospace prefix (`us-east-1`, `eu-west-1`, …).
- **Key prefix monospace**: `orcl_live_…` and `orcl_test_…` always
  appear in JetBrains Mono with the suffix masked except on the row
  immediately after creation. Last-used time renders next to the prefix.
- **Tenant ID pills**: monospace, indigo on transparent
  (`ten_01HJ7…F8H`), middle-truncated when narrow.
- **Quality score**: 0–100 number rendered inside a colored ring
  (≥ 90 emerald, 75–89 indigo, 60–74 amber, &lt; 60 rose). Same scale used
  for lint score and dependency-debt score.
- **Quota bars**: thin progress bar with a tick at 80 % (warn) and
  100 % (cap). Color shifts at each threshold.
- **Audit pulse**: a 24-hour spark histogram in the audit row showing
  event volume; spike colors flag elevated sensitivity events.
- **Version pipeline**: draft → review → published rendered as a
  horizontal funnel with counts and a transition rate beneath each step.

## Conventions matched from production code

Shared layout tokens come from
[`app/components/ade/dashboard/dashboardScreenClasses.ts`](../../../src/app/components/ade/dashboard/dashboardScreenClasses.ts)
and
[`app/components/ade/dashboard/DashboardSideNav.tsx`](../../../src/app/components/ade/dashboard/DashboardSideNav.tsx):

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a
  1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for the header bar inside a
  card and `bg-white dark:bg-gray-800` for the body
- Active nav items use a 10 % indigo fill + 1 px border + indigo text +
  a small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  [`dashboard/page.tsx`](../../../src/app/ade/dashboard/page.tsx)
- Status pills mirror those in `mockups/automation/integrations.html`,
  `mockups/connect/connections.html`, and `mockups/db/dashboard.html`

## What's intentionally faked

- All tenants, members, keys, projects, versions, primitives, audit
  events, traffic numbers, and consumer counts are hard-coded
- Charts and sparklines are static SVG — no live data
- The system status row is always green except for one demo amber row
- The "Rotate key" and "Revoke key" buttons do not call any API
- The theme toggle and Lucide icon hydration are the only working JS

## Out of scope

- Sub-resource detail pages (e.g. tenant member detail, API-key audit
  log, primitive detail) — surfaced as side panels / drawers in the
  parent screens but not designed as full pages
- Billing portal — `tenants.html` shows plan + spend; the dedicated
  invoices / receipts surface is left for a billing mockup set
- Settings / preferences sub-pages beyond what fits inside `profile.html`
- Real-time WebSocket connection indicators — collapsed into the
  "Realtime" health pill on `overview.html`
