# Objectified: Canvas & Visual Editor Enhancements - Feature Roadmap

> Advanced canvas and visual editor enhancements that add reusable group templates, layout snapshot management, and granular node visibility controls—enabling teams to organize complex schemas visually and navigate large models efficiently.
>
> **Revenue Model**: Core platform feature, available in all tiers
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, PostgreSQL, ReactFlow for canvas rendering
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Pre-defined group templates for common schema patterns (REST Resource, Authentication, E-commerce, Audit)
- Group template CRUD API with tenant scoping and versioning
- Save custom canvas groups as reusable templates
- Layout snapshot capture with thumbnail preview generation
- Compare two layout snapshots side-by-side with visual diff
- Auto-snapshots before destructive canvas operations
- Node-level visibility toggles with hide/show individual nodes
- Criteria-based node filtering (empty classes, no relationships, deprecated, by group)

---

## Epic 1: Group Templates & Layout Snapshots

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                              | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|------------------------------------------------------|----------|
| 1.1 (#1330) | Group Template Data Model & API    | Core template entity with PostgreSQL schema and REST CRUD endpoints          | `enhancement`, `mvp`, `canvas`, `rest`, `ai-generated` | Yes      |
| 1.2 (#1352) | Pre-defined Template Library       | Built-in templates for REST Resource, Auth, E-commerce, and Audit groups     | `enhancement`, `mvp`, `canvas`, `ai-generated`         | Yes      |
| 1.3 (#1363) | Custom Group Template Authoring    | Save current canvas groups as reusable templates and share across tenants    | `enhancement`, `canvas`, `rest`, `ai-generated`        | No       |
| 1.4 (#1377) | Layout Snapshot Capture & Preview  | Take snapshots of current layout with thumbnail previews and side-by-side comparison | `enhancement`, `mvp`, `canvas`, `rest`, `ai-generated` | Yes      |
| 1.5 (#1388) | Auto-Snapshots & Snapshot Metadata | Automatic snapshots before destructive changes with rich metadata            | `enhancement`, `canvas`, `ai-generated`                | No       |

### Detailed Issue Descriptions

---

#### 1.1 (#1330) — Group Template Data Model & API

Group templates are the foundation for reusable canvas patterns. A template captures a group's structure—its name, constituent class nodes, their relative positions within the group, inter-node relationships, and default styling (color, icon, collapse state). Templates are version-tracked so updates to a shipped template do not break projects that pinned an earlier version.

The PostgreSQL schema includes a `group_templates` table with columns for `id`, `tenant_id` (nullable for system templates), `name`, `description`, `category`, `version`, `structure` (JSONB containing node definitions, relative positions, and relationship stubs), `thumbnail_url`, `is_system` (boolean distinguishing built-in from custom), `created_by`, `created_at`, and `updated_at`. A `group_template_versions` table tracks revisions so teams can upgrade or roll back.

REST endpoints follow standard CRUD patterns: `POST /api/v1/canvas/group-templates` (create), `GET /api/v1/canvas/group-templates` (list with filters for category, tenant, and system/custom), `GET /api/v1/canvas/group-templates/{id}` (detail with full structure), `PUT /api/v1/canvas/group-templates/{id}` (update custom template), and `DELETE /api/v1/canvas/group-templates/{id}` (soft-delete custom template). System templates are immutable via the API—only the platform can update them through migrations.

```
┌────────────────────────────────────────────────────────┐
│                  group_templates                       │
├────────────────────────────────────────────────────────┤
│  id              UUID PRIMARY KEY                      │
│  tenant_id       UUID REFERENCES tenants(id) NULLABLE  │
│  name            VARCHAR(255) NOT NULL                 │
│  description     TEXT                                  │
│  category        VARCHAR(100) NOT NULL                 │
│  version         INTEGER DEFAULT 1                     │
│  structure       JSONB NOT NULL                        │
│  thumbnail_url   TEXT                                  │
│  is_system       BOOLEAN DEFAULT FALSE                 │
│  created_by      UUID REFERENCES users(id)             │
│  created_at      TIMESTAMPTZ DEFAULT NOW()             │
│  updated_at      TIMESTAMPTZ DEFAULT NOW()             │
├────────────────────────────────────────────────────────┤
│  UNIQUE (tenant_id, name, version)                     │
└────────────────────────────────────────────────────────┘
         │
         │ 1:N
         ▼
┌────────────────────────────────────────────────────────┐
│            group_template_versions                     │
├────────────────────────────────────────────────────────┤
│  id              UUID PRIMARY KEY                      │
│  template_id     UUID REFERENCES group_templates(id)   │
│  version         INTEGER NOT NULL                      │
│  structure       JSONB NOT NULL                        │
│  changelog       TEXT                                  │
│  created_at      TIMESTAMPTZ DEFAULT NOW()             │
└────────────────────────────────────────────────────────┘
```

The `structure` JSONB captures node definitions as an array of objects, each containing `classNamePlaceholder` (e.g., `"{{Resource}}"` for the REST template), `relativePosition` (x/y offset from the group origin), and `relationships` (an array of intra-group edges with source/target placeholders). When a template is instantiated, placeholder names are resolved against the user's actual class names.

**Acceptance Criteria**

- Group template CRUD endpoints are available and conform to OpenAPI 3.1 spec
- System templates are read-only through the REST API; custom templates support full CRUD
- Templates are scoped by tenant; listing returns system templates plus the current tenant's custom templates
- Template versioning tracks structure changes with changelog entries
- The `structure` JSONB validates against a defined JSON Schema on create and update
- Soft-deleted templates are excluded from listings but recoverable by admins
- List endpoint supports cursor pagination with filters for category, tenant, and is_system

**Part of Epic: Group Templates & Layout Snapshots**

---

#### 1.2 (#1352) — Pre-defined Template Library

The pre-defined template library ships four built-in group templates covering the most common schema patterns. These templates dramatically reduce setup time for new projects by providing battle-tested node arrangements that teams can instantiate with a single click and customize to their domain.

The four system templates are: (1) **REST Resource Group** containing Create, Read, Update, Delete, and List class nodes arranged in a horizontal flow with CRUD relationship edges; (2) **Authentication Group** containing User, Token, Session, and Role nodes in a hub-and-spoke layout with the User node at center; (3) **E-commerce Group** containing Product, Cart, Order, and Payment nodes in a linear pipeline layout reflecting the purchase flow; (4) **Audit Group** containing Event, Log, and History nodes in a vertical stack with temporal relationship edges.

```
┌──────────────────────────────────────────────────────────────────┐
│  Template Gallery                          [Search...] [Filter ▾]│
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  System Templates                                                │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   ┌─┐ ┌─┐   │  │     ┌─┐      │  │  ┌─┐→┌─┐    │           │
│  │   │C│→│R│   │  │   ┌─┤U├─┐   │  │  │P│ │C│    │           │
│  │   └─┘ └─┘   │  │   │ └─┘ │   │  │  └─┘ └─┘    │           │
│  │   ┌─┐ ┌─┐   │  │  ┌┴┐   ┌┴┐  │  │   ↓    ↓     │           │
│  │   │U│→│D│   │  │  │T│   │S│  │  │  ┌─┐  ┌─┐    │           │
│  │   └─┘ └─┘   │  │  └─┘   └─┘  │  │  │O│→ │$│    │           │
│  │              │  │     ┌─┐     │  │  └─┘  └─┘    │           │
│  │ REST Resource│  │     │R│     │  │               │           │
│  │  4 nodes     │  │     └─┘     │  │ E-commerce    │           │
│  │              │  │ Auth  4nodes│  │  4 nodes      │           │
│  │  [Use ▸]     │  │  [Use ▸]    │  │  [Use ▸]      │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│                                                                  │
│  ┌──────────────┐                                                │
│  │  ┌─┐         │  Custom Templates                              │
│  │  │E│         │                                                │
│  │  └┬┘         │  No custom templates yet.                      │
│  │  ┌┴┐         │  Save a group from the canvas to create one.   │
│  │  │L│         │                                                │
│  │  └┬┘         │                                                │
│  │  ┌┴┐         │                                                │
│  │  │H│         │                                                │
│  │  └─┘         │                                                │
│  │ Audit 3nodes │                                                │
│  │  [Use ▸]     │                                                │
│  └──────────────┘                                                │
└──────────────────────────────────────────────────────────────────┘
```

The template gallery lives at `/app/canvas/templates` as a NextJS page. It renders templates as cards using a CSS grid layout with Radix `Tabs` separating system and custom templates. Each card shows a thumbnail preview of the group layout, the template name, node count, and a description. Clicking "Use" opens a Radix `Dialog` where the user maps placeholder class names to their actual schema classes before inserting the group onto the canvas.

Template instantiation calls `POST /api/v1/canvas/group-templates/{id}/instantiate` with a body containing `classNameMappings` (placeholder → actual class name), `canvasPosition` (where to place the group), and `projectId`. The endpoint creates the group and its nodes on the canvas, returning the new group ID and node IDs for the frontend to render via ReactFlow.

**Acceptance Criteria**

- Four system templates are seeded on first deployment: REST Resource, Authentication, E-commerce, Audit
- Template gallery renders all templates as cards with thumbnail previews and metadata
- "Use" action opens a mapping dialog for resolving placeholder class names to real schema classes
- Instantiation creates the group and all constituent nodes at the specified canvas position
- Template thumbnails are auto-generated SVG snapshots of the node layout
- Gallery supports search by template name and filtering by category via Radix `Tabs` and `Select`

**Part of Epic: Group Templates & Layout Snapshots**

---

#### 1.3 (#1363) — Custom Group Template Authoring

Beyond the system-provided templates, teams need to save their own canvas groups as reusable templates. This issue delivers the authoring workflow: selecting an existing group on the canvas, abstracting its class-specific details into placeholders, and saving it as a template available to the current tenant or shared across tenants.

When a user right-clicks a group on the canvas, the context menu includes a "Save as Template" action. This opens a Radix `Dialog` with fields for template name, description, category (Radix `Select` with options like "Domain Model", "Microservice", "Data Pipeline", "Custom"), and a sharing scope (Radix `RadioGroup` with "This project only", "This organization", or "All tenants" for platform admins). The dialog previews the abstracted structure, showing which class names will become placeholders.

The abstraction engine analyzes the selected group's nodes and replaces concrete class names with sequential placeholders (`{{Node1}}`, `{{Node2}}`, etc.) while preserving relative positions and intra-group relationships. Users can rename placeholders to semantically meaningful labels (e.g., `{{Entity}}`, `{{Controller}}`) before saving. The engine also strips instance-specific data like field values and UUIDs, keeping only the structural skeleton.

Sharing across tenants is restricted to platform administrators. Organization-scoped templates are visible to all users within the tenant. Project-scoped templates are private to the project. The REST endpoint `POST /api/v1/canvas/group-templates` accepts a `scope` field (`project`, `organization`, `platform`) and validates permissions accordingly.

**Acceptance Criteria**

- Right-click context menu on a canvas group includes "Save as Template"
- Abstraction engine replaces concrete class names with editable placeholders
- Template metadata captures name, description, category, and sharing scope
- Project-scoped templates are visible only within the originating project
- Organization-scoped templates are visible to all users in the tenant
- Platform-scoped templates require admin privileges and appear as system templates
- Saved templates appear immediately in the template gallery (1.2) without page refresh

**Part of Epic: Group Templates & Layout Snapshots**

---

#### 1.4 (#1377) — Layout Snapshot Capture & Preview

Layout snapshots preserve the current state of the canvas—node positions, group memberships, zoom level, viewport offset, and visibility states—as a named checkpoint that teams can compare against later versions. This issue delivers snapshot capture, thumbnail preview generation, and side-by-side comparison.

Capturing a snapshot is triggered from a toolbar button or keyboard shortcut (`Ctrl+Shift+S`). The capture process serializes the current ReactFlow state (nodes, edges, viewport) along with group membership and visibility metadata into a `layout_snapshots` PostgreSQL table. A server-side thumbnail renderer generates a PNG preview of the canvas layout at the time of capture, stored in object storage and referenced by URL.

The snapshot panel is a slide-out drawer (Radix `Sheet`) accessible from the canvas toolbar. It displays snapshots as a vertical timeline of thumbnail cards, each showing the snapshot name, timestamp, author, and description. Clicking a snapshot card opens a detail view. The comparison mode renders two snapshots side-by-side in split panes, highlighting nodes that moved, groups that changed, and nodes that were added or removed since the earlier snapshot.

```
┌─ Canvas ──────────────────┐  ┌─ Snapshot Panel ──────────────┐
│                            │  │                                │
│   ┌───┐    ┌───┐          │  │  ⊕ Take Snapshot               │
│   │ A ├───▶│ B │          │  │                                │
│   └───┘    └─┬─┘          │  │  ┌──────────────────────────┐  │
│              │             │  │  │ ░░░░░░░░░░░░ thumbnail   │  │
│           ┌──┴──┐         │  │  │ "Before refactor"         │  │
│           │  C  │         │  │  │ Apr 2 · kenji · 3 groups  │  │
│           └─────┘         │  │  │            [Compare] [⋯]  │  │
│                            │  │  └──────────────────────────┘  │
│                            │  │  ┌──────────────────────────┐  │
│                            │  │  │ ░░░░░░░░░░░░ thumbnail   │  │
│                            │  │  │ "Initial layout"          │  │
│                            │  │  │ Apr 1 · kenji · 2 groups  │  │
│                            │  │  │            [Compare] [⋯]  │  │
│                            │  │  └──────────────────────────┘  │
└────────────────────────────┘  └────────────────────────────────┘
```

REST endpoints include `POST /api/v1/canvas/projects/{projectId}/snapshots` (capture), `GET /api/v1/canvas/projects/{projectId}/snapshots` (list with pagination), `GET /api/v1/canvas/projects/{projectId}/snapshots/{id}` (detail with full layout data), and `GET /api/v1/canvas/projects/{projectId}/snapshots/compare?a={id}&b={id}` (diff between two snapshots). The compare endpoint returns a structured diff with arrays of `added`, `removed`, `moved`, and `modified` nodes.

**Acceptance Criteria**

- Snapshot capture serializes the full ReactFlow state including nodes, edges, groups, and viewport
- Thumbnail previews are generated server-side and displayed in the snapshot panel
- Snapshot panel renders as a slide-out Radix `Sheet` with a timeline of snapshot cards
- Side-by-side comparison highlights added, removed, and moved nodes with color coding
- Compare endpoint returns a structured diff with categorized node changes
- Snapshots support naming and description fields editable after creation
- Snapshot list supports cursor pagination sorted by creation date descending

**Part of Epic: Group Templates & Layout Snapshots**

---

#### 1.5 (#1388) — Auto-Snapshots & Snapshot Metadata

Manual snapshots are useful for intentional checkpoints, but destructive canvas operations can catch users off guard. This issue adds automatic snapshot creation before operations that significantly alter the canvas layout, and enriches all snapshots with queryable metadata.

Auto-snapshots trigger before the following operations: bulk node deletion (3+ nodes), group dissolution, template instantiation (which may rearrange existing nodes), and layout algorithm execution (auto-layout). The auto-snapshot is created transparently and labeled with a system-generated name describing the trigger (e.g., "Before bulk delete of 5 nodes"). Auto-snapshots are visually distinguished in the snapshot panel with a clock icon and a lighter background. Users can configure auto-snapshot behavior via a settings panel at `/app/canvas/settings` using Radix `Switch` toggles for each trigger type.

Snapshot metadata extends beyond name and timestamp to include: author (user who triggered or was active), node count at capture time, group count, a tag list (user-defined strings for categorization), and a free-text description. Metadata is indexed for search—the snapshot panel's search bar queries across name, description, and tags. Metadata is editable after capture via `PATCH /api/v1/canvas/projects/{projectId}/snapshots/{id}` updating only the mutable fields (name, description, tags).

Auto-snapshot retention follows a rolling window policy: the system retains the last 50 auto-snapshots per project and prunes older ones automatically. Manual snapshots are never pruned. The retention policy is configurable per project via `PUT /api/v1/canvas/projects/{projectId}/snapshot-settings` with fields for `autoSnapshotEnabled`, `retentionCount`, and trigger toggles.

**Acceptance Criteria**

- Auto-snapshots are created before bulk deletion, group dissolution, template instantiation, and auto-layout
- Auto-snapshots are labeled with the triggering operation and visually distinguished in the panel
- Each trigger type is independently toggleable via canvas settings
- Snapshot metadata includes author, node count, group count, tags, and description
- Snapshot panel search queries across name, description, and tag fields
- Rolling retention prunes auto-snapshots beyond the configured limit (default 50)
- Manual snapshots are exempt from automatic pruning

**Part of Epic: Group Templates & Layout Snapshots**

---

## Epic 2: Node Visibility & Canvas Navigation

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                              | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|------------------------------------------------------|----------|
| 2.1 (#1411) | Node Visibility Toggle Engine      | Hide/show individual nodes and isolate selected nodes on the canvas          | `enhancement`, `mvp`, `canvas`, `rest`, `ai-generated` | Yes      |
| 2.2 (#1426) | Criteria-Based Node Filtering      | Bulk hide nodes matching criteria: empty classes, no relationships, deprecated | `enhancement`, `mvp`, `canvas`, `ai-generated`         | Yes      |
| 2.3 (#1439) | Ghost Mode                         | Render hidden nodes as semi-transparent overlays for spatial context         | `enhancement`, `canvas`, `ai-generated`                | Yes      |
| 2.4 (#1453) | Visibility History & Presets       | Track visibility changes over time and save named visibility configurations  | `enhancement`, `canvas`, `rest`, `ai-generated`        | No       |
| 2.5 (#1463) | Quick Restore & Bulk Controls      | One-click restore of hidden nodes with bulk visibility management toolbar    | `enhancement`, `canvas`, `ai-generated`                | Yes      |

### Detailed Issue Descriptions

---

#### 2.1 (#1411) — Node Visibility Toggle Engine

Large schema canvases with hundreds of nodes become visually overwhelming. The visibility toggle engine lets users hide individual nodes to focus on the subset they are actively working with. Hidden nodes are removed from the ReactFlow render tree but preserved in the layout data, so showing them again restores their exact position.

Visibility state is stored per-node as a `visible` boolean in the canvas layout data. When a node is hidden, its connected edges are also hidden, but the relationship data is preserved. The toggle is accessible via the node's context menu ("Hide Node") and via a multi-select action ("Hide Selected"). An inverse operation, "Show Only Selected," hides all nodes except the currently selected set—useful for isolating a specific workflow or domain area.

```
  Before                          After "Show Only Selected" (A, B)

  ┌───┐    ┌───┐    ┌───┐        ┌───┐    ┌───┐
  │ A ├───▶│ B ├───▶│ C │        │ A ├───▶│ B │
  └───┘    └─┬─┘    └───┘        └───┘    └───┘
             │
          ┌──┴──┐   ┌───┐
          │  D  ├──▶│ E │           C, D, E hidden
          └─────┘   └───┘           (positions preserved)
```

The visibility engine is implemented as a ReactFlow node filter that runs before rendering. The filter reads the visibility state from the layout store and excludes hidden nodes and their edges from the render pass. This is more performant than setting CSS opacity, as hidden nodes are entirely removed from the DOM, reducing ReactFlow's render cost on large canvases.

REST endpoints include `PATCH /api/v1/canvas/projects/{projectId}/nodes/{nodeId}/visibility` (toggle single node), `POST /api/v1/canvas/projects/{projectId}/visibility/batch` (batch update with an array of `{nodeId, visible}` pairs), and `GET /api/v1/canvas/projects/{projectId}/visibility` (current visibility map). The batch endpoint is critical for "Show Only Selected" which may toggle hundreds of nodes at once.

**Acceptance Criteria**

- Individual nodes can be hidden via context menu and shown again from a hidden-nodes list
- "Hide Selected" hides all currently selected nodes in a single action
- "Show Only Selected" hides all nodes except the current selection
- Hidden nodes retain their position data; showing them restores exact placement
- Connected edges are hidden when both endpoints are hidden; partially connected edges remain visible
- Batch visibility updates complete within 200ms for canvases with up to 500 nodes
- Visibility state persists across page reloads via the layout save mechanism

**Part of Epic: Node Visibility & Canvas Navigation**

---

#### 2.2 (#1426) — Criteria-Based Node Filtering

Toggling individual nodes is useful for small adjustments, but large canvases need bulk filtering based on structural criteria. This issue adds filter-by-criteria controls that hide all nodes matching a selected condition, allowing teams to suppress noise and focus on structurally significant parts of the schema.

The filter toolbar sits above the canvas and provides filter chips for common criteria: **Empty Classes** (classes with zero fields defined), **Unconnected Nodes** (nodes with no relationship edges), **Deprecated** (classes marked with a deprecated flag in the schema), and **By Group** (hide or show all nodes in a specific group). Filters are combinable—activating "Empty Classes" and "Deprecated" simultaneously hides nodes matching either condition. A counter badge on each chip shows how many nodes match.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Filters: [Empty (3)] [Unconnected (7)] [Deprecated (2)] [Group ▾] │
│           Active: 2 filters · 10 nodes hidden                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                          Canvas Area                                │
│        (only nodes passing all active filters are visible)          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

The filter engine evaluates criteria against the schema metadata and canvas layout state. "Empty Classes" queries the schema capture for classes where `properties` is empty or absent. "Unconnected Nodes" counts edges per node in the ReactFlow edge list. "Deprecated" checks the `x-deprecated` or `deprecated` flag on the schema class. "By Group" reads group membership from the canvas layout. Filter results are computed client-side for instant feedback, with the schema metadata preloaded during canvas initialization.

The filter toolbar uses Radix `ToggleGroup` for the criteria chips and Radix `Popover` for the group filter (which renders a checklist of all groups). Filter state is stored in the URL query string so that sharing a canvas link preserves the active filters. A "Clear All Filters" button resets to the default fully-visible state.

**Acceptance Criteria**

- Filter chips for Empty, Unconnected, Deprecated, and By Group are available in the canvas toolbar
- Each chip displays a badge count of matching nodes before activation
- Activating a filter immediately hides matching nodes without a loading state
- Multiple filters combine with OR logic—nodes matching any active filter are hidden
- Group filter renders a Radix `Popover` with a checklist of all canvas groups
- Active filter state is encoded in the URL query string for shareable links
- "Clear All Filters" restores all nodes to visible in a single action

**Part of Epic: Node Visibility & Canvas Navigation**

---

#### 2.3 (#1439) — Ghost Mode

Hiding nodes entirely removes spatial context—users lose their sense of where hidden nodes sit relative to visible ones. Ghost Mode addresses this by rendering hidden nodes as semi-transparent overlays (10–20% opacity) that show position and shape but are clearly non-interactive. Ghosts provide a spatial map of the full schema while keeping the focus on visible nodes.

Ghost Mode is toggled via a toolbar button or keyboard shortcut (`Ctrl+G`). When active, hidden nodes render as ReactFlow nodes with a custom `ghostNode` type that applies reduced opacity, desaturated colors, dashed borders, and disabled pointer events. Ghost edges render as thin dotted lines at 15% opacity. The ghost layer sits behind visible nodes in the z-order so it never obscures active work.

```
  Ghost Mode ON                          Ghost Mode OFF

  ┌───┐    ┌───┐    ┌ ─ ─ ┐             ┌───┐    ┌───┐
  │ A ├───▶│ B │╌╌╌▷  C                 │ A ├───▶│ B │
  └───┘    └─┬─┘    └ ─ ─ ┘             └───┘    └───┘
             │
          ┌ ─┴─ ┐   ┌ ─ ─ ┐
            D   ╌╌▷   E                    (ghosts not visible)
          └ ─ ─ ┘   └ ─ ─ ┘

  ━━━ visible nodes/edges
  ╌╌╌ ghost nodes/edges (10% opacity)
```

Clicking a ghost node triggers a "Reveal" action that makes the node visible without dismissing Ghost Mode—a convenient way to progressively build up the visible set. A Radix `Tooltip` on ghost hover shows the node's class name and group membership, giving users enough information to decide whether to reveal it.

Ghost Mode state is a client-side rendering preference and does not affect the persisted layout data. It works in combination with criteria-based filters (2.2)—ghosts represent nodes hidden by any mechanism (manual toggle or filter criteria). The ghost rendering layer is implemented as a custom ReactFlow `nodeTypes` registration, avoiding modifications to the core node components.

**Acceptance Criteria**

- Ghost Mode toggles via toolbar button and `Ctrl+G` keyboard shortcut
- Hidden nodes render at 10–20% opacity with dashed borders and desaturated colors
- Ghost edges render as dotted lines at reduced opacity behind visible edges
- Clicking a ghost node reveals it (makes it visible) without exiting Ghost Mode
- Hovering a ghost node shows a Radix `Tooltip` with class name and group membership
- Ghost layer sits behind visible nodes in z-order and does not capture pointer events
- Ghost Mode is purely a rendering preference—no changes to persisted layout data

**Part of Epic: Node Visibility & Canvas Navigation**

---

#### 2.4 (#1453) — Visibility History & Presets

As teams repeatedly adjust node visibility during design sessions, they need a way to recall previous visibility states without re-configuring filters and toggles manually. This issue adds a visibility history stack and named presets that store and restore complete visibility configurations.

The visibility history tracks every visibility change as a timestamped entry in a local stack (stored in the canvas layout data). Each entry records the operation (hide, show, filter applied, filter cleared), the affected node IDs, and a human-readable summary. The history panel—a Radix `Popover` triggered from the toolbar—shows the last 20 entries, and clicking any entry restores the visibility state to that point. This functions like an undo/redo specifically for visibility, independent of the canvas's general undo stack.

```
┌── Visibility History ───────────────────┐
│                                          │
│  ↺ Hide 3 nodes (Empty filter)   12:45  │
│  ↺ Show Only: Auth group         12:42  │
│  ↺ Hide node "LegacyPayment"    12:38  │
│  ↺ Show all                      12:30  │
│  ─────────────────────────────────       │
│  Saved Presets                           │
│  ┌────────────────────────────────┐      │
│  │ "Auth Focus"    4/12 visible   │      │
│  │                 [Apply] [Edit] │      │
│  ├────────────────────────────────┤      │
│  │ "Full Schema"  12/12 visible   │      │
│  │                 [Apply] [Edit] │      │
│  └────────────────────────────────┘      │
│                       [+ Save Current]   │
└──────────────────────────────────────────┘
```

Visibility presets are named configurations that capture the complete visibility map (which nodes are visible, which are hidden) along with active filter criteria. Presets are saved via "Save Current as Preset" which opens a Radix `Dialog` for naming and optionally describing the preset. Presets are stored in the layout data and also persisted via `POST /api/v1/canvas/projects/{projectId}/visibility-presets` for cross-session access. Applying a preset restores the exact visibility and filter state.

Presets support a "default" designation—the preset applied when the canvas loads. This lets project leads configure an opinionated initial view that hides noise for newcomers. The REST API includes `GET /api/v1/canvas/projects/{projectId}/visibility-presets` (list), `PUT /api/v1/canvas/projects/{projectId}/visibility-presets/{id}` (update), `DELETE /api/v1/canvas/projects/{projectId}/visibility-presets/{id}` (delete), and `PATCH /api/v1/canvas/projects/{projectId}/visibility-presets/{id}/default` (set as default).

**Acceptance Criteria**

- Visibility history tracks the last 20 visibility changes with timestamps and summaries
- Clicking a history entry restores the visibility state to that point in time
- Named presets capture the complete visibility map and active filter criteria
- Presets are saved and loaded via REST API for cross-session persistence
- One preset can be designated as the default applied on canvas load
- Preset names must be unique within a project; duplicates are rejected with a clear error
- History entries and presets are displayed in a Radix `Popover` accessible from the toolbar

**Part of Epic: Node Visibility & Canvas Navigation**

---

#### 2.5 (#1463) — Quick Restore & Bulk Controls

After extended visibility manipulation, users need efficient ways to return to a clean state or make sweeping changes. This issue delivers quick-restore actions and a bulk visibility control toolbar that reduces multi-step operations to single clicks.

The primary quick-restore action is "Show All Nodes" which resets every node to visible and clears all active filters in one click. A companion action, "Show All in Group," restores visibility for all nodes within a specific group without affecting nodes outside it. Both actions are available in the canvas toolbar and via keyboard shortcuts (`Ctrl+Shift+A` for show all, `Ctrl+Shift+G` + group click for show all in group).

The bulk controls toolbar appears when multiple nodes are selected (3+). It renders as a floating action bar above the selection with buttons for "Hide Selected," "Show Only Selected," "Select All Hidden" (selects nodes that are currently hidden, useful in combination with Ghost Mode for targeted reveals), and "Invert Visibility" (swaps visible and hidden states for all nodes). Each button includes a count label showing how many nodes the action will affect.

```
┌─ Bulk Controls (5 selected) ─────────────────────────────────┐
│  [Hide Selected (5)] [Show Only (5)] [Invert All] [Select ↻] │
└──────────────────────────────────────────────────────────────┘
```

The "Invert Visibility" action is useful for debugging: if a user has carefully built up a visible set, inverting lets them inspect what they have been hiding without losing the curated view (they can invert back). All bulk operations emit a single visibility history entry (2.4) for clean undo behavior.

A "Hidden Nodes" counter badge on the canvas toolbar shows how many nodes are currently hidden. Clicking the badge opens a Radix `Popover` listing all hidden nodes by name with individual "Show" buttons and a "Show All" button at the top. This provides an inventory of what is hidden without needing Ghost Mode.

**Acceptance Criteria**

- "Show All Nodes" resets all visibility to true and clears active filters in one action
- "Show All in Group" restores visibility for all nodes in a selected group only
- Bulk controls toolbar appears when 3+ nodes are selected with Hide, Show Only, Invert, and Select Hidden
- "Invert Visibility" swaps visible and hidden states for all nodes on the canvas
- Hidden Nodes badge displays the count of currently hidden nodes on the toolbar
- Clicking the badge opens a Radix `Popover` listing hidden nodes with individual show buttons
- All bulk operations record a single entry in the visibility history for clean undo

**Part of Epic: Node Visibility & Canvas Navigation**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 (Group Templates & Layout Snapshots):**
- 1.1 (Data Model & API), 1.2 (Pre-defined Library), and 1.4 (Snapshot Capture) can all be developed in parallel. The data model is needed for template storage, but the library UI and snapshot engine operate on independent code paths. The snapshot system has its own table and endpoints entirely separate from templates.
- 1.3 (Custom Template Authoring) depends on 1.1 being complete since it writes to the same data model and API.
- 1.5 (Auto-Snapshots) depends on 1.4 for the snapshot capture mechanism it wraps with automation triggers.

**Epic 2 (Node Visibility & Canvas Navigation):**
- 2.1 (Toggle Engine), 2.2 (Criteria Filtering), 2.3 (Ghost Mode), and 2.5 (Quick Restore) can all start in parallel since they operate on independent rendering and interaction layers. The toggle engine manages per-node state, criteria filtering works on schema metadata, ghost mode is a rendering overlay, and quick restore provides toolbar actions.
- 2.4 (Visibility History & Presets) depends on 2.1 and 2.2 being at least partially implemented since it tracks changes produced by those systems.

**Cross-Epic Parallelism:**
- Epic 1 and Epic 2 are fully independent and can be developed by separate teams or developers. Group templates and snapshots operate on layout structure data, while node visibility operates on render-time display state—no shared code paths or data models.
- The snapshot system (1.4, 1.5) captures visibility state, so integration testing should run after both epics reach MVP.
