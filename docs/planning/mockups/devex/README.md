# DevEx mockups

Static, browser-openable design mockups for the
[Developer Experience feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_DEVEX.md).

These files cover the **MVP scope** across all four epics: Auto-Generated
Documentation (Epic 1), Schema Changelog & Migration Guides (Epic 2), IDE
Extensions (Epic 3), and Advanced Git Workflows (Epic 4). They are visual
references — no API calls, no auth, no build step.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/devex/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/devex/index.html
```

## Files

| File                  | Maps to roadmap issue                                          |
| --------------------- | -------------------------------------------------------------- |
| `index.html`          | Mockup hub linking to all screens, grouped by epic             |
| `redoc.html`          | 1.1 ReDoc Documentation Renderer (MVP)                         |
| `custom-pages.html`   | 1.4 Custom Pages, Guides & Branding (MVP)                      |
| `changelog.html`      | 2.1 Changelog Engine · 2.2 Breaking Change Classification (MVP)|
| `diff.html`           | 2.4 Visual Side-by-Side Schema Diff (MVP)                      |
| `migration-guide.html`| 2.3 Migration Guide Generator                                  |
| `vscode.html`         | 3.1 IntelliSense · 3.2 Preview Canvas & Cloud Sync (MVP)       |
| `git-branches.html`   | 4.1 Branch-Per-Version Strategy (MVP)                          |
| `pull-request.html`   | 4.2 Schema PR Workflow (MVP) · 4.4 Inline Schema Diff in PRs   |
| `blame.html`          | 4.3 Git Blame & Property Authorship History                    |

## Design system

Mockups intentionally mirror the live `apiome-ui` shell and align with
the sibling `mockups/architect`, `mockups/academy`, and `mockups/analytics`
sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, IDs,
  field names, and version strings
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`), with a
  purple gradient on the DevEx wordmark to differentiate from sibling sets
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 260 px gradient sidebar, 48 px top platform bar, panel cards
  (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700`)
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set
- **Theme**: class-based dark mode toggle, persisted to `localStorage`
  under `devex-mockup-theme`. Honors `prefers-color-scheme` on first load.

## DevEx-specific visual language

Beyond the shared shell, the DevEx mockups introduce a few conventions that
the production build is expected to honor:

- **Change classification dots**: emerald (additive), amber (deprecated),
  rose / red (breaking), cyan (modified non-breaking) — used consistently
  in `changelog.html`, `diff.html`, `pull-request.html`, and `blame.html`.
- **Version pills**: `mono` text on a tinted background that matches the
  branch type — emerald for v1.x, cyan for v2.x, amber for v3.x. The pill
  itself replaces the chip-with-icon pattern used elsewhere.
- **Inline diff hunks**: red strike-through for removals, green for
  additions, slate for context — wrapped in `mono` and rendered inside
  rounded panels rather than the classic two-column gutter.
- **PR review threads** (`pull-request.html`): comment cards anchor to the
  field path (`User.phone`) rather than a line number, so they survive
  schema restructuring.
- **Branch lineage** (`git-branches.html`): an inline SVG renders the
  `release/v*` branches as horizontal lanes with merge arrows, mirroring
  what the production Git integration layer will draw.
- **VS Code chrome** (`vscode.html`): the activity bar, side bar, editor,
  and minimap follow VS Code's spacing exactly so screenshots can stand in
  for marketplace assets without rework.

## Conventions matched from production code

Shared layout tokens come from
`app/components/ade/dashboard/dashboardScreenClasses.ts` and
`app/components/ade/dashboard/DashboardSideNav.tsx`:

- Section headers in the sidebar use `text-[0.65rem]` uppercase with a
  1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Active nav items use a 10% indigo fill + 1 px border + indigo text + a
  small dot indicator
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- Code blocks use `JetBrains Mono` at `12px / 1.5` line-height, matching
  the Designer canvas property sheet

## What's intentionally faked

- All schemas, versions, commits, authors, and changelog entries are
  hard-coded
- Monaco-style editors are static markup with class-based syntax colors —
  no real tokenizer
- ReDoc, Slate, and the VS Code preview canvas are screenshots-in-HTML, not
  embedded renderers
- Branch graphs use static SVG paths; merge arrows do not animate
- Diff and blame views read from inline data, not the
  `property_blame` materialised view described in the roadmap
- The theme toggle is the only piece of working JS (plus Lucide icon
  hydration)

## Out of scope (not included)

These belong to later phases of the roadmap and were excluded from the MVP
mockup set:

- 1.2 Slate Documentation Generator (alternate renderer; reuses the
  ReDoc layout)
- 1.3 Custom Static Site Builder (deployment / pipeline concern, not UI)
- 3.3 JetBrains Plugin and 3.4 Vim/Neovim Plugin (the VS Code mockup is the
  reference; other IDEs will reuse its visual conventions)
- 4.5 Schema Conflict Resolution UI (a focused detail of the PR mockup;
  represented inline within `pull-request.html` as a banner)
