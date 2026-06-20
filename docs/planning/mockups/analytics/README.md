# Analytics mockups

Static, browser-openable design mockups for the
[Analytics feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_ANALYTICS.md).

These files cover the **MVP scope** (Epic 1: Usage Analytics + Epic 2:
Executive Reporting & Custom Reports). They are visual references — no API
calls, no auth, no build step.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/analytics/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/analytics/index.html
```

## Files

| File                         | Maps to roadmap issue                          |
| ---------------------------- | ---------------------------------------------- |
| `index.html`                 | Mockup hub linking to all screens              |
| `executive-dashboard.html`   | 2.1 Executive Dashboard UI · 2.2 Portfolio · 2.3 Quality Trend |
| `schema-analytics.html`      | 1.2 Most Viewed/Updated · 1.3 Complexity Trend |
| `team-analytics.html`        | 1.7 Active Contributors · 1.9 Review Turnaround |
| `api-analytics.html`         | 1.12 Endpoint Popularity · 1.13 Error Rate     |
| `export-center.html`         | 2.9 Multi-Format Export (PDF / XLSX / CSV / JSON) |

## Design system

Mockups intentionally mirror the live `objectified-ui` shell and the sibling
`mockups/academy/` folder:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, IDs, and metric values
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280px gradient sidebar, 48px top platform bar, panel cards (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Charts**: hand-rolled inline SVG (line, bar, donut, sparkline, gauge, heatmap) — no chart library, intentionally; final implementation will use Recharts/D3.js per the roadmap tech stack
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under `analytics-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Conventions matched from production code

The shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`. Notable patterns:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1px border + indigo text + a small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from `dashboard/page.tsx`
- Time-range pill groups appear in the header right slot (7d / 30d / 90d / 1y)

## What's intentionally faked

- All data is hard-coded (numbers, names, sparklines, percentages)
- Filters, sort buttons, search inputs, and time range pills are visual only
- Export job progress bars and the spinning indicator are static / CSS-only
- The cURL block is a static code sample — no actual request is made
- The theme toggle is the only piece of working JS (plus Lucide icon hydration and a deterministic heatmap renderer on `schema-analytics.html`)

## Out of scope (not included)

These are part of later issues / epics in the roadmap and were excluded from
the MVP mockup set:

- **Epic 1**: Property usage stats (1.4), deprecated property tracking (1.5), schema growth (1.6), contribution heatmaps as standalone (1.8 — partial preview only on the schema page), bottleneck detection (1.10), team productivity composite (1.11), latency percentiles standalone (1.14 — appears as a card on `api-analytics.html`), consumer adoption (1.15), version adoption (1.16), deprecation impact (1.17)
- **Epic 2**: Breaking change frequency (2.4), cost attribution (2.5), risk & compliance summary (2.6 — appears as a preview card on `executive-dashboard.html`), custom report builder (2.7), customizable KPI widgets (2.8), scheduled report delivery (2.10), report sharing links (2.11), SQL query interface (2.12), report templates library (2.13)
- **Epic 3**: Business Intelligence Integrations (Snowflake / Tableau / Power BI / Looker / custom warehouse / iframe embeds) — sidebar only, links are inert

Sidebar items marked `Soon` or `Ent` are intentional placeholders showing the
eventual nav surface area without committing to a screen design.
