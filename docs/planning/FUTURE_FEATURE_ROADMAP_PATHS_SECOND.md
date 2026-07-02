# Apiome: Paths Designer - Feature Roadmap

> A visual canvas for designing, testing, and exporting OpenAPI 3.1 path definitions. The Paths Designer provides a React Flow-based canvas where engineers drag HTTP operation nodes, bind parameters and request bodies, link response schemas to classes, and export production-ready OpenAPI specs — without leaving Apiome.
>
> **Revenue Model**: Core paths designer is included in all tiers; enterprise features (real-time collaboration, audit trail, mock server, multi-spec coordination, advanced export) are Pro/Enterprise-gated; code generation and API gateway integration are Enterprise-only.
>
> **Tech Stack**: NextJS App Router, React Flow, Monaco Editor, Radix UI, PostgreSQL, OpenAPI 3.1, Playwright (E2E), TypeScript

---

## MVP Definition

- Operation Focus Mode: click an operation to isolate it; all unrelated nodes dim to 20% opacity with 200ms CSS transition
- Editor Overlay: floating panel (60–70% canvas width) with tabbed content replacing the right-side properties panels
- Canvas toolbar: Add Path, Auto-Layout, Fit View, Compact/Expanded toggle, Export dropdown, Validate button
- Real-time OpenAPI validation: unique operationId check, path variable syntax, status code validity, schema reference integrity
- OpenAPI 3.1 export: JSON and YAML formats, inline or $ref bundling, validation gate before export
- Code-level editors: JSON Schema editor with syntax highlighting and autocomplete; Markdown description editor with live preview
- Keyboard-first navigation: full shortcut set (Cmd+K command palette, G/P/U/A/X for HTTP methods, Cmd+Z/Shift+Z undo/redo)
- Undo/redo history stack (50-operation depth) covering all canvas mutations
- REST API for all path operations (OpenAPI 3.1 documented)

---

## Epic 1 (#2240): Canvas Editor & Node Design

### Summary Table

| #    | Title                          | Description                                                                                          | Labels                                           | MVP | Parallel |
|------|--------------------------------|------------------------------------------------------------------------------------------------------|--------------------------------------------------|-----|----------|
| 1.1 (#2241) | Operation Focus Mode           | Click-to-isolate: focused operation at full opacity, all other nodes/edges dim to 20%                | `enhancement`, `mvp`, `paths`                    | Yes | No       |
| 1.2 (#2242) | Editor Overlay (Replace Sidebar) | Floating panel with tabbed content for operation editing; reclaims canvas real estate              | `enhancement`, `mvp`, `paths`                    | Yes | Yes      |
| 1.3 (#2243) | Professional Node Visual Redesign | Accent-bar node design: compact method badges, inline parameter/response chips, unified shell     | `enhancement`, `paths`                           | No  | Yes      |
| 1.4 (#2244) | Canvas Toolbar for Paths       | Horizontal toolbar: Add Path, Auto-Layout, Fit View, view-mode toggles, Export, Validate, Settings  | `enhancement`, `mvp`, `paths`                    | Yes | Yes      |
| 1.5 (#2245) | Paths Canvas Layout Improvements | Vertical swimlane, horizontal flow, grouped-by-path, grouped-by-tag, and RESTful resource layouts  | `enhancement`, `paths`                           | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#2241) — Operation Focus Mode

When an HTTP operation node is selected, all nodes not associated with that operation fade to 20% opacity over a 200ms CSS transition. Only the selected operation and its directly connected nodes (parameters, request body, responses, response bodies, and referenced classes at any traversal depth) remain at full opacity. This dramatically improves readability for APIs with many endpoints.

Multi-operation focus: holding `Shift` and clicking additional operations adds them to the focus set (additive). Exiting focus mode restores all nodes to full opacity and is triggered by pressing `Esc` or clicking empty canvas space. A banner pill at the top of the canvas reads "Focus: GET /users/{id}" with an X button.

```
Before focus:
  [GET /users] [POST /users] [GET /users/{id}] [DELETE /users/{id}] (all fully visible)

After clicking GET /users/{id}:
  [GET /users]░░  [POST /users]░░  [GET /users/{id}]  [DELETE /users/{id}]░░
                                      ↑ focused           ↓ dimmed
                               [Parameters: id]    [Response: 200 User]
                                (full opacity)      (full opacity)
```

**Acceptance Criteria:**
- Single-click an operation node to enter focus mode; connected nodes are identified by edge traversal at any depth
- Non-focused nodes: `opacity: 0.2`, `pointer-events: none`, `grayscale(50%)`
- Focused edges: full opacity with `filter: drop-shadow(0 0 3px <methodColor>)`
- Non-focused edges: `opacity: 0.15`, `stroke-dasharray: 4 4`
- All transitions use `transition: opacity 200ms ease-in-out`
- `Shift+click` additional operations to include them in the focus set
- `Esc` or empty canvas click exits focus mode; `Tab`/`Shift+Tab` cycles through focused nodes
- Focus mode indicator banner visible at canvas top; `X` button exits focus
- Crossing-free routing: focused edges are re-routed in isolation to guarantee zero crossings in focus mode

**Tech Stack:** React Flow node/edge opacity via node data; CSS transitions; edge traversal using `getConnectedEdges`

Part of Epic: Canvas Editor & Node Design

---

#### 1.2 (#2242) — Editor Overlay (Replace Sidebar Properties Panels)

The current three-panel layout (left library, canvas, right properties panel) confines the canvas to a narrow strip. Replacing right-side properties panels with a floating overlay reclaims the canvas area and follows UX patterns familiar from Figma, Postman, and VS Code.

Double-clicking a node (or pressing `Enter` on a selected node) opens the editor overlay centered over the canvas. The overlay covers approximately 60–70% of canvas width and 70–80% of canvas height, with a draggable title bar, a semi-transparent backdrop (clicking it saves and closes), a resize handle in the bottom-right corner, and auto-save on close (debounced 300ms). A single-click on a node shows a compact floating toolbar with the most-used quick actions; double-click opens the full overlay.

For operations, the overlay is tabbed: **General** (summary, description with live Markdown preview, operationId, tags, deprecated), **Parameters** (table with add/edit/remove, schema selectors), **Request Body** (content types, schema builder, examples), **Responses** (status code list, content types, schema builders, headers), **Security** (scheme selector with OAuth2 scopes), **Extensions** (custom `x-*` key-value editor), **Preview** (Monaco read-only tab showing generated OpenAPI YAML, updating in real-time).

The three existing properties panels (`OperationPropertiesPanel`, `ParameterPropertiesPanel`, `ResponsePropertiesPanel`) are removed; the canvas expands to fill the freed space.

**Acceptance Criteria:**
- Double-click or `Enter` on selected node opens the editor overlay; `Esc` or backdrop click closes and saves
- Overlay title bar is draggable to reposition; resize handle in bottom-right corner
- All changes are auto-saved with 300ms debounce; closing overlay never discards unsaved work
- Single-click quick-edit toolbar shows 3–5 most-used actions (change status code, toggle required, change type)
- Tabbed content renders the correct editor for the node type (operation vs. parameter vs. response)
- Monaco Preview tab shows the OpenAPI YAML fragment for the current node, updating as the user types
- Breadcrumb navigation in overlay header when editing nested elements
- Right-side properties panels are removed from the layout; canvas width increases to fill the space

**Tech Stack:** Radix UI Dialog (overlay); Monaco Editor (preview tab); React state with auto-save debounce

Part of Epic: Canvas Editor & Node Design

---

#### 1.3 (#2243) — Professional Node Visual Redesign

The current nodes use full-width colored headers with inconsistent sizing and mixed design patterns. An enterprise-grade designer tool needs a unified visual system with consistent width (280px), clear type differentiation via a 4px left accent bar rather than large color floods, and a reduced visual noise approach inspired by Stoplight Studio and Insomnia.

**Unified node shell:** `PathsBaseNode` wrapper provides `rounded-xl`, `border` (1px default, `border-2` selected), `shadow-md` (default) → `shadow-lg` (hover) → `shadow-xl` (selected), and `bg-white dark:bg-zinc-900`. All node types share this shell. Node type is identified by a 16px Lucide icon in the top-right corner of the header (Operation: HTTP method pill; Parameter: `Settings2`; Response: `Reply`; Request Body: `ArrowUpFromLine`; Class: `Box`).

**Operation node:** 4px left accent bar in the HTTP method color extending the full node height. Header background is `bg-zinc-50 dark:bg-zinc-800` with the method name as a compact pill badge. Path in `font-mono text-sm`. Below: operationId in `text-xs text-zinc-500 font-mono`, summary truncated to one line. Micro-badge row: parameter count, response count, security icon (🔒/🔓), deprecated badge. Tags as tiny colored chips at the bottom.

**Parameter node:** Compact chip (fixed 36px height): `[location-dot] name : type [required-star]`. Location dot is an 8px circle (green=path, blue=query, purple=header, orange=cookie). 3px left border in the location color.

**Response node:** Status code pill (`rounded-full text-xs font-bold`) with description text. 3px left border in status color. Schema preview tooltip on hover.

**Dark mode:** Node background `dark:bg-zinc-900`, border `dark:border-zinc-700`, lightened accent bar colors for readability against dark canvas backgrounds.

**Acceptance Criteria:**
- All nodes use the `PathsBaseNode` wrapper with consistent shadow scale and border radius
- All nodes standardized to 280px width (±20px for content overflow)
- Operation node: 4px left accent bar, compact method pill badge, micro-badge row visible
- Parameter node: 36px chip height with location-color dot and 3px left border
- Response node: status code pill with status-color left border; schema preview in hover tooltip
- Request/response body nodes: 4px left bar (indigo for request, emerald for response); content type tab pills in header
- Class nodes: indigo left bar; first 3–4 property names shown in `font-mono text-[11px]`
- Handles: circular (`w-3 h-3 rounded-full`), hidden by default, fade in on node hover/select
- Dark mode: all nodes use `zinc-900` background with lightened accent bar colors

**Tech Stack:** `PathsBaseNode` React component; Tailwind CSS; Lucide icons; React Flow custom node components

Part of Epic: Canvas Editor & Node Design

---

#### 1.4 (#2244) — Canvas Toolbar for Paths

The Paths Designer currently has no dedicated toolbar. A 40px-tall horizontal toolbar spanning the canvas width provides quick access to the most common actions, consistent with professional API design tools. Flat icons with tooltips (no text labels by default); tooltip reveals label on hover.

**Left section (actions):** Add Path button (+), Add Operation dropdown (HTTP method selector), Auto-Layout button (dropdown for direction: TB/LR/BT/RL), Fit View button. **Center section (view controls):** View Mode toggle (Full Canvas / Focused), Compact/Expanded toggle, Show/Hide Classes toggle. **Right section (tools):** Search (🔍, `Cmd+F`), Validate (✓, runs spec validation and shows results panel), Export dropdown (OpenAPI JSON/YAML, PNG, SVG, PDF), Settings (⚙️), Help (?) showing keyboard shortcut overlay.

Active toggles show a colored underline matching the theme accent. Dark mode: dark background with light icons and subtle hover states.

**Acceptance Criteria:**
- Toolbar renders as a fixed 40px horizontal bar between the left sidebar and canvas, spanning full canvas width
- Add Path opens a dialog for path pattern input with path variable detection
- Add Operation dropdown lists all HTTP methods; adds operation to selected path node
- Auto-Layout applies the selected direction with live animation (400ms ease-in-out) to new node positions
- View Mode toggle immediately enters/exits Operation Focus Mode
- Compact/Expanded toggle switches between inline parameter/response display and separate external nodes
- Export dialog includes: format (JSON/YAML), bundling (inline/$ref), include/exclude options, server URLs, live preview, validation gate, download/copy buttons
- Validate runs OpenAPI 3.1 validation and opens a results panel listing errors/warnings with click-to-navigate

**Tech Stack:** React toolbar component; Radix UI DropdownMenu/Tooltip; NextJS App Router

Part of Epic: Canvas Editor & Node Design

---

#### 1.5 (#2245) — Paths Canvas Layout Improvements

The current horizontal row layout (operations at y=200, parameters at y=350, responses at y=500) works for small APIs but becomes unwieldy at 10+ endpoints. Multiple layout algorithms give developers the right view for their context.

**Layout algorithms:** Vertical Swimlane (each path is a vertical column; operation → parameters → request body → responses within the column, separated by subtle vertical dividers), Horizontal Flow (left-to-right: Operation → Parameters → Request Body → Responses), Grouped-by-Path (all operations for the same path in a visual container with the path name as header), Grouped-by-Tag (color-coded containers by OpenAPI tag), RESTful Resource (GET + POST + PUT + DELETE for the same resource grouped in a single resource block). Layout selection via toolbar dropdown with live preview.

**Path grouping containers:** Auto-generated rounded-rectangle containers per unique path prefix. Header shows path in `font-mono text-xs`. Background is a very subtle tinted overlay per path group. Color auto-assigned from an 8-color palette based on first path segment hash. Collapse/expand toggle per container.

**Spacing:** Minimum 40px horizontal and 30px vertical gaps enforced by layout algorithm. Post-layout edge crossing minimization pass. Smart alignment guides on manual drag.

**Acceptance Criteria:**
- Toolbar layout dropdown lists all 5 algorithms; switching applies layout with 400ms animation
- Vertical Swimlane: each unique path gets a dedicated column; operations are vertically stacked within the column
- Grouped-by-Path: containers with collapsible headers; container color derived from path segment hash
- Grouped-by-Tag: containers use the tag color from the OpenAPI tags object if defined
- Auto-Group by Path creates containers automatically when layout is applied; containers persist collapse state across sessions
- Edge crossing minimization runs after auto-layout (Barycenter heuristic, ≤5 iterations, debounced 200ms)
- Alignment guides appear as blue horizontal/vertical lines when dragging nodes within 8px of alignment positions

**Tech Stack:** React Flow layout utilities; custom layout algorithms; edge crossing minimization heuristic

Part of Epic: Canvas Editor & Node Design

---

## Epic 2 (#2246): Engineer DX (Code Generation, Stubs & Testing)

### Summary Table

| #    | Title                          | Description                                                                                             | Labels                                              | MVP | Parallel |
|------|--------------------------------|---------------------------------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 2.1 (#2247) | Code-Level Editors             | JSON Schema editor, Example Value editor, Markdown description editor — each with IDE-quality features  | `enhancement`, `mvp`, `paths`                       | Yes | No       |
| 2.2 (#2248) | Real-Time Validation           | Continuous OpenAPI 3.1 validation: unique operationId, path variables, $ref integrity, status codes     | `enhancement`, `mvp`, `paths`                       | Yes | Yes      |
| 2.3 (#2249) | OpenAPI Export & Import        | Export to OpenAPI 3.1/3.0/Swagger 2.0/Postman/Insomnia; selective import with merge support            | `enhancement`, `mvp`, `paths`, `rest`               | Yes | Yes      |
| 2.4 (#2250) | Automatic Endpoint Generation  | Right-click class → Generate CRUD Endpoints; schema-to-path inference with standard error responses     | `enhancement`, `paths`                              | No  | Yes      |
| 2.5 (#2251) | Pattern Libraries              | Pagination, filtering, sorting, RFC 7807 error, and auth pattern templates for quick endpoint creation  | `enhancement`, `paths`                              | No  | Yes      |
| 2.6 (#2252) | Client SDK Generation          | Type-safe client libraries from path definitions: TypeScript, Python, Java, C#, Go, Rust               | `enhancement`, `paths`                              | No  | Yes      |
| 2.7 (#2253) | Server Stub Generation         | Backend API stubs with routing and validation: Express, FastAPI, Spring Boot, Gin, Actix-web            | `enhancement`, `paths`                              | No  | Yes      |
| 2.8 (#2254) | Interactive Documentation      | ReDoc/Swagger UI documentation with Try It Out; embedded preview panel; standalone preview URL          | `enhancement`, `paths`                              | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#2247) — Code-Level Editors

Engineers need precision and control when defining schema structures, example values, and descriptions. Three specialized editors are embedded in the editor overlay (Epic 1.2) tabs.

**JSON Schema Editor:** Monaco Editor instance configured for JSON with OpenAPI 3.1 JSON Schema awareness: syntax highlighting with light/dark theme support, bracket matching and auto-closing, real-time validation with inline error messages in the Monaco gutter, autocomplete for OpenAPI keywords (`required`, `additionalProperties`, `$ref`, `oneOf`, etc.) and property names from existing classes, quick reference sidebar for OpenAPI 3.1 spec.

**Example Value Editor:** Format toggle (JSON / YAML / XML / form-data); syntax validation per content type; auto-format with `Shift+Alt+F`; copy example as cURL command; import from file or paste from clipboard.

**Markdown Description Editor:** Split-view (editor left, live preview right); CommonMark + GitHub Flavored Markdown; code block syntax highlighting; link to schema definitions (`@ClassName` auto-links to the class in the schema canvas); image upload to S3-compatible storage.

**Acceptance Criteria:**
- JSON Schema editor uses Monaco with custom language configuration for JSON Schema keywords; autocomplete suggests existing class names from the project as `$ref` targets
- Inline validation errors appear as Monaco gutter markers; hovering shows error detail
- Example editor switches format modes without data loss (converts between JSON/YAML); validates against the defined schema on blur
- Markdown editor live preview renders CommonMark in a scrollable right pane; synchronized scroll position
- All editors respect dark/light theme; no theme switching flicker
- Image upload returns a CDN URL inserted at the cursor position; max file size 5MB, accepted types: jpg/png/gif/webp

**Tech Stack:** Monaco Editor with JSON/Markdown language configuration; `marked` (Markdown render); S3 upload

Part of Epic: Engineer DX

---

#### 2.2 (#2248) — Real-Time Validation

Catch errors as you design, not during export. Validation runs continuously in a Web Worker (to avoid blocking the main thread) and updates node visual states within 500ms of each change.

**Validation rules (errors):** Unique operation IDs across all paths; valid path variable syntax (`{var}` not `<var>` or `:var`); all path variables have matching parameter definitions; required request body has at least one content type; status codes are valid HTTP codes (100–599); `$ref` schema references point to existing classes; no circular dependencies in schema composition; security schemes referenced in operations exist in the global security definitions.

**Validation rules (warnings):** Operations missing descriptions; operations without tags; deprecated operations without migration documentation.

**Visual indicators:** Red border on error nodes; yellow border on warning nodes; error/warning badge with count in top-right corner of node; hover for detailed message; click badge to open the Validation Panel (see Epic 4.4).

**Acceptance Criteria:**
- Validation runs in a Web Worker; main thread is not blocked during validation
- All 8 error rules and 3 warning rules implemented and tested with unit tests
- Node border colors update within 500ms of the triggering change
- Click-to-navigate: clicking a validation issue in the panel pans the canvas to and selects the affected node
- Auto-fix suggestions offered for: missing operationId (generate from method + path), missing description (open overlay description tab)
- Validation state is persisted to prevent re-running on unchanged nodes

**Tech Stack:** Web Worker; custom rule engine; React Flow node data update for visual state

Part of Epic: Engineer DX

---

#### 2.3 (#2249) — OpenAPI Export & Import

**Export formats:** OpenAPI 3.1 JSON (prettified or minified), OpenAPI 3.1 YAML, Swagger 2.0 (legacy), Postman Collection v2.1, Insomnia Collection. **Export options:** include/exclude examples, include/exclude descriptions, bundle schemas inline or use `$ref` links, add custom `x-*` extensions, dereference all `$ref` to embedded schemas, add server URLs for multiple environments.

**Export dialog:** Live preview of the generated spec in Monaco Editor within the dialog. Validation gate: runs full validation before export; blocks export on errors (override option for advanced users). Download as file or copy to clipboard buttons.

**Import:** Selective import dialog allowing the user to choose which paths/operations to import. Merge import mode integrates with existing paths on the canvas, detecting and flagging conflicts. Supported import sources: OpenAPI JSON/YAML file (upload), Postman Collection v2.1, Insomnia Workspace, HAR file (reverse-engineer from browser DevTools recordings), URL (fetch from a remote OpenAPI spec endpoint).

```
OpenAPI Export paths:
POST /projects/{id}/versions/{v}/paths/export
  body: { format, options }
  → { content: "...", filename: "api.yaml" }

POST /projects/{id}/versions/{v}/paths/import
  body: { source_type, content, options: { selective: true, merge: true } }
  → { imported_count, conflict_count, conflicts: [...] }
```

**Acceptance Criteria:**
- Export dialog shows real-time Monaco preview of the generated spec as options change
- Validation gate blocks export when errors exist; "Export Anyway" override requires confirmation
- Postman Collection v2.1 export maps operations to Postman requests with pre-populated example values
- HAR import reverse-engineers a minimum of paths, HTTP methods, and response status codes from recorded traffic
- Selective import presents a checkbox list of operations; unchecked operations are ignored
- Merge import detects conflicts (same path + method already exists) and shows a diff before applying

**Tech Stack:** OpenAPI generator (custom or openapi-generator-cli); HAR parser; import conflict detection

Part of Epic: Engineer DX

---

#### 2.4 (#2250) — Automatic Endpoint Generation

Right-clicking a class on the canvas opens a context menu item "Generate CRUD Endpoints" that creates GET (list), GET (detail), POST (create), PUT (update), and DELETE (delete) operations pre-populated from the class schema.

**Path pattern:** Configurable: `/resources` (list/create), `/resources/{id}` (detail/update/delete), `/resources/{id}/subresources` (nested). **Request body binding:** POST/PUT operations bind the class as the JSON request body schema. **Response schema inference:** list endpoints wrap the class in an array response envelope; detail endpoints use a single class instance. **Standard error responses:** 400, 401, 403, 404, 500 are generated with RFC 7807 Problem Details schema. **OperationId generation:** follows RESTful conventions (`listUsers`, `getUser`, `createUser`, `updateUser`, `deleteUser`).

Advanced: nested resource generation (`/users/{userId}/posts`), bulk operation generation (`POST /resources/bulk`, `DELETE /resources/bulk`), search endpoint with query parameter inference from schema filterable fields, action endpoint generation (`POST /resources/{id}/actions/activate`), soft delete vs hard delete pattern selection.

**Acceptance Criteria:**
- Right-click a class node → "Generate CRUD Endpoints" → configuration dialog opens
- Configuration dialog: path pattern (configurable prefix), operations to include (checkboxes), error response format (RFC 7807 or custom)
- Generated operations appear on the canvas in the configured layout, connected to the source class node
- OperationIds follow RESTful naming conventions and are unique within the project version
- Generated error responses use a shared Problem Details schema component to avoid duplication
- All generated operations pass the real-time validation rules from 2.2 immediately after creation

**Tech Stack:** Class schema introspection; template-based operation generation; React Flow batch node creation

Part of Epic: Engineer DX

---

#### 2.5 (#2251) — Pattern Libraries

Pattern libraries provide pre-built operation templates for the most common API design patterns, reducing the boilerplate work of adding parameters and responses from scratch.

**Built-in patterns:** Pagination (page/limit, cursor-based, or offset-based with standardized response envelope showing `data[]`, `pagination.cursor`, `pagination.total`), Filtering (generate query parameters from schema fields with `filter[field]` naming), Sorting (`sort`, `order` query parameters with field enum validation from schema), Error Response (RFC 7807 Problem Details format with `type`, `title`, `status`, `detail`, `instance`), Authentication (Bearer token, API key header/query, OAuth2 scope requirement).

**Pattern application:** Patterns are applied to a selected operation from the command palette (`Cmd+K` → "Apply Pattern") or from the context menu. Applying a pattern adds the corresponding parameters, request body sections, or response objects to the selected operation, which can then be customized.

**Advanced:** Custom pattern creation and sharing within the organization; industry-specific patterns (FHIR pagination, Open Banking consent headers); pattern versioning for organizational standards tracking.

**Acceptance Criteria:**
- Pattern library is accessible from the command palette and context menu
- Pagination pattern: user selects cursor-based or page-based; generates corresponding query params and response schema
- Filter pattern: reads schema properties and generates `filter[field]` query parameters for all filterable fields
- RFC 7807 error pattern creates a shared `Problem` schema component and applies it to selected status codes
- Custom patterns can be saved by name; saved patterns are available organization-wide via the pattern library browser
- Applying a pattern is undoable (single undo entry, not one per generated node)

**Tech Stack:** Pattern template engine; OpenAPI component deduplication; Radix UI pattern browser dialog

Part of Epic: Engineer DX

---

#### 2.6 (#2252) — Client SDK Generation

Generate type-safe client libraries from the current path definitions. Supported languages: TypeScript/JavaScript (fetch or axios), Python (httpx or requests), Java (OkHttp or RestTemplate), C# (HttpClient), Go (net/http with generated structs), Rust (reqwest with serde). SDK features: type-safe request/response models, automatic serialization/deserialization, error handling with typed exceptions, retry logic with exponential backoff, authentication handling (API key, OAuth2), request/response interceptors, TypeScript IntelliSense support.

Generation is triggered from the Export dropdown in the toolbar. An async job generates the SDK ZIP file; a download link is provided on completion. Generated code is production-ready but intended as a starting point — comments indicate where to add environment-specific configuration.

**Acceptance Criteria:**
- SDK generation dialog: select language, HTTP client library, authentication scheme, and output options
- Generation job completes within 30 seconds for specs with ≤200 operations
- TypeScript SDK includes `.d.ts` declarations and is compatible with TypeScript 5.x strict mode
- Python SDK includes type hints compatible with mypy strict mode
- Generated SDKs include a README.md with quick-start usage and configuration examples
- Download link expires after 24 hours; regeneration is available at any time

**Tech Stack:** OpenAPI Generator CLI (containerized) or openapi-ts; async job queue; S3 download link

Part of Epic: Engineer DX

---

#### 2.7 (#2253) — Server Stub Generation

Generate backend API stubs with routing and validation matching the OpenAPI spec. Supported frameworks: Node.js (Express, Fastify, NestJS), Python (FastAPI, Flask, Django REST), Java (Spring Boot, Quarkus), Go (Gin, Echo, Chi), Rust (Actix-web, Rocket). Generated code includes: route definitions mapped to operations, request validation middleware, response serialization, OpenAPI documentation endpoint, health check endpoint, error handling middleware, authentication middleware stubs.

Stubs are intentionally minimal — routes return 501 Not Implemented by default so developers can incrementally implement each operation. Each route is annotated with the operationId and a link to the corresponding spec section.

**Acceptance Criteria:**
- Server stub dialog: select framework and language; preview first 50 lines of generated code before downloading
- All operations in the spec generate corresponding route stubs returning 501
- Request validation middleware validates incoming requests against path parameters, query parameters, and request body schema
- FastAPI/NestJS stubs include Pydantic/class-validator models generated from the request/response schemas
- Generated code passes lint checks for the target language (ESLint for JS/TS, Black for Python, golangci-lint for Go)
- Stubs include a Dockerfile and docker-compose.yml for immediate local development startup

**Tech Stack:** OpenAPI Generator CLI (framework-specific templates); Docker template; async generation job

Part of Epic: Engineer DX

---

#### 2.8 (#2254) — Interactive Documentation

**Embedded preview tab:** A resizable bottom panel or split-view toggle shows a live Swagger UI or ReDoc rendering of the current API spec, updating as the user edits operations. **Try It Out:** The embedded Swagger UI "Try It Out" functionality works against the integrated mock server (see P10 in Epic 5) or a configured real server. **Toggle:** developers switch between Swagger UI and ReDoc with a button. **Standalone preview URL:** generates a shareable read-only URL rendering the current spec as API documentation for stakeholders.

The preview panel is lazy-loaded (only initialized when first opened) to avoid impacting canvas performance. ReDoc and Swagger UI are loaded from CDN or bundled per tier.

**Acceptance Criteria:**
- "Preview" toggle button in toolbar opens the bottom documentation panel
- Panel refreshes within 500ms of canvas changes (debounced)
- Swagger UI "Try It Out" uses the mock server URL when mock server is running (P10)
- ReDoc renders navigation sidebar, search, and operation detail correctly
- Standalone preview URL is accessible without login if the project is public; requires `browse:read` for private projects
- Panel can be resized by dragging the top edge; minimum height 200px; height persists in user preferences

**Tech Stack:** Swagger UI (React), ReDoc; iframe or iframe-less embed; shareable preview URL via NextJS route

Part of Epic: Engineer DX

---

## Epic 3 (#2255): Enterprise Features

### Summary Table

| #    | Title                            | Description                                                                                             | Labels                                           | MVP | Parallel |
|------|----------------------------------|---------------------------------------------------------------------------------------------------------|--------------------------------------------------|-----|----------|
| 3.1 (#2256) | Security Configuration           | Security scheme library: OAuth2, API Key, HTTP Basic/Bearer, OpenID Connect; drag-to-assign scopes     | `enhancement`, `paths`                           | No  | No       |
| 3.2 (#2257) | Multi-Tenant & Team Collaboration | Org-scoped path libraries; path ownership; comment threads; real-time collaboration indicators         | `enhancement`, `paths`                           | No  | Yes      |
| 3.3 (#2258) | API Gateway Integration          | Rate limiting, transformation rules, CORS, caching policy; export to Kong/AWS API Gateway/Azure APIM   | `enhancement`, `paths`                           | No  | Yes      |
| 3.4 (#2259) | Contract Testing                 | Example-based request generation; Pact/Dredd contract generation; CI/CD integration hooks               | `enhancement`, `paths`                           | No  | Yes      |
| 3.5 (#2260) | Integrated Swagger UI (Testing)  | Embedded Swagger UI panel within Studio for live API testing; real-time spec sync                       | `enhancement`, `paths`                           | No  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#2256) — Security Configuration

A security scheme library panel in the left sidebar provides: OAuth2 flows (authorization code, client credentials, implicit, password), API Key (header, query, cookie), HTTP Basic/Bearer, OpenID Connect. Users drag security scheme nodes onto operation nodes to apply authentication requirements; a scope selector for OAuth2 flows shows a visual scope hierarchy with AND/OR logic. Global security defaults can be set per project version with per-operation overrides.

Advanced: custom security scheme extensions for proprietary auth systems; security requirement inheritance from parent paths; role-based access preview showing which roles can access which endpoints; security audit report generation for compliance review; JWT claim mapping visualization.

**Acceptance Criteria:**
- Security scheme library panel shows all defined schemes with scheme type icons
- Drag a security scheme node onto an operation to add it to `security[]`; drop on the background to set global security
- OAuth2 scope selector: hierarchical tree of defined scopes with checkbox selection; AND logic (all selected scopes required) vs. OR logic toggle
- "Security" tab in the editor overlay shows per-operation security with override toggle
- Security audit report: `GET /projects/{id}/versions/{v}/security-report` returns all operations with their security requirements, flagging any without security
- Role-based access preview: given a defined set of scopes, highlights which operations are accessible (overlay on canvas)

**Tech Stack:** React Flow security scheme node type; Radix UI CheckboxTree for scope selector; OpenAPI security spec

Part of Epic: Enterprise Features

---

#### 3.2 (#2257) — Multi-Tenant & Team Collaboration

Organization-scoped path libraries allow teams to define reusable endpoint pattern templates (CRUD generators, pagination patterns) accessible across all projects in the organization. Path ownership assigns edit/view permissions per path, enabling fine-grained access control for production API changes.

Comment threads: team members can pin comment bubbles to specific operation nodes; threads support replies, `@mentions`, markdown with code blocks, and resolved/unresolved state. Real-time collaboration indicators show avatar badges of users currently viewing the canvas and display live cursors for other users' positions. Path approval workflows require designated approvers to review and approve before changes are merged to the published version.

**Acceptance Criteria:**
- Organization path library: `GET/POST /organizations/{id}/path-templates` CRUD; templates appear in the left library panel
- Path ownership: `PUT /paths/{id}/ownership` assigns edit/view-only roles to users/groups
- Comment threads: right-click operation node → "Add Comment"; threads are persistent and shared with project members
- `@Mentions` trigger in-app notifications to tagged team members
- Collaboration indicators: active user avatars shown in the toolbar; cursor positions rendered as colored crosshairs with user names
- Approval workflow: `POST /paths/{id}/change-requests` creates a change request; approvers receive notification; merge requires approval

**Tech Stack:** WebSocket/SSE for collaboration cursors; Radix UI for comment thread dialog; PostgreSQL for threads

Part of Epic: Enterprise Features

---

#### 3.3 (#2258) — API Gateway Integration

Rate limiting configuration per operation uses custom `x-rateLimit` extensions (requests per second, burst size). Request/response transformation rules are attached to operations as `x-transform` extensions with key-value mapping configuration. CORS configuration at path and operation level. Caching policy with TTL and invalidation rules via `x-cache` extensions.

Export to major gateways: Kong (generate `kong.yaml` with plugins for rate limiting, CORS, and auth), AWS API Gateway (generate `x-amazon-apigateway-integration` extensions in the OpenAPI spec), Azure APIM (generate API Management policy XML). Advanced: circuit breaker configuration, canary/blue-green/A/B traffic policy metadata.

**Acceptance Criteria:**
- "Extensions" tab in editor overlay shows gateway-specific extension templates (rate limit, cache, transform, CORS)
- `x-rateLimit` extension adds a visual badge on the operation node showing the configured limit
- Kong export: `POST /projects/{id}/versions/{v}/paths/export/kong` generates a valid `kong.yaml` with plugin configurations
- AWS API Gateway export: generates OpenAPI spec with all `x-amazon-apigateway-*` extensions populated from the canvas configuration
- CORS configuration UI: method checkboxes, allowed origins (with wildcard support), max-age input, credentials toggle
- Gateway export validation: warns when required gateway-specific fields are missing before export

**Tech Stack:** OpenAPI extension editor; Kong/AWS/Azure template generators; extension visualization in node badges

Part of Epic: Enterprise Features

---

#### 3.4 (#2259) — Contract Testing

Contract testing validates that the implementation conforms to the API design. The Paths Designer generates test artifacts from the operation definitions.

**Example-based request generation:** For each operation, auto-generate request examples from parameter types and request body schemas (using faker-style data generators keyed to OpenAPI format hints: `format: email` → email address, `format: uuid` → UUID, etc.). **Response schema validation:** Validate actual API responses against the defined response schemas; display mismatches as diff highlights. **Postman/Insomnia export:** Export test cases as Postman Collection v2.1 or Insomnia workspace with pre-populated examples. **Pact contract generation:** Generate consumer-driven Pact contracts from the operation definitions. **Dredd test generation:** Generate Dredd test configuration for automated contract validation. **CI/CD integration:** Webhook endpoint that CI pipelines can call to fetch the latest contract and run tests against a deployed service.

**Acceptance Criteria:**
- "Generate Test Suite" action in toolbar export dropdown generates all example requests for every operation
- Example generation uses format hints (`format: email/uuid/date-time/uri`) for realistic data; falls back to type-appropriate defaults
- Postman Collection v2.1 export includes one test case per operation with example request and schema validation test script
- Pact contract JSON is generated from consumer perspective; format is Pact Specification v3
- `GET /projects/{id}/versions/{v}/contracts/dredd` returns a `dredd.yml` configuration file
- CI webhook: `GET /projects/{id}/versions/{v}/contracts/latest` returns the current OpenAPI spec for contract validation

**Tech Stack:** Faker-lite for example generation; Pact JSON generator; Dredd config generator; OpenAPI contract endpoint

Part of Epic: Enterprise Features

---

#### 3.5 (#2260) — Integrated Swagger UI (Testing)

An embedded Swagger UI panel within the Studio allows developers to test operations directly without leaving the Paths Designer. The panel syncs in real-time with canvas changes: as the user edits an operation, the Swagger UI updates within 500ms.

Features: Try It Out functionality with configurable base URL and authentication headers, request/response logging with copy-to-cURL capability, environment variable support for dynamic base URLs and auth tokens, response validation against defined schemas with error highlighting, response diff comparison between expected and actual, mock server generation from spec, request history with replay capability.

**Acceptance Criteria:**
- "Test" panel accessible via toolbar toggle; lazy-loaded on first open
- Swagger UI renders all operations from the current canvas state; updates within 500ms of canvas changes
- "Try It Out" button on each operation allows setting base URL, auth headers, and executing the request
- Response inspector shows: body (syntax-highlighted), headers, status code, response time, payload size
- Response validation: actual response schema is validated against the defined response schema; mismatches highlighted in red
- Request history persists for the session; each entry has a "Replay" button
- "Copy as cURL" generates a cURL command for the last test request

**Tech Stack:** Swagger UI React; SSE for real-time spec sync; fetch API for test execution; localStorage for request history

Part of Epic: Enterprise Features

---

## Epic 4 (#2261): UX Polish

### Summary Table

| #    | Title                              | Description                                                                                            | Labels                                        | MVP | Parallel |
|------|------------------------------------|--------------------------------------------------------------------------------------------------------|-----------------------------------------------|-----|----------|
| 4.1 (#2262) | Keyboard-First Navigation          | Full keyboard shortcut set: navigation, editing, quick-add by HTTP method, display toggles             | `enhancement`, `mvp`, `paths`                 | Yes | No       |
| 4.2 (#2263) | Undo/Redo for Paths Canvas         | 50-operation undo stack; coalescing for rapid moves; visual feedback toast; persistent undo option     | `enhancement`, `mvp`, `paths`                 | Yes | Yes      |
| 4.3 (#2264) | Paths Canvas Search & Filter       | Canvas search (`Cmd+F`) with result highlighting; filter by HTTP method, tag, status, path segment     | `enhancement`, `paths`                        | No  | Yes      |
| 4.4 (#2265) | Validation Panel & API Design Linting | Validation sidebar tab: errors/warnings/info; naming convention check; quality score 0–100         | `enhancement`, `paths`                        | No  | Yes      |
| 4.5 (#2266) | Minimap for Paths Canvas           | Bird's-eye minimap in bottom-right corner; viewport rectangle; click-to-navigate; `M` key toggle      | `enhancement`, `paths`                        | No  | Yes      |
| 4.6 (#2267) | Context Menu for Paths Nodes       | Right-click context menus for operation, parameter, response, and canvas background                    | `enhancement`, `paths`                        | No  | Yes      |
| 4.7 (#2268) | Edge & Connection Visual Improvements | Semantic edge labels; orthogonal routing; edge bundling; animated data flow; focus-mode re-routing   | `enhancement`, `paths`                        | No  | Yes      |
| 4.8 (#2269) | Left Sidebar Improvements          | Icon-only tabs with collapsible rail; hierarchical path tree; drag preview; drop zone highlighting     | `enhancement`, `paths`                        | No  | Yes      |
| 4.9 (#2270) | Paths Canvas Export Enhancements   | OpenAPI export dialog; visual export (PNG/SVG/PDF/Mermaid sequence); canvas export in 2x resolution   | `enhancement`, `paths`, `rest`                | No  | Yes      |
| 4.10 (#2271) | Canvas Visual Polish               | Dot grid, semantic zoom levels, node entrance/exit animations, visual grouping containers, status bar  | `enhancement`, `paths`                        | No  | Yes      |

### Detailed Issue Descriptions

#### 4.1 (#2262) — Keyboard-First Navigation

A comprehensive keyboard shortcut set makes the Paths Designer first-class for engineers who prefer keyboard over mouse.

**Navigation:** `Cmd/Ctrl+F` (canvas search), `Cmd/Ctrl+K` (command palette), `Space+Drag` (pan), `Scroll` (zoom), `Cmd+0` (reset zoom 100%), `Cmd+Shift+0` (fit all nodes), `Esc` (exit focus mode / close overlay / close search), `Tab` (cycle nodes in focus mode), `M` (toggle minimap).

**Editing:** `Enter` (open editor overlay for selected node), `Delete/Backspace` (delete with confirmation), `Cmd+D` (duplicate), `Cmd+C/V` (copy/paste), `Cmd+Z` (undo), `Cmd+Shift+Z` (redo), `Cmd+S` (save/persist).

**Quick-add (when operation selected):** `G` (add GET to selected path), `P` (add POST), `U` (add PUT), `A` (add PATCH), `X` (add DELETE), `Q` (add query parameter), `H` (add header parameter), `B` (focus request body), `2` (add 200 OK response), `4` (add 400 Bad Request), `5` (add 500 Server Error).

**Display:** `Cmd+Shift+L` (toggle auto-layout), `Cmd+Shift+E` (export dialog), `Cmd+Shift+V` (toggle OpenAPI preview panel), `Cmd+.` (toggle compact/expanded mode), `?` (keyboard shortcut overlay).

**Acceptance Criteria:**
- All shortcuts listed above are implemented and non-conflicting with browser defaults
- `?` key opens a shortcut overlay organized by category (Navigation, Editing, Quick-add, Display)
- Quick-add shortcuts only activate when a path or operation node is selected (not when a form input has focus)
- `Cmd+K` command palette is fuzzy-searchable across all Paths Designer actions
- Shortcuts are discoverable: tooltips on toolbar buttons show the keyboard shortcut
- Shortcut reference is accessible via the `?` toolbar button as well as the `?` key

**Tech Stack:** `useHotkeys` or custom keyboard event handler; Radix UI Dialog for overlay; localStorage for shortcut customization

Part of Epic: UX Polish

---

#### 4.2 (#2263) — Undo/Redo for Paths Canvas

The Paths canvas currently has no undo/redo capability. Any accidental deletion or edit is irreversible. This issue implements a client-side history stack that covers all canvas mutations.

**Tracked operations:** Operation CRUD (create/update/delete), parameter add/edit/delete, response add/edit/delete, request body changes, node moves, edge changes, layout changes. **Undo stack:** configurable depth (default 50, max 500). **Operation coalescing:** rapid sequential moves of the same node within a 300ms window collapse into a single undo entry. **Visual feedback:** brief toast notification on undo/redo showing what was undone ("Undone: Delete GET /users"). **History panel:** visual timeline of all changes with ability to jump to any point. **Persistent undo (optional):** persist the undo stack to the database so changes survive page reload (Enterprise tier).

**Acceptance Criteria:**
- `Cmd+Z` undoes the most recent tracked operation; `Cmd+Shift+Z` redoes it
- All tracked operation types are correctly reversed by undo (including edge creation, node creation, property changes)
- Operation coalescing: dragging a node 10 times in rapid succession produces one undo entry
- Toast notification appears for 2 seconds after each undo/redo; shows the operation description
- History panel: accessible from the toolbar; shows operation name, timestamp, and preview; click jumps canvas to that state
- Undo stack is cleared when the project version is changed

**Tech Stack:** Immer-based history stack or custom command pattern; React toast library; optional PostgreSQL persistence

Part of Epic: UX Polish

---

#### 4.3 (#2264) — Paths Canvas Search & Filter

**Search (`Cmd/Ctrl+F`):** Search overlay that searches across operation paths, operationIds, descriptions, parameter names, and response descriptions. Matching nodes are highlighted with a bright ring; non-matching nodes dim to 30% opacity. Up/Down arrows cycle through results; canvas auto-pans to center each result. Scope toggle: All, Paths only, Operations only, Parameters only, Responses only.

**Filter:** HTTP method toggle buttons (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS) to show/hide operations by method. Tag dropdown to filter by OpenAPI tag. Status filter showing only operations with validation errors or warnings. Path segment filter (e.g., `/users*`). Active filter badge on the filter button showing how many items are hidden.

**Operation table view:** Toolbar toggle switches from canvas view to a dense sortable table listing all operations (columns: Method, Path, OperationId, Summary, Parameters count, Responses count, Security, Tags, Validation Status). Click any row to jump to the operation on canvas. Bulk edit in table: select multiple rows and batch-edit tags, security, deprecated status.

**Acceptance Criteria:**
- Search overlay opens with `Cmd+F`; closes with `Esc`; overlay does not cover the toolbar
- Search highlights update within 100ms of typing; no debounce lag feels noticeable
- Cycling results (`Enter` / arrow keys) pans the canvas with 300ms ease-in-out animation
- HTTP method filter toggles are visually styled with the method color; active state clearly indicated
- Table view: sortable by any column; virtual scroll for >200 operations; row click selects and pans canvas
- Bulk edit in table: "Set Tag" dialog allows adding/removing tags from all selected operations in one action

**Tech Stack:** Canvas search overlay as React component; virtual table (TanStack Table); Fuse.js or simple substring match for search

Part of Epic: UX Polish

---

#### 4.4 (#2265) — Validation Panel & API Design Linting

A dedicated Validation tab in the left sidebar provides a persistent view of all current OpenAPI spec issues, organized by severity.

**Issue categories:** Errors (red, blocking export): missing required fields, invalid status codes, broken `$ref`, duplicate operationIds. Warnings (yellow): missing descriptions, operations without tags, missing examples, operations without security. Info (blue): best practice suggestions, documentation coverage notes, consistency observations.

**API design linting:** Naming convention check (warns when paths use verb-style naming like `/getUser` instead of `/users/{id}`); consistent pluralization check; HTTP method semantics (GET with request body, DELETE returning 201); response completeness (missing 400/401/404/500); security coverage; path-based versioning consistency.

**Quality score (0–100):** Displayed in the toolbar; calculated from documentation coverage (descriptions, examples), security coverage (% of operations with security requirements), validation compliance (zero errors, zero warnings each worth points), consistency (naming patterns), and completeness (responses and parameters defined). Hover shows score breakdown by category. Score trend tracked over time.

**Acceptance Criteria:**
- Validation tab shows all issues grouped by severity with a count badge on the tab icon
- Click any issue pans the canvas to the affected node and selects it
- Auto-fix: clicking "Fix" on a missing operationId generates one from method + path and applies it
- Quality score updates within 1 second of any canvas change; displayed as a colored number (green ≥80, yellow 60–79, red <60)
- Score breakdown tooltip shows the 5 category scores when hovering the quality score indicator
- Issue suppression: right-click an issue → "Suppress with reason"; suppressed issues are hidden from the panel

**Tech Stack:** Validation rule engine (Web Worker); quality score calculator; Radix UI sidebar tab

Part of Epic: UX Polish

---

#### 4.5 (#2266) — Minimap for Paths Canvas

The Paths canvas needs a minimap for navigating large APIs with many endpoints.

- **Minimap component:** Bird's-eye view in the bottom-right corner showing all operation nodes as colored dots (HTTP method color). Fixed size default 200×150px; draggable corner to resize.
- **Viewport rectangle:** Shows the current visible canvas area as a draggable semi-transparent rectangle. Dragging the viewport rectangle pans the canvas.
- **Click to navigate:** Clicking anywhere on the minimap pans the canvas to center that position.
- **Path group regions:** Color-code minimap background regions by path group (matching the group container colors from Epic 1.5).
- **Toggle:** `M` key or toolbar button shows/hides the minimap; state persists in user preferences.

**Acceptance Criteria:**
- Minimap renders all operation nodes as 4px × 4px colored dots in their relative canvas positions
- Viewport rectangle is draggable; dragging updates canvas pan in real-time
- Minimap updates within 100ms of canvas changes (node added, moved, or deleted)
- Path group regions are visible as subtle colored background areas in the minimap
- `M` key toggles minimap visibility; preference persists across sessions
- Minimap is not rendered during canvas export (PNG/SVG) to avoid appearing in output

**Tech Stack:** React Flow `MiniMap` component (customized); viewport sync; user preference storage

Part of Epic: UX Polish

---

#### 4.6 (#2267) — Context Menu for Paths Nodes

Right-click context menus provide instant access to common actions without navigating toolbars.

**Operation node menu:** Edit Operation (open overlay), Add Parameter (sub-menu: Query/Path/Header/Cookie), Add Response (sub-menu with common status codes), Set Request Body, Duplicate Operation, Move to Path (sub-menu of all paths), Copy as cURL, Copy as OpenAPI YAML, Generate Code (language sub-menu), Toggle Deprecated, Delete Operation.

**Parameter node menu:** Edit Parameter, Change Location (sub-menu), Toggle Required, Apply Primitive Template (UUID/email/pagination), Duplicate, Delete.

**Response node menu:** Edit Response, Change Status Code, Add Content Type, Bind Schema (class selector), Add Headers (template sub-menu: pagination/rate-limit/CORS headers), Duplicate, Delete.

**Canvas background menu:** Add Path, Add Operation (HTTP method sub-menu), Paste Operation, Auto-Layout, Fit View, Toggle Grid, Canvas Settings.

**Acceptance Criteria:**
- Right-click on each node type shows the correct context menu; menus close on `Esc` or external click
- "Copy as cURL" generates a valid cURL command with example values from the operation definition
- "Copy as OpenAPI YAML" copies the YAML fragment for the selected operation to clipboard
- "Apply Primitive Template" sub-menu shows common parameter presets (UUID, email, pagination limit/offset, search query)
- All destructive actions (Delete) show a confirmation dialog with operation description before executing
- Context menu items that require a selection (e.g., Move to Path) show a nested sub-menu with the relevant options

**Tech Stack:** Radix UI ContextMenu; clipboard API; confirmation dialog

Part of Epic: UX Polish

---

#### 4.7 (#2268) — Edge & Connection Visual Improvements

**Edge labels:** Parameter edges show location and name (e.g., "query: page"); response edges show status code ("200", "404"); schema binding edges show type ("$ref: Pet"); content type edges show content type ("application/json"). Semi-transparent pill background on labels for readability.

**Orthogonal (Manhattan) routing:** Strict right-angle routing (no diagonal segments). Configurable corner radius (default 10px, 0–20px range). Minimum segment length 20px (eliminating short jogs). Preferred routing direction per edge type (operation→parameter: downward; operation→response: rightward). Routing channel allocation (12px spacing for parallel edges).

**Edge crossing minimization:** Layer-based Barycenter heuristic; post-layout re-routing (debounced 200ms after drag-end); crossing count display in status bar. **Edge bundling:** Automatic bundling of 3+ parallel edges into a trunk that fans out near terminals; bundle expands on hover (300ms); manual bundle/unbundle via right-click. **Edge animation for data flow:** Animated dots for request flow (parameters → operation → request body) and response flow (operation → responses); animation speed control in canvas settings; `prefers-reduced-motion` respected.

**Port-based connections:** Multi-port nodes — operation nodes have left-side ports (request body), right-side ports (responses), bottom ports (parameters). Circular 6px port circles; auto-assignment to nearest available port; port color coding by relationship type; port hover tooltip ("Connect Response").

**Acceptance Criteria:**
- All edge types display their label; labels have a semi-transparent pill background
- Orthogonal routing produces right-angle paths with no diagonal segments
- Corner radius is configurable in canvas settings (slider 0–20px)
- Edge crossing count is displayed in the canvas status bar
- Edge bundling activates when 3+ parallel edges exist; bundle count label shows on trunk
- Data flow animation can be toggled in canvas settings; animates at 60fps; disabled when `prefers-reduced-motion` is active
- Port circles are hidden by default; appear on node hover; glow on connection drag

**Tech Stack:** Custom SmartEdge routing engine; SVG path generation; React Flow edge types; CSS animation

Part of Epic: UX Polish

---

#### 4.8 (#2269) — Left Sidebar Improvements

**Icon-only tab rail:** Replace text tabs with icon-only tabs (with tooltips): 🛤️ Paths, ⚡ Operations, 📦 Classes, 🔑 Security, 🌐 Servers. Collapsible to a 48px icon rail with `Cmd+B`. Auto-collapse when canvas is clicked (pinned/unpinned toggle).

**Hierarchical path tree:** Display paths as a tree structure grouped by path segments with collapsible nodes. Method color badges next to each operation. Validation status icons (✅/⚠️/❌). Click-to-navigate (pan canvas); double-click to open editor overlay directly.

**Drag-and-drop improvements:** Ghost preview showing method color and path during drag. Drop zone highlighting on valid targets. Red flash on invalid drop. Smart drop: dropping a class onto an operation opens a dialog asking where to bind it (request body, response body, or parameter type).

**Acceptance Criteria:**
- Icon-only tabs render with Radix Tooltip showing the tab name on hover
- `Cmd+B` collapses the sidebar to 48px icon rail; clicking an icon expands the panel to that tab
- Hierarchical tree renders paths grouped by first and second path segments correctly
- Tree nodes show method badges and validation icons without requiring a hover
- Drag preview: ghost follows cursor with 50% opacity; dropped nodes animate onto the canvas
- Smart drop on operation: dialog with 3 options (Request Body / Response Body / Parameter Type); selecting creates the appropriate node and edge

**Tech Stack:** Radix UI Collapsible; custom tree component; React DnD drag preview

Part of Epic: UX Polish

---

#### 4.9 (#2270) — Paths Canvas Export Enhancements

**OpenAPI export dialog enhancements:** Format (JSON/YAML), version (OpenAPI 3.1/3.0/Swagger 2.0), bundling (inline/$ref), include/exclude options, server URL editor, Monaco live preview, validation gate (block on errors with override), download or copy buttons, export to Git (push generated spec to configured repo), export history (timestamp, format, user).

**Visual export (PNG/SVG/PDF):** Same export wizard as the schema canvas, adapted for paths. Export-optimized rendering: 2x resolution, anti-aliased edges, hidden handles, visible edge labels, 40px padding. Light mode forced in export by default (with dark mode override option). Export focused view (only the focused operation and its connected nodes when in focus mode). Export as Mermaid sequence diagram (generates Mermaid syntax for request/response flow of selected operation). Export as API map (visual poster showing all endpoints organized by resource/tag).

**Acceptance Criteria:**
- OpenAPI export dialog includes a Monaco live preview that updates as options change
- "Export to Git" requires a configured Git repository integration; pushes a commit with the spec file
- Export history: last 20 exports listed with timestamp, format, user, and download link (valid 24h)
- PNG/SVG export renders at 2x device pixel ratio; edge labels are visible; handles are hidden
- Mermaid export: `POST /projects/{id}/versions/{v}/paths/export/mermaid?operation_id=` generates valid Mermaid `sequenceDiagram` syntax
- Focused view export: when focus mode is active, export dialog shows "Export Focused View" option

**Tech Stack:** html-to-image or react-to-print for canvas capture; Mermaid diagram generator; Git integration API

Part of Epic: UX Polish

---

#### 4.10 (#2271) — Canvas Visual Polish & Presentation

**Grid & background:** Dot grid option (dots at grid intersections, less visually dominant than lines). Grid fades out below 40% zoom, fades in above 50%. Isometric grid (optional, 30-degree angled). Canvas region shading: subtly shade areas by path group (`bg-blue-500/3` for `/users`, `bg-green-500/3` for `/products`).

**Visual grouping:** Auto-generated rounded-rectangle group containers around operations sharing the same base path; header shows path prefix; background is a very subtle tinted overlay; dashed border; collapse/expand toggle. Nested group indentation for sub-paths. Group color auto-assigned from an 8-color palette based on path prefix hash; consistent across sessions.

**Canvas status bar (28px):** Left: total operations/parameters/responses count. Center: edge crossing count, validation summary. Right: zoom percentage (click to open zoom dropdown), snap status, layout mode. Click actions on each status bar item.

**Semantic zoom:** 100%+ (Detail View): all content visible, edge labels visible. 60–100% (Standard View): method pill + path + status indicators; parameters/responses as count badges; edge labels visible. 30–60% (Overview): method pill + path only; nodes as compact cards (200×40px). <30% (Map View): nodes as colored rectangles (80×20px), edges as 1px lines. Smooth 150ms crossfade between levels.

**Animation & motion:** Node entrance (scale-0→1, opacity-0→1, 200ms ease-out); exit (scale-1→0, opacity-1→0, 150ms); edge draw animation (SVG stroke-dashoffset, 300ms); layout transition (400ms ease-in-out); `prefers-reduced-motion` disables all animations.

**Acceptance Criteria:**
- Dot grid toggle available in canvas settings; visually preferred over line grid in user testing
- Group containers auto-generate when "Group by Path" layout is applied; collapse state persists
- Status bar is always visible at canvas bottom; clicking zoom percentage opens a zoom dropdown (50%, 75%, 100%, 150%, 200%, Fit)
- Semantic zoom: correct content is shown at each zoom breakpoint with 150ms crossfade
- Node entrance animation plays when a new node is created via drag, quick-add, or auto-generate
- `prefers-reduced-motion` OS setting disables all transitions and animations immediately on preference change

**Tech Stack:** React Flow `Background` (dots variant); CSS zoom-level classes on canvas wrapper; `ResizeObserver` for status bar metrics

Part of Epic: UX Polish

---

## Epic 5 (#2272): Enterprise Improvements (P1–P16)

### Summary Table

| #    | Title                              | Description                                                                                          | Labels                                              | MVP | Parallel |
|------|------------------------------------|------------------------------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 5.1 (#2273) | Command Palette (P1)               | Fuzzy-search over all Paths Designer actions; recent actions; contextual commands for selected node  | `enhancement`, `paths`                              | No  | No       |
| 5.2 (#2274) | Integrated API Testing Panel (P2)  | Per-operation test button; test panel with server selector, editable params, response inspector      | `enhancement`, `paths`                              | No  | Yes      |
| 5.3 (#2275) | Paths Diff & Version Comparison (P3) | Side-by-side diff between versions; breaking change detection; changelog generation; cherry-pick   | `enhancement`, `paths`                              | No  | Yes      |
| 5.4 (#2276) | Paths Annotations & Comments (P4)  | Sticky notes; pin comment threads to operations; @mentions; review mode                              | `enhancement`, `paths`                              | No  | Yes      |
| 5.5 (#2277) | Real-Time Collaboration (P5)       | Presence indicators; live cursors; CRDT conflict-free editing; follow mode; activity feed            | `enhancement`, `paths`                              | No  | Yes      |
| 5.6 (#2278) | Paths Audit Trail (P6)             | Change log per operation and path; diff playback; blame view; export audit trail CSV/JSON            | `enhancement`, `paths`, `rest`                      | No  | Yes      |
| 5.7 (#2279) | Paths Performance Optimization (P7) | Extract custom hooks; lazy-load dialogs; virtualized node rendering; memoized components            | `enhancement`, `paths`                              | No  | Yes      |
| 5.8 (#2280) | Paths Import Enhancements (P8)     | Import from Postman/Insomnia/HAR/API Gateway; selective import; merge with conflict resolution       | `enhancement`, `paths`, `rest`                      | No  | Yes      |
| 5.9 (#2281) | Operation Grouping & Resource View (P9) | Resource groups; tag-based groups; manual groups; collapsed group view; nested resources        | `enhancement`, `paths`                              | No  | Yes      |
| 5.10 (#2282) | Integrated Mock Server (P10)       | One-click mock server; example-based responses; configurable latency; request validation             | `enhancement`, `paths`                              | No  | Yes      |
| 5.11 (#2283) | Paths Accessibility (P11)          | WCAG 2.1 AA: keyboard-only navigation, ARIA live regions, high-contrast colors, reduced motion       | `enhancement`, `paths`                              | No  | Yes      |
| 5.12 (#2284) | Dark IDE Theme Integration (P12)   | First-class dark mode: adjusted method colors, edge visibility, Monaco dark theme, Blueprint theme   | `enhancement`, `paths`                              | No  | Yes      |
| 5.13 (#2285) | OpenAPI Extension Support (P13)    | Extension editor in overlay; common extension templates; extension visualization as node badges      | `enhancement`, `paths`, `rest`                      | No  | Yes      |
| 5.14 (#2286) | API Metrics & Analytics (P14)      | Surface area metrics; complexity score; documentation coverage; naming consistency; metrics panel    | `enhancement`, `paths`                              | No  | Yes      |
| 5.15 (#2287) | Swagger UI / ReDoc Preview (P15)   | Embedded preview tab; auto-refresh; Try It Out via mock server; standalone preview URL               | `enhancement`, `paths`                              | No  | Yes      |
| 5.16 (#2288) | Multi-Spec & Microservice Coordination (P16) | Multi-spec canvas; cross-service schema references; service dependency map; merged export  | `enhancement`, `paths`, `rest`                      | No  | Yes      |
| 5.17 (#2289) | Advanced Edge Routing Engine (P16-routing) | Orthogonal routing engine; crossing minimization; port-based connections; edge bundling; presets | `enhancement`, `paths`                          | No  | Yes      |
| 5.18 (#2290) | Node Visual Design System (P17)    | PathsBaseNode unified shell; consistent 280px width; interaction states; node design presets         | `enhancement`, `paths`                              | No  | Yes      |

### Detailed Issue Descriptions

#### 5.1 (#2273) — Command Palette (P1)

`Cmd/Ctrl+K` opens a fuzzy-search overlay centered on the canvas that indexes every Paths Designer action by name. Categories: Navigation ("Go to GET /users", "Go to operation createUser"), Creation ("Add path", "Add GET operation"), View ("Fit view", "Toggle minimap"), Export ("Export OpenAPI YAML"), Layout ("Auto-layout top-to-bottom"), Settings ("Change edge style"). Fuzzy matching accepts partial and out-of-order terms. Recent actions appear at the top. When a node is selected, contextual commands for that node appear first. Keyboard navigation: arrow keys to move, Enter to execute, Esc to dismiss.

**Acceptance Criteria:**
- `Cmd/Ctrl+K` opens the palette; closes with `Esc` or backdrop click
- Fuzzy matching: "get user" matches "Go to GET /users/{id}"
- Contextual commands: when an operation is selected, "Add parameter", "Edit operation", "Delete" appear at the top
- Recent commands list: last 5 used commands; persisted across sessions in localStorage
- All Paths Designer toolbar and context menu actions are indexed in the command palette

**Parallel Group:** ENTERPRISE-P1 | **Can run alongside:** 5.2, 5.3, 5.4

Part of Epic: Enterprise Improvements

---

#### 5.2 (#2274) — Integrated API Testing Panel (P2)

Each operation node has a "▶ Test" button. Clicking it opens a resizable bottom panel. The panel contains: server selector dropdown (from OpenAPI servers array), auto-populated request fields (URL, method, headers, query params, path params, request body from the operation definition), editable parameter and body fields, authentication selector (auto-applies security scheme credentials), Send button with loading indicator, response viewer (status code, headers, syntax-highlighted body, response time, payload size), environment variable support (`{{baseUrl}}`, `{{apiKey}}`), request history log with replay, cURL export, and response schema validation (highlights mismatches against the defined response schema).

**Acceptance Criteria:**
- "▶ Test" button visible on hover over any operation node; also accessible via context menu → "Test This Operation"
- Server selector pre-populates from `servers[]` in the OpenAPI spec; allows manual URL entry
- Auto-populated request: path parameters are extracted from the path pattern and shown as required input fields
- Environment variables: `PATCH /projects/{id}/test-environments` stores key-value pairs; substituted in all test requests
- Response validation: actual JSON response is validated against the defined success response schema; mismatches shown as red highlights with JSON Pointer paths
- Request history persists for the session (not across page reloads); max 50 entries per operation

**Parallel Group:** ENTERPRISE-P2 | **Can run alongside:** 5.1, 5.3, 5.4

Part of Epic: Enterprise Improvements

---

#### 5.3 (#2275) — Paths Diff & Version Comparison (P3)

Enterprise teams need to compare API definitions across versions. A split-canvas view shows the current version on the left and a selected comparison version on the right, linked so pan/zoom are synchronized. Each operation shows a badge: "Added" (green), "Modified" (yellow), "Removed" (red), "Unchanged" (no badge). Expanding a modified operation shows which parameters, responses, or schemas changed. Breaking changes (removed operation, removed required parameter, changed response schema) are flagged with a red "BREAKING" badge. Changelog generation produces a human-readable summary. Cherry-pick merge allows selecting individual changes from the comparison version to apply to the current.

**Acceptance Criteria:**
- Version selector dropdown in toolbar; selecting a comparison version activates diff mode
- Split canvas: left panel is current version (editable), right panel is comparison version (read-only)
- Pan/zoom are synchronized: panning one panel mirrors the other
- Operation badges update within 1 second of version selection
- "Next/Previous change" navigation buttons cycle through all diff items
- Breaking change detection: operations that are removed, or have required parameters removed, or have response schemas made more restrictive are marked `BREAKING`
- Changelog generation: `POST /projects/{id}/versions/{v}/paths/changelog?compare_to={v2}` returns a structured changelog
- Cherry-pick: select operation from right panel → "Apply to Current Version" copies the operation definition; presents conflict dialog if operation already exists

**Parallel Group:** ENTERPRISE-P3 | **Can run alongside:** 5.1, 5.2, 5.4

Part of Epic: Enterprise Improvements

---

#### 5.4 (#2276) — Paths Annotations & Comments (P4)

Sticky notes (freeform text, placeable anywhere on the canvas) and comment threads pinned to operation nodes support collaborative design review. Comment threads support replies, `@mentions` (triggering in-app notifications), rich text (Markdown with code blocks), and resolved/unresolved state. A filter toggle shows/hides all annotations. Review mode makes the canvas read-only with comment-only interaction. Comment export includes comments in PDF or Markdown export reports.

**Acceptance Criteria:**
- Right-click canvas → "Add Sticky Note" creates a draggable text box; content saved on blur
- Right-click operation → "Add Comment" opens a thread panel anchored to the node
- @mention lookup shows organization members; tagged users receive in-app notifications
- Resolve button marks thread as resolved; resolved threads are hidden by default (toggle to show)
- Unresolved comment threads show a badge count on the operation node
- Review mode: toolbar toggle that locks the canvas to read-only; editing the canvas shows a "Exit Review Mode" prompt
- Export: comment export includes thread content, resolution status, and timestamps in export report

**Parallel Group:** ENTERPRISE-P4 | **Can run alongside:** 5.1, 5.2, 5.3

Part of Epic: Enterprise Improvements

---

#### 5.5 (#2277) — Real-Time Collaboration (P5)

Enterprise teams need concurrent editing on the Paths Designer. Presence indicators (avatar badges in toolbar) show who is currently viewing the canvas. Live cursors render other users' cursor positions as colored crosshairs with name labels. CRDT or operational transform ensures conflict-free concurrent edits to the same operation. Activity feed in the sidebar shows a live stream of changes by all users. Follow mode locks your viewport to another user's position. Editing lock indicator: when a user has the editor overlay open for an operation, a lock icon appears on that node for other users.

**Acceptance Criteria:**
- Presence indicators: up to 8 avatar badges shown in toolbar; "+N more" overflow for larger groups
- Live cursors: each connected user's cursor renders as a 20px crosshair in their assigned color with their display name below
- CRDT: concurrent edits to the same operation property converge to a consistent state without data loss; tested with 2 simultaneous users making conflicting edits
- Activity feed: sidebar shows last 50 changes with user, timestamp, and change description; auto-scrolls to latest
- Follow mode: click an avatar → "Follow [name]" locks viewport; any movement by that user pans the canvas for you
- Editing lock: when User A opens the editor overlay for GET /users, User B sees a 🔒 badge on the GET /users node

**Parallel Group:** ENTERPRISE-P5 | **Depends on:** 5.4 (P4) comment infrastructure

Part of Epic: Enterprise Improvements

---

#### 5.6 (#2278) — Paths Audit Trail (P6)

Every create, update, and delete of a path, operation, parameter, response, or request body is recorded with timestamp and user. The per-operation change log shows a diff of what changed at each point. Diff playback allows stepping through the change history chronologically to watch the API design evolve. Blame view color-codes operation nodes by last editor. CSV/JSON audit trail export. Configurable retention period for audit entries (default 90 days, Enterprise: unlimited).

**Acceptance Criteria:**
- Audit trail is accessible from the operation context menu → "View History"
- Per-operation change log shows: timestamp, actor, change type, and a field-level diff
- Diff playback: "Step Forward"/"Step Backward" buttons transition the canvas through historical states
- Blame view: toggled from toolbar; each node header shows the last editor's avatar and "X days ago" timestamp
- `GET /projects/{id}/versions/{v}/paths/audit?since=&operation_id=&format=csv` exports filtered trail
- Retention policy: `PATCH /tenants/{id}/paths-audit-config` sets retention days; records older than the window are purged on a nightly job

**Parallel Group:** ENTERPRISE-P6 | **Can run alongside:** 5.5, 5.7, 5.8

Part of Epic: Enterprise Improvements

---

#### 5.7 (#2279) — Paths Performance Optimization (P7)

The `PathsCanvasView.tsx` component is approximately 3,800 lines. For APIs with 50+ operations, performance and maintainability improvements are critical.

**Custom hooks to extract:** `usePathsOperations` (CRUD state), `usePathsDragDrop` (drag-and-drop handlers), `usePathsKeyboard` (shortcut handlers), `usePathsFocusMode` (focus/isolation logic), `usePathsLayout` (layout algorithm and positioning), `usePathsEdges` (edge creation and routing). **Sub-components to extract:** `PathsToolbar`, `PathsSearchOverlay`, `PathsEditorOverlay`, `PathsCodePreview`, `PathsStatusBar`. **Additional:** lazy-load dialogs (editor overlay, export dialog, import dialog) with code-split; virtualized node rendering (React Flow viewport culling) for 100+ nodes; `React.memo` on all node components; 300ms debounce on all API calls and database writes.

**Acceptance Criteria:**
- `PathsCanvasView.tsx` reduced to ≤800 lines (primary orchestration only; logic moved to hooks)
- Each extracted hook has its own file with unit tests covering its primary logic
- Dialog lazy-loading: editor overlay JS is not included in the initial canvas bundle; loads on first open
- FPS benchmark: 100-node canvas maintains ≥50fps on a mid-range laptop (Chrome DevTools Performance panel)
- `React.memo` applied to all 7 node types; verified with React DevTools profiler showing 0 unnecessary re-renders during canvas pan/zoom
- Debounce: rapid property changes (e.g., typing in description field) produce at most one API call per 300ms

**Parallel Group:** ENTERPRISE-P7 | **Can run alongside:** 5.6, 5.8, 5.9

Part of Epic: Enterprise Improvements

---

#### 5.8 (#2280) — Paths Import Enhancements (P8)

**Import from project schemas:** Right-click a class → "Generate CRUD Endpoints" (already in Epic 2.4, extended here with schema canvas cross-navigation). **Import Postman Collection:** Parse Postman Collection v2.1 and create paths, operations, parameters, request bodies, and responses on the canvas. **Import Insomnia Workspace:** Parse Insomnia export format. **Import HAR file:** Parse HTTP Archive (HAR) from browser DevTools recordings; reverse-engineer path definitions from recorded traffic. **Import from API Gateway:** Fetch endpoint definitions from AWS API Gateway, Azure APIM, or Kong and create corresponding paths. **Selective import:** Choose which paths/operations to import. **Merge import:** Integrate into existing canvas with conflict detection and resolution UI.

**Acceptance Criteria:**
- Import dialog: file upload, URL fetch, or API Gateway connection; source format auto-detected
- Postman Collection v2.1 import maps all requests to operations with their pre-request scripts extracted as description notes
- HAR import: from a `.har` file, extract unique (method, path, status) combinations as operation stubs
- AWS API Gateway import: uses AWS SDK credentials configured in organization settings to fetch the API definition
- Selective import: checkbox list of all importable operations; "Import Selected" button
- Merge conflict: when an operation already exists at the same path+method, show a side-by-side diff with "Keep Existing"/"Use Imported"/"Merge" options per conflict

**Parallel Group:** ENTERPRISE-P8 | **Can run alongside:** 5.7, 5.9, 5.10

Part of Epic: Enterprise Improvements

---

#### 5.9 (#2281) — Operation Grouping & Resource View (P9)

Enterprise APIs with 50+ endpoints need visual organization beyond flat node lists. Resource groups automatically group operations by resource (first path segment) into collapsible containers with colored headers. Tag-based groups organize by OpenAPI tags. Manual groups: drag operations into custom-named groups. Collapsed group view shows: resource name, operation count, HTTP method pills. Group-level actions via right-click: Expand/Collapse, Add Operation, Delete All, Move Group, Set Tag, Export Group as OpenAPI fragment. Nested resources appear as child groups. Resource color coding with persistent color choices.

**Acceptance Criteria:**
- "Group by Resource" toolbar button creates container nodes grouping operations by first path segment
- Collapsed group shows resource name + operation count + method pill badges (one per HTTP method present)
- Right-click group container → group-level context menu with all documented actions
- Nested groups: `/users/{id}/posts` operations appear as a child group container within the `/users` group
- Color picker: right-click group → "Change Color" opens an 8-color palette; choice persists in project state
- `POST /projects/{id}/versions/{v}/paths/groups` CRUD API for saving/restoring group configuration

**Parallel Group:** ENTERPRISE-P9 | **Can run alongside:** 5.8, 5.10, 5.11

Part of Epic: Enterprise Improvements

---

#### 5.10 (#2282) — Integrated Mock Server (P10)

Frontend developers need to work against the API design before the backend is built. A one-click mock server starts a local mock service that serves responses based on the current path definitions. Features: example-based responses (from spec examples; fallback to auto-generated data), configurable latency slider (0–5000ms), error simulation (configurable % chance of 4xx/5xx), request validation (validate incoming requests against defined schemas; return 400 on mismatch), mock server URL display in toolbar, live request/response log, dynamic mock rules ("If `userId` is 999, return 404").

The mock server runs as a Docker container managed by the Apiome backend. The container is started/stopped via a WebSocket control API and assigned an ephemeral URL with TLS termination.

**Acceptance Criteria:**
- "Start Mock Server" button in toolbar spins up a container within 10 seconds; URL displayed in toolbar
- Mock server returns responses from `example` or `examples` fields in the spec; auto-generates data for fields without examples using faker keyed to JSON Schema format hints
- Latency slider: 0ms (default) to 5000ms; value displayed as "X ms artificial delay"
- Error simulation: configurable percentage (0–100%); when triggered, randomly selects a 4xx/5xx response from the operation's defined responses
- Request validation: incoming requests that fail schema validation return a `400 Bad Request` with validation errors in RFC 7807 format
- Request log: live list of last 50 mock server hits with method, path, status, and duration
- Dynamic mock rules: UI to add conditional rules (field = value → return status code); stored in project state

**Parallel Group:** ENTERPRISE-P10 | **Can run alongside:** 5.9, 5.11, 5.15

Part of Epic: Enterprise Improvements

---

#### 5.11 (#2283) — Paths Accessibility (P11)

Enterprise products must meet WCAG 2.1 AA accessibility standards. The Paths Designer canvas must be navigable via keyboard only, provide screen reader announcements for state changes, ensure sufficient color contrast, and respect system-level motion preferences.

- **Keyboard-only navigation:** Tab/Shift+Tab cycles through all canvas nodes; arrow keys move the selected node; Enter opens the editor overlay; Delete deletes with confirmation
- **Screen reader:** ARIA live regions announce "Operation added: GET /users", "Operation deleted: DELETE /users/{id}", "Focus mode entered: GET /users/{id}"
- **High-contrast method colors:** All HTTP method colors meet 4.5:1 contrast ratio against white background (WCAG AA); verified with axe-core automated tests
- **Focus ring indicators:** Visible `focus-visible` outline on selected nodes for keyboard users using the node's accent color
- **Reduced motion:** `prefers-reduced-motion` disables all canvas animations and transitions (see 4.10)
- **Zoom with keyboard:** `+`/`-` keys zoom in/out; `0` resets zoom
- **Alt text:** All node types have descriptive `aria-label` ("GET /users/{id} operation node, 3 parameters, 2 responses, 1 warning")

**Acceptance Criteria:**
- axe-core automated accessibility tests pass with zero violations on the canvas page
- Keyboard-only navigation: Tab cycles through all visible nodes; focused node is visually distinct from selected node
- ARIA live region announces every node addition, removal, and focus mode change
- HTTP method color contrast: verified with browser color contrast checker for all 8 methods in light and dark mode
- Screen reader audit: NVDA + Firefox and VoiceOver + Safari complete the "add an operation" task successfully

**Parallel Group:** ENTERPRISE-P11 | **Can run alongside:** 5.10, 5.12, 5.13

Part of Epic: Enterprise Improvements

---

#### 5.12 (#2284) — Dark IDE Theme Integration (P12)

Developers overwhelmingly prefer dark themes. The Paths Designer must have a first-class dark mode that feels native to dark IDEs, not a simple color inversion.

- **Node colors in dark mode:** HTTP method colors lightened/saturated for dark backgrounds (GET: `#4ade80`, POST: `#60a5fa`, PUT: `#fb923c`, PATCH: `#c084fc`, DELETE: `#f87171`)
- **Edge colors in dark mode:** Lighter edge colors with higher opacity
- **Monaco editors:** Dark theme (VS Code Dark+, Monokai, Dracula) selectable in user preferences
- **Sidebar dark theme:** Dark gradient with subtle borders
- **Blueprint theme:** Dedicated "API Blueprint" theme: dark navy background (`#0a0e1a`), cyan grid (`#0891b2`), neon-accented nodes — a cyberpunk/developer-aesthetic alternative
- **Consistent theming:** All new components (command palette, search overlay, context menus, tooltips) must respect the current theme with no flash of wrong theme on load

**Acceptance Criteria:**
- Dark mode: all 7 node types correctly render with zinc-900 backgrounds and lightened accent bar colors
- Dark mode: Monaco Preview tab uses VS Code Dark+ by default; user can change in preferences
- Blueprint theme: selectable from canvas settings; applies navy background, cyan grid, and neon accent bars
- No flash of wrong theme on page load (theme class applied before first paint via cookie/localStorage read in layout)
- All new Epic 5 components (command palette, collaboration cursors, comment bubbles) support dark mode on day one

**Parallel Group:** ENTERPRISE-P12 | **Can run alongside:** 5.11, 5.13, 5.14

Part of Epic: Enterprise Improvements

---

#### 5.13 (#2285) — OpenAPI Extension Support (P13)

Enterprise teams use custom `x-*` OpenAPI extensions for API gateway configuration, documentation metadata, and internal tooling. A dedicated Extensions tab in the editor overlay provides a key-value editor for `x-*` extensions on operations, parameters, and responses.

**Common extension templates:** `x-rateLimit` (requests/second, burst), `x-cache` (TTL, vary-by), `x-internal` (mark operation internal-only), `x-stability` (alpha/beta/stable), `x-permissions` (required permissions/scopes), `x-codegen-request-body-name` (OpenAPI Generator hint), `x-amazon-apigateway-integration` (AWS API Gateway). **Extension visualization:** Node badges for common extensions (e.g., a "Rate Limited" chip when `x-rateLimit` is set). **Organization extension library:** Define custom extension schemas available across all projects. **Extension validation:** Validate extension values against their defined JSON Schema.

**Acceptance Criteria:**
- "Extensions" tab in editor overlay shows a key-value list for `x-*` fields on the current entity
- "Add Extension" dropdown lists common templates; selecting a template pre-fills key and provides the correct input type (number, string, enum)
- `x-rateLimit` extension: displays a "⚡ Xrps" badge on the operation node header when set
- `x-internal` extension: displays a "🔵 Internal" badge and applies a subtle visual treatment (dashed border) on the node
- Organization extension library: `GET/POST /organizations/{id}/extension-schemas` CRUD; schemas appear in the "Add Extension" template dropdown
- Extension validation: values that don't match the extension's JSON Schema show inline error in the editor

**Parallel Group:** ENTERPRISE-P13 | **Can run alongside:** 5.12, 5.14, 5.15

Part of Epic: Enterprise Improvements

---

#### 5.14 (#2286) — API Metrics & Analytics (P14)

Architects need data-driven insight into their API design to make informed decisions. A metrics panel shows real-time analytics about the current API spec.

**Metrics:** Total paths, operations, parameters, responses (with trend over version history); operations per HTTP method distribution (bar chart); average parameters per operation; response coverage (% of operations with 2xx, 4xx, 5xx responses); security coverage (% of operations with security requirements). **Complexity score:** Per-operation score based on parameter count, response count, schema depth, and content type variety. **Documentation coverage:** % of operations with descriptions; % of parameters with descriptions; % of responses with examples. **Naming consistency score:** Analysis of operationId patterns, path naming conventions, parameter naming patterns. **Metrics panel:** Collapsible bottom panel or sidebar tab with visual charts. **Metrics export:** `GET /projects/{id}/versions/{v}/paths/metrics?format=json` exports as JSON or CSV.

**Acceptance Criteria:**
- Metrics panel opens from toolbar → Analytics button; shows all 6 metric categories
- HTTP method distribution is rendered as a horizontal bar chart with method colors
- Response coverage: per-operation coverage shown as a small colored bar in the table view
- Complexity score: shown as a number badge on each operation node in the "Metrics" view mode (toggled in toolbar)
- Metrics are calculated client-side from the current canvas state; update within 200ms of any canvas change
- `GET /projects/{id}/versions/{v}/paths/metrics` API returns a stable JSON structure for CI integration

**Parallel Group:** ENTERPRISE-P14 | **Can run alongside:** 5.13, 5.15, 5.16

Part of Epic: Enterprise Improvements

---

#### 5.15 (#2287) — Swagger UI / ReDoc Preview Panel (P15)

(See Epic 2.8 for baseline; this issue extends it with enterprise integration features.)

An embedded preview tab connected to the integrated mock server (P10/5.10). When the mock server is running, "Try It Out" in the embedded Swagger UI automatically routes requests to the mock server URL. Toggle between Swagger UI and ReDoc renderers. Standalone preview URL generates a public or access-controlled read-only documentation page for sharing with stakeholders without requiring an Apiome account.

**Acceptance Criteria:**
- When mock server is running (P10 active), "Try It Out" base URL is auto-set to the mock server URL
- "Try It Out" responses from the mock server show request/response details including artificial latency
- ReDoc rendering supports all OpenAPI 3.1 features used in Apiome path definitions
- Standalone preview URL: `GET /projects/{id}/versions/{v}/paths/preview-url` generates a shareable URL
- Preview URL: accessible without login for public projects; requires `browse:read` token for private projects
- Preview URL reflects the current spec state (not a snapshot); updates when the spec changes

**Parallel Group:** ENTERPRISE-P15 | **Can run alongside:** 5.14, 5.16, 5.10

Part of Epic: Enterprise Improvements

---

#### 5.16 (#2288) — Multi-Spec Support & Microservice Coordination (P16)

Enterprise architectures involve multiple microservices, each with their own OpenAPI spec. The Paths Designer should support working with multiple specs and understanding cross-service dependencies.

**Multi-spec canvas:** Display operations from multiple project versions on the same canvas, color-coded by service (each service gets a distinct background color for its operations). **Cross-service references:** Visualize when one service's operation references a schema owned by another service (dotted cross-service edge). **Service dependency map:** High-level overview showing which services depend on which based on shared schemas and cross-references. **Unified search:** Search across all services' operations from a single search box. **Merged export:** `POST /organizations/{id}/multi-spec-export` combines selected project versions into a unified OpenAPI spec with namespace prefixes. **Gateway view:** Aggregated view of all operations as they appear through an API gateway.

**Acceptance Criteria:**
- Multi-spec canvas: dropdown to add additional project versions; each service's nodes have a colored service indicator chip
- Cross-service `$ref` edges: when operation A uses a schema from project B, a dotted cross-service edge connects A to the class node with a "External" label
- Service dependency map: modal showing a directed graph of service dependencies; node size proportional to number of cross-service references
- Unified search: search input searches across all loaded specs simultaneously; results grouped by service
- Merged export: generates a valid OpenAPI spec with path prefixes (`/service-a/...`, `/service-b/...`) to avoid conflicts

**Parallel Group:** ENTERPRISE-P16 | **Can run alongside:** 5.15, 5.17, 5.18

Part of Epic: Enterprise Improvements

---

#### 5.17 (#2289) — Advanced Edge Routing Engine (P16-routing)

Production-grade orthogonal routing with crossing minimization, port-based connections, edge bundling, and style presets.

**Orthogonal routing:** Strict right-angle segments (no diagonals). Configurable corner radius (default 10px, 0–20px). Minimum segment length 20px. Preferred routing direction per edge type. Routing channel allocation (parallel edges spaced 12px apart). **Crossing minimization:** Barycenter heuristic post-layout; 2-opt improvement passes (≤5 iterations); crossing count in status bar. **Port-based connections:** Multi-port layouts per node type (left ports for request body, right ports for responses, bottom ports for parameters). Port auto-assignment; port ordering to minimize crossings; port color coding. **Edge bundling:** 3+ parallel edges bundled into a trunk; hover to expand (300ms); count label; manual bundle/unbundle. **Dynamic re-routing:** Live re-route during drag (16ms throttle); snap-to-route for cleaner paths; post-drag optimization pass. **Edge style presets:** "Blueprint" (1.5px, sharp corners, steel-blue), "Modern" (2px, 12px radius, gradient), "Minimal" (1px, hidden labels), "Neon" (dark mode, glowing edges), "Hand-Drawn" (rough.js style).

**Acceptance Criteria:**
- All edges use orthogonal routing; no diagonal segments visible on any canvas
- Corner radius slider in canvas settings: 0px (sharp) to 20px (rounded); updates live
- Crossing count displayed in status bar; decreases after running minimization passes
- Port circles: 6px circles, hidden by default, visible on node hover, glow during connection drag
- Edge bundling: when 3+ operation-to-parameter edges share source and target direction, a bundle trunk appears automatically
- Style presets: 5 presets selectable from canvas settings → "Edge Style"; all settings change simultaneously
- Live re-routing during drag: edges connected to a dragged node re-route at ≥30fps

**Parallel Group:** ENTERPRISE-P17-routing | **Can run alongside:** 5.16, 5.18

Part of Epic: Enterprise Improvements

---

#### 5.18 (#2290) — Node Visual Design System (P17)

A unified visual design system for all node types, delivering consistency, hierarchy, and polish across the entire canvas.

**Unified shell (`PathsBaseNode`):** `rounded-xl`, consistent shadow scale, `bg-white dark:bg-zinc-900`, 280px width, type icon in top-right corner, elevation hierarchy (operation=shadow-lg, response/body=shadow-md, parameter/class=shadow-sm). **Operation node overhaul:** 4px left accent bar in method color; compact method pill badge; summary line; micro-badge row (parameter count, response count, security indicator, deprecated badge, private badge); tags as colored chips. **Parameter node refinement:** Compact chip (36px), location dot, name:type format, required asterisk, 3px left border, expanded view on double-click. **Response node refinement:** Status code pill, status-color left bar, schema preview, headers badge. **Request/response body refinement:** Accent bar (indigo request, emerald response), content type tabs, schema snippet preview. **Class node refinement:** Schema card with indigo left bar, first 3–4 property names, property count badge, link to schema canvas. **Interaction states:** Idle, hover, selected, dragging, focused (focus mode), dimmed (focus mode), error, drop target — each with defined Tailwind classes. **Node design presets:** "Professional" (default, accent bars, minimal shadows), "Developer" (high density, monospace), "Colorful" (full-width headers, current style), "Blueprint" (navy/cyan), selectable from canvas settings with live preview thumbnails.

**Acceptance Criteria:**
- All 7 node types use `PathsBaseNode` wrapper; no node has custom outer styling outside the wrapper
- All nodes standardized to 280px width (verified with snapshot tests)
- Operation node: micro-badge row renders all 5 badges with correct data; updates in real-time with canvas state
- Parameter chip: 36px height verified in all browsers; expands to full detail on double-click
- Interaction states: Playwright visual regression tests for each of the 8 states on each node type
- Node design presets: switching presets applies changes to all nodes on canvas within 100ms; no layout shift
- Dark mode palette: all nodes render correctly in dark mode with zinc-900 backgrounds and lightened accent bars

**Parallel Group:** ENTERPRISE-P18-design | **Can run alongside:** 5.17

Part of Epic: Enterprise Improvements
