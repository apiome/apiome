# API Paths Designer mockups

Visual designs for the Objectified **API Paths Designer** — the OpenAPI 3.1
surface shipped at `/ade/studio/paths` plus the natural extensions surfaced in
`docs/FUTURE_FEATURE_ROADMAP_PATHS_SECOND.md`,
`docs/FUTURE_FEATURE_ROADMAP_CODE_GENERATION.md` and
`docs/FUTURE_FEATURE_ROADMAP_TESTING.md`.

Open `index.html` for the hub.

> **Naming note.** "Paths" in Objectified means **OpenAPI URL paths**
> (e.g. `/customers/{id}`), not JSONPath and not the per-field provenance
> tracing you'll find at `/mockups/mdm/lineage.html`. The mockups consistently
> use "API path" in copy where that distinction matters.

## What's mocked here

The Paths Designer is where teams **describe their HTTP API as a graph** —
paths are nodes, operations are chips on the node, and request/response
schemas are pulled from the same project the Data Designer manages. Mockups
split the experience into three epics:

### Epic 1 · Canvas & editors (in product today)

| Screen | What it shows |
|---|---|
| `canvas.html` | Full **React Flow** paths canvas. 280px-wide nodes, one per `PathItem`, with method chips for each operation; sidebar (paths · operations · classes · properties · security · servers); focus mode that walks the **traversal graph** at any depth (matching the roadmap). |
| `path-editor.html` | Single path detail page. Path-template params, summary · description · tags, per-method tabs (GET · POST · PUT · PATCH · DELETE · HEAD · OPTIONS), `x-` extensions, and a "tag for ownership" panel. |
| `operation-editor.html` | Single operation editor: parameters table (path · query · header · cookie), request body (content-type matrix · schema picker · examples), responses by status code, security override, callbacks, deprecation banner, "test in playground" button. |

### Epic 2 · Reusable components (in product today, fleshed out)

| Screen | What it shows |
|---|---|
| `parameters.html` | Library of reusable parameters (`#/components/parameters/*`). Type · location · style · explode · usage counts · last edited. Bulk rename and "find unused". |
| `responses.html` | Shared response shapes (`#/components/responses/*`) and a separate panel for `#/components/schemas/*` that double as response bodies. Standard error envelope template. |
| `security.html` | Security schemes (API key · HTTP basic · HTTP bearer · OAuth2 flows · OIDC · mTLS) and the **server matrix** (dev · staging · prod · regions) with per-environment variable substitution. |

### Epic 3 · Code · CRUD generation

| Screen | What it shows |
|---|---|
| `code-view.html` | **Monaco** rendering the same project as OpenAPI 3.1 YAML / JSON. Diff vs. last published, validate button, copy-tagged-section, "round-trip" badge that goes red if canvas and code disagree (mirrors the Data Designer code view). |
| `crud-generator.html` | Pick a class from the project, pick the endpoints (`list` / `get` / `create` / `update` / `delete` / `bulk` / `search`), preview the OpenAPI fragment, and drop the new paths onto the canvas. Links forward to **code-gen** for the server stub. |

## Visual system

- **Gradient identity**: `from-emerald-500 to-teal-500` (icon: `route`).
- **Theme key**: `paths-mockup-theme` (persists `dark` / `light`, honors `prefers-color-scheme`).
- **Typography**: Inter for UI, JetBrains Mono for paths, methods, schemas.
- **Layout**: 280px gradient sidebar (`.sidebar-light` / `.sidebar-dark`), 48px top platform bar, panel cards.
- **Method chips**: emerald (GET), sky (POST), amber (PUT), violet (PATCH), rose (DELETE), gray (HEAD/OPTIONS).
- **Charts**: hand-rolled inline SVG (traffic, error rate, deprecation timeline).
- **Icons**: Lucide via CDN.

## Relation to other mockup packs

- **Data Designer** (`/mockups/designer`) builds the classes that this
  designer references in request/response bodies.
- **Code-gen** (`/mockups/code-gen`) consumes published paths to emit server
  stubs and client SDKs.
- **MDM** (`/mockups/mdm`) and **Detective** consume paths for
  webhook subscribers and delivery audit.
- **Browser** (`/mockups/browser`) renders read-only API docs from the
  same OpenAPI document.

## Phased delivery

Following `.cursorrules` (≤ 5 files per phase):

- **Phase 1** — `index.html` · `README.md` (this commit).
- **Phase 2** — `dashboard.html` · `canvas.html` · `path-editor.html`.
- **Phase 3** — `operation-editor.html` · `parameters.html` · `responses.html`.
- **Phase 4** — `security.html` · `code-view.html` · `crud-generator.html`.
