# Browse mockups

Static, browser-openable design mockups for the
[Browse feature roadmap](../../../../docs/FUTURE_FEATURE_ROADMAP_BROWSER.md).

These files cover the **MVP scope** for the public-facing spec viewer — tenant
discovery (Epic 1), Monaco-based spec viewing (Epic 2), version comparison and
diffing (Epic 3), share & embed (Epic 4), global search (Epic 5), changelog &
timeline (Epic 3.5), and tenant analytics (Epic 9). They are visual references —
no API calls, no auth, no build step.

## Open

Either open the files directly:

```
open apiome-ui/public/mockups/browser/index.html
```

Or, with the Next.js dev server running, browse to:

```
http://localhost:3000/mockups/browser/index.html
```

## Files

| File                  | Maps to roadmap issue                                                  |
| --------------------- | ---------------------------------------------------------------------- |
| `index.html`          | Mockup hub linking to all screens                                      |
| `tenant-home.html`    | 1.3 Tenant home · 1.4 Tag filters · 9.1 Most viewed · 9.4 Relationships |
| `version-viewer.html` | 1.1 Deep links · 2.1 Outline tree · 2.2 Monaco viewer · 2.3 Lint · 2.5 Examples · 4.4 Copy snippets · 11.1 Shortcuts |
| `compare.html`        | 3.1 Side-by-side diff · 3.2 Breaking changes · 3.3 Section filters · 3.4 Export |
| `playground.html`     | 2.4 Paste-and-view (client-side, no persistence)                       |
| `search.html`         | 5.2 Global search · 5.3 Autocomplete · 5.4 Advanced filters            |
| `changelog.html`      | 3.5 Changelog & version timeline                                       |
| `embed-share.html`    | 4.4 Shareable links · 1.2 Embed widget · domain allowlist              |
| `analytics.html`      | 9.2 Tenant analytics dashboard · CSV export                            |

## Design system

Mockups intentionally mirror the live `apiome-ui` shell and align with the
sibling `mockups/architect`, `mockups/academy`, and `mockups/analytics` sets:

- **Typography**: Inter (400/500/600/700), JetBrains Mono for code, IDs, paths,
  and metric values
- **Accent**: indigo-500 / 600 (Radix `accentColor="indigo"`)
- **Gray scale**: slate (Radix `grayColor="slate"`)
- **Layout**: 48 px top platform bar with breadcrumb (`tenant / project / view`),
  panel cards (`bg-white dark:bg-gray-800 rounded-lg border border-gray-200
  dark:border-gray-700`), `bg-gray-50 dark:bg-gray-900` panel headers
- **Icons**: Lucide (CDN), matching the live `lucide-react` icon set —
  `compass` is the Browse product mark
- **Theme**: class-based dark mode toggle, persisted to `localStorage` under
  `browser-mockup-theme`. Honors `prefers-color-scheme` on first load.

## Browse-specific visual language

Beyond the shared shell, the Browse mockups introduce a few conventions that
the production build is expected to honor:

- **Spec format chips** use color-coded pills: indigo for OpenAPI, fuchsia for
  Arazzo, emerald for JSON Schema
- **Outline tree** in `version-viewer.html` uses a 2-space-indented mono list
  with chevrons; HTTP verbs render as colored mono badges
  (`get` cyan, `post` emerald, `put` amber, `delete` rose, `patch` violet)
- **Diff gutters** use `bg-emerald-50` for additions, `bg-rose-50` for deletions,
  `bg-amber-50` for modifications, with a 4 px left border in the matching color
- **Breaking change** flag uses a rose pill with `alert-triangle` icon, always
  paired with the change classification (`removed`, `narrowed`, `required`)
- **Deprecated surfaces** use a strikethrough on the path/property name plus an
  amber `clock` icon, mirroring the spec's `deprecated: true`
- **Required fields** in schema previews use a red asterisk after the property
  name (`name *`), distinct from the value type chip
- **Share / embed tokens** render as truncated mono strings with the
  significant prefix highlighted in indigo

## Conventions matched from production code

Shared layout tokens come from `app/components/ade/dashboard/dashboardScreenClasses.ts`
and the sidebar / breadcrumb pattern in the live shell:

- Section headers use `text-[0.65rem]` uppercase with a 1×1 indigo dot
- Panels use `bg-gray-50 dark:bg-gray-900` for header bars
- Page headers follow the `<h2>` + lucide icon + subtitle pattern from
  `dashboard/page.tsx`
- Toggles use the same 32×18 indigo pill defined inline in `embed-share.html`,
  matching the production `Switch` component visually
- Stat cards use the same metric-tile layout as `mockups/analytics`

## What's intentionally faked

- All tenants, projects, versions, diffs, and metrics are hard-coded
- Monaco is rendered as static HTML with hand-tokenized YAML — not a real
  editor (the production `version-viewer` will host an actual Monaco instance
  in read-only mode)
- The line chart and sparklines in `analytics.html` are inline SVG paths with
  no data binding
- Diff highlighting in `compare.html` is hand-painted; production will use
  jsondiffpatch + a custom decorator
- Search autocomplete and "recent" history are static lists
- The theme toggle and Lucide icon hydration are the only working JS

## Out of scope (not included as standalone screens)

These belong to later phases of the roadmap or are sub-views of an existing
mockup, and were excluded from the MVP mockup set:

- 1.5 Cross-spec navigation drawer (sub-panel of `version-viewer`)
- 2.6 Spec linting rules editor (admin-only configuration page)
- 3.6 Three-way comparison view (post-MVP)
- 4.1 PDF / static HTML export configuration (sub-flow from `version-viewer`
  share menu)
- 5.5 Saved searches & alerts
- 6.x Performance & caching admin views (operator-only)
- 7.x Accessibility audit dashboard (covered by global a11y testing, not a
  product surface)
- 8.x Internationalization management (covered by `next-intl` config)
- 10.x Enterprise theming page (covered in tenant settings, not Browse)
- 12.x Audit log viewer (admin product, separate roadmap)
- 13.x Public marketing site (separate Next.js app)
