# Apiome: Architect - Feature Roadmap

> Enterprise architecture tool that provides high-level visualization of system landscapes, service dependencies, and data flow across the organization. Architect enables teams to reason about bounded contexts, enforce architecture patterns, and record decisions — all grounded in Apiome's schema and API metadata.
>
> **Revenue Model**: Enterprise architecture tier, consulting services
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, D3.js / ReactFlow for canvas rendering, REST API backed by PostgreSQL, OpenAPI 3.1 spec

---

## MVP Definition

- Interactive system landscape canvas with pan, zoom, and drag-and-drop service nodes
- Automatic service dependency graph generation from Apiome schema relationships and API references
- Domain grouping with visual bounded context boundaries
- Data flow diagram view showing how data moves between services
- Impact analysis: select a service or schema and see upstream/downstream dependents highlighted
- Architecture Decision Record (ADR) CRUD with markdown body and metadata
- Pattern compliance checker that validates the current landscape against a chosen reference pattern
- Export landscape and dependency views as SVG/PNG

---

## Epic 1: System Landscape Canvas

### Summary Table

| #   | Title                              | Description                                                                              | Labels                              | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------------------|--------------------------------------|----------|
| 1.1 (#907) | Landscape Canvas Foundation        | Interactive infinite canvas with pan, zoom, minimap, and grid snapping                   | `enhancement`, `mvp`, `architect`    | Yes      |
| 1.2 (#908) | Service Node CRUD                  | Create, edit, delete, and style service nodes on the canvas                              | `enhancement`, `mvp`, `architect`    | Yes      |
| 1.3 (#909) | Domain Grouping & Bounded Contexts | Visual containers that group services into domains with color-coded boundaries           | `enhancement`, `mvp`, `architect`    | No       |
| 1.4 (#910) | Canvas Persistence & REST API      | Backend storage and retrieval of landscape state                                         | `enhancement`, `mvp`, `architect`, `rest` | No       |
| 1.5 (#911) | DDD Capability Mapping View        | Alternate lens that overlays business capabilities onto domain groups                    | `enhancement`, `architect`           | Yes      |
| 1.6 (#912) | Canvas Export & Sharing            | Export the current viewport as SVG/PNG and generate shareable read-only links             | `enhancement`, `architect`           | Yes      |

### Detailed Issue Descriptions

---

#### 1.1 (#907) — Landscape Canvas Foundation

The landscape canvas is the primary workspace for Architect. It must feel fluid and responsive even with hundreds of nodes, similar to tools like Excalidraw or Figma's infinite canvas.

The canvas renders on an HTML5 `<canvas>` element managed by ReactFlow (or a comparable library). It supports panning via middle-click drag or two-finger trackpad, zoom via scroll wheel with configurable min/max bounds, and an optional grid overlay with snap-to-grid. A minimap in the bottom-right corner (built with Radix UI `Popover` for collapse/expand) shows the full landscape at a glance and allows click-to-navigate.

Performance must stay smooth at 60 fps with up to 500 nodes and 2000 edges visible. Offscreen elements should be virtualized. The canvas background supports light and dark themes, toggled through a Radix UI `Switch` in the toolbar.

The NextJS page lives at `app/(dashboard)/architect/landscape/page.tsx`. The toolbar across the top uses Radix UI `Toolbar` with icon buttons for zoom-to-fit, toggle grid, toggle minimap, and undo/redo.

```
┌──────────────────────────────────────────────────────────┐
│  Toolbar: [Zoom Fit] [Grid] [Minimap] [Undo] [Redo]     │
├──────────────────────────────────────────────────────────┤
│                                                          │
│    ┌─────────┐          ┌─────────┐                      │
│    │ Service │──────────│ Service │                      │
│    │    A    │          │    B    │                      │
│    └─────────┘          └────┬────┘                      │
│                              │                           │
│                         ┌────▼────┐                      │
│                         │ Service │                      │
│                         │    C    │                      │
│                         └─────────┘                      │
│                                            ┌───────────┐ │
│                                            │  Minimap  │ │
│                                            └───────────┘ │
└──────────────────────────────────────────────────────────┘
```

**Acceptance Criteria**

- Canvas renders with pan (middle-click / trackpad) and scroll-wheel zoom
- Grid overlay toggles on/off with configurable spacing (16/32/64 px)
- Minimap renders a scaled-down view and supports click-to-navigate
- Undo/redo stack tracks node add, move, delete, and edge changes (minimum 50 steps)
- Maintains 60 fps with 500 nodes and 2000 edges in a stress test
- Light and dark theme support via Radix UI `Switch`

**Tech Stack Callouts**

- Radix UI: `Toolbar`, `Switch`, `Popover` (minimap container)
- NextJS: `app/(dashboard)/architect/landscape/page.tsx`
- ReactFlow or D3 for canvas rendering

Part of Epic: System Landscape Canvas

---

#### 1.2 (#908) — Service Node CRUD

Service nodes are the fundamental building blocks of the landscape. Each node represents a service, application, database, queue, or external system and carries metadata such as name, type, owner team, health status, and a link to its Apiome schema project.

Users add nodes via a Radix UI `Dialog` triggered from the toolbar or by right-clicking the canvas (Radix UI `ContextMenu`). The dialog collects required fields (name, type from a Radix UI `Select` dropdown) and optional fields (description, owner, schema project link). Editing an existing node opens the same dialog pre-filled. Deleting a node prompts a Radix UI `AlertDialog` confirming the action, since it may break edges.

Nodes are styled by type: rounded rectangles for services, cylinders for databases, hexagons for message queues, and cloud shapes for external systems. Each node displays an icon, name, and a small status badge (green/amber/red) that can be set manually or pulled from monitoring integrations in later phases.

Dragging a node updates its position in real time for all collaborators once real-time sync is added. For MVP the position is saved on explicit save or auto-save with debounce.

**Acceptance Criteria**

- Users can create a node via toolbar button or canvas right-click context menu
- Node creation dialog validates that name is non-empty and unique within the landscape
- Nodes render with type-appropriate shapes (service, database, queue, external)
- Users can edit node metadata by double-clicking or selecting "Edit" from context menu
- Delete prompts confirmation and removes connected edges
- Node positions persist across page reloads

**Tech Stack Callouts**

- Radix UI: `Dialog`, `ContextMenu`, `AlertDialog`, `Select`, `Label`, `TextField`
- REST: `POST /api/v1/architect/landscapes/{id}/nodes`, `PATCH /api/v1/architect/landscapes/{id}/nodes/{nodeId}`, `DELETE /api/v1/architect/landscapes/{id}/nodes/{nodeId}`
- OpenAPI 3.1: `LandscapeNode` schema with properties `id`, `name`, `type`, `position`, `metadata`

Part of Epic: System Landscape Canvas

---

#### 1.3 (#909) — Domain Grouping & Bounded Contexts

Domain groupings let architects visually cluster related services into bounded contexts. A domain group is a labeled, color-coded rectangle that sits behind its member nodes on the z-axis. Groups can be resized by dragging corners and can nest (a subdomain inside a domain).

When a user drags a node into a group boundary it is automatically added to that group. Dragging it out removes it. Groups carry metadata: name, description, owning team, and an optional link to the DDD ubiquitous language glossary (future feature).

The group creation flow uses a Radix UI `Dialog` with a color picker (Radix UI `Popover` wrapping a small palette). The group border uses a dashed stroke in the selected color with a semi-transparent fill.

This feature depends on 1.1 (canvas) and 1.2 (nodes) because groups are containers for existing nodes.

**Acceptance Criteria**

- Users can create a domain group with name, color, and optional description
- Groups render as labeled dashed rectangles behind member nodes
- Drag-and-drop a node into/out of a group updates membership automatically
- Groups support nesting (one level deep for MVP)
- Resizing a group via corner handles works without disrupting contained nodes
- Group metadata is editable and deletable

**Tech Stack Callouts**

- Radix UI: `Dialog`, `Popover` (color picker), `Tooltip` (group info on hover)
- REST: `POST /api/v1/architect/landscapes/{id}/groups`, `PATCH .../{groupId}`, `DELETE .../{groupId}`
- OpenAPI 3.1: `DomainGroup` schema with `id`, `name`, `color`, `bounds`, `memberNodeIds`

Part of Epic: System Landscape Canvas

---

#### 1.4 (#910) — Canvas Persistence & REST API

All landscape state — nodes, edges, groups, viewport position — must be persisted so users can close the browser and return to the same view. The backend exposes a REST API that stores landscapes as JSON documents in PostgreSQL (JSONB column for the graph payload, relational columns for metadata).

Each tenant can have multiple landscapes. The API supports listing landscapes, creating a new landscape, fetching a landscape with its full graph, and updating the graph payload. The frontend auto-saves after a debounce period (2 seconds of inactivity) by PATCHing the graph payload. A manual save button and a "last saved" timestamp are shown in the toolbar.

The API route handlers live under `app/api/v1/architect/landscapes/` in the NextJS app router. Authentication and tenant scoping follow the existing middleware patterns from the Apiome platform.

Optimistic concurrency control uses an `etag` header derived from a version counter to prevent lost updates when two users edit simultaneously (before real-time sync is available).

**Acceptance Criteria**

- `GET /api/v1/architect/landscapes` returns a paginated list of landscapes for the tenant
- `POST /api/v1/architect/landscapes` creates a new empty landscape
- `GET /api/v1/architect/landscapes/{id}` returns full graph payload
- `PATCH /api/v1/architect/landscapes/{id}` updates graph payload with ETag concurrency check
- Auto-save triggers after 2 seconds of inactivity and shows "Saving..." / "Saved" indicator
- 409 Conflict response when ETag mismatch occurs, with client-side merge prompt

**Tech Stack Callouts**

- NextJS: `app/api/v1/architect/landscapes/route.ts` (list, create), `app/api/v1/architect/landscapes/[id]/route.ts` (get, patch, delete)
- OpenAPI 3.1: `Landscape` schema with `id`, `tenantId`, `name`, `graphPayload` (JSONB), `version`, `createdAt`, `updatedAt`
- PostgreSQL: `architect_landscapes` table with JSONB `graph_payload` column

Part of Epic: System Landscape Canvas

---

#### 1.5 (#911) — DDD Capability Mapping View

Capability mapping provides an alternate lens on the same landscape data. Instead of showing service nodes with their technical details, this view organizes the canvas by business capabilities (e.g., "Customer Management," "Order Fulfillment," "Payment Processing") and maps services to the capabilities they support.

The view is toggled via a Radix UI `Tabs` component in the toolbar that switches between "Landscape" and "Capability Map." In capability mode, the canvas renders a treemap-style layout where each rectangle represents a capability, sized by the number of services mapped to it. Services appear as small chips inside their parent capability.

Capabilities are defined through a simple Radix UI `Dialog` form and linked to services via a many-to-many relationship. The capability hierarchy supports two levels (capability → sub-capability) for MVP.

**Acceptance Criteria**

- Toolbar tabs switch between Landscape view and Capability Map view without data loss
- Users can create, edit, and delete capabilities with name, description, and parent
- Services can be mapped to one or more capabilities via drag-and-drop or a link dialog
- Capability Map renders as a treemap where rectangle size reflects mapped service count
- Hovering a capability highlights its services on the Landscape view
- Capability data persists via the landscape REST API

**Tech Stack Callouts**

- Radix UI: `Tabs`, `Dialog`, `Badge` (service chips)
- REST: `POST /api/v1/architect/landscapes/{id}/capabilities`, `PATCH`, `DELETE`
- D3 treemap layout for capability visualization

Part of Epic: System Landscape Canvas

---

#### 1.6 (#912) — Canvas Export & Sharing

Architects need to share their landscape visualizations with stakeholders who may not have Apiome access. This issue covers exporting the current viewport (or the entire canvas) as high-resolution SVG or PNG, and generating time-limited shareable links that render a read-only view.

Export uses the browser's built-in SVG serialization for vector output, and `html2canvas` or a server-side renderer for raster PNG. A Radix UI `DropdownMenu` in the toolbar provides the export options: "Export as SVG," "Export as PNG," "Copy shareable link." Shareable links create a token-authenticated read-only page at `app/(public)/architect/shared/[token]/page.tsx` with a 7-day default expiry configurable by the user.

The share token is stored in a `landscape_shares` table with the landscape ID, token, expiry timestamp, and creator. The public page loads the graph payload and renders it on a non-editable canvas.

**Acceptance Criteria**

- "Export as SVG" downloads an SVG file containing all visible nodes, edges, and groups
- "Export as PNG" downloads a raster image at 2x resolution for print quality
- "Copy shareable link" generates a URL and copies it to the clipboard with a toast confirmation
- Shared links expire after the configured TTL (default 7 days)
- The public shared page renders a read-only canvas with pan and zoom but no editing
- Expired or invalid share links show a clear error page

**Tech Stack Callouts**

- Radix UI: `DropdownMenu`, `Toast`
- NextJS: `app/(public)/architect/shared/[token]/page.tsx`
- REST: `POST /api/v1/architect/landscapes/{id}/shares` (create share token)
- OpenAPI 3.1: `LandscapeShare` schema with `token`, `landscapeId`, `expiresAt`

Part of Epic: System Landscape Canvas

---

## Epic 2: Dependency Analysis & Impact Mapping

### Summary Table

| #   | Title                                | Description                                                                                  | Labels                                    | Parallel |
|-----|--------------------------------------|----------------------------------------------------------------------------------------------|-------------------------------------------|----------|
| 2.1 (#914) | Service Dependency Graph Generation  | Auto-generate directed dependency graphs from schema relationships and API references        | `enhancement`, `mvp`, `architect`, `rest` | Yes      |
| 2.2 (#915) | Data Flow Diagram View              | Overlay showing how data moves between services with volume and direction indicators         | `enhancement`, `mvp`, `architect`         | Yes      |
| 2.3 (#916) | Impact Analysis Engine              | Select a node and see highlighted upstream producers and downstream consumers                | `enhancement`, `mvp`, `architect`, `rest` | No       |
| 2.4 (#917) | Critical Path Identification        | Identify the longest dependency chains and single points of failure in the landscape          | `enhancement`, `architect`                | No       |
| 2.5 (#918) | Dependency Diff Between Versions    | Compare two landscape snapshots to see added/removed/changed dependencies                   | `enhancement`, `architect`                | Yes      |

### Detailed Issue Descriptions

---

#### 2.1 (#914) — Service Dependency Graph Generation

Manually drawing edges between services is tedious and error-prone. This feature auto-generates a dependency graph by analyzing Apiome schema `$ref` relationships, API endpoint consumer/provider declarations, and explicit dependency annotations.

The generation algorithm runs server-side. It scans all schema projects within the tenant, resolves cross-project `$ref` references, and extracts dependency edges. Each edge carries metadata: dependency type (data, API call, event, shared database), strength (required vs. optional), and the schema paths that establish the relationship.

On the frontend, auto-generated edges appear as dashed lines (to distinguish from manually drawn solid edges). Users can accept, reject, or override auto-generated edges. Accepted edges become solid. The generation can be re-run at any time, and it merges new findings with existing accepted edges without duplicating them.

A "Generate Dependencies" button in the toolbar triggers the analysis. Progress is shown via a Radix UI `Progress` bar since the scan may take several seconds for large tenants.

**Acceptance Criteria**

- Clicking "Generate Dependencies" triggers a server-side scan of all schema projects for the tenant
- Edges are created for each cross-project `$ref`, API consumer/provider relationship, and explicit annotation
- Auto-generated edges render as dashed lines; accepted edges render as solid
- Users can accept, reject, or override each auto-generated edge via a context menu
- Re-running generation merges new edges without duplicating existing accepted ones
- Progress feedback is displayed during the scan

**Tech Stack Callouts**

- REST: `POST /api/v1/architect/landscapes/{id}/generate-dependencies` (triggers async job), `GET /api/v1/architect/landscapes/{id}/dependencies` (list edges)
- OpenAPI 3.1: `DependencyEdge` schema with `sourceNodeId`, `targetNodeId`, `type`, `status`, `schemaPaths`
- Radix UI: `Progress`, `ContextMenu`

Part of Epic: Dependency Analysis & Impact Mapping

---

#### 2.2 (#915) — Data Flow Diagram View

While the dependency graph shows structural relationships, the data flow diagram view shows how data moves through the system at runtime. Edges are annotated with data type, estimated volume (requests/sec or records/day), and direction.

The view is activated via a Radix UI `Tabs` component alongside the Landscape and Capability Map views. In data flow mode, edges are rendered as animated dashed lines (particles moving along the path) with arrow heads showing direction. Edge thickness is proportional to volume. Hovering an edge shows a Radix UI `Tooltip` with the data type, volume, and latency if available.

Data flow metadata is initially entered manually per edge via a Radix UI `Dialog`. In future phases, this data could be populated automatically from API gateway metrics.

```
┌─────────────┐    orders (150 req/s)    ┌─────────────┐
│   Frontend  │ ──────────────────────── │  Order API  │
│   (React)   │                          │  (NextJS)   │
└─────────────┘                          └──────┬──────┘
                                                │
                                    inventory    │  payments
                                    check        │  (80 req/s)
                                    (150 req/s)  │
                                                │
                              ┌─────────────┐   │   ┌─────────────┐
                              │  Inventory  │◄──┘──►│  Payment    │
                              │   Service   │       │   Gateway   │
                              └──────┬──────┘       └─────────────┘
                                     │
                              stock updates
                              (500 events/min)
                                     │
                              ┌──────▼──────┐
                              │  Warehouse  │
                              │   System    │
                              └─────────────┘
```

**Acceptance Criteria**

- Data Flow tab appears in the toolbar tabs alongside Landscape and Capability Map
- Edges in data flow mode show animated directional particles and arrow heads
- Edge thickness scales proportionally to the configured volume
- Hovering an edge displays a tooltip with data type, volume, and optional latency
- Users can add/edit data flow metadata per edge via a dialog
- The view correctly handles bidirectional flows with two separate animated paths

**Tech Stack Callouts**

- Radix UI: `Tabs`, `Dialog`, `Tooltip`
- ReactFlow animated edges or custom D3 path animation
- REST: `PATCH /api/v1/architect/landscapes/{id}/edges/{edgeId}` (update flow metadata)

Part of Epic: Dependency Analysis & Impact Mapping

---

#### 2.3 (#916) — Impact Analysis Engine

Impact analysis is the highest-value feature for enterprise architects. When evaluating a change to a service or schema, architects need to answer: "What breaks if I change this?"

Selecting a node and clicking "Analyze Impact" (or pressing a keyboard shortcut) triggers a traversal of the dependency graph. The engine walks outward from the selected node in both directions: upstream (who feeds data into this service) and downstream (who consumes data from this service). Each impacted node is highlighted with a color-coded ring: red for direct dependents, amber for transitive dependents, and the selected node in blue.

A side panel (Radix UI `Sheet`) opens showing the impact report: a table of affected services, the dependency path, and the type of coupling (data, API, event). The report can be exported as JSON or CSV for change management workflows.

The traversal runs server-side via a recursive CTE query on the dependency edges table, with a configurable depth limit (default 5 hops) to prevent runaway traversals in highly connected graphs.

**Acceptance Criteria**

- Selecting a node and triggering "Analyze Impact" highlights all upstream and downstream dependents
- Direct dependents are highlighted red; transitive dependents are amber; the source node is blue
- A side panel displays the impact report with service names, paths, and coupling types
- Depth limit is configurable (1–10 hops) via a Radix UI `Slider` in the side panel
- The impact report is exportable as JSON and CSV
- The server-side traversal completes within 2 seconds for graphs with up to 1000 edges

**Tech Stack Callouts**

- Radix UI: `Sheet`, `Table`, `Slider`, `Badge` (coupling type labels)
- REST: `POST /api/v1/architect/landscapes/{id}/impact-analysis` with body `{ nodeId, maxDepth }`
- OpenAPI 3.1: `ImpactReport` schema with `sourceNode`, `impactedNodes[]` each having `nodeId`, `distance`, `path`, `couplingType`
- PostgreSQL: recursive CTE on `dependency_edges` table

Part of Epic: Dependency Analysis & Impact Mapping

---

#### 2.4 (#917) — Critical Path Identification

Large landscapes often contain hidden single points of failure — services that sit on every critical path. This feature identifies the longest dependency chains (critical paths) and flags services with high fan-in (many dependents) as risk hotspots.

The analysis produces two views: a "Critical Paths" list showing the top N longest chains (rendered as horizontal swimlanes), and a "Risk Heatmap" overlay on the landscape canvas where node color intensity reflects the number of services that transitively depend on it.

The critical path algorithm uses a topological sort with longest-path computation on the directed acyclic subgraph of dependencies. Cycles are detected and reported separately. Fan-in scores are simple in-degree counts on the dependency graph.

Results are displayed in a Radix UI `Sheet` side panel with Radix UI `Tabs` switching between "Critical Paths" and "Risk Heatmap." A toggle on the canvas activates the heatmap overlay.

**Acceptance Criteria**

- The analysis identifies the top 10 longest dependency chains in the landscape
- Critical paths are rendered as horizontal swimlanes in the side panel
- Risk heatmap overlay colors nodes by transitive dependent count (green → amber → red)
- Cycles in the dependency graph are detected and listed as warnings
- The heatmap overlay toggles on/off without affecting the underlying canvas
- Hovering a node in heatmap mode shows the fan-in count and top dependents

**Tech Stack Callouts**

- Radix UI: `Sheet`, `Tabs`, `Switch` (heatmap toggle), `Tooltip`
- REST: `GET /api/v1/architect/landscapes/{id}/critical-paths`
- OpenAPI 3.1: `CriticalPathReport` with `paths[]` and `riskScores[]`

Part of Epic: Dependency Analysis & Impact Mapping

---

#### 2.5 (#918) — Dependency Diff Between Versions

Landscapes evolve over time. Architects need to compare two snapshots of the landscape to understand what changed: which services were added or removed, which dependencies shifted, and whether the overall architecture is converging toward or diverging from the target state.

The backend stores landscape snapshots on every explicit save (not auto-save) with a version number and timestamp. The diff API accepts two version numbers and returns a structured diff: added nodes, removed nodes, added edges, removed edges, and changed edge metadata.

The frontend renders the diff on a split-pane canvas (Radix UI `ResizablePanelGroup` pattern via CSS) with the older version on the left and the newer version on the right. Added elements are highlighted green, removed elements red, and changed elements amber. A unified view option overlays both versions on a single canvas.

**Acceptance Criteria**

- Each explicit save creates a versioned snapshot accessible via the API
- Diff API returns structured added/removed/changed lists for nodes, edges, and groups
- Split-pane view renders old and new versions side by side with synchronized pan/zoom
- Added elements are green, removed are red, changed are amber
- A unified overlay view shows both versions on one canvas with color coding
- Version selector uses a Radix UI `Select` dropdown with timestamp labels

**Tech Stack Callouts**

- Radix UI: `Select` (version picker), `ToggleGroup` (split vs unified)
- REST: `GET /api/v1/architect/landscapes/{id}/versions`, `GET /api/v1/architect/landscapes/{id}/diff?from={v1}&to={v2}`
- OpenAPI 3.1: `LandscapeDiff` schema with `addedNodes[]`, `removedNodes[]`, `addedEdges[]`, `removedEdges[]`, `changedEdges[]`

Part of Epic: Dependency Analysis & Impact Mapping

---

## Epic 3: Pattern Library & Compliance

### Summary Table

| #   | Title                                | Description                                                                                   | Labels                               | Parallel |
|-----|--------------------------------------|-----------------------------------------------------------------------------------------------|---------------------------------------|----------|
| 3.1 (#920) | Architecture Pattern Catalog         | Curated library of reference patterns (microservices, event-driven, layered, etc.)            | `enhancement`, `mvp`, `architect`     | Yes      |
| 3.2 (#921) | Pattern Compliance Checker           | Validate a landscape against a selected reference pattern and report deviations                | `enhancement`, `mvp`, `architect`, `rest` | No       |
| 3.3 (#922) | Anti-Pattern Scanner                 | Detect known anti-patterns (circular deps, god services, chatty integrations)                 | `enhancement`, `architect`, `rest`    | No       |
| 3.4 (#923) | Custom Pattern Definition            | Allow organizations to define and share their own architecture patterns                       | `enhancement`, `architect`            | Yes      |
| 3.5 (#924) | Refactoring Recommendation Engine    | Suggest concrete refactoring steps to move from current state toward a target pattern         | `enhancement`, `architect`, `ai-generated` | No       |

### Detailed Issue Descriptions

---

#### 3.1 (#920) — Architecture Pattern Catalog

The pattern catalog is a browsable library of well-known enterprise architecture patterns. Each pattern includes a name, description, a reference diagram, a set of structural rules (e.g., "no direct database sharing between services"), and example use cases.

The catalog ships with 8–12 built-in patterns covering microservices, event-driven architecture, layered monolith, hexagonal architecture, CQRS, saga pattern, strangler fig, and BFF (Backend for Frontend). Each pattern is stored as a JSON document containing the reference graph structure and rule definitions.

The catalog page at `app/(dashboard)/architect/patterns/page.tsx` presents patterns as cards (Radix UI `Card`-style layout using a CSS grid). Clicking a card opens a detail page showing the reference diagram rendered on a read-only canvas, the rule set, and a "Check Compliance" button that navigates to the compliance checker (3.2) with the pattern pre-selected.

**Acceptance Criteria**

- Catalog page displays 8–12 built-in patterns as cards with name, icon, and short description
- Clicking a card opens a detail view with the full reference diagram, description, and rules
- Reference diagrams render on a read-only canvas with the same rendering engine as the landscape
- Each pattern's rule set is displayed as a structured list (rule name, description, severity)
- "Check Compliance" button navigates to the compliance checker with the pattern pre-selected
- Patterns are searchable and filterable by category (structural, behavioral, decomposition)

**Tech Stack Callouts**

- NextJS: `app/(dashboard)/architect/patterns/page.tsx`, `app/(dashboard)/architect/patterns/[patternId]/page.tsx`
- Radix UI: `TextField` (search), `Select` (category filter), `Separator`
- REST: `GET /api/v1/architect/patterns` (list), `GET /api/v1/architect/patterns/{id}` (detail)

Part of Epic: Pattern Library & Compliance

---

#### 3.2 (#921) — Pattern Compliance Checker

The compliance checker validates a user's landscape against a selected reference pattern and produces a detailed report of conformities and deviations. This is the core value proposition of the pattern library.

Compliance checking works by evaluating the landscape graph against the pattern's rule set. Rules are expressed as graph predicates: "no cycles in service dependencies," "every service has exactly one database," "all inter-service communication goes through a message broker," etc. Each rule evaluation produces a pass/fail result with an explanation and a reference to the specific nodes or edges involved.

The checker runs server-side. The user selects a pattern and a landscape, then triggers the check. Results are displayed in a Radix UI `Table` with columns for rule name, status (pass/warn/fail as Radix UI `Badge`), affected nodes, and recommendation. An overall compliance score (percentage of rules passed) is shown at the top.

Users can suppress individual rule violations with a justification (stored for audit). Suppressed violations appear grayed out and don't count against the compliance score.

**Acceptance Criteria**

- Users can select a pattern and landscape to check via dropdown selectors
- The checker evaluates all rules in the pattern against the landscape graph
- Results display in a table with rule name, pass/warn/fail status, affected nodes, and recommendation
- An overall compliance score (percentage) is shown prominently
- Users can suppress violations with a justification reason
- Suppressed violations are visually distinct and excluded from the score
- The check completes within 5 seconds for landscapes with up to 200 nodes

**Tech Stack Callouts**

- Radix UI: `Select` (pattern picker, landscape picker), `Table`, `Badge`, `Dialog` (suppression reason)
- REST: `POST /api/v1/architect/compliance-checks` with body `{ landscapeId, patternId }`, returns `ComplianceReport`
- OpenAPI 3.1: `ComplianceReport` schema with `score`, `results[]` each having `ruleId`, `status`, `affectedNodeIds`, `recommendation`
- NextJS: `app/(dashboard)/architect/compliance/page.tsx`

Part of Epic: Pattern Library & Compliance

---

#### 3.3 (#922) — Anti-Pattern Scanner

While the compliance checker validates against a positive reference, the anti-pattern scanner looks for known bad patterns regardless of any reference. This is a proactive health check for the architecture.

The scanner checks for: circular dependencies (A→B→C→A), god services (nodes with fan-in + fan-out exceeding a threshold), chatty integrations (many fine-grained edges between two services), shared databases (multiple services pointing to the same database node), distributed monolith indicators (all services tightly coupled despite being "separate"), and orphan services (nodes with zero edges).

The scan runs via the same REST pattern as compliance checks. Results are displayed in a dedicated panel with severity levels (critical, warning, info) and visual highlighting on the canvas — e.g., circular dependency cycles are traced with red animated edges.

Each anti-pattern result includes a description of why it's problematic, the specific nodes/edges involved, and a link to the refactoring recommendation engine (3.5) for suggested fixes.

**Acceptance Criteria**

- Scanner detects at least 6 anti-pattern types: circular deps, god services, chatty integrations, shared databases, distributed monolith indicators, orphan services
- Results are categorized by severity (critical, warning, info)
- Detected anti-patterns are highlighted on the canvas with color-coded overlays
- Each result includes a description, affected elements, and a "Get Recommendation" link
- Scanner runs within 3 seconds for landscapes with up to 200 nodes
- Results can be exported as a JSON report

**Tech Stack Callouts**

- REST: `POST /api/v1/architect/landscapes/{id}/anti-pattern-scan`
- OpenAPI 3.1: `AntiPatternReport` schema with `findings[]` each having `type`, `severity`, `affectedElements`, `description`
- Radix UI: `Accordion` (collapsible findings by severity), `Badge`, `ScrollArea`

Part of Epic: Pattern Library & Compliance

---

#### 3.4 (#923) — Custom Pattern Definition

Organizations have their own architecture standards that go beyond the built-in catalog. This feature allows enterprise architects to define custom patterns with custom rule sets, save them to the tenant's private catalog, and share them across teams.

The custom pattern editor provides a form-based UI for defining the pattern metadata (name, description, category) and a rule builder. The rule builder uses a Radix UI `Select`-based predicate system: users pick a subject (node type, edge type, group), an operator (has, does not have, count equals, count greater than), and a value. Complex rules can combine predicates with AND/OR logic.

The reference diagram for a custom pattern is drawn on the same landscape canvas in a special "pattern editing" mode where nodes represent archetypes rather than concrete services.

Custom patterns are stored per-tenant and can be marked as "recommended" by admins, which adds them to the compliance dashboard.

**Acceptance Criteria**

- Users can create a custom pattern with name, description, category, and reference diagram
- The rule builder supports predicate-based rules with AND/OR composition
- At least 5 predicate types are available (node type count, edge existence, cycle detection, fan-in threshold, group membership)
- Custom patterns appear in the tenant's pattern catalog alongside built-in patterns
- Admins can mark custom patterns as "recommended" for compliance tracking
- Custom patterns can be exported and imported as JSON

**Tech Stack Callouts**

- Radix UI: `Dialog`, `Select` (predicate builder), `TextField`, `Switch` (recommended toggle)
- REST: `POST /api/v1/architect/patterns` (create custom), `PATCH /api/v1/architect/patterns/{id}`, `DELETE /api/v1/architect/patterns/{id}`
- NextJS: `app/(dashboard)/architect/patterns/new/page.tsx`

Part of Epic: Pattern Library & Compliance

---

#### 3.5 (#924) — Refactoring Recommendation Engine

When the compliance checker or anti-pattern scanner finds issues, architects need actionable guidance on how to fix them. The refactoring recommendation engine analyzes the gap between the current landscape and the target pattern, then produces a prioritized list of refactoring steps.

Each recommendation includes: what to change (split a service, introduce a message broker, remove a direct dependency), why (which rule or anti-pattern it addresses), estimated effort (T-shirt sizing), risk level, and a before/after mini-diagram showing the local topology change.

The engine uses a rule-based approach for MVP: each anti-pattern type maps to a set of known refactoring strategies. In future phases, this could be augmented with AI-generated recommendations based on the self-hosted Ollama cluster.

Recommendations are presented in a side panel (Radix UI `Sheet`) ordered by impact (most compliance score improvement first). Users can accept a recommendation, which creates a "planned change" annotation on the landscape, or dismiss it with a reason.

**Acceptance Criteria**

- Each anti-pattern finding and compliance violation has at least one refactoring recommendation
- Recommendations include what, why, effort estimate, risk level, and a before/after topology diff
- Recommendations are ordered by potential compliance score improvement
- Users can accept a recommendation (creates a planned change annotation) or dismiss with reason
- Before/after mini-diagrams render inline in the side panel
- Accepted recommendations are tracked and visible in the landscape as planned changes

**Tech Stack Callouts**

- Radix UI: `Sheet`, `Badge` (effort/risk labels), `Button`, `Textarea` (dismiss reason)
- REST: `GET /api/v1/architect/landscapes/{id}/recommendations`, `POST /api/v1/architect/landscapes/{id}/recommendations/{recId}/accept`
- OpenAPI 3.1: `RefactoringRecommendation` schema

Part of Epic: Pattern Library & Compliance

---

## Epic 4: ADR Management & Capacity Planning

### Summary Table

| #   | Title                              | Description                                                                                | Labels                               | Parallel |
|-----|------------------------------------|--------------------------------------------------------------------------------------------|---------------------------------------|----------|
| 4.1 (#926) | ADR CRUD & Markdown Editor         | Create, edit, view, and archive Architecture Decision Records with rich markdown           | `enhancement`, `mvp`, `architect`     | Yes      |
| 4.2 (#927) | ADR Linking to Landscape Elements  | Associate ADRs with specific nodes, edges, or groups in the landscape                      | `enhancement`, `architect`            | No       |
| 4.3 (#928) | Decision History Timeline          | Chronological timeline view of all ADRs with status transitions                            | `enhancement`, `architect`            | Yes      |
| 4.4 (#929) | Architecture Principles Registry   | Define and enforce architecture principles that guide decision-making                       | `enhancement`, `architect`            | Yes      |
| 4.5 (#930) | Capacity Modeling Dashboard        | Service sizing, scalability analysis, bottleneck identification, and growth projections     | `enhancement`, `architect`, `rest`    | Yes      |

### Detailed Issue Descriptions

---

#### 4.1 (#926) — ADR CRUD & Markdown Editor

Architecture Decision Records (ADRs) capture the context, decision, and consequences of significant architecture choices. Apiome Architect provides first-class ADR management with a structured markdown editor.

Each ADR follows a standard template: Title, Status (Proposed → Accepted → Deprecated → Superseded), Context (why the decision is needed), Decision (what was decided), Consequences (positive, negative, and neutral outcomes), and optional Alternatives Considered. The editor uses a markdown textarea with live preview (split pane) and supports the standard ADR status lifecycle.

The ADR list page at `app/(dashboard)/architect/adrs/page.tsx` shows all ADRs in a Radix UI `Table` with columns for number, title, status, date, and author. Filtering by status and searching by title/content are supported. Creating a new ADR opens the editor page with the template pre-filled.

ADRs are numbered sequentially per tenant (ADR-0001, ADR-0002, etc.). The number is auto-assigned on creation and never reused.

**Acceptance Criteria**

- Users can create an ADR with the standard template (Title, Status, Context, Decision, Consequences)
- ADR numbers are auto-assigned sequentially and displayed prominently
- Status lifecycle follows Proposed → Accepted → Deprecated → Superseded with transition validation
- Markdown editor with live preview renders correctly
- ADR list page supports filtering by status and searching by title/content
- ADRs can be edited after creation; status changes are logged in an audit trail

**Tech Stack Callouts**

- Radix UI: `Table`, `Select` (status filter), `TextField` (search), `Badge` (status), `Tabs` (edit/preview)
- NextJS: `app/(dashboard)/architect/adrs/page.tsx` (list), `app/(dashboard)/architect/adrs/[adrId]/page.tsx` (detail/edit), `app/(dashboard)/architect/adrs/new/page.tsx` (create)
- REST: `GET /api/v1/architect/adrs`, `POST /api/v1/architect/adrs`, `PATCH /api/v1/architect/adrs/{id}`, `GET /api/v1/architect/adrs/{id}`
- OpenAPI 3.1: `ArchitectureDecisionRecord` schema with `id`, `number`, `title`, `status`, `context`, `decision`, `consequences`, `author`, `createdAt`, `updatedAt`

Part of Epic: ADR Management & Capacity Planning

---

#### 4.2 (#927) — ADR Linking to Landscape Elements

ADRs are most valuable when they're connected to the specific landscape elements they affect. This feature allows users to link ADRs to nodes, edges, or groups in the landscape, creating a bidirectional relationship between decisions and architecture.

On the landscape canvas, linked elements display a small document icon badge. Clicking the badge opens a Radix UI `Popover` listing the related ADRs with titles and statuses. From the ADR detail page, a "Linked Elements" section shows the associated landscape components with clickable links that navigate to and highlight them on the canvas.

Linking is done via a Radix UI `Dialog` that presents a searchable list of landscape elements. Multiple elements can be linked to a single ADR. When an ADR is superseded, its linked elements automatically inherit the link to the superseding ADR.

**Acceptance Criteria**

- Users can link an ADR to one or more landscape elements (nodes, edges, groups) via a dialog
- Linked elements show a document icon badge on the canvas
- Clicking the badge opens a popover listing related ADRs
- ADR detail page shows a "Linked Elements" section with navigation links to the canvas
- Superseded ADRs transfer their links to the superseding ADR
- Removing a link from either side (canvas or ADR) updates both views

**Tech Stack Callouts**

- Radix UI: `Dialog` (linker), `Popover` (badge click), `Badge` (document icon)
- REST: `POST /api/v1/architect/adrs/{id}/links`, `DELETE /api/v1/architect/adrs/{id}/links/{elementId}`
- OpenAPI 3.1: `AdrLink` schema with `adrId`, `elementType`, `elementId`

Part of Epic: ADR Management & Capacity Planning

---

#### 4.3 (#928) — Decision History Timeline

The decision timeline provides a chronological view of all ADRs across the project, making it easy to understand the sequence of architecture decisions and how they relate to each other.

The timeline renders vertically with each ADR as a card on alternating left/right sides. Cards show the ADR number, title, status badge, date, and author avatar. Status transitions are shown as smaller events between cards (e.g., "ADR-0005 status changed from Proposed to Accepted"). Supersession relationships are drawn as connector lines between cards.

The timeline page lives at `app/(dashboard)/architect/adrs/timeline/page.tsx`. A date range filter (Radix UI date picker pattern) lets users focus on a specific period. The timeline supports infinite scroll for long histories.

The timeline also integrates with landscape version snapshots when available, showing which landscape changes coincided with which decisions.

**Acceptance Criteria**

- Timeline renders ADRs chronologically with alternating left/right card layout
- Each card displays ADR number, title, status badge, date, and author
- Status transition events appear as smaller inline entries
- Supersession relationships are drawn as connector lines between cards
- Date range filtering narrows the visible timeline
- Infinite scroll loads older entries on demand

**Tech Stack Callouts**

- Radix UI: `Badge` (status), `Avatar` (author), `ScrollArea`, `Popover` (date picker)
- NextJS: `app/(dashboard)/architect/adrs/timeline/page.tsx`
- REST: `GET /api/v1/architect/adrs?view=timeline&from={date}&to={date}`

Part of Epic: ADR Management & Capacity Planning

---

#### 4.4 (#929) — Architecture Principles Registry

Architecture principles are the guardrails that guide ADR creation. They express organizational values like "prefer event-driven over synchronous integration" or "every service must own its data." The principles registry lets architects define, categorize, and enforce these principles.

Each principle has a name, description, rationale, implications, and a priority level (must, should, may per RFC 2119). Principles can be linked to pattern compliance rules (Epic 3) so that compliance checks automatically reference the underlying principle.

The registry page displays principles in a categorized list (Radix UI `Accordion` for categories). When creating an ADR, the editor presents a checklist of applicable principles so the author can confirm the decision aligns with organizational guidance.

Admins can create, edit, and archive principles. Archived principles remain visible in historical ADRs but don't appear in new ADR checklists.

**Acceptance Criteria**

- Admins can create principles with name, description, rationale, implications, and priority (must/should/may)
- Principles are categorized and displayed in collapsible accordion sections
- ADR creation form shows a checklist of applicable principles for the author to review
- Principles can be linked to compliance rules from the Pattern Library
- Archived principles are hidden from new ADR checklists but visible in historical ADRs
- Principles are searchable by name and category

**Tech Stack Callouts**

- Radix UI: `Accordion`, `Checkbox` (ADR checklist), `Select` (priority), `Badge`
- REST: `GET /api/v1/architect/principles`, `POST /api/v1/architect/principles`, `PATCH /api/v1/architect/principles/{id}`
- NextJS: `app/(dashboard)/architect/principles/page.tsx`

Part of Epic: ADR Management & Capacity Planning

---

#### 4.5 (#930) — Capacity Modeling Dashboard

The capacity modeling dashboard helps architects reason about service sizing, scalability limits, and growth projections. It combines landscape topology data with manually entered or imported capacity metrics.

The dashboard presents each service node as a row in a capacity table with columns for current load, max capacity, utilization percentage (rendered as a Radix UI `Progress` bar), scaling strategy (horizontal/vertical/none), and growth projection. Growth projections are calculated from a linear or exponential model fitted to historical data points entered by the user.

A bottleneck view highlights services where projected load will exceed capacity within a configurable horizon (30/60/90 days). These services are also highlighted on the landscape canvas with a warning icon.

The dashboard page at `app/(dashboard)/architect/capacity/page.tsx` includes a chart area showing utilization trends over time (line chart) for selected services. Users can add data points manually or import CSV files with historical metrics.

**Acceptance Criteria**

- Dashboard displays a capacity table with one row per service node
- Utilization percentage renders as a color-coded progress bar (green < 60%, amber < 85%, red ≥ 85%)
- Users can enter capacity data points manually or import via CSV
- Growth projection uses linear regression on historical data points
- Bottleneck view highlights services projected to exceed capacity within the selected horizon
- Bottleneck services are also highlighted on the landscape canvas with a warning icon

**Tech Stack Callouts**

- Radix UI: `Table`, `Progress`, `Select` (horizon picker), `Dialog` (data entry), `Tooltip`
- NextJS: `app/(dashboard)/architect/capacity/page.tsx`
- REST: `GET /api/v1/architect/landscapes/{id}/capacity`, `POST /api/v1/architect/landscapes/{id}/capacity/{nodeId}/data-points`
- OpenAPI 3.1: `CapacityMetric` schema with `nodeId`, `currentLoad`, `maxCapacity`, `scalingStrategy`, `dataPoints[]`

Part of Epic: ADR Management & Capacity Planning

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 — System Landscape Canvas**
- **1.1** (Canvas Foundation) and **1.2** (Service Node CRUD) can start in parallel since nodes can be developed against a mock canvas API while the canvas is being built — integration comes at the end.
- **1.5** (DDD Capability Mapping) and **1.6** (Canvas Export & Sharing) are independent of each other and can run in parallel once 1.1 is complete.
- **1.3** (Domain Grouping) requires 1.1 and 1.2. **1.4** (Persistence API) requires 1.1 and 1.2.

**Epic 2 — Dependency Analysis & Impact Mapping**
- **2.1** (Dependency Graph Generation) and **2.2** (Data Flow Diagram View) are independent and can be built in parallel.
- **2.3** (Impact Analysis) requires 2.1. **2.4** (Critical Path) requires 2.1 and 2.3.
- **2.5** (Dependency Diff) can be built in parallel with 2.3/2.4 since it only depends on 1.4 (persistence with versioning).

**Epic 3 — Pattern Library & Compliance**
- **3.1** (Pattern Catalog) and **3.4** (Custom Pattern Definition) can be built in parallel since custom patterns extend the same storage.
- **3.2** (Compliance Checker) requires 3.1. **3.3** (Anti-Pattern Scanner) requires 2.1 (dependency graph) but not 3.1/3.2.
- **3.5** (Refactoring Engine) requires 3.2 and 3.3.

**Epic 4 — ADR Management & Capacity Planning**
- **4.1** (ADR CRUD), **4.3** (Decision Timeline), **4.4** (Principles Registry), and **4.5** (Capacity Dashboard) are all independent and can be worked in parallel.
- **4.2** (ADR Linking) requires 4.1 and Epic 1 canvas features.

**Cross-Epic Parallelism**
- All of Epic 4 can be developed in parallel with Epics 1–3 since ADRs and capacity modeling are independent features that connect to the landscape via linking (4.2) which comes last.
- Epic 2 depends on Epic 1 for the canvas rendering layer but the backend analysis engines (2.1, 2.3) can be developed and tested independently with mock graph data.
- Epic 3 can start as soon as 2.1 is available for the anti-pattern scanner, but the pattern catalog (3.1) has no dependency on Epics 1 or 2.
