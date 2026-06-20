# Data Insights mockups

Static, browser-openable design mockups for the
[Data Insights feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_INSIGHTS.md).

These files cover the **MVP scope** plus a forward look at higher-value
analytics surfaces (churn, funnels, dashboard builder, scheduled reports).
They are visual references — no API calls, no auth, no build step.

## Open

Either open the files directly:

```
open objectified-ui/public/mockups/data-insights/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/data-insights/index.html
```

## Files

| File                       | Maps to roadmap issue                                      |
| -------------------------- | ---------------------------------------------------------- |
| `index.html`               | Mockup hub linking to all screens                          |
| `pipeline.html`            | 1.1 Taxonomy · 1.2 Ingestion · 1.3 Stream · 1.4 Warehouse · 1.5 Retention |
| `health-score.html`        | 2.1 Schema Health Score · 2.2 Quality Trend Visualization  |
| `tech-debt.html`           | 2.3 Technical Debt Quantification · 2.5 Schema Complexity  |
| `deprecation.html`         | 2.4 Deprecation Impact Forecasting                         |
| `revenue.html`             | 3.1 API Monetization Tracking · 3.5 Revenue Attribution & ROI |
| `funnels.html`             | 3.2 Consumer Adoption Funnels                              |
| `churn.html`               | 3.3 Churn Prediction for API Consumers                     |
| `dx-metrics.html`          | 3.4 Developer Experience Metrics                           |
| `portfolio.html`           | 4.2 Portfolio Overview & KPI Tracking                      |
| `dashboard-builder.html`   | 4.1 Executive Dashboard Builder                            |
| `reports.html`             | 4.3 Scheduled Report Generation · 4.4 Multi-Format Export  |

## Design system

Mockups intentionally mirror the live `objectified-ui` shell and the sibling
`mockups/analytics/` folder (Insights is the spiritual successor to the
Analytics roadmap):

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, IDs, metric values
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280px gradient sidebar, 48px top platform bar, panel cards (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Charts**: hand-rolled inline SVG (line, bar, donut, sparkline, gauge, radar, bubble, funnel, heatmap) — no chart library, intentionally; final implementation will use Recharts per the roadmap tech stack
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under `data-insights-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Conventions matched from production code

The shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`. Notable patterns:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1px border + indigo text + a small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from `dashboard/page.tsx`
- Time-range pill groups appear in the header right slot (7d / 30d / 90d / 1y)

## What's intentionally faked

- All data is hard-coded (numbers, names, sparklines, percentages, ML scores)
- Filters, sort buttons, search inputs, and time range pills are visual only
- Drag-and-drop on the dashboard builder canvas is decorative; widgets do not move
- Export job progress bars and the spinning indicators are static / CSS-only
- The cURL blocks are static code samples — no actual request is made
- ML predictions on `churn.html` are deterministic placeholders
- The theme toggle is the only piece of working JS (plus Lucide icon hydration)

## Out of scope (not included as standalone screens)

These appear as inline preview cards or sidebar links but do not have a
dedicated screen in this mockup set:

- **Epic 1**: GDPR deletion endpoint detail (1.5), per-tenant retention editor (1.5), event taxonomy editor (1.1) — pipeline status page summarizes all five issues
- **Epic 2**: Per-dimension health drill-down editor (2.1) — surfaced inline on `health-score.html`
- **Epic 4**: Custom widget marketplace (4.1), embed iframe configurator (4.4) — referenced from the dashboard builder toolbar but no dedicated page

Sidebar items marked `Soon` or `Ent` are intentional placeholders showing the
eventual nav surface area without committing to a screen design.
