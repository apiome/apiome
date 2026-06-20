# Data Designer mockups

Visual designs for the Objectified **schema designer** — the React Flow canvas
shipped at `/ade/studio/editor` plus the natural extensions surfaced in the
roadmap docs (`FUTURE_FEATURE_ROADMAP_OFFLINE.md`, `PLANNED_FEATURE_ROADMAP_AI.md`,
`FUTURE_FEATURE_ROADMAP_LINTING.md`, `FUTURE_FEATURE_ROADMAP_DIFF.md`).

Open `index.html` for the hub.

## What's mocked here

The Data Designer is where teams **draw their domain as a graph**: classes are
nodes, `$ref` / `link_def` relationships are edges, and the JSON-Schema-style
properties on each class are the source of truth that downstream features
(MDM, code-gen, paths, mock server, lineage, lint) all consume.

Mockups split the experience into three epics:

### Epic 1 · Canvas & class authoring (in product today)

| Screen | What it shows |
|---|---|
| `editor.html` | Full **React Flow** canvas. Node toolbar (add class · group · auto-layout · fit · density), mini-map, edge legend (direct / optional / weak / bidirectional), focus mode, AI chat dock, version chip in header. Mirrors `/ade/studio/editor`. |
| `class-edit.html` | Full-page **`ClassEditDialog`** equivalent: identity (name · slug · namespace · tags), property table with type · format · constraints, composition tabs (`allOf` / `anyOf` / `oneOf` / `if-then-else`), examples, JSON Schema preview pane. |
| `groups.html` | **Bounded-context lanes** on canvas. Color-tagged groups with class membership, "promote group → microservice" CTA (links to code-gen), per-group lint score. |

### Epic 2 · Reuse & relationships (extensions of current behavior)

| Screen | What it shows |
|---|---|
| `property-library.html` | A **shared, typed property catalog**. Each row is a reusable property (e.g. `email`, `iso_country`, `monetary_amount`) with usage counts across classes, change-impact preview ("renaming this touches 14 classes / 87 instances"), drift warnings, and one-click safe rename. |
| `references.html` | First-class **reference editor**. Source class · target class · cardinality (1, 0..1, *, 0..*) · reference kind (direct, optional, weak, bidirectional) · on-delete (restrict, cascade, null) · projection ("which target fields denormalize"). Companion graph view highlights orphans, cycles, and unconnected nodes (linting). |

### Epic 3 · Code · versions · AI

| Screen | What it shows |
|---|---|
| `code-view.html` | **Monaco** rendering of the same project as OpenAPI 3.1 / JSON Schema / GraphQL SDL / SQL DDL / AsyncAPI / Arazzo. Format selector, diff toggle, copy-with-namespace, "round-trip" badge that goes red if the canvas and code disagree. |
| `versions.html` | Immutable **`schema_capture`** timeline (per database roadmap §1.1). Each capture row: who · when · hash · description · diff to current · used by which paths · used by which MDM domain. Branch / tag / pin / rollback. |
| `ai-assistant.html` | The Studio **AI co-pilot** as a full-page workspace: natural-language class generation, "explain this reference graph", "find missing index", "convert this enum to a reference data table", inline diff preview before commit. |

## Visual system

- **Gradient identity**: `from-violet-500 to-fuchsia-500` (icon: `pencil-ruler`).
- **Theme key**: `designer-mockup-theme` (persists `dark` / `light`, honors `prefers-color-scheme` on first visit).
- **Typography**: Inter for UI, JetBrains Mono for code, IDs, paths.
- **Layout**: 280px gradient sidebar (`.sidebar-light` / `.sidebar-dark`), 48px top platform bar, panel cards (`bg-white dark:bg-gray-800 rounded-lg border`).
- **Charts / graphs**: hand-rolled inline SVG (graphs, sparklines, gauges).
- **Icons**: Lucide via CDN.

## Relation to other mockup packs

- **MDM** (`/mockups/mdm`) consumes the classes built here — promoting one to
  a master-data domain happens against a **frozen** schema capture.
- **Paths** (`/mockups/paths`) consumes classes as request / response schemas;
  the CRUD generator there reads the same project model.
- **Linting** (`/mockups/linting`) overlays schema-quality findings on the
  canvas (cycles, naming, missing examples, unbounded enums).
- **Detective** records every canvas mutation as an event; **versions.html**
  is just a curated view over that audit trail.

## Phased delivery

Following `.cursorrules` (≤ 5 files per phase):

- **Phase 1** — `index.html` · `README.md` (this commit).
- **Phase 2** — `dashboard.html` · `editor.html` · `class-edit.html`.
- **Phase 3** — `property-library.html` · `references.html` · `groups.html`.
- **Phase 4** — `code-view.html` · `versions.html` · `ai-assistant.html`.
