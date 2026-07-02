# Linting & Quality Scoring mockups

Static, browser-openable design mockups for the
[Schema Linting & Quality Scoring feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_LINTING.md).

These files cover the **MVP scope** (Epic 1: Real-Time Validation Engine +
Epic 2: Quality Scoring System) and include preview screens for selected
Pro/Enterprise capabilities from Epic 3 (Validation Rules Engine) and Epic 4
(Schema Intelligence & Analysis). They are visual references — no API calls,
no auth, no build step.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/linting/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/linting/index.html
```

## Files

| File                         | Maps to roadmap issue                                                                  |
| ---------------------------- | -------------------------------------------------------------------------------------- |
| `index.html`                 | Mockup hub linking to all screens                                                      |
| `editor-validation.html`     | 1.1 Pipeline · 1.2 Squiggles · 1.3 Hover tooltip · 1.5 Summary panel · 1.6 Naming · 1.7 Docs · 1.8 Cycles |
| `quality-score.html`         | 2.1 Scoring engine · 2.2 Header score · 2.3 Breakdown · 2.4 History · 2.5 Color · 2.6 Gauge animation |
| `rule-config.html`           | 3.1 Naming rules · 3.2 Docs rules · 3.7 Configuration UI                               |
| `custom-rules.html`          | 3.8 Custom Rule Builder (TypeScript sandbox + diagnostics + live preview)              |
| `dependency-graph.html`      | 4.4 Doc coverage · 4.5 Dependency Graph Visualization (with cycle highlighting)        |
| `breaking-changes.html`      | 4.8 Breaking Change Detection (side-by-side diff + REST/CI integration)                |

## Design system

Mockups intentionally mirror the live `apiome-ui` shell and the sibling
`mockups/analytics/` and `mockups/code-gen/` folders:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, IDs, line numbers, and metric values
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Semantic colors**: rose (error), amber (warning), sky (info), emerald (good), purple (Pro tier)
- **Layout**: 260px gradient sidebar, 48px top platform bar, panel cards (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Charts**: hand-rolled inline SVG (gauge, line chart, bar/category bars, force-directed graph layout) — no chart library, intentionally; final implementation will use Recharts/D3.js per the roadmap tech stack
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under `linting-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Conventions matched from production code

Same patterns as the live ADE shell:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1px border + indigo text + a small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern
- Severity badges (Error/Warning/Info) are color-pill chips with mono font count
- Pro/Soon/Ent affordances are tiny uppercase pill labels (matches sibling mockups)

## What's intentionally faked

- All data is hard-coded (rule violations, quality scores, version timestamps, consumer counts)
- Toggle switches, severity dropdowns, search inputs, and time range pills are visual only
- The "Quick fix" buttons inside the validation summary do not actually mutate any schema
- The custom rule editor is a static syntax-highlighted snippet (no Monaco, no real TypeScript compilation)
- The dependency graph is a hand-laid SVG (no actual force layout) — production uses D3.js per the roadmap
- The diff viewer shows two static `<pre>` blocks — production will use a real diff engine
- The "Live" pulsing dot and the gauge fill animation are CSS-only
- The theme toggle is the only piece of working JS (plus Lucide icon hydration)

## Out of scope (not included)

These are part of later issues / epics in the roadmap and were excluded from
the mockup set:

- **Epic 1**: Quick fix suggestions full UX (1.4 — appears as an inline button only), unused class detection standalone (1.9 — appears as a row in the editor summary), deprecated pattern detection (1.10)
- **Epic 2**: Score comparison across versions (2.7 — referenced as a "Compare versions" button), team average score benchmarking (2.8 — appears as a sidebar card on `quality-score.html`), score report export as PDF (2.9 — referenced as an "Export PDF" button), schema statistics dashboard (2.10)
- **Epic 3**: Schema/API/Security/Performance rule sets dedicated screens (3.3–3.6 — represented as categories in `rule-config.html`), shared lint configurations (3.9), rule set import/export (3.10 — referenced as an "Import JSON" button), rule templates library (3.11 — sidebar only)
- **Epic 4**: Complexity score (4.1), maintainability index (4.2), reusability score (4.3), orphaned property detection (4.6 — appears as a "1 orphan" stat on `dependency-graph.html`), duplicate class detection (4.7), API surface area calculation (4.9)

Sidebar items marked `Soon`, `Pro`, or `Ent` are intentional placeholders
showing the eventual nav surface area without committing to a screen design.
