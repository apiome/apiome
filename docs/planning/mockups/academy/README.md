# Academy mockups

Static, browser-openable design mockups for the
[Academy feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_ACADEMY.md).

These files cover the **MVP scope** (Epic 1: Course Management Platform + Epic 2:
Student Experience & Gamification). They are visual references — no API calls,
no auth, no build step.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/academy/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/academy/index.html
```

## Files

| File                       | Maps to roadmap issue              |
| -------------------------- | ---------------------------------- |
| `index.html`               | Mockup hub linking to all screens  |
| `student-dashboard.html`   | 2.3 Student Dashboard              |
| `catalog.html`             | 1.5 Course Catalog & Discovery UI  |
| `course-detail.html`       | 1.5 / 2.1 detail + enrollment      |
| `lesson-viewer.html`       | 2.2 Progress + lesson rendering    |
| `course-editor.html`       | 1.3 Rich Content Editor            |
| `media-library.html`       | 1.4 Media Upload & Storage         |
| `badges.html`              | 2.4 Badge & Achievement System     |

## Design system

Mockups intentionally mirror the live `apiome-ui` shell:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 280px gradient sidebar, 48px top platform bar, panel cards (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under `academy-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Conventions matched from production code

The shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and `app/components/ade/dashboard/DashboardSideNav.tsx`. Notable patterns:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1px border + indigo text + a small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from `dashboard/page.tsx`

## What's intentionally faked

- All data is hard-coded
- Drag handles, dropdowns, and toggles are visual only
- The theme toggle is the only piece of working JS (plus Lucide icon hydration)

## Out of scope (not included)

These are part of later epics in the roadmap and were excluded from MVP:

- Epic 3 — Certification & Assessment Engine (exam authoring, taking, certificates)
- Epic 4 — Enterprise Training & Integration (curricula, HR connectors, compliance, analytics)
- Course publishing workflow (1.6, not flagged `mvp`)
- Student enrollment system fine details (waitlist UI from 2.1)
- Leaderboards & social learning (2.5, not flagged `mvp`)
