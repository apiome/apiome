# Objectified: Developer Experience (DevEx) - Feature Roadmap

> Developer-facing tools and workflows that accelerate schema design—auto-generated documentation beyond Swagger, schema changelogs with breaking-change detection, IDE extensions for VS Code and JetBrains, and advanced Git workflows for branch-per-version and PR-based schema review.
>
> **Revenue Model**: Pro tier feature, IDE extensions free with cloud sync on Pro
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, Monaco Editor (for IDE-like editing), Language Server Protocol (LSP), REST/OpenAPI 3.1, PostgreSQL, Git integration layer
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- ReDoc documentation renderer with automatic schema-driven page generation
- Changelog generation engine with structured diff output between schema versions
- Breaking-change detection with severity classification and deprecation notices
- VS Code extension with syntax highlighting, IntelliSense, and schema validation via LSP
- Branch-per-version strategy with automatic branch creation on schema publish
- Pull request workflow for schema changes with inline review comments
- Custom documentation pages and branding for Pro tenants

---

## Epic 1: Auto-Generated Documentation

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1323) | ReDoc Documentation Renderer | Render published schemas as interactive ReDoc documentation pages | `enhancement`, `devex`, `mvp`, `rest`, `ai-generated` | Yes |
| 1.2 (#1348) | Slate Documentation Generator | Generate Slate-based three-panel API docs from schema captures | `enhancement`, `devex`, `rest`, `ai-generated` | Yes |
| 1.3 (#1356) | Custom Static Site Builder | Build and deploy a fully customizable static documentation site from schemas | `enhancement`, `devex`, `rest`, `ai-generated` | Yes |
| 1.4 (#1364) | Custom Pages, Guides & Branding | Author custom documentation pages, integration guides, and apply tenant branding | `enhancement`, `devex`, `mvp`, `rest`, `ai-generated` | No |

### Detailed Issue Descriptions

---

#### 1.1 (#1323) — ReDoc Documentation Renderer

ReDoc is the most popular open-source alternative to Swagger UI for rendering OpenAPI specifications. This issue integrates ReDoc as a documentation output format, automatically generating interactive three-panel documentation pages from published Objectified schemas. Unlike the existing Swagger UI integration (which lives inside Studio), ReDoc documentation is a standalone, publicly shareable artifact that tenants can embed in their own developer portals.

The rendering pipeline reads a schema capture via `GET /api/v1/schema-captures/{id}` and transforms it into an OpenAPI 3.1 specification enriched with descriptions, examples, and constraints from the Objectified data model. The generated spec is served at `GET /api/v1/docs/{namespaceId}/redoc-spec?version={v}` and the rendered ReDoc page is a NextJS route at `/app/docs/[namespaceId]/redoc`. The page uses ISR with a 60-second revalidation interval so documentation updates automatically when schemas change.

```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐     ┌──────────┐
│   Schema     │────▶│   OpenAPI     │────▶│   ReDoc      │────▶│  Static  │
│   Capture    │     │   Generator   │     │   Renderer   │     │  Page    │
│   (frozen)   │     │   (3.1 spec)  │     │   (client)   │     │  (ISR)   │
└──────────────┘     └───────────────┘     └──────────────┘     └──────────┘
       │                     │
       │  classes,           │  enriched with
       │  properties,        │  examples,
       │  constraints        │  descriptions
       ▼                     ▼
 ┌──────────────┐     ┌───────────────┐
 │  Objectified │     │  Tenant       │
 │  REST API    │     │  Branding     │
 └──────────────┘     └───────────────┘
```

Version selection is handled by a Radix `Select` dropdown at the top of the page, allowing readers to switch between schema versions without navigating away. A Radix `Tabs` component separates the documentation into logical sections when the schema contains multiple top-level classes. The ReDoc configuration (expand depth, hide download button, theme colors) is stored per namespace and editable via `PUT /api/v1/docs/{namespaceId}/redoc-config`.

**Acceptance Criteria**
- Published schemas render as interactive ReDoc documentation at `/app/docs/[namespaceId]/redoc`
- OpenAPI 3.1 spec is generated from schema captures with descriptions, examples, and constraints
- Version selector allows switching between schema versions via Radix `Select`
- ReDoc configuration (theme, expand depth, download button) is customizable per namespace
- ISR ensures documentation updates within 60 seconds of a new schema publish
- The generated OpenAPI spec endpoint is publicly accessible for external tooling consumption
- ReDoc pages are embeddable via iframe with configurable CORS headers

**Part of Epic: Auto-Generated Documentation**

---

#### 1.2 (#1348) — Slate Documentation Generator

Slate produces the classic three-panel API documentation layout favored by companies like Stripe and Twilio: navigation on the left, prose documentation in the center, and code examples on the right. This issue builds a Slate-compatible documentation generator that transforms Objectified schemas into Slate markdown source files, which are then compiled into a static HTML bundle.

The generator reads schema captures and produces markdown files following Slate's format conventions: YAML front matter for navigation ordering, heading-based section structure, and fenced code blocks with language tags for multi-language examples. Each schema class becomes a documentation section with subsections for properties, constraints, relationships, and example payloads. Code examples are generated in multiple languages (cURL, JavaScript, Python, Ruby) using request/response shapes derived from the schema.

The build pipeline is triggered via `POST /api/v1/docs/{namespaceId}/slate/build` and runs as an async job that compiles the markdown into a static HTML bundle. Build status is available at `GET /api/v1/docs/{namespaceId}/slate/build/{buildId}`. Completed builds are downloadable as a ZIP archive or previewable at `/app/docs/[namespaceId]/slate/preview`. The build configuration page at `/app/docs/[namespaceId]/slate/configure` uses Radix `Checkbox` for selecting which schema classes to include, `Select` for target languages, and `Accordion` for advanced build options.

**Acceptance Criteria**
- Schema captures are transformed into Slate-compatible markdown with correct front matter
- Generated documentation includes property tables, constraints, relationships, and example payloads
- Code examples are generated in at least four languages (cURL, JavaScript, Python, Ruby)
- Build runs asynchronously with status tracking via REST API
- Completed builds are downloadable as ZIP and previewable in the browser
- Build configuration allows selecting schema classes and target languages
- Incremental rebuilds only regenerate sections for changed schema classes

**Part of Epic: Auto-Generated Documentation**

---

#### 1.3 (#1356) — Custom Static Site Builder

While ReDoc and Slate serve specific documentation formats, some teams need full control over their documentation site's structure, styling, and deployment. This issue builds a configurable static site generator that produces a complete documentation website from schema captures, custom templates, and tenant-provided content—deployable to any CDN or custom domain.

The site builder uses a template engine with a default theme (clean, responsive, sidebar navigation) that can be overridden with custom HTML/CSS templates uploaded by the tenant. Templates access schema data through a simple variable system: `{{classes}}`, `{{class.properties}}`, `{{class.examples}}`. The build pipeline compiles templates against schema data and produces a static HTML/CSS/JS bundle with client-side search powered by a pre-built search index.

```
┌────────────┐     ┌──────────────┐     ┌──────────────┐
│  Schema    │     │   Template   │     │   Custom     │
│  Capture   │     │   Engine     │     │   Content    │
└─────┬──────┘     └──────┬───────┘     └──────┬───────┘
      │                   │                    │
      └───────────┬───────┘────────────────────┘
                  ▼
         ┌────────────────┐
         │  Static Site   │
         │  Build Pipeline │
         └───────┬────────┘
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
   ┌────────┐ ┌──────┐ ┌──────────┐
   │  HTML  │ │ CSS  │ │  Search  │
   │  Pages │ │ Theme│ │  Index   │
   └────────┘ └──────┘ └──────────┘
                 │
                 ▼
         ┌────────────────┐
         │  CDN / Custom  │
         │  Domain Deploy │
         └────────────────┘
```

Site configuration is managed at `/app/docs/[namespaceId]/site/configure` with Radix `Tabs` for switching between "Theme," "Templates," and "Deploy" panels. The REST API exposes `POST /api/v1/docs/{namespaceId}/site/build` (trigger build), `GET /api/v1/docs/{namespaceId}/site/status` (build status and deploy URL), and `PUT /api/v1/docs/{namespaceId}/site/config` (update site configuration including custom domain and template overrides). Template uploads use `POST /api/v1/docs/{namespaceId}/site/templates` with multipart form data.

**Acceptance Criteria**
- Static site builds from schema captures with default theme producing a navigable documentation website
- Custom HTML/CSS templates can override the default theme via template upload
- Client-side search index is pre-built during the build step and works without a backend
- Build status and deploy URL are accessible via REST API
- Custom domain configuration is supported with CNAME verification
- Template variable system exposes schema classes, properties, constraints, and examples
- Build output is downloadable as a ZIP for self-hosting

**Part of Epic: Auto-Generated Documentation**

---

#### 1.4 (#1364) — Custom Pages, Guides & Branding

Auto-generated documentation covers API structure, but teams also need custom content: getting-started guides, authentication tutorials, rate-limit policies, and integration walkthroughs. This issue adds a custom page editor that lets tenants author markdown content alongside their auto-generated docs, and a branding system that applies tenant identity (logo, colors, typography) across all documentation outputs.

The page editor at `/app/docs/[namespaceId]/pages` renders a list of custom pages in a Radix `Table` with columns for title, URL slug, last modified, and status (draft/published). Creating or editing a page opens a split-pane editor: Monaco Editor on the left for markdown authoring with live preview on the right. Pages support front matter for metadata (title, description, order, parent page) and can embed schema references using a `{{schema:className}}` shortcode that renders an inline property table.

Branding configuration lives at `/app/docs/[namespaceId]/branding` with controls for logo upload (Radix `Avatar` preview), accent color (color picker), favicon, custom CSS injection, and footer text. Branding is applied consistently across ReDoc, Slate, and custom static site outputs. The branding API endpoints are `PUT /api/v1/docs/{namespaceId}/branding` (update branding settings) and `GET /api/v1/docs/{namespaceId}/branding` (retrieve current branding). Custom pages use CRUD at `POST /api/v1/docs/{namespaceId}/pages`, `GET /api/v1/docs/{namespaceId}/pages`, `PUT /api/v1/docs/{namespaceId}/pages/{pageId}`, and `DELETE /api/v1/docs/{namespaceId}/pages/{pageId}`.

Pages are organized into a tree structure via a `parent_page_id` field, rendered as a collapsible sidebar using Radix `Accordion`. Navigation ordering uses a `sort_order` integer field, and the sidebar merges custom pages with auto-generated schema pages into a single unified navigation tree.

**Acceptance Criteria**
- Custom pages are authored in markdown with Monaco Editor and live preview
- Schema reference shortcodes (`{{schema:className}}`) render inline property tables
- Pages support hierarchical organization with parent-child relationships
- Branding (logo, accent color, favicon, custom CSS) applies across all documentation outputs
- Navigation sidebar merges custom and auto-generated pages into a unified tree
- Page status (draft/published) controls visibility in public documentation
- Custom pages are versioned—editing creates a new revision with rollback support
- Branding preview shows the applied theme before publishing

**Part of Epic: Auto-Generated Documentation**

---

## Epic 2: Schema Changelog & Migration

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1382) | Changelog Generation Engine | Auto-generate structured changelogs between schema versions | `enhancement`, `devex`, `mvp`, `rest`, `ai-generated` | Yes |
| 2.2 (#1392) | Breaking Change Detection & Deprecation Notices | Classify changes by severity and manage deprecation timelines | `enhancement`, `devex`, `mvp`, `rest`, `ai-generated` | Yes |
| 2.3 (#1403) | Migration Guide Generator | Generate actionable migration guides from breaking changes | `enhancement`, `devex`, `rest`, `ai-generated` | No |
| 2.4 (#1415) | Visual Diff View | Side-by-side visual comparison of schema versions with field-level highlighting | `enhancement`, `devex`, `mvp`, `ai-generated` | Yes |

### Detailed Issue Descriptions

---

#### 2.1 (#1382) — Changelog Generation Engine

Every schema version publish should produce a human-readable changelog describing what changed, why it matters, and who is affected. This issue builds the changelog generation engine that compares two schema captures and produces a structured diff document with entries categorized by change type: added classes, removed classes, modified properties, changed constraints, and updated descriptions.

The engine fetches two schema captures via the Objectified REST API (`GET /api/v1/schema-captures/{id}`) and performs a deep structural comparison. For each detected change, the engine generates a changelog entry with: the change path (e.g., `User.address.zipCode`), the change type (added/removed/modified), the before and after values, and an auto-generated summary sentence. Changes are grouped by class for readability.

```
┌──────────────┐     ┌──────────────┐
│  Capture v1  │     │  Capture v2  │
│  (frozen)    │     │  (frozen)    │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └────────┬───────────┘
                ▼
       ┌────────────────┐
       │  Structural    │
       │  Diff Engine   │
       └───────┬────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌──────────┐
│ Added  │ │Removed │ │ Modified │
│ Fields │ │ Fields │ │ Fields   │
└────────┘ └────────┘ └──────────┘
               │
               ▼
       ┌────────────────┐
       │  Changelog     │
       │  Document      │
       │  (MD / JSON)   │
       └────────────────┘
```

Changelogs are generated via `POST /api/v1/schemas/{schemaId}/changelog` with parameters for `fromVersion` and `toVersion`. The response includes a JSON changelog object and a rendered markdown string. Changelogs are persisted in a `schema_changelogs` table keyed by `(schema_id, from_version, to_version)` so they only need to be computed once. The changelog view at `/app/schemas/[id]/changelog` displays the changelog entries in a timeline using Radix `Accordion` for expandable change groups and `Badge` for change type labels (green for added, red for removed, yellow for modified).

**Acceptance Criteria**
- Changelogs are generated from structural comparison of two schema captures
- Change entries include path, type (added/removed/modified), before/after values, and summary
- Changes are grouped by schema class for readability
- Output is available in both JSON and rendered markdown formats
- Computed changelogs are cached in PostgreSQL to avoid redundant computation
- The changelog page at `/app/schemas/[id]/changelog` renders entries with Radix `Accordion` and `Badge`
- Changelogs can be generated for non-adjacent versions (e.g., v1 → v5)

**Part of Epic: Schema Changelog & Migration**

---

#### 2.2 (#1392) — Breaking Change Detection & Deprecation Notices

Not all changes are equal. Removing a required field breaks every consumer; adding an optional field breaks nobody. This issue adds a severity classifier to the changelog engine that categorizes each change as breaking, non-breaking, or informational—and provides deprecation management tools for phasing out fields gracefully over time.

Breaking changes include: removing a class or required property, narrowing a type (e.g., `string` → `enum`), adding new required properties, tightening constraints (lowering maxLength, raising minimum), and removing enum values. Non-breaking changes include: adding optional properties, widening types, loosening constraints, and adding enum values. The classifier uses a rules engine stored in a `breaking_change_rules` table, allowing tenants to customize severity for domain-specific patterns.

Deprecation notices are managed through a `deprecated_at` and `removal_target_version` annotation on schema properties. When a property is marked deprecated via `PUT /api/v1/schemas/{schemaId}/classes/{className}/properties/{propName}/deprecate`, the system records the deprecation timestamp, target removal version, and a migration hint (free-text explaining what to use instead). Deprecated properties surface as warnings in changelogs, IDE extensions (issue 3.1), and documentation outputs.

The deprecation dashboard at `/app/schemas/[id]/deprecations` shows all deprecated properties across the schema using a Radix `Table` with columns for property path, deprecated since, target removal version, migration hint, and consumer impact count. The REST API provides `GET /api/v1/schemas/{schemaId}/breaking-changes?from={v1}&to={v2}` for the classified change list and `GET /api/v1/schemas/{schemaId}/deprecations` for active deprecation notices.

**Acceptance Criteria**
- Changes are classified as breaking, non-breaking, or informational using the rules engine
- Breaking change rules are customizable per tenant for domain-specific patterns
- Deprecated properties carry `deprecated_at`, `removal_target_version`, and migration hint metadata
- Deprecation warnings appear in changelogs, documentation, and IDE diagnostics
- The deprecation dashboard shows all deprecated properties with consumer impact counts
- Publishing a version that removes a non-deprecated required property triggers an explicit warning
- Breaking change classification is deterministic—the same inputs always produce the same result

**Part of Epic: Schema Changelog & Migration**

---

#### 2.3 (#1403) — Migration Guide Generator

Changelogs describe what changed; migration guides explain what to do about it. This issue builds a guide generator that consumes the breaking change list (from 2.2) and produces a step-by-step migration document with code examples showing the old pattern, the new pattern, and any data transformation required.

For each breaking change, the generator produces a migration step with: a title, an explanation of why the change was made (pulled from the changelog summary or commit message), a "before" code example showing the old usage, an "after" code example showing the new usage, and any intermediate transformation logic. Code examples are generated in configurable target languages (default: cURL, JavaScript, Python). When a deprecated property has a migration hint, that hint is expanded into the guide's explanation.

The guide is generated via `POST /api/v1/schemas/{schemaId}/migration-guide` with parameters for `fromVersion`, `toVersion`, and `targetLanguages`. The response includes both JSON (structured steps) and rendered markdown. The guide page at `/app/schemas/[id]/migration` renders the steps in a numbered list with Radix `Tabs` for language-specific code examples and `Accordion` for expanding step details. A "Download Guide" button exports the guide as a standalone markdown file.

Migration guides are stored in a `schema_migration_guides` table and associated with the changelog they were derived from. When a changelog is regenerated (due to a schema re-capture), the associated migration guide is flagged as stale and queued for regeneration.

**Acceptance Criteria**
- Migration guide is generated from breaking changes with step-by-step instructions
- Each step includes before/after code examples in configurable target languages
- Deprecated property migration hints are incorporated into guide explanations
- Guide is available in JSON and rendered markdown formats
- The guide page renders with Radix `Tabs` for language selection and `Accordion` for step detail
- Stale guides are flagged and re-queued when underlying changelogs are regenerated
- Guide download exports a standalone markdown file suitable for inclusion in a repository

**Part of Epic: Schema Changelog & Migration**

---

#### 2.4 (#1415) — Visual Diff View

Changelogs and migration guides are text-based. For a quick visual understanding of what changed between two schema versions, developers need a side-by-side diff view with field-level highlighting—similar to a Git diff but specialized for structured schema data rather than raw text.

The diff view at `/app/schemas/[id]/diff` renders two schema versions side by side in a split panel. Each panel displays the schema's class hierarchy as an expandable tree. Added nodes are highlighted green, removed nodes red, and modified nodes yellow. Clicking a modified node expands an inline comparison showing the old and new values for each changed attribute (type, constraints, description, default). A summary bar at the top shows counts: "3 added, 1 removed, 7 modified."

```
┌─────────────────────────────────────────────────────────────┐
│  Schema Diff: v2.1.0  ←→  v3.0.0        [v2.1.0 ▼] [v3.0.0 ▼]  │
│  Summary: 3 added · 1 removed · 7 modified                 │
├────────────────────────────┬────────────────────────────────┤
│  v2.1.0                    │  v3.0.0                        │
│                            │                                │
│  ▼ User                    │  ▼ User                        │
│    ├─ id: string           │    ├─ id: string               │
│    ├─ name: string         │    ├─ name: string             │
│    ├─ email: string        │    ├─ email: string            │
│  ░░├─ phone: string  ░░░░░│  ░░├─ phone: string  ░░░░░░░░░│
│  ░░│  maxLen: 20     ░░░░░│  ░░│  maxLen: 15     ░░░░░░░░░│
│  ──├─ age: integer─────── │                                │
│    │                       │  ++├─ dateOfBirth: date-time++ │
│    │                       │  ++├─ locale: string        ++ │
│    └─ address: object      │    └─ address: object          │
└────────────────────────────┴────────────────────────────────┘
  ░░ modified   ── removed   ++ added
```

Version selection uses two Radix `Select` dropdowns. The diff computation reuses the structural diff engine from 2.1 but adds positional alignment so that the two panels scroll in sync. A "Show unchanged" toggle (Radix `Switch`) hides unmodified nodes to focus attention on changes. The diff data is served by `GET /api/v1/schemas/{schemaId}/diff?from={v1}&to={v2}` which returns a structured diff object with aligned node positions.

**Acceptance Criteria**
- Side-by-side diff renders two schema versions with synchronized scrolling
- Added, removed, and modified nodes are color-coded (green, red, yellow)
- Modified nodes expand to show before/after values for each changed attribute
- Summary bar displays accurate counts of added, removed, and modified elements
- Version selection uses Radix `Select` dropdowns with all available versions
- "Show unchanged" toggle hides unmodified nodes for focused review
- Diff view handles schemas with 500+ properties without performance degradation

**Part of Epic: Schema Changelog & Migration**

---

## Epic 3: IDE Extensions

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1432) | VS Code Extension: Schema Editing & IntelliSense | LSP-powered editing with syntax highlighting, completion, and diagnostics | `enhancement`, `devex`, `mvp`, `ai-generated` | Yes |
| 3.2 (#1442) | VS Code Extension: Preview Canvas & Cloud Sync | Visual schema preview panel and bidirectional sync with Objectified cloud | `enhancement`, `devex`, `ai-generated` | No |
| 3.3 (#1451) | JetBrains Plugin | IntelliJ, WebStorm, and PyCharm integration with LSP-based schema tooling | `enhancement`, `devex`, `ai-generated` | Yes |
| 3.4 (#1460) | Vim/Neovim Plugin | Terminal-first schema editing with LSP integration and syntax support | `enhancement`, `devex`, `ai-generated` | Yes |

### Detailed Issue Descriptions

---

#### 3.1 (#1432) — VS Code Extension: Schema Editing & IntelliSense

The VS Code extension is the primary IDE integration for Objectified, providing schema editing capabilities comparable to TypeScript's language tooling. At its core is a Language Server Protocol (LSP) server written in TypeScript that understands Objectified schema files (`.objschema.json`) and provides real-time diagnostics, completions, and hover information.

The LSP server implements four key protocol features: (1) `textDocument/completion` provides IntelliSense for property types, constraint keywords, and schema references—suggesting valid types when the cursor is inside a `type` field, valid constraints when inside a property definition, and existing class names for `$ref` targets. (2) `textDocument/hover` shows documentation for the element under the cursor, including the property's constraints, description, and usage across the schema. (3) `textDocument/diagnostic` validates the schema in real-time, reporting errors for invalid types, constraint violations (e.g., `minLength > maxLength`), and dangling `$ref` pointers. (4) `textDocument/definition` navigates from a `$ref` to its target class definition.

```
┌────────────────────────────────────┐
│           VS Code Editor           │
│                                    │
│  {                                 │
│    "name": "User",                 │
│    "properties": {                 │
│      "email": {                    │
│        "type": "stri│"             │
│        ┌──────────────────┐        │
│        │ ▸ string          │        │
│        │   number          │        │
│        │   integer         │        │
│        │   boolean         │        │
│        │   array           │        │
│        │   object          │        │
│        └──────────────────┘        │
│      }                             │
│    }                               │
│  }                                 │
│                                    │
│  ⚠ Line 12: minLength (5) >       │
│    maxLength (3) — constraint      │
│    conflict                        │
└────────────────────────────────────┘
         │              ▲
         │  LSP JSON    │  diagnostics,
         │  RPC         │  completions,
         ▼              │  hover info
┌────────────────────────────────────┐
│      Objectified LSP Server        │
│  ┌──────────┐  ┌───────────────┐  │
│  │  Schema   │  │  Validation   │  │
│  │  Parser   │  │  Engine       │  │
│  └──────────┘  └───────────────┘  │
│  ┌──────────┐  ┌───────────────┐  │
│  │  $ref     │  │  Completion   │  │
│  │  Resolver │  │  Provider     │  │
│  └──────────┘  └───────────────┘  │
└────────────────────────────────────┘
```

The extension also ships with a snippet library providing templates for common schema patterns: class definition, property with constraints, enum property, nested object, and array of objects. Snippets are triggered via standard VS Code prefix completion (e.g., typing `obj-class` expands into a full class scaffold). The extension is distributed via the VS Code Marketplace and installable with a single click.

**Acceptance Criteria**
- IntelliSense provides type-aware completions for property types, constraints, and `$ref` targets
- Real-time diagnostics report schema errors (invalid types, constraint conflicts, dangling refs)
- Hover information shows property documentation including constraints and description
- Go-to-definition navigates from `$ref` to the referenced class
- Snippet library includes at least 6 templates for common schema patterns
- The LSP server starts within 2 seconds and provides completions within 100ms
- Extension is installable from the VS Code Marketplace with zero configuration
- Syntax highlighting differentiates schema keywords, types, constraints, and values

**Part of Epic: IDE Extensions**

---

#### 3.2 (#1442) — VS Code Extension: Preview Canvas & Cloud Sync

Schema editing in a text editor benefits from a visual feedback loop. This issue adds a preview canvas panel to the VS Code extension that renders the schema being edited as a visual class diagram in real-time, plus cloud synchronization that lets developers push and pull schemas between their local editor and the Objectified platform.

The preview canvas opens as a VS Code webview panel beside the editor. It renders the current schema file as a node-and-edge diagram: classes as cards showing their properties, and `$ref` relationships as connecting lines. The canvas updates on every keystroke (debounced to 200ms) so the developer sees the visual impact of their edits immediately. The canvas supports zoom, pan, and click-to-navigate (clicking a class in the canvas scrolls the editor to that class definition).

Cloud sync authenticates via an API token stored in VS Code's secret storage. Once authenticated, the extension adds a "Schemas" view to the VS Code sidebar that lists remote schemas from the tenant's Objectified instance. Developers can pull a remote schema to a local file, edit it, and push changes back. Push operations create a new draft version on the platform. Conflict detection warns when the remote schema has been modified since the last pull, requiring the developer to pull and merge before pushing.

The sync REST endpoints are standard Objectified APIs: `GET /api/v1/schemas` (list), `GET /api/v1/schema-captures/{id}` (pull), and `POST /api/v1/schemas/{id}/versions` (push draft). The extension wraps these with convenience commands in the VS Code command palette: "Objectified: Pull Schema," "Objectified: Push Schema," and "Objectified: Compare with Remote."

**Acceptance Criteria**
- Preview canvas renders the active schema file as a visual class diagram in real-time
- Canvas updates within 300ms of editor changes (debounced)
- Click-to-navigate scrolls the editor to the clicked class definition
- Cloud sync authenticates via API token stored in VS Code secret storage
- Pull downloads a remote schema to a local `.objschema.json` file
- Push creates a new draft version on the platform from the local file
- Conflict detection prevents pushing when the remote has diverged since last pull
- Sidebar "Schemas" view lists all remote schemas with version and status

**Part of Epic: IDE Extensions**

---

#### 3.3 (#1451) — JetBrains Plugin

JetBrains IDEs (IntelliJ IDEA, WebStorm, PyCharm) have significant market share among Java, Kotlin, and Python developers. This issue delivers a JetBrains plugin that provides the same schema editing capabilities as the VS Code extension, powered by the shared LSP server from issue 3.1.

The plugin uses JetBrains' built-in LSP client support (available since IntelliJ 2023.2) to connect to the Objectified LSP server bundled with the plugin. This shared-server architecture means all language features—completions, diagnostics, hover, go-to-definition—work identically across VS Code and JetBrains without maintaining separate implementations. The LSP server binary is packaged within the plugin and launched automatically when a `.objschema.json` file is opened.

File type registration associates `.objschema.json` with the Objectified file type, enabling syntax highlighting via a TextMate grammar (JetBrains supports TextMate bundles). The plugin adds a tool window for schema preview (similar to the VS Code canvas) rendered via JCEF (JetBrains Chromium Embedded Framework). Cloud sync uses the same API token approach as VS Code, stored via JetBrains' credential store API. The plugin is distributed through the JetBrains Marketplace.

Snippets are implemented as JetBrains Live Templates, providing the same schema scaffolding shortcuts available in the VS Code extension. A settings page under `Preferences > Tools > Objectified` configures the API endpoint URL, authentication token, and LSP server options.

**Acceptance Criteria**
- Plugin installs from JetBrains Marketplace and activates on `.objschema.json` files
- LSP-powered completions, diagnostics, hover, and go-to-definition work identically to VS Code
- Syntax highlighting differentiates schema keywords, types, and values
- Schema preview tool window renders a visual class diagram via JCEF
- Cloud sync supports pull, push, and conflict detection using the Objectified REST API
- Live Templates provide schema scaffolding snippets triggered by prefix
- Settings page configures API endpoint, authentication, and LSP options
- Plugin is compatible with IntelliJ IDEA, WebStorm, and PyCharm (2023.2+)

**Part of Epic: IDE Extensions**

---

#### 3.4 (#1460) — Vim/Neovim Plugin

Terminal-first developers using Vim or Neovim need schema tooling that works within their workflow. This issue delivers a Vim/Neovim plugin that provides LSP integration, syntax highlighting, and schema-aware editing without requiring a GUI.

For Neovim users (0.8+), the plugin provides an LSP client configuration that connects to the Objectified LSP server. This is distributed as a Lua plugin compatible with popular plugin managers (lazy.nvim, packer.nvim). The configuration registers the LSP server for `.objschema.json` files and integrates with nvim-cmp for completion, nvim-lspconfig for diagnostics, and telescope.nvim for schema search. All LSP features from 3.1 (completions, diagnostics, hover, go-to-definition) work through the native Neovim LSP client.

For classic Vim users, the plugin provides a syntax file for `.objschema.json` highlighting and integrates with vim-lsp or coc.nvim for language server features. The syntax file defines highlighting groups for schema keywords (`type`, `properties`, `required`, `$ref`), constraint keywords (`minLength`, `maxLength`, `pattern`, `enum`), and values.

Cloud sync is implemented as a set of Vim commands: `:ObjPull <schema-id>`, `:ObjPush`, and `:ObjDiff`. Authentication uses an environment variable (`OBJECTIFIED_API_TOKEN`) or a `.objectified.json` config file in the project root. The commands call the Objectified REST API via curl and display results in a scratch buffer.

**Acceptance Criteria**
- Neovim LSP client config connects to the Objectified LSP server for `.objschema.json` files
- Completions, diagnostics, hover, and go-to-definition work through nvim-cmp and nvim-lspconfig
- Syntax highlighting covers schema keywords, constraint keywords, types, and values
- Classic Vim support via vim-lsp or coc.nvim integration
- Cloud sync commands (`:ObjPull`, `:ObjPush`, `:ObjDiff`) use the Objectified REST API
- Authentication supports environment variable and project-level config file
- Plugin installs via lazy.nvim, packer.nvim, or vim-plug with documented setup steps

**Part of Epic: IDE Extensions**

---

## Epic 4: Advanced Git Workflows

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 4.1 (#1473) | Branch-Per-Version Strategy | Automatic Git branch creation and management aligned with schema versions | `enhancement`, `devex`, `mvp`, `rest`, `ai-generated` | Yes |
| 4.2 (#1480) | Pull Request Workflow & Schema Review | PR-based schema change review with inline comments on schema fields | `enhancement`, `devex`, `mvp`, `rest`, `ai-generated` | Yes |
| 4.3 (#1485) | Git Blame & Property History | Track authorship and change history at the individual property level | `enhancement`, `devex`, `rest`, `ai-generated` | Yes |
| 4.4 (#1493) | Schema Diff in PRs & Merge Conflict Resolution | Render structured schema diffs in PR views and resolve merge conflicts intelligently | `enhancement`, `devex`, `rest`, `ai-generated` | No |

### Detailed Issue Descriptions

---

#### 4.1 (#1473) — Branch-Per-Version Strategy

Schema versioning benefits from the same branch isolation that code repositories use. This issue implements an automatic branch creation strategy where each schema version maps to a dedicated Git branch, enabling parallel version development, hotfixes on older versions, and a clear lineage between schema evolution and code changes.

When a new schema version is published via the Objectified platform, the system automatically creates a Git branch named `schema/{schemaSlug}/v{major}.{minor}.{patch}` in the connected repository. The branch contains the schema definition files at that version, any generated artifacts (documentation, client stubs), and a `CHANGELOG.md` specific to that version. The main branch always reflects the latest published version.

```
main ─────●────●────●────●────●──────▶
           \        \        \
            \        \        └── schema/user/v3.0.0
             \        └── schema/user/v2.1.0
              └── schema/user/v1.0.0

  ● = schema version publish event
```

The branch strategy is configured per schema via `PUT /api/v1/schemas/{schemaId}/git/branch-strategy` with options for branch naming template, auto-create toggle, and protection rules (prevent force-push on version branches). The configuration page at `/app/schemas/[id]/git/settings` uses Radix `RadioGroup` for strategy selection (branch-per-version, branch-per-major, tag-only), `Switch` for auto-create toggle, and `TextField` for custom branch naming templates. The REST API also exposes `GET /api/v1/schemas/{schemaId}/git/branches` to list all version branches with their status and latest commit.

Hotfix branches follow a `schema/{schemaSlug}/v{major}.{minor}.{patch}-hotfix` naming convention and can be created from any version branch via `POST /api/v1/schemas/{schemaId}/git/branches/{versionBranch}/hotfix`.

**Acceptance Criteria**
- Schema version publishes automatically create a Git branch with the version schema files
- Branch naming follows a configurable template defaulting to `schema/{slug}/v{version}`
- Branch strategy is selectable: branch-per-version, branch-per-major-version, or tag-only
- Hotfix branches can be created from any version branch via REST API
- Version branches are protected from force-push and deletion by default
- The Git settings page at `/app/schemas/[id]/git/settings` manages strategy with Radix controls
- Branch list endpoint returns all version branches with status and latest commit SHA

**Part of Epic: Advanced Git Workflows**

---

#### 4.2 (#1480) — Pull Request Workflow & Schema Review

Schema changes deserve the same review rigor as code changes. This issue builds a pull request workflow where schema modifications go through a proposal → review → approval → merge cycle, with inline comments targeting specific schema fields rather than arbitrary source lines.

When a developer proposes a schema change (via the platform UI or by pushing to a feature branch), the system creates a schema pull request. The PR view at `/app/schemas/[id]/pulls/[prId]` renders the schema diff (reusing the visual diff from 2.4) with an inline comment system. Reviewers click on any field in the diff to leave a comment—comments are anchored to the schema path (e.g., `User.address.zipCode`) rather than a file line number, so they remain valid even if the schema is restructured.

The review workflow supports three actions: approve, request changes, and comment-only. A configurable approval policy (e.g., "requires 2 approvals from schema-owners group") gates merging. When approved and merged, the schema change is applied as a new draft version, and the branch strategy from 4.1 handles branch creation.

```
┌────────────────────────────────────────────────────────────┐
│  Schema PR #42: Add locale field to User                   │
│  Status: In Review · 1/2 approvals · 3 comments           │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ▼ User (modified)                                         │
│    ├─ id: string                                           │
│    ├─ name: string                                         │
│  ++├─ locale: string  ◀── 💬 2 comments                   │
│  ++│    pattern: ^[a-z]{2}-[A-Z]{2}$                       │
│  ++│    default: "en-US"                                   │
│    ├─ email: string                                        │
│    └─ address: object                                      │
│                                                            │
│  [Approve]  [Request Changes]  [Comment]                   │
└────────────────────────────────────────────────────────────┘
```

REST endpoints include `POST /api/v1/schemas/{schemaId}/pulls` (create PR), `GET /api/v1/schemas/{schemaId}/pulls` (list), `POST /api/v1/schemas/{schemaId}/pulls/{prId}/reviews` (submit review), `POST /api/v1/schemas/{schemaId}/pulls/{prId}/comments` (inline comment), and `POST /api/v1/schemas/{schemaId}/pulls/{prId}/merge` (merge). The PR page uses Radix `Tabs` for switching between "Changes," "Comments," and "Checks" views, and `Dialog` for the review submission form.

**Acceptance Criteria**
- Schema pull requests show a visual diff with inline comment capability on any schema field
- Comments are anchored to schema paths, not line numbers, and survive restructuring
- Review actions include approve, request changes, and comment-only
- Configurable approval policy gates merging (e.g., N approvals from owners group)
- Merging a PR creates a new draft schema version
- PR list view at `/app/schemas/[id]/pulls` shows open, merged, and closed PRs with Radix `Table`
- Breaking changes detected in the PR diff are flagged with severity badges
- Email notifications are sent for new PRs, comments, and approval status changes

**Part of Epic: Advanced Git Workflows**

---

#### 4.3 (#1485) — Git Blame & Property History

When investigating why a schema property exists or understanding the rationale behind a constraint, developers need property-level authorship tracking—the schema equivalent of `git blame`. This issue implements a blame view that shows who added or last modified each property, when, and as part of which version change.

The blame data is derived from the schema version history. For each property in the current schema, the system traces backward through version snapshots to find the version where the property was introduced and the most recent version where it was modified. This computation is performed on-demand and cached in a `property_blame` materialized view that maps `(schema_id, class_name, property_path)` to `(introduced_in_version, introduced_by_user, introduced_at, last_modified_version, last_modified_by_user, last_modified_at)`.

The blame view at `/app/schemas/[id]/blame` renders the schema as a tree with blame annotations beside each property. Annotations show the author avatar, version tag, and relative timestamp (e.g., "jdoe · v2.1.0 · 3 months ago"). Clicking an annotation opens a Radix `Popover` with the full change context: version changelog entry, commit message, and a link to the PR that introduced the change.

Per-property version history is available by clicking a property and selecting "View History" from a Radix `ContextMenu`. The history panel shows a chronological list of changes to that specific property across all schema versions, with before/after values for each change. REST endpoints include `GET /api/v1/schemas/{schemaId}/blame` (full blame for current version) and `GET /api/v1/schemas/{schemaId}/classes/{className}/properties/{propPath}/history` (property-level history).

**Acceptance Criteria**
- Blame view shows author, version, and timestamp for each property's introduction and last modification
- Blame data is derived from schema version history and cached for performance
- Clicking a blame annotation shows full change context in a Radix `Popover`
- Per-property history shows all changes to a specific property across versions
- History entries include before/after values and links to the originating PR or version publish
- Blame cache refreshes automatically when a new schema version is published
- Blame view handles schemas with 500+ properties without visible latency

**Part of Epic: Advanced Git Workflows**

---

#### 4.4 (#1493) — Schema Diff in PRs & Merge Conflict Resolution

Standard Git diffs treat schema files as flat text, producing confusing output when properties are reordered or nested objects are restructured. This issue builds a schema-aware diff renderer for pull request views and an intelligent merge conflict resolver that understands schema structure.

The schema diff renderer replaces the raw text diff in PR views with a structured diff (reusing the diff engine from 2.1 and 2.4). When a PR modifies a schema file, the diff is computed by comparing the parsed schema objects rather than raw text lines. This eliminates false diffs from whitespace changes, property reordering, and formatting differences. The rendered diff groups changes by schema class and highlights semantic changes (type changes, constraint modifications, new required fields) rather than textual edits.

Merge conflict resolution uses a three-way merge algorithm specialized for JSON Schema structures. When two branches modify the same schema, the resolver compares the base version against both branch tips. Non-overlapping changes are auto-merged (e.g., branch A adds a property to class User, branch B adds a different property to class Order). Overlapping changes (both branches modify the same property's constraints) surface a conflict with a three-panel resolution UI.

```
┌────────────────────────────────────────────────────────────┐
│  Merge Conflict: User.email                                │
├──────────────┬───────────────┬─────────────────────────────┤
│    Base       │    Branch A    │    Branch B                 │
│              │               │                             │
│  type: string│  type: string │  type: string               │
│  maxLen: 255 │  maxLen: 320  │  maxLen: 255                │
│  format: –   │  format: email│  format: –                  │
│  pattern: –  │  pattern: –   │  pattern: ^[^@]+@[^@]+$     │
│              │               │                             │
├──────────────┴───────────────┴─────────────────────────────┤
│  Resolved:                                                  │
│  type: string  maxLen: 320  format: email                  │
│  pattern: ^[^@]+@[^@]+$                                    │
│                                                            │
│  [Accept Resolved]  [Edit Manually]  [Abort Merge]         │
└────────────────────────────────────────────────────────────┘
```

The conflict resolution page at `/app/schemas/[id]/pulls/[prId]/conflicts` uses Radix `Tabs` for switching between conflicting files, `RadioGroup` for selecting a resolution strategy per field (accept A, accept B, accept both, custom), and `Dialog` for the manual edit fallback. REST endpoints include `GET /api/v1/schemas/{schemaId}/pulls/{prId}/conflicts` (list conflicts) and `POST /api/v1/schemas/{schemaId}/pulls/{prId}/conflicts/resolve` (submit resolutions).

**Acceptance Criteria**
- Schema diffs in PRs are computed from parsed objects, ignoring whitespace and property ordering
- Diff output groups changes by schema class with semantic change highlighting
- Three-way merge auto-resolves non-overlapping changes without manual intervention
- Overlapping changes surface a conflict with a three-panel resolution UI
- Resolution strategies include accept-A, accept-B, accept-both, and custom edit
- Resolved conflicts are validated against the schema rules before merge completion
- Conflict resolution page uses Radix `Tabs`, `RadioGroup`, and `Dialog` components

**Part of Epic: Advanced Git Workflows**

---

## Parallel Work Guide

**Epic 1 — Auto-Generated Documentation:**
Issues 1.1 (ReDoc), 1.2 (Slate), and 1.3 (Custom Static Site) can be developed in parallel since they are independent documentation renderers consuming the same schema capture API. Issue 1.4 (Custom Pages & Branding) depends on at least one renderer being available to apply branding and merge custom pages into the navigation tree.

**Epic 2 — Schema Changelog & Migration:**
Issues 2.1 (Changelog Engine) and 2.4 (Visual Diff) can start in parallel—the changelog engine produces the data model and the diff view provides the visual layer, sharing the structural diff engine as a common dependency. Issue 2.2 (Breaking Change Detection) depends on 2.1 for the raw changelog data to classify. Issue 2.3 (Migration Guide) depends on 2.2 for the classified breaking change list.

**Epic 3 — IDE Extensions:**
Issues 3.1 (VS Code), 3.3 (JetBrains), and 3.4 (Vim/Neovim) can be developed in parallel once the shared LSP server is built as part of 3.1. The LSP server is the first deliverable within 3.1; client integrations can proceed concurrently. Issue 3.2 (Preview Canvas & Cloud Sync) depends on 3.1's extension scaffold being in place.

**Epic 4 — Advanced Git Workflows:**
Issues 4.1 (Branch-Per-Version), 4.2 (PR Workflow), and 4.3 (Git Blame) can be developed in parallel since they address independent Git features. Issue 4.4 (Diff & Merge Conflict Resolution) depends on 4.2 for the PR view infrastructure and on the diff engine from Epic 2.

**Cross-Epic Parallelism:**
Epic 1 (Documentation) and Epic 3 (IDE Extensions) are fully independent and can be built by separate teams. Epic 2 (Changelog) provides the diff engine used by Epic 4 (Git Workflows), so 2.1 should be completed early. Epic 4's PR workflow (4.2) benefits from the visual diff view (2.4) but can initially render text-based diffs while 2.4 is in progress. Within these constraints, UI work across all four epics can proceed in parallel.
