# Architect mockups

Static, browser-openable design mockups for the
[Architect feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_ARCHITECT.md).

These files cover the **MVP scope** across all four epics: System Landscape Canvas
(Epic 1), Dependency Analysis & Impact Mapping (Epic 2), Pattern Library &
Compliance (Epic 3), and ADR Management (Epic 4). They are visual references —
no API calls, no auth, no build step.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/architect/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/architect/index.html
```

## Files

| File                       | Maps to roadmap issue                                |
| -------------------------- | ---------------------------------------------------- |
| `index.html`               | Mockup hub linking to all screens                    |
| `landscape.html`           | 1.1 Canvas · 1.2 Nodes · 1.3 Domain Groups · 1.6 Export |
| `data-flow.html`           | 2.1 Auto-generated dependencies · 2.2 Data Flow View |
| `impact-analysis.html`     | 2.3 Impact Analysis Engine                           |
| `pattern-catalog.html`     | 3.1 Architecture Pattern Catalog                     |
| `compliance-checker.html`  | 3.2 Pattern Compliance Checker (+ 3.3 anti-patterns) |
| `adrs.html`                | 4.1 ADR CRUD & Markdown Editor (+ 4.2 linking, 4.4 principles) |

## Design system

Mockups intentionally mirror the live `apiome-ui` shell and align with the
sibling `mockups/academy` and `mockups/analytics` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, IDs, and metric values
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 260 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `architect-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Architect-specific visual language

Beyond the shared shell, the Architect mockups introduce a few canvas
conventions that the production build is expected to honor:

- **Service nodes** render as `rounded-lg` cards with a typed icon, owner
  metadata, and a status dot (emerald / amber / rose).
- **Databases** use a `rounded-2xl` (cylinder-ish) card variant.
- **Message queues** use a CSS `clip-path` parallelogram.
- **External systems** use a dashed border in the `violet` palette.
- **Domain groups** are dashed `rounded-xl` rectangles in the domain's accent
  color, with a labeled tag pinned to the top edge.
- **Auto-generated dependency edges** render dashed in `violet-400`; manually
  drawn edges are solid `slate-400`.
- **Impact highlights**: indigo ring for the source node, rose ring for direct
  dependents, amber ring for transitive dependents.

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1 px border + indigo text + a small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from `dashboard/page.tsx`

## What's intentionally faked

- All landscapes, services, ADRs, and metrics are hard-coded
- Drag handles, dropdowns, sliders, and version pickers are visual only
- The pan / zoom canvas is not interactive — node positions are absolute
- The dashed "animated flow" edges in `data-flow.html` use a pure CSS
  `stroke-dashoffset` animation, with no real volume data behind them
- The theme toggle is the only piece of working JS (plus Lucide icon hydration)

## Out of scope (not included)

These belong to later phases of the roadmap and were excluded from the MVP
mockup set:

- 1.4 Canvas Persistence & REST API (backend-only concern)
- 1.5 DDD Capability Mapping View (alternate canvas lens, post-MVP)
- 2.4 Critical Path Identification (uses same Sheet pattern as impact)
- 2.5 Dependency Diff Between Versions
- 3.4 Custom Pattern Definition (rule builder UI — the catalog already shows the
  outcome)
- 3.5 Refactoring Recommendation Engine (referenced from compliance, not its
  own page)
- 4.3 Decision History Timeline (button visible in `adrs.html` header)
- 4.5 Capacity Modeling Dashboard
