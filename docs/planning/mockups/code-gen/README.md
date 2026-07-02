# Code Generation mockups

Static, browser-openable design mockups for the
[Code Generation feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_CODE_GENERATION.md).

These files cover the full roadmap surface area across all four epics:
Schema-to-Code Generation (Epic 1), OpenAPI Client SDK Generation (Epic 2),
Path-to-Code Generation / Server Stubs & CRUD (Epic 3), and Mock Data Generation
(Epic 4). They are visual references — no API calls, no auth, no build step.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/code-gen/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/code-gen/index.html
```

## Files

| File                       | Maps to roadmap issue                                                        |
| -------------------------- | ---------------------------------------------------------------------------- |
| `index.html`               | Mockup hub linking to all screens                                            |
| `studio.html`              | 1.1 TS · 1.3 Pydantic · 1.4 Dataclasses · 1.12 Markdown · 1.14 Preview · 1.15 Project ZIP |
| `settings.html`            | 1.13 Per-language settings (TypeScript, Pydantic, Dataclasses, Markdown, Java/Pro, Enterprise templates) |
| `client-sdk.html`          | 2.1 OpenAPI Generator · 2.2 One-click SDK · 2.3 npm · 2.4 PyPI · 2.5 Maven   |
| `crud-generator.html`      | 3.1 CRUD auto-gen · 3.2 URL pattern · 3.3 Op selection · 3.4 Response wrapper · 3.5 Bulk |
| `server-stubs.html`        | 3.6 Express · 3.7 FastAPI · 3.8 Spring · 3.9 NestJS · 3.10 Gin · 3.11 Axum   |
| `mock-data.html`           | 4.1 Examples · 4.2 Faker · 4.3 FK consistency · 4.4 Bulk · 4.5 Export · 4.6 Seed DB |
| `jobs.html`                | Cross-cutting: async generation jobs (HTTP 202) and artifact downloads       |

## Design system

Mockups intentionally mirror the live `apiome-ui` shell and align with the
sibling `mockups/academy`, `mockups/analytics`, `mockups/architect`, and
`mockups/automation` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, identifiers, file names
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 260 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `codegen-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Code-gen specific visual language

Beyond the shared shell, the Code Generation mockups introduce a few
conventions that the production build is expected to honor:

- **Language chips**: 20 px square colour-coded badges for each language
  (TypeScript = blue, Pydantic = yellow, SQLAlchemy = rose, Java = orange,
  C# = violet, Go = cyan, Rust = orange-700, Scala = red-700, Ruby = fuchsia,
  Swift = indigo-700) — used in language pickers and SDK cards.
- **Tier badges**: emerald `MVP` / amber `Pro` / purple `Enterprise` pills next
  to languages and features that are gated.
- **HTTP verb chips**: monospace, all-caps verbs in tinted backgrounds
  (GET = emerald, POST = indigo, PUT = amber, PATCH = teal, DELETE = rose).
- **Code panes**: dark slate background (`#0b1220`) with a fixed left gutter
  for line numbers, regardless of the page-level theme — preview always reads
  as a code editor.
- **Token colours**: pink keywords, blue types, purple keys, green strings,
  amber numbers, slate-italic comments — consistent across `studio.html` and
  `server-stubs.html` previews.
- **Conflict highlights**: amber row tint plus a `triangle-alert` icon for
  CRUD path collisions, and a rose tint for failed jobs.
- **Status dots**: animated indigo pulse for `RUNNING`, emerald check for
  `SUCCEEDED`, rose X for `FAILED` (job history page).

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1 px border + indigo text + a small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from `dashboard/page.tsx`

## What's intentionally faked

- All schemas, classes, paths, jobs, SDK packages, and metrics are hard-coded
- Dropdowns, sliders, toggles, range inputs, and language tabs are visual only
- The "live preview" panes are static snapshots — no AST is actually parsed
- Faker output and FK simulation in `mock-data.html` show plausible but
  pre-rendered records
- The framework picker in `server-stubs.html` only highlights the Express card;
  switching frameworks would re-render the preview in production
- The progress bar on the running job in `jobs.html` is a static gradient at 64%
- The theme toggle is the only piece of working JS (plus Lucide icon hydration)

## Out of scope (not included)

These belong to later phases of the roadmap and were excluded from the mockup
set in favour of the screens above:

- 1.5 Python SQLAlchemy · 1.6 Hybrid models · 1.7 Java POJOs · 1.8 C# · 1.9 Go ·
  1.10 Rust · 1.11 Scala — these would each surface as additional language tabs
  in `studio.html` and additional cards in `settings.html`; the visual pattern
  is identical to the MVP languages
- 1.16 Generate unit tests with models — surfaces as a per-language toggle in
  `settings.html`
- 1.17 Liquibase changesets · 1.18 Excel export · 1.19 PDF export — surface as
  additional output format buttons in `studio.html`'s Output panel
- All sub-flows of Epic 2 (publishing UI, registry-config wizards) live behind
  the "Configure" buttons in `client-sdk.html`
