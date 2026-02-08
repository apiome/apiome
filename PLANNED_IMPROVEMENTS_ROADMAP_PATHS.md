# Paths Designer Improvements Roadmap

## Paths Designer Improvements (CONSOLIDATED)

> **Purpose**: All Paths Designer improvement features consolidated in one place for focused development.
> **Priority**: 🔴 High - Critical for developer-centered API design experience
> **Timeline**: Q1-Q3 2026
> **Status**: Mix of ✅ Implemented, 🚧 Partial, 📋 Planned
> **Audience**: Software engineers, API architects, platform teams

---

## Current State Summary

The Paths Designer is a fully implemented visual API design tool built on React Flow. It supports:

- ✅ Six node types: Operation, Parameter, Response, RequestBody, ResponseBody, Class
- ✅ Three-panel layout: Left Sidebar (280px) | Center Canvas | Right Properties Panel
- ✅ Drag-and-drop from sidebar library to canvas
- ✅ HTTP method color coding (GET=green, POST=blue, PUT=orange, PATCH=purple, DELETE=red)
- ✅ Status code color bands (2xx=green, 3xx=blue, 4xx=yellow, 5xx=red)
- ✅ Parameter location color coding (path=green, query=blue, header=purple, cookie=orange)
- ✅ Smart edge routing (straight, bezier, orthogonal, smart)
- ✅ Edge animations (flow, pulse, dash)
- ✅ Auto-layout algorithm (Sugiyama-style hierarchical)
- ✅ OpenAPI 3.1 compliance validation
- ✅ Schema binding via class references ($ref) and inline schemas
- ✅ Multi-content-type support (JSON, XML, multipart/form-data)
- ✅ Security scheme configuration (API Key, HTTP Bearer/Basic)
- ✅ Canvas background customization, grid snapping, themes

### Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `paths/page.tsx` | ~240 | Main page, three-panel layout orchestration |
| `PathsCanvasView.tsx` | ~3,800 | Canvas, React Flow, node creation, drag/drop, inline OperationNode |
| `PathsSidebar.tsx` | ~1,067 | Left sidebar with tabs (Paths, Operations, Classes, Properties, Security, Servers) |
| `OperationPropertiesPanel.tsx` | ~1,687 | Right panel for editing operations |
| `ParameterPropertiesPanel.tsx` | ~1,015 | Right panel for editing parameters |
| `ResponsePropertiesPanel.tsx` | ~1,498 | Right panel for editing responses |
| `PathRequestBodyNode.tsx` | ~1,250 | Request body node with schema editor |
| `PathResponseBodyNode.tsx` | ~778 | Response body node with schema editor |
| `PathResponseNode.tsx` | ~464 | Response node with status code colors |
| `PathParameterNode.tsx` | ~136 | Parameter node with location colors |
| `PathClassNode.tsx` | ~77 | Class reference node |
| `paths-operation-colors.ts` | ~33 | HTTP method color definitions |

---

---

## 1. Operation Focus Mode (Isolation View) 📋 PLANNED

[TODO] When an HTTP operation is selected on the canvas, all nodes **not** associated with that operation should fade to 20% opacity. Only the selected operation and its directly connected nodes (parameters, request body, responses, response bodies, referenced classes) remain fully visible. This dramatically improves readability for APIs with many endpoints.

### Core Behavior

- [TODO] **Click-to-Isolate**: Single-click an operation node to enter focus mode; all unrelated nodes and edges transition to 20% opacity over a 200ms CSS transition
- [TODO] **Connected Node Detection**: Automatically identify all nodes connected to the selected operation by traversing edges (parameters, request bodies, responses, response bodies, class references) at any depth
- [TODO] **Edge Dimming**: Edges not connected to the focused operation also dim to 20% opacity; focused edges remain at full opacity with a subtle glow effect
- [TODO] **Focused Node Highlight Ring**: The selected operation node gets a prominent colored ring (matching its HTTP method color) to clearly indicate it is the focus anchor
- [TODO] **Multi-Operation Focus**: Hold `Shift` and click additional operations to include them in the focus set (additive focus)
- [TODO] **Exit Focus Mode**: Press `Esc` or click empty canvas space to exit focus mode and restore all nodes to full opacity
- [TODO] **Focus Mode Indicator**: Show a small banner/pill at the top of the canvas reading "Focus: GET /users/{id}" with an X button to exit

### Visual Design

- [TODO] **Dimmed Node Style**: Non-focused nodes render at `opacity: 0.2` with `pointer-events: none` (cannot be clicked while dimmed)
- [TODO] **Dimmed Edge Style**: Non-focused edges render at `opacity: 0.15` with `stroke-dasharray: 4 4` to further de-emphasize
- [TODO] **Focused Edge Glow**: Focused edges receive a subtle `filter: drop-shadow(0 0 3px <methodColor>)` to trace the data flow path
- [TODO] **Smooth Transition**: All opacity changes use `transition: opacity 200ms ease-in-out` for a polished feel
- [TODO] **Background Dim**: Optionally darken the canvas background slightly (e.g., overlay at 5% black) to further draw attention to focused nodes

### Keyboard Integration

- [TODO] **Tab Cycling**: While in focus mode, `Tab` / `Shift+Tab` cycles through the focused nodes (operation → parameters → request body → responses)
- [TODO] **Arrow Navigation**: Arrow keys navigate between focused nodes in layout order
- [TODO] **Enter to Edit**: Press `Enter` on a focused node to open its editor overlay

---

## 2. Editor Overlay (Replace Sidebar Properties Panels) 📋 PLANNED

[TODO] Replace the current right-side properties panels (`OperationPropertiesPanel`, `ParameterPropertiesPanel`, `ResponsePropertiesPanel`) with a floating overlay/modal that appears when a node is clicked or double-clicked. This reclaims canvas real estate, centers the developer's attention on the editing context, and follows patterns familiar to developers from tools like Figma, Postman, and VS Code.

### Core Behavior

- [TODO] **Trigger**: Double-click (or `Enter` key on selected node) opens the editor overlay centered over the canvas
- [TODO] **Overlay Design**: A floating panel (not a full-screen modal) that covers approximately 60-70% of the canvas width and 70-80% of the canvas height, with a semi-transparent backdrop behind it
- [TODO] **Backdrop Click**: Clicking the backdrop dismisses the overlay and saves changes
- [TODO] **Close Button**: `X` button in the top-right corner; `Esc` key also closes
- [TODO] **Drag to Reposition**: The overlay title bar is draggable so developers can move it to see the canvas underneath
- [TODO] **Resize Handle**: Optional resize handle in the bottom-right corner to expand/shrink the overlay
- [TODO] **Auto-Save on Close**: All changes are persisted (debounced 300ms) as the user types; closing the overlay does not discard work
- [TODO] **Quick-Edit Mini Mode**: Single-click a node to show a compact floating toolbar (not the full overlay) with the most-used actions (e.g., change status code, toggle required, change type); double-click for the full editor

### Overlay Layout

- [TODO] **Title Bar**: Shows the node type icon + name (e.g., "🟢 GET /users/{id}" or "📋 Parameter: userId") with the close button
- [TODO] **Tabbed Content**: For operations, organize editor into tabs:
  - [TODO] **General**: Summary, description (Markdown with live preview), operationId, tags, deprecated, x-private
  - [TODO] **Parameters**: Linked parameters table with add/edit/remove, schema type selectors
  - [TODO] **Request Body**: Content type tabs, schema builder, examples
  - [TODO] **Responses**: Response list with status codes, content types, schema builders, headers
  - [TODO] **Security**: Security scheme selector with scope configuration
  - [TODO] **Extensions**: Custom `x-*` extension key-value editor
- [TODO] **JSON/YAML Preview Tab**: A read-only Monaco editor tab showing the generated OpenAPI fragment for the current operation, updating in real-time as the user edits
- [TODO] **Breadcrumb Navigation**: When editing a nested element (e.g., a parameter within an operation), show breadcrumbs at the top so the user can navigate back without closing

### Remove Right Panel

- [TODO] **Remove `OperationPropertiesPanel`** from the three-panel layout; the overlay replaces it
- [TODO] **Remove `ParameterPropertiesPanel`** from the three-panel layout; the overlay replaces it
- [TODO] **Remove `ResponsePropertiesPanel`** from the three-panel layout; the overlay replaces it
- [TODO] **Expand Canvas**: With the right panel removed, the canvas area expands to fill the remaining space, giving developers a larger working surface

---

## 3. Professional Node Visual Redesign 📋 PLANNED

[TODO] The current operation nodes use basic colored headers with white/dark bodies. For an enterprise-grade developer tool, the nodes need a more refined, information-dense, and visually distinctive design inspired by tools like Insomnia, Stoplight Studio, and Swagger Editor.

### Operation Node Redesign

- [TODO] **Method Badge**: Replace the full-width colored header with a compact, pill-shaped HTTP method badge (e.g., `[GET]`, `[POST]`) in the top-left corner, saving vertical space
- [TODO] **Path Display**: Show the full path (e.g., `/users/{id}/posts`) in a monospace font next to the method badge, with path variables highlighted in a contrasting color
- [TODO] **Operation ID Subtext**: Show the `operationId` in a smaller, muted font below the path (e.g., `getUserPosts`)
- [TODO] **Summary Line**: If a summary is set, show it as a single line of truncated text below the operationId
- [TODO] **Compact Metadata Row**: A row of small icon badges showing:
  - [TODO] Parameter count badge (e.g., `📋 3` for 3 parameters)
  - [TODO] Response count badge (e.g., `📬 4` for 4 responses)
  - [TODO] Security indicator (🔒 if secured, 🔓 if not)
  - [TODO] Deprecated badge (⚠️ strikethrough if deprecated)
  - [TODO] Private badge (🔵 if x-private)
- [TODO] **Tags Row**: Display operation tags as tiny colored chips at the bottom of the node
- [TODO] **Content Type Indicators**: Small icons showing which content types the operation accepts/returns (JSON, XML, multipart)
- [TODO] **Node Width Standardization**: All operation nodes should have a consistent width (e.g., 320px) for visual alignment
- [TODO] **Subtle Drop Shadow**: Add `box-shadow: 0 2px 8px rgba(0,0,0,0.08)` for depth, increasing on hover to `0 4px 16px rgba(0,0,0,0.12)`

### Parameter Node Redesign

- [TODO] **Inline Parameter Chips**: Instead of separate parameter nodes connected by edges, display parameters as compact chips directly inside the operation node's body (collapsible section)
- [TODO] **Chip Layout**: `[location] name: type` format (e.g., `[query] page: integer`, `[path] id: string(uuid)`)
- [TODO] **Required Indicator**: Red asterisk `*` on required parameters; optional parameters in muted color
- [TODO] **Expand/Collapse**: Click the "Parameters" section header to toggle between chip view and detailed view showing descriptions and constraints

### Response Node Redesign

- [TODO] **Inline Response List**: Display responses as a collapsible list inside the operation node body, showing `[status] description` (e.g., `[200] Success`, `[404] Not Found`)
- [TODO] **Status Code Color Dots**: Small colored dots before each status code (green for 2xx, blue for 3xx, yellow for 4xx, red for 5xx) instead of large colored nodes
- [TODO] **Schema Preview**: On hover over a response, show a tooltip with the response schema structure
- [TODO] **Expand to External Nodes**: Toggle button to "explode" responses into separate connected nodes for detailed view (toggle between compact and expanded modes)

### Request Body Compact View

- [TODO] **Inline Request Body Section**: Show request body as a collapsible section within the operation node (for POST/PUT/PATCH) showing content type and schema name
- [TODO] **Schema Type Badge**: Show `$ref: Pet` or `inline: object (5 props)` as a compact badge
- [TODO] **Expand to External Node**: Toggle to explode the request body into a separate detailed node for complex schemas

---

## 4. Canvas Toolbar for Paths 📋 PLANNED

[TODO] The Paths Designer currently has no dedicated toolbar. A horizontal toolbar above the canvas provides quick access to common actions, consistent with professional API design tools.

### Toolbar Layout

- [TODO] **Position**: Fixed horizontal bar between the left sidebar and the canvas, spanning the canvas width
- [TODO] **Left Section** (actions):
  - [TODO] **Add Path** button (+ icon): Opens a quick dialog to create a new path
  - [TODO] **Add Operation** dropdown: Select HTTP method to add to the selected path
  - [TODO] **Auto-Layout** button: Apply hierarchical layout with dropdown for layout direction (TB, LR, BT, RL)
  - [TODO] **Fit View** button: Zoom to fit all nodes
- [TODO] **Center Section** (view controls):
  - [TODO] **View Mode Toggle**: Switch between "Full Canvas" (all nodes visible) and "Focused" (operation isolation) modes
  - [TODO] **Compact/Expanded Toggle**: Switch between compact (inline parameters/responses) and expanded (separate nodes) display modes
  - [TODO] **Show/Hide Classes** toggle: Toggle visibility of class reference nodes
- [TODO] **Right Section** (tools):
  - [TODO] **Search** (🔍): Open canvas search overlay (`Cmd+F`)
  - [TODO] **Validate** (✓): Run OpenAPI validation and show results panel
  - [TODO] **Export** dropdown: Export as OpenAPI JSON/YAML, PNG, SVG, PDF
  - [TODO] **Settings** (⚙️): Canvas settings (grid, snapping, edge style, animations)
  - [TODO] **Help** (?): Toggle keyboard shortcut overlay

### Toolbar Styling

- [TODO] **Minimal Design**: Flat icons with tooltips, no text labels by default; hover reveals label
- [TODO] **Separator Lines**: Thin vertical separators between action groups
- [TODO] **Active State**: Active toggles (e.g., "Focused" mode) show a colored underline matching the theme accent
- [TODO] **Dark Mode**: Toolbar adapts to current theme (dark background with light icons in dark mode)
- [TODO] **Compact Height**: 40px tall to minimize canvas area loss

---

## 5. Paths Canvas Layout Improvements 📋 PLANNED

[TODO] The current canvas layout positions nodes in horizontal rows (operations at y=200, parameters at y=350, responses at y=500). This works for small APIs but becomes unwieldy for APIs with 10+ endpoints. The layout needs to be smarter and more developer-friendly.

### Layout Algorithms

- [TODO] **Vertical Swimlane Layout**: Each path gets a vertical column (swimlane). Within each column, the operation is at the top, parameters below, request body below that, and responses at the bottom. Swimlanes are separated by subtle vertical dividers
- [TODO] **Horizontal Flow Layout**: Operations flow left-to-right: `Operation → Parameters → Request Body → Responses → Response Bodies`. Each operation is a horizontal chain
- [TODO] **Grouped by Path Layout**: Group all operations for the same path together in a visual container (similar to the schema canvas groups), with the path name as the container header
- [TODO] **Grouped by Tag Layout**: Group operations by their OpenAPI tags into color-coded containers
- [TODO] **RESTful Resource Layout**: Group related CRUD operations (GET, POST, PUT, DELETE for the same resource) into a single "resource block" showing the full lifecycle
- [TODO] **Layout Selector**: Dropdown in the toolbar to switch between layout algorithms with live preview

### Path Grouping Containers

- [TODO] **Auto-Group by Path**: Automatically create visual containers for each unique path (e.g., `/users`, `/users/{id}`, `/products`)
- [TODO] **Container Header**: Shows the path pattern in monospace font with a colored left border
- [TODO] **Container Actions**: Collapse/expand, delete all operations in path, add operation to path
- [TODO] **Color by Resource**: Auto-assign colors to path groups based on the first path segment (e.g., all `/users/*` paths share one color, all `/products/*` share another)

### Spacing & Alignment

- [TODO] **Consistent Node Gaps**: Enforce minimum 40px horizontal gap and 30px vertical gap between nodes via layout algorithm
- [TODO] **Edge Routing Optimization**: After auto-layout, run an edge crossing minimization pass to reduce visual clutter
- [TODO] **Alignment Guides**: Smart guides (horizontal/vertical lines) appear when manually dragging nodes to align with other nodes

---

## 6. Developer-Centered Code Preview 📋 PLANNED

[TODO] Developers think in code, not just visual boxes. The Paths Designer should provide instant code previews for the operations they are designing.

### Real-Time OpenAPI Preview

- [TODO] **Split-View Mode**: Toggle a bottom panel (resizable, collapsible) showing the generated OpenAPI YAML/JSON for the currently selected operation, updating in real-time as the user edits
- [TODO] **Full Spec Preview**: Toggle to see the entire generated OpenAPI specification (all paths, components, security schemes)
- [TODO] **Monaco Editor**: Use Monaco Editor for the preview with syntax highlighting, folding, and search
- [TODO] **Copy to Clipboard**: One-click copy button for the preview content
- [TODO] **Format Toggle**: Switch between YAML and JSON with one click
- [TODO] **Diff Mode**: When making changes, show a diff view (green for added, red for removed) against the last saved state

### Code Snippet Generation

- [TODO] **cURL Preview**: Show a cURL command for the selected operation, auto-populated with example values from parameters and request body
- [TODO] **Language Snippets**: Dropdown to generate request code in:
  - [TODO] JavaScript (fetch, axios)
  - [TODO] Python (requests, httpx)
  - [TODO] Go (net/http)
  - [TODO] Java (OkHttp, HttpClient)
  - [TODO] C# (HttpClient)
  - [TODO] Rust (reqwest)
- [TODO] **Copy Snippet**: One-click copy for any generated snippet
- [TODO] **Snippet in Overlay**: Code snippets available as a tab in the editor overlay

### Schema Preview on Hover

- [TODO] **Schema Tooltip**: When hovering over a schema reference (`$ref: Pet`) anywhere on the canvas, show a floating tooltip with the full JSON Schema definition of the referenced class
- [TODO] **Property Tooltip**: When hovering over a parameter name, show its type, format, constraints, and description in a compact tooltip
- [TODO] **Response Preview Tooltip**: When hovering over a response status code badge, show the response body schema structure

---

## 7. Paths Canvas Search & Filter 📋 PLANNED

[TODO] The Paths Designer needs search and filter capabilities to help developers navigate large API surfaces.

### Search

- [TODO] **Canvas Search** (`Cmd/Ctrl+F`): Open a search overlay that searches across operation paths, operationIds, descriptions, parameter names, response descriptions
- [TODO] **Search Highlighting**: Matching nodes are highlighted with a bright ring; non-matching nodes dim to 30% opacity
- [TODO] **Navigate Results**: Up/Down arrows or `Enter` to cycle through search results, with the canvas auto-panning to center each result
- [TODO] **Search Scope**: Toggle search scope: All, Paths only, Operations only, Parameters only, Responses only

### Filter

- [TODO] **Filter by HTTP Method**: Toggle buttons (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS) to show/hide operations by method
- [TODO] **Filter by Tag**: Dropdown to filter operations by OpenAPI tag
- [TODO] **Filter by Status**: Show only operations with validation errors/warnings
- [TODO] **Filter by Path Segment**: Text filter to show only paths matching a pattern (e.g., `/users*` shows all user-related paths)
- [TODO] **Active Filter Indicator**: When filters are active, show a colored badge on the filter button indicating how many items are hidden

### Operation Table View

- [TODO] **Table Toggle**: Button to switch from canvas view to a sortable table view showing all operations in a dense, spreadsheet-like format:
  - Columns: Method, Path, OperationId, Summary, Parameters, Responses, Security, Tags, Status (valid/warning/error)
  - Click any row to jump to that operation on the canvas (or open the editor overlay)
- [TODO] **Bulk Edit in Table**: Select multiple rows and batch-edit tags, security, deprecated status

---

## 8. Context Menu for Paths Nodes 📋 PLANNED

[TODO] Right-click context menus provide quick access to common actions without navigating toolbars or sidebars.

### Operation Node Context Menu

- [TODO] **Edit Operation**: Open editor overlay (same as double-click)
- [TODO] **Add Parameter**: Sub-menu: Query, Path, Header, Cookie
- [TODO] **Add Response**: Sub-menu: 200 OK, 201 Created, 204 No Content, 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 500 Server Error
- [TODO] **Set Request Body**: Quick-add request body with default JSON content type
- [TODO] **Duplicate Operation**: Clone the operation (with new operationId)
- [TODO] **Move to Path**: Sub-menu listing all paths to move the operation to a different path
- [TODO] **Copy as cURL**: Copy a cURL command for this operation to clipboard
- [TODO] **Copy as OpenAPI**: Copy the OpenAPI YAML fragment for this operation to clipboard
- [TODO] **Generate Code**: Sub-menu with language options to generate a client request snippet
- [TODO] **Toggle Deprecated**: Quick-toggle the deprecated flag
- [TODO] **Delete Operation**: Delete with confirmation

### Parameter Node Context Menu

- [TODO] **Edit Parameter**: Open editor overlay
- [TODO] **Change Location**: Sub-menu: Query, Path, Header, Cookie
- [TODO] **Toggle Required**: Quick-toggle required status
- [TODO] **Apply Primitive Template**: Apply a predefined schema type (UUID, email, pagination, etc.)
- [TODO] **Duplicate Parameter**: Clone the parameter
- [TODO] **Delete Parameter**: Delete with confirmation

### Response Node Context Menu

- [TODO] **Edit Response**: Open editor overlay
- [TODO] **Change Status Code**: Quick-change dropdown
- [TODO] **Add Content Type**: Sub-menu of common content types
- [TODO] **Bind Schema**: Quick-select a class to bind as the response schema
- [TODO] **Add Headers**: Sub-menu of common header templates (pagination, rate limit, CORS)
- [TODO] **Duplicate Response**: Clone the response
- [TODO] **Delete Response**: Delete with confirmation

### Canvas Background Context Menu

- [TODO] **Add Path**: Create a new path
- [TODO] **Add Operation**: Sub-menu with HTTP methods
- [TODO] **Paste Operation**: If an operation was copied, paste it here
- [TODO] **Auto-Layout**: Apply auto-layout
- [TODO] **Fit View**: Zoom to fit all nodes
- [TODO] **Toggle Grid**: Show/hide grid
- [TODO] **Canvas Settings**: Open settings

---

## 9. Keyboard Shortcuts for Paths 📋 PLANNED

[TODO] Developer-focused tools must be keyboard-first. The Paths Designer should support a comprehensive set of keyboard shortcuts.

### Navigation

| Shortcut | Action | Status |
|----------|--------|--------|
| `Cmd/Ctrl + F` | [TODO] Open canvas search | 📋 |
| `Cmd/Ctrl + K` | [TODO] Open command palette | 📋 |
| `Space + Drag` | Pan canvas | ✅ |
| `Scroll` | Zoom in/out | ✅ |
| `Cmd/Ctrl + 0` | [TODO] Reset zoom to 100% | 📋 |
| `Cmd/Ctrl + Shift + 0` | [TODO] Fit all nodes in view | 📋 |
| `Esc` | [TODO] Exit focus mode / close overlay / close search | 📋 |
| `Tab` | [TODO] Cycle through nodes (in focus mode: cycle focused nodes) | 📋 |
| `M` | [TODO] Toggle minimap | 📋 |

### Editing

| Shortcut | Action | Status |
|----------|--------|--------|
| `Enter` | [TODO] Open editor overlay for selected node | 📋 |
| `Delete` / `Backspace` | [TODO] Delete selected node with confirmation | 📋 |
| `Cmd/Ctrl + D` | [TODO] Duplicate selected node | 📋 |
| `Cmd/Ctrl + C` | [TODO] Copy selected node(s) | 📋 |
| `Cmd/Ctrl + V` | [TODO] Paste copied node(s) at cursor | 📋 |
| `Cmd/Ctrl + Z` | [TODO] Undo | 📋 |
| `Cmd/Ctrl + Shift + Z` | [TODO] Redo | 📋 |
| `Cmd/Ctrl + S` | [TODO] Save / persist changes | 📋 |

### Quick-Add (when an operation is selected)

| Shortcut | Action | Status |
|----------|--------|--------|
| `G` | [TODO] Add GET operation to selected path | 📋 |
| `P` | [TODO] Add POST operation to selected path | 📋 |
| `U` | [TODO] Add PUT operation to selected path | 📋 |
| `A` | [TODO] Add PATCH operation to selected path | 📋 |
| `X` | [TODO] Add DELETE operation to selected path | 📋 |
| `Q` | [TODO] Add query parameter to selected operation | 📋 |
| `H` | [TODO] Add header parameter to selected operation | 📋 |
| `B` | [TODO] Add/focus request body for selected operation | 📋 |
| `2` | [TODO] Add 200 OK response | 📋 |
| `4` | [TODO] Add 400 Bad Request response | 📋 |
| `5` | [TODO] Add 500 Server Error response | 📋 |

### Display

| Shortcut | Action | Status |
|----------|--------|--------|
| `Cmd/Ctrl + Shift + L` | [TODO] Toggle auto-layout | 📋 |
| `Cmd/Ctrl + Shift + E` | [TODO] Open export dialog | 📋 |
| `Cmd/Ctrl + Shift + V` | [TODO] Toggle OpenAPI preview panel | 📋 |
| `Cmd/Ctrl + .` | [TODO] Toggle compact/expanded node mode | 📋 |
| `?` | [TODO] Show keyboard shortcut overlay | 📋 |

---

## 10. Undo/Redo for Paths Canvas 📋 PLANNED

[TODO] The Paths canvas currently has no undo/redo capability. Any accidental deletion or edit is irreversible.

- [TODO] **Undo Stack**: Configurable depth (default 50, max 500 operations)
- [TODO] **Tracked Operations**: Operation CRUD, parameter add/edit/delete, response add/edit/delete, request body changes, node moves, edge changes, layout changes
- [TODO] **Keyboard Shortcuts**: `Cmd/Ctrl + Z` (Undo), `Cmd/Ctrl + Shift + Z` (Redo)
- [TODO] **History Panel**: Visual timeline of all changes with the ability to jump to any point
- [TODO] **Operation Coalescing**: Rapid sequential moves of the same node collapse into a single undo entry
- [TODO] **Persistent Undo**: Optionally persist undo stack to database so changes survive page reload
- [TODO] **Visual Feedback**: Brief toast notification on undo/redo showing what was undone/redone (e.g., "Undone: Delete GET /users")

---

## 11. Edge & Connection Visual Improvements 📋 PLANNED

[TODO] Edges in the Paths Designer carry semantic meaning (parameter binding, response linking, schema reference). They should be more informative and visually distinct.

### Edge Labels

- [TODO] **Parameter Edge Labels**: Show parameter location and name on the edge (e.g., "query: page")
- [TODO] **Response Edge Labels**: Show status code on the edge (e.g., "200", "404")
- [TODO] **Schema Binding Labels**: Show the schema type on edges connecting to classes (e.g., "$ref: Pet")
- [TODO] **Content Type Labels**: Show content type on request/response body edges (e.g., "application/json")
- [TODO] **Label Background**: Semi-transparent pill background on edge labels for readability against canvas backgrounds

### Edge Routing

- [TODO] **Operation-Scoped Routing**: When in focus mode, routes edges for the focused operation using orthogonal routing to avoid overlap with dimmed nodes
- [TODO] **Edge Bundling**: When multiple edges share a similar path (e.g., multiple parameters from one operation), bundle them into a single trunk that splits near the target nodes
- [TODO] **Hover Highlight**: Hovering over an edge highlights both the source and target nodes with a colored ring
- [TODO] **Click to Select**: Clicking an edge selects it and shows its details in a mini tooltip (source, target, relationship type)

### Edge Animation for Data Flow

- [TODO] **Request Flow Animation**: When "Animate Data Flow" is enabled, show animated dots flowing from parameters → operation → request body (representing the request lifecycle)
- [TODO] **Response Flow Animation**: Animated dots flowing from operation → responses (representing the response lifecycle)
- [TODO] **Animation Direction**: Dots flow in the direction of data movement (inbound for request, outbound for response)
- [TODO] **Animation Speed Control**: Adjustable animation speed in canvas settings

---

## 12. Left Sidebar Improvements 📋 PLANNED

[TODO] The left sidebar provides access to paths, operations, classes, properties, security, and servers. Several improvements would make it more developer-friendly.

### 12.1 Sidebar Tabs Redesign

- [TODO] **Icon-Only Tabs**: Replace text tabs with icon-only tabs (with tooltips) to save vertical space: 🛤️ Paths, ⚡ Operations, 📦 Classes, 🔑 Security, 🌐 Servers
- [TODO] **Collapsible Sidebar**: Collapse the sidebar to a thin icon rail (~48px) with tooltips, maximizing canvas space; expand on click or `Cmd+B`
- [TODO] **Pinned Sidebar**: Toggle to pin/unpin the sidebar; when unpinned, it auto-collapses when the canvas is clicked

### 12.2 Path Tree View

- [TODO] **Hierarchical Path Tree**: Display paths as a tree structure grouped by path segments:
  ```
  📁 /users
    ├─ GET  /users (listUsers)
    ├─ POST /users (createUser)
    └─ 📁 /{id}
       ├─ GET    /users/{id} (getUser)
       ├─ PUT    /users/{id} (updateUser)
       ├─ DELETE /users/{id} (deleteUser)
       └─ 📁 /posts
          └─ GET /users/{id}/posts (getUserPosts)
  📁 /products
    ├─ GET  /products (listProducts)
    └─ ...
  ```
- [TODO] **Method Color Badges**: Show HTTP method as a colored badge next to each operation in the tree
- [TODO] **Validation Status Icons**: Show ✅ / ⚠️ / ❌ icons next to operations with validation issues
- [TODO] **Click to Navigate**: Click an operation in the tree to pan the canvas to that node and select it
- [TODO] **Double-Click to Edit**: Double-click to open the editor overlay directly

### 12.3 Drag-and-Drop Improvements

- [TODO] **Drag Preview**: Show a ghost preview of the node being dragged, with its method color and path
- [TODO] **Drop Zone Highlighting**: Highlight valid drop targets on the canvas when dragging (e.g., highlight an operation node when dragging a parameter to indicate it can be dropped on that operation)
- [TODO] **Invalid Drop Feedback**: Red flash/shake animation when dropping on an invalid target
- [TODO] **Smart Drop**: Dropping a class onto an operation node automatically opens a dialog asking where to bind it (request body, response body, or parameter type)

---

## 13. OpenAPI Spec Quality Panel 📋 PLANNED

[TODO] Provide real-time feedback on API design quality directly within the Paths Designer, helping developers catch issues before export.

### Validation Panel

- [TODO] **Validation Sidebar Tab**: Add a "Validation" tab to the left sidebar showing all current OpenAPI spec issues
- [TODO] **Issue Categories**:
  - [TODO] Errors (red): Missing required fields, invalid status codes, broken $ref, duplicate operationIds
  - [TODO] Warnings (yellow): Missing descriptions, operations without tags, missing examples, no security
  - [TODO] Info (blue): Best practice suggestions, documentation coverage, consistency notes
- [TODO] **Click to Navigate**: Click any issue to pan the canvas to the affected node and highlight it
- [TODO] **Auto-Fix Suggestions**: For common issues (missing operationId, missing description), offer one-click auto-fix
- [TODO] **Issue Count Badge**: Show total issue count on the Validation tab icon
- [TODO] **Issue Suppression**: Right-click an issue to suppress it (with comment explaining why)

### API Design Linting

- [TODO] **Naming Convention Check**: Warn when paths don't follow REST conventions (e.g., `/getUser` instead of `/users/{id}`)
- [TODO] **Consistent Pluralization**: Flag inconsistent pluralization (e.g., `/user` vs. `/products`)
- [TODO] **HTTP Method Semantics**: Warn when GET operations have request bodies, DELETE operations return 201, etc.
- [TODO] **Response Completeness**: Warn when operations are missing standard error responses (400, 401, 404, 500)
- [TODO] **Security Coverage**: Highlight operations that have no security requirements defined
- [TODO] **Versioning Check**: Detect path-based versioning patterns (e.g., `/v1/users`) and flag inconsistencies

### Quality Score

- [TODO] **Spec Quality Score**: Display an overall quality score (0-100) in the toolbar, calculated from:
  - Documentation coverage (descriptions, examples)
  - Security coverage (% of operations with security)
  - Validation compliance (0 errors, 0 warnings)
  - Consistency (naming, patterns)
  - Completeness (responses, parameters defined)
- [TODO] **Score Breakdown Tooltip**: Hover over the score to see a breakdown by category
- [TODO] **Score Trend**: Track the score over time and show whether it's improving or declining

---

## 14. Minimap for Paths Canvas 📋 PLANNED

[TODO] The Paths canvas needs a minimap for navigating APIs with many endpoints.

- [TODO] **Minimap Component**: Small bird's-eye view in the bottom-right corner showing all operation nodes as colored dots (method color)
- [TODO] **Viewport Rectangle**: Show the current visible area as a draggable rectangle on the minimap
- [TODO] **Click to Navigate**: Click anywhere on the minimap to pan the canvas to that position
- [TODO] **Path Group Regions**: Color-code minimap regions by path group/resource
- [TODO] **Toggle Visibility**: `M` key or toolbar button to show/hide the minimap
- [TODO] **Resizable**: Drag the minimap corner to resize it

---

## 15. Paths Canvas Export Enhancements 📋 PLANNED

[TODO] Extend the canvas export capabilities specific to the Paths Designer.

### OpenAPI Export

- [TODO] **Export Dialog**: Modal with options for OpenAPI export:
  - [TODO] Format: JSON or YAML
  - [TODO] Version: OpenAPI 3.1 (default), OpenAPI 3.0, Swagger 2.0
  - [TODO] Bundling: Inline schemas vs. $ref references
  - [TODO] Include/exclude: Examples, descriptions, extensions, deprecated operations
  - [TODO] Server URLs: Add/edit server configurations before export
- [TODO] **Live Preview**: Show the generated spec in a Monaco editor within the export dialog
- [TODO] **Validation Gate**: Run full validation before export; block export if errors exist (with override option)
- [TODO] **Download or Copy**: Buttons for both downloading as file and copying to clipboard
- [TODO] **Export to Git**: Push the generated spec directly to a configured Git repository
- [TODO] **Export History**: Track past exports with timestamp, format, and user

### Visual Export

- [TODO] **Export Canvas as PNG/SVG/PDF**: Same as the schema canvas export wizard, adapted for the Paths canvas
- [TODO] **Export Focused View**: When in focus mode, export only the focused operation and its connected nodes
- [TODO] **Export as Mermaid Sequence Diagram**: Generate a Mermaid sequence diagram showing the request/response flow for the selected operation
- [TODO] **Export API Map**: Generate a visual API map showing all endpoints organized by resource/tag as a printable poster format

---

## 16. Advanced Edge Routing Engine 📋 PLANNED

[TODO] The current SmartEdge component uses a basic A*-inspired pathfinding algorithm with horizontal-first / vertical-first / around-obstacle strategies. While functional, it produces suboptimal routing for dense canvases — edges overlap, crossings accumulate, and connection paths feel cluttered. A production-grade routing engine should produce clean, orthogonal paths with minimal crossings, proper port assignments, and visual bundling for parallel connections.

### Orthogonal (Manhattan) Routing

- [TODO] **Strict Right-Angle Routing**: Replace the current free-form waypoint routing with a strict orthogonal router where every edge segment is either perfectly horizontal or perfectly vertical — no diagonal segments allowed. This produces the clean, schematic look expected in enterprise architecture diagrams
- [TODO] **Configurable Corner Radius**: Allow a global corner radius setting (default 10px, range 0–20px) for the 90-degree turns, controlled via a canvas settings slider. The current hardcoded `borderRadius: 8` in `getSmoothStepPath` should become configurable
- [TODO] **Minimum Segment Length**: Enforce a minimum segment length (default 20px) so that short jogs are eliminated. When two turns would be closer than the minimum, merge them into a single offset
- [TODO] **Preferred Routing Direction**: Allow edges to declare a preferred direction (e.g., operation→parameter edges prefer downward routing, operation→response edges prefer rightward), producing more predictable visual patterns aligned with the layout direction
- [TODO] **Routing Channel Allocation**: Assign parallel edges to distinct routing channels (spaced 12px apart) so that when multiple edges run alongside each other, they maintain consistent spacing rather than stacking on top of one another

### Edge Crossing Minimization

- [TODO] **Layer-Based Crossing Reduction**: After initial routing, run a Barycenter heuristic or median heuristic pass to reorder node ports and reduce the total number of edge crossings across the canvas
- [TODO] **Post-Layout Re-Routing**: After auto-layout or manual node repositioning, automatically re-run the routing engine to minimize crossings introduced by the new node positions. Debounce at 200ms after drag-end
- [TODO] **Crossing Count Display**: Show the current edge crossing count in the canvas status bar (e.g., "12 crossings"). Highlight crossing points with subtle red dots when a "Show Crossings" debug toggle is enabled
- [TODO] **Iterative Improvement**: Apply 2-opt or sifting passes (up to 5 iterations) to progressively reduce crossings after each layout change
- [TODO] **Crossing-Free Focus Mode**: When in Operation Focus Mode (Section 1), guarantee zero crossings among the focused operation's edges by re-routing them in isolation

### Port-Based Connection Points

- [TODO] **Multi-Port Nodes**: Replace the current single top/bottom `Handle` pairs with multi-port layouts:
  - **Operation nodes**: Left-side ports for inbound connections (request body), right-side ports for outbound connections (responses), bottom ports for parameters. Each port is a 6px circle positioned at calculated intervals along the node edge
  - **Parameter nodes**: Single top port (input from operation)
  - **Response nodes**: Single top port (input from operation), optional right-side port (output to response body or class)
  - **Request Body nodes**: Single right port (output to operation)
  - **Response Body nodes**: Single left port (input from response)
  - **Class nodes**: Top port (input from response or request body binding)
- [TODO] **Port Auto-Assignment**: When creating an edge, automatically assign it to the nearest available port on both source and target nodes. If all ports on one side are occupied, dynamically add a new port
- [TODO] **Port Ordering**: Order ports by the vertical/horizontal position of their connected node to minimize edge crossings at the node boundary
- [TODO] **Port Color Coding**: Ports inherit the edge color for their relationship type (gray for parameters, purple for responses, blue for response bodies, indigo for class refs), providing a visual cue for what connects where
- [TODO] **Port Hover Preview**: Hovering over an unconnected port shows a tooltip indicating what can connect to it (e.g., "Drop a Response node here") and highlights compatible nodes on the canvas

### Edge Bundling & Grouping

- [TODO] **Automatic Edge Bundling**: When 3+ edges share a common source or target and follow similar paths, merge them into a single bundled trunk that fans out near the terminal nodes. The trunk uses a thicker stroke (4px) and each fan-out branch returns to the standard stroke width (2px)
- [TODO] **Bundle Expansion on Hover**: Hovering over an edge bundle smoothly expands it (300ms ease-out) to reveal individual edges, each labeled with its relationship type
- [TODO] **Bundle Color Blending**: The bundled trunk uses a blended color derived from its constituent edges (e.g., gray + purple = muted lavender), reverting to individual colors on expansion
- [TODO] **Manual Bundle/Unbundle**: Right-click a group of selected edges → "Bundle Edges" / "Unbundle Edges" to manually control bundling
- [TODO] **Bundle Label**: Show a count label on the bundle trunk (e.g., "4 connections") with a semi-transparent pill background

### Edge Z-Ordering & Layering

- [TODO] **Edges Behind Nodes**: By default, render all edges behind (below) node elements so that nodes are never obscured by edge paths. Currently React Flow renders edges and nodes in the same SVG layer
- [TODO] **Selected Edge Promotion**: When an edge is selected or hovered, promote it to the top layer so it renders above all other edges and shows its full path clearly
- [TODO] **Focus Mode Edge Layering**: In Operation Focus Mode, focused edges render in a top layer with full opacity; dimmed edges render in a bottom layer at 15% opacity with `pointer-events: none`
- [TODO] **Edge Layer Toggle**: Canvas settings option to toggle between "Edges Behind Nodes" (cleaner) and "Edges Above Nodes" (more visible) rendering modes

### Dynamic Re-Routing on Drag

- [TODO] **Live Re-Route During Drag**: While dragging a node, connected edges should re-route in real-time (throttled at 16ms / 60fps) so the developer can see how the edge path changes as they reposition the node
- [TODO] **Snap-to-Route**: When dragging a node near an alignment position that would produce a cleaner edge route (straight segment instead of bend), show a blue alignment guide and snap the node to that position
- [TODO] **Post-Drag Optimization**: After releasing a node drag, run a single optimization pass on all connected edges to clean up any suboptimal routing introduced during the drag (eliminate unnecessary bends, straighten segments where possible)

### Edge Style Presets

- [TODO] **"Blueprint" Edge Style**: Thin (1.5px) steel-blue edges with sharp 90-degree corners and no radius, suited for technical schematic look
- [TODO] **"Modern" Edge Style**: Medium (2px) edges with 12px corner radius, subtle gradient from source color to target color along the path, and a very faint drop shadow (`filter: drop-shadow(0 1px 2px rgba(0,0,0,0.05))`)
- [TODO] **"Minimal" Edge Style**: Thin (1px) light-gray edges with 6px corner radius, no labels (labels appear on hover only), no animations — maximum canvas cleanliness
- [TODO] **"Neon" Edge Style**: For dark mode; edges use bright saturated colors with a `filter: drop-shadow(0 0 4px <edgeColor>)` glow effect, producing a cyberpunk/IDE aesthetic
- [TODO] **"Hand-Drawn" Edge Style**: Use a `rough.js`-style renderer to give edges a hand-sketched appearance, useful for early design/whiteboard sessions
- [TODO] **Preset Selector**: Dropdown in canvas settings → "Edge Style" with the above presets; each preset adjusts stroke width, color, corner radius, shadow, and animation simultaneously

---

## 17. Node Visual Design System 📋 PLANNED

[TODO] The current node components use ad-hoc Tailwind classes with inconsistent sizing (`shadow-sm` on parameters vs. `shadow-xl` on operations), variable width ranges (`min-w-[220px]`–`max-w-[280px]` on operations vs. `min-w-[320px]`–`max-w-[400px]` on request bodies), and mixed design patterns (gradient headers on some, solid headers on others). A unified visual design system should bring consistency, hierarchy, and polish across all node types while maintaining clear type differentiation.

### Unified Node Shell

- [TODO] **Base Node Component**: Create a shared `PathsBaseNode` wrapper component that all node types extend. It provides consistent outer styling:
  - Border radius: `rounded-xl` (12px) on all nodes
  - Border: `border` (1px) by default, `border-2` (2px) when selected
  - Shadow: `shadow-md` by default, `shadow-lg` on hover, `shadow-xl` when selected. Use a consistent shadow scale instead of per-node ad-hoc shadows
  - Transition: `transition-shadow duration-150 ease-in-out` for smooth hover/selection effects
  - Background: `bg-white dark:bg-zinc-900` (replacing the current `dark:bg-gray-800` for better contrast)
- [TODO] **Consistent Width Grid**: Standardize all nodes to a 280px width (± 20px for content overflow). The current wildly varying widths (200–400px) create a chaotic canvas. Parameters and class nodes should match the operation node width so that vertical alignment works cleanly
- [TODO] **Node Type Icon in Corner**: Each node type gets a small (16px) type-identifying icon in the top-right corner of the header:
  - Operation: HTTP method pill (already exists, refine)
  - Parameter: `Settings2` Lucide icon
  - Response: `Reply` Lucide icon
  - Request Body: `ArrowUpFromLine` Lucide icon
  - Response Body: `ArrowDownToLine` Lucide icon
  - Class: `Box` Lucide icon
- [TODO] **Elevation Hierarchy**: Use shadow depth to communicate node importance:
  - Operation nodes: `shadow-lg` (primary, highest elevation)
  - Response/Request Body nodes: `shadow-md` (secondary)
  - Parameter/Response Body/Class nodes: `shadow-sm` (tertiary)
  - On hover, all nodes increase one level (e.g., `shadow-md` → `shadow-lg`)

### Operation Node Visual Overhaul

- [TODO] **Refined Header**: Replace the current full-width solid-color header with a two-tone design:
  - Left 4px vertical accent bar in the HTTP method color (replacing the full background flood)
  - Header background: `bg-zinc-50 dark:bg-zinc-800` with the method name as a compact pill badge (`px-2 py-0.5 rounded text-xs font-bold text-white`) in the method color
  - Path displayed in `font-mono text-sm` adjacent to the method pill
  - This reduces visual noise from the large blocks of saturated color currently dominating the canvas
- [TODO] **Method Color Accent Bar**: A 4px-wide vertical bar on the left edge of the entire node (not just the header) in the HTTP method color, extending from top to bottom. This provides method identification at a glance without overwhelming color
- [TODO] **Compact Summary Section**: Below the header, show the operationId in `text-xs text-zinc-500 font-mono` and the summary (if set) in `text-xs text-zinc-600 dark:text-zinc-400` truncated to one line with `text-ellipsis overflow-hidden whitespace-nowrap`
- [TODO] **Inline Status Indicators**: A horizontal row of micro-badges below the summary:
  - Parameter count: `📋 3` in `text-[10px]`
  - Response count: `📬 2` in `text-[10px]`
  - Security: 🔒/🔓 icon (8px)
  - Deprecated: ⚠️ with `line-through` on the path text
  - Each badge uses `bg-zinc-100 dark:bg-zinc-800 rounded px-1` for a subtle chip appearance
- [TODO] **Selected State**: When selected, the node border color changes to the method color, border width becomes `3px`, and a subtle outer ring (`ring-2 ring-<methodColor>/30 ring-offset-2`) appears. Current selected styling is minimal and hard to distinguish
- [TODO] **Hover State**: On hover, increase shadow by one level, add `scale-[1.01]` with `transition-transform duration-100`, and show connection-point indicators (small dots) on all four sides of the node

### Connection Point (Handle) Visual Redesign

- [TODO] **Circular Handles**: Replace the current rectangular handles (`!w-3 !h-2 !rounded-t-md !rounded-b-none`) with circular handles (`w-3 h-3 rounded-full`) for a cleaner, more universal look. The rectangular tab-style handles look dated compared to modern diagramming tools
- [TODO] **Handle Visibility**: Handles should be hidden by default (`opacity-0`) and appear (`opacity-100`) with a 100ms fade when the node is hovered or selected. This reduces visual clutter when browsing the canvas
- [TODO] **Handle Glow on Drag**: When the user is dragging from a handle to create a new connection, the compatible target handles on other nodes should pulse with a subtle glow animation (`animate-pulse` with the edge relationship color) to indicate valid drop targets
- [TODO] **Handle Tooltips**: On handle hover, show a tiny tooltip (`text-[10px]`) indicating the connection type: "Connect Parameter", "Connect Response", "Connect Schema"
- [TODO] **Handle Position**: Move handles from the strict top-center/bottom-center positions to side-aware positions:
  - Input handles: left-center or top-center depending on layout direction
  - Output handles: right-center or bottom-center depending on layout direction
  - When layout direction changes (TB vs LR), handles automatically reposition
- [TODO] **Active Handle Ring**: When a handle is being hovered for connection, show a 2px ring around it in the relationship color with `ring-offset-1`

### Parameter Node Refinement

- [TODO] **Compact Chip Design**: Reduce the parameter node to a compact chip layout:
  - Height: fixed 36px (single-line display)
  - Layout: `[location-dot] name : type [required-star]` all on one line
  - Location dot: 8px colored circle (green for path, blue for query, purple for header, orange for cookie) instead of the current colored background
  - Name: `font-mono text-sm font-medium`
  - Type: `text-xs text-zinc-500`
  - Required: red asterisk `*` suffix on the name
- [TODO] **Parameter Location Left Bar**: Similar to the operation method bar, a 3px left border in the location color (green/blue/purple/orange) instead of the full background tint, reducing visual noise
- [TODO] **Expanded Parameter View**: On double-click or hover, expand the chip to show description, constraints (min/max/pattern), example value, and serialization style in a dropdown panel below the chip

### Response Node Refinement

- [TODO] **Status Code Pill Design**: Reduce the response header to a compact status code pill:
  - Status code in a rounded pill (`px-2 py-0.5 rounded-full text-xs font-bold text-white`) using the status color
  - Description text next to the pill in `text-sm`
  - This replaces the current full-width colored header which consumes significant vertical space
- [TODO] **Status Color Left Bar**: A 3px left border in the status code color (green/blue/yellow/red) extending the full height of the node, consistent with the operation node accent bar pattern
- [TODO] **Response Content Preview**: Show a compact one-line preview of the response schema: `{ Pet }` or `[ Pet ]` or `string` in `font-mono text-xs text-zinc-500`, giving developers a quick glance at what the response returns
- [TODO] **Headers Badge**: If the response defines custom headers, show a small `H` badge with a count (e.g., `H:3`) in the top-right corner

### Request/Response Body Node Refinement

- [TODO] **Unified Body Node Design**: Make request and response body nodes follow the same accent-bar design pattern:
  - Request body: 4px left bar in indigo (`border-l-4 border-indigo-500`)
  - Response body: 4px left bar in emerald (`border-l-4 border-emerald-500`)
  - Replace the current gradient headers (`bg-gradient-to-r from-indigo-500 to-purple-600`) with a clean solid header using the accent color as a left bar. Gradients are visually heavy and inconsistent with the leaner accent-bar style on operations
- [TODO] **Content Type Tabs**: Show content types as small tab pills in the header (e.g., `[JSON] [XML] [form-data]`) with the active type highlighted, replacing the current dropdown or full-width display
- [TODO] **Schema Snippet**: Show a 2-3 line JSON schema snippet of the body content in a `font-mono text-[11px] bg-zinc-50 dark:bg-zinc-950 rounded p-1` block within the node, providing immediate context about the body structure

### Class Node Refinement

- [TODO] **Schema Card Design**: Redesign class nodes as compact "schema cards":
  - 4px left bar in indigo (matching the schema canvas styling)
  - Header: Class name in `font-mono text-sm font-semibold` with a small `Box` icon
  - Body: Show the first 3-4 property names in `text-[11px] font-mono text-zinc-500` as a comma-separated list (e.g., `id, name, email, ...+5`)
  - This gives developers an at-a-glance understanding of the referenced schema without opening an editor
- [TODO] **Property Count Badge**: Small badge showing total property count (e.g., `8 props`) in the bottom-right corner
- [TODO] **Link to Schema Canvas**: Small external-link icon in the top-right corner that navigates to this class on the Schema Canvas

### Node Interaction States

- [TODO] **Idle State**: Default appearance with `shadow-md`, `border` (1px), handles hidden
- [TODO] **Hover State**: `shadow-lg`, `scale-[1.01]`, handles visible at `opacity-60`, border darkens slightly
- [TODO] **Selected State**: `shadow-xl`, `border-2` in node accent color, handles visible at `opacity-100`, outer `ring-2` in accent color at 30% opacity
- [TODO] **Dragging State**: `shadow-2xl`, `scale-[1.02]`, `opacity-90`, cursor `grabbing`
- [TODO] **Focused (Focus Mode) State**: Full opacity, `ring-2` in accent color, all connected edges glow
- [TODO] **Dimmed (Focus Mode) State**: `opacity-20`, `pointer-events: none`, `grayscale(50%)`, shadow removed
- [TODO] **Error State**: `ring-2 ring-red-500/50`, small red error badge in top-right corner with tooltip showing the validation error
- [TODO] **Drop Target State**: When a draggable item hovers over a valid drop target node, show a dashed `border-2 border-dashed border-blue-400` with `bg-blue-50/30 dark:bg-blue-950/20` background tint

### Dark Mode Node Palette

- [TODO] **Dark Mode Color Adjustments**: The current dark mode uses `dark:bg-gray-800` which lacks contrast against typical dark canvas backgrounds. Switch to:
  - Node background: `dark:bg-zinc-900` (darker, more contrast)
  - Node border: `dark:border-zinc-700` (visible but not harsh)
  - Header background: `dark:bg-zinc-800/80` (slightly lighter than body)
  - Text: `dark:text-zinc-100` (primary), `dark:text-zinc-400` (secondary)
  - Method/status color pills: Increase saturation by 10% and lightness by 15% in dark mode so colors remain vibrant against the dark background
- [TODO] **Dark Mode Accent Bar Colors**: Slightly lighten the accent bar colors in dark mode:
  - GET: `#4ade80` (from `#22c55e`)
  - POST: `#60a5fa` (from `#3b82f6`)
  - PUT: `#fb923c` (from `#f97316`)
  - PATCH: `#c084fc` (from `#a855f7`)
  - DELETE: `#f87171` (from `#ef4444`)
- [TODO] **Dark Mode Shadows**: Replace traditional `box-shadow` in dark mode with subtle colored glows. E.g., operation nodes get `shadow-[0_0_12px_rgba(99,102,241,0.08)]` (indigo tint) in dark mode instead of the black box-shadow that is invisible against dark backgrounds
- [TODO] **Dark Mode Handle Colors**: Increase handle brightness in dark mode so connection points remain discoverable; use the lightened accent colors from above

### Node Design Presets

- [TODO] **"Professional" Preset** (default): Clean accent bars, minimal shadows, zinc color palette, hidden handles. Suited for enterprise presentations and documentation screenshots
- [TODO] **"Developer" Preset**: Higher information density, monospace fonts throughout, visible handles, code-style borders (`border border-zinc-300 dark:border-zinc-600`), terminal-inspired aesthetic
- [TODO] **"Colorful" Preset**: Full-width colored headers (current style), larger shadows, visible handles, bolder fonts. Suited for workshops, demos, and quick visual scanning
- [TODO] **"Blueprint" Preset**: Navy/cyan color scheme, thin borders, no shadows, grid-aligned nodes, technical drawing aesthetic. Works best with the "Blueprint" edge style preset (Section 16)
- [TODO] **Preset Selector**: Canvas settings → "Node Style" dropdown with live preview thumbnails showing how each preset renders a sample operation node

---

## 18. Canvas Visual Polish & Presentation 📋 PLANNED

[TODO] Beyond individual node and edge styling, the overall canvas needs cohesive visual polish to feel like a premium, enterprise-grade design tool.

### Grid & Background

- [TODO] **Dot Grid Option**: In addition to the current line grid, offer a dot grid (small dots at grid intersections) which is less visually dominant and preferred in modern design tools (Figma, Miro)
- [TODO] **Grid Fade at Zoom**: Fade the grid out when zoom level drops below 40% (the grid becomes too dense to be useful) and fade it in when zoom rises above 50%, using `opacity` transitions
- [TODO] **Isometric Grid**: Optional isometric (30-degree angled) grid for a distinctive 3D-perspective look
- [TODO] **Canvas Region Shading**: Subtly shade canvas regions by path group (e.g., the area around all `/users` operations gets a `bg-blue-500/3` tint, `/products` gets `bg-green-500/3`), providing visual clustering without explicit group containers

### Visual Grouping

- [TODO] **Auto-Generated Group Containers**: Automatically draw rounded-rectangle group containers around operations that share the same base path. Each container gets:
  - Header: Path prefix in `font-mono text-xs text-zinc-500` with a left-colored accent matching the group color
  - Background: `bg-<color>-50/30 dark:bg-<color>-950/20` (very subtle tint)
  - Border: `border border-<color>-200/50 dark:border-<color>-800/50` (dashed)
  - Collapse/expand toggle in the header
- [TODO] **Group Color Auto-Assignment**: Assign group colors from a preset palette (blue, green, amber, violet, rose, cyan, orange, teal) based on path prefix hash, ensuring consistent colors across sessions
- [TODO] **Nested Group Indentation**: For nested paths like `/users/{id}/posts`, show the group container indented within the parent `/users` group container

### Canvas Status Bar

- [TODO] **Bottom Status Bar**: A 28px-tall status bar at the bottom of the canvas showing:
  - Left: Total operations count, parameter count, response count (e.g., "24 operations · 67 parameters · 52 responses")
  - Center: Current edge crossing count and validation status (e.g., "3 crossings · 2 warnings")
  - Right: Zoom level percentage (e.g., "75%"), grid snap status ("Snap: On"), current layout mode ("Layout: Vertical")
- [TODO] **Status Bar Click Actions**: Clicking the zoom percentage opens a zoom dropdown; clicking the validation status opens the validation panel; clicking the crossing count highlights crossing points

### Zoom-Based Detail Levels (Semantic Zoom)

- [TODO] **Zoom Level 100%+ (Detail View)**: Show all node content — method pill, path, operationId, summary, inline parameters, inline responses, status indicators, tags. Full edge labels visible
- [TODO] **Zoom Level 60-100% (Standard View)**: Show method pill + path + status indicators. Collapse inline parameters/responses to count badges only. Edge labels visible
- [TODO] **Zoom Level 30-60% (Overview)**: Show only method pill + path. Hide all interior content. Edge labels hidden. Nodes render as compact cards (fixed 200×40px)
- [TODO] **Zoom Level <30% (Map View)**: Nodes render as small colored rectangles (80×20px) with only the method color visible. Edges render as thin 1px lines. Useful for navigating large API surfaces
- [TODO] **Smooth Level Transitions**: Crossfade between detail levels using `opacity` transitions (150ms) so content doesn't abruptly appear/disappear during zoom

### Animation & Motion

- [TODO] **Node Entrance Animation**: When new nodes are added to the canvas (via drag-and-drop or auto-create), animate them in with `scale-0 → scale-100` and `opacity-0 → opacity-100` over 200ms with a slight `ease-out` bounce
- [TODO] **Node Exit Animation**: When nodes are deleted, animate out with `scale-100 → scale-0` and `opacity-100 → opacity-0` over 150ms
- [TODO] **Edge Draw Animation**: When a new edge is created, animate the path drawing from source to target using SVG `stroke-dasharray` and `stroke-dashoffset` animation over 300ms
- [TODO] **Layout Transition**: When applying auto-layout, animate nodes from their current positions to their new positions over 400ms with `ease-in-out` easing (instead of instant repositioning)
- [TODO] **Reduce Motion Respect**: When the OS-level `prefers-reduced-motion` setting is enabled, disable all animations and apply instant state changes

### Canvas Export Polish

- [TODO] **Export-Optimized Rendering**: When exporting the canvas as PNG/SVG/PDF, render at 2x resolution with anti-aliased edges, hidden handles (connection points), visible edge labels, and a 40px padding around all content
- [TODO] **Light Mode Export**: Always export in light mode (regardless of current theme) unless the user explicitly selects "Export in Dark Mode", since light backgrounds reproduce better in documents and presentations
- [TODO] **Watermark Option**: Optional project name/logo watermark in the bottom-right corner of exported images, configurable in canvas settings

---

# Completed Features Reference

The following features are fully implemented in the Paths Designer:

### Canvas Core ✅ IMPLEMENTED
- ✅ React Flow canvas with custom node types and edge types
- ✅ Drag-and-drop from sidebar to canvas
- ✅ Node creation, deletion, and selection
- ✅ Edge creation and routing (straight, bezier, orthogonal, smart)
- ✅ Canvas background customization (solid, gradient, image, texture, grid)
- ✅ Grid snapping with adjustable size
- ✅ Fit view and zoom controls
- ✅ Auto-layout (Sugiyama-style hierarchical)
- ✅ Dark mode support

### Node Types ✅ IMPLEMENTED
- ✅ Operation nodes with HTTP method color coding
- ✅ Parameter nodes with location color coding
- ✅ Response nodes with status code color bands
- ✅ Request body nodes with multi-content-type support
- ✅ Response body nodes with schema binding
- ✅ Class reference nodes

### Editing ✅ IMPLEMENTED
- ✅ Operation properties: summary, description, operationId, tags, deprecated, x-private, external docs, extensions
- ✅ Parameter properties: name, location, schema type/format/constraints, serialization, required
- ✅ Response properties: status code, description, content types, schema modes, headers, links
- ✅ Request body: content types, inline schema editor, class reference binding, examples
- ✅ Security scheme configuration (API Key, HTTP Bearer/Basic)
- ✅ Drag-and-drop schema binding (drop class onto operation, request body, or response)

### Validation ✅ IMPLEMENTED
- ✅ Unique operation IDs
- ✅ Valid path variable syntax
- ✅ Path variable parameter definitions
- ✅ Required request body content types
- ✅ Valid HTTP status codes
- ✅ Schema reference validation
- ✅ Circular dependency detection
- ✅ Security scheme validation
- ✅ Example value conformance

### Sidebar ✅ IMPLEMENTED
- ✅ Tabbed sidebar: Paths, Operations, Classes, Properties, Security, Servers
- ✅ Path CRUD operations
- ✅ Draggable operations, classes, and properties
- ✅ Search and filter within tabs
- ✅ Auto-create CRUD operations

---

---

## Suggested Enterprise Improvements

> The following features were identified by reviewing the current Paths Designer implementation against enterprise developer expectations, cross-referencing with the canvas improvements roadmap, and analyzing competitive gaps in API design tools (Stoplight Studio, Swagger Editor, Insomnia, Postman). They are organized by priority and impact.

---

### P1. Command Palette for Paths 📋 PLANNED

[TODO] A quick-access command palette (like VS Code `Cmd+K`) to search and execute any Paths Designer action by name, maximizing keyboard-driven developer workflows.

- [TODO] **Trigger**: `Cmd/Ctrl + K` opens a search overlay centered on the canvas
- [TODO] **Action Index**: All actions searchable by name:
  - Navigation: "Go to GET /users", "Go to operation createUser", "Go to path /products/{id}"
  - Creation: "Add path", "Add GET operation", "Add query parameter", "Add 200 response"
  - View: "Fit view", "Toggle minimap", "Toggle compact mode", "Toggle focus mode"
  - Export: "Export OpenAPI YAML", "Export OpenAPI JSON", "Copy as cURL"
  - Layout: "Auto-layout top-to-bottom", "Auto-layout left-to-right"
  - Settings: "Toggle grid", "Toggle snap-to-grid", "Change edge style"
- [TODO] **Fuzzy Matching**: Matches partial and out-of-order terms (e.g., "get user" matches "Go to GET /users/{id}")
- [TODO] **Recent Actions**: Show recently used commands at the top
- [TODO] **Contextual Commands**: When a node is selected, show relevant commands first (e.g., "Add parameter", "Edit operation", "Delete")
- [TODO] **Keyboard Navigation**: Arrow keys to move, Enter to execute, Esc to dismiss

---

### P2. Integrated API Testing Panel 📋 PLANNED

[TODO] Developers need to test their API designs without leaving the Paths Designer. An integrated testing panel eliminates context-switching to external tools.

- [TODO] **Test Button on Nodes**: Each operation node has a "▶ Test" button (or right-click → "Test This Operation")
- [TODO] **Test Panel**: A bottom panel (resizable) opens with:
  - [TODO] Server selector dropdown (populated from OpenAPI servers array)
  - [TODO] Auto-populated request: URL, method, headers, query params, path params, request body from the operation definition
  - [TODO] Editable fields: Modify any parameter/header/body value before sending
  - [TODO] Authentication: Auto-apply security scheme credentials (API key, bearer token)
  - [TODO] Send button with loading indicator
  - [TODO] Response viewer: Status code, headers, body (syntax-highlighted JSON/XML), response time, size
- [TODO] **Environment Variables**: Define variables (e.g., `{{baseUrl}}`, `{{apiKey}}`) and use them across test requests
- [TODO] **Request History**: Log of past test requests with replay button
- [TODO] **cURL Export**: Copy the test request as a cURL command
- [TODO] **Response Validation**: Automatically validate the actual response against the defined response schema; highlight mismatches

---

### P3. Paths Diff & Version Comparison 📋 PLANNED

[TODO] Enterprise teams need to compare API definitions across versions to understand what changed.

- [TODO] **Version Selector**: Dropdown in the toolbar to select a comparison version
- [TODO] **Side-by-Side Diff**: Split the canvas into two linked panels (current version left, comparison version right) that pan/zoom together
- [TODO] **Diff Badges on Nodes**: Each operation shows a badge: "Added" (green), "Modified" (yellow), "Removed" (red), "Unchanged" (no badge)
- [TODO] **Property-Level Diff**: Expand a modified operation to see which parameters, responses, or schemas changed (inline green/red/yellow)
- [TODO] **Diff Navigation**: "Next change" / "Previous change" buttons to jump between differences
- [TODO] **Breaking Change Detection**: Flag changes that are breaking (removed operation, removed required parameter, changed response schema) with a red "BREAKING" badge
- [TODO] **Changelog Generation**: Auto-generate a human-readable changelog from the diff (e.g., "Added POST /users, Modified GET /products response schema, Removed DELETE /legacy-endpoint")
- [TODO] **Cherry-Pick Merge**: Select individual changes from the comparison version to apply to the current version

---

### P4. Paths Annotations & Comments 📋 PLANNED

[TODO] Enterprise design reviews and architecture discussions require the ability to leave comments on API operations.

- [TODO] **Sticky Notes**: Freeform text notes placeable anywhere on the Paths canvas
- [TODO] **Pin Comments to Operations**: Attach a comment bubble to a specific operation node; the bubble moves with the node
- [TODO] **Comment Threads**: Reply to comments, mark as resolved; unresolved comments show a badge on the operation node
- [TODO] **@Mentions**: Tag team members in comments to trigger notifications
- [TODO] **Rich Text**: Markdown support with code blocks for discussing request/response examples
- [TODO] **Comment Filter**: Toggle to show/hide all annotations; filter by resolved/unresolved, by author
- [TODO] **Review Mode**: A dedicated "Review" mode where the canvas is read-only and users can only add/resolve comments
- [TODO] **Comment Export**: Include comments in export reports for offline review

---

### P5. Real-Time Collaboration on Paths 📋 PLANNED

[TODO] Enterprise teams need concurrent editing support on the Paths Designer.

- [TODO] **Presence Indicators**: Show avatar badges of users currently viewing the Paths canvas
- [TODO] **Live Cursors**: Display other users' cursor/selection positions on the canvas in real time
- [TODO] **Conflict-Free Editing**: Use CRDT or operational transform to handle concurrent edits to the same operation
- [TODO] **Change Attribution**: Show who last modified each operation (tooltip or badge)
- [TODO] **Activity Feed**: Sidebar showing a live stream of changes by all users
- [TODO] **Follow Mode**: Click a user's avatar to lock your viewport to their position
- [TODO] **Editing Lock Indicator**: When another user has the editor overlay open for an operation, show a lock icon on that operation node for others

---

### P6. Paths Audit Trail 📋 PLANNED

[TODO] Enterprise compliance requires knowing who changed what and when in the API design.

- [TODO] **Change Log Per Operation**: Every create, update, delete recorded with timestamp + user
- [TODO] **Change Log Per Path**: Aggregated changelog across all operations in a path
- [TODO] **Diff Playback**: Step through the change history chronologically to see the API design evolve
- [TODO] **Blame View**: Color-code operation nodes by last editor
- [TODO] **Export Audit Trail**: CSV/JSON export of all changes for compliance reporting
- [TODO] **Retention Policy**: Configurable retention period for audit entries

---

### P7. Paths Performance Optimization 📋 PLANNED

[TODO] The `PathsCanvasView.tsx` is approximately 3,800 lines. For APIs with 50+ operations, performance and maintainability improvements are critical.

- [TODO] **Extract Custom Hooks**: Move interaction handlers into dedicated hooks:
  - `usePathsOperations` — operation CRUD and state
  - `usePathsDragDrop` — drag-and-drop handlers
  - `usePathsKeyboard` — keyboard shortcut handlers
  - `usePathsFocusMode` — focus/isolation logic
  - `usePathsLayout` — layout algorithm and node positioning
  - `usePathsEdges` — edge creation and routing
- [TODO] **Extract Sub-Components**: Break the render into smaller components:
  - `PathsToolbar` — toolbar above canvas
  - `PathsSearchOverlay` — search functionality
  - `PathsEditorOverlay` — floating editor panel
  - `PathsCodePreview` — OpenAPI preview panel
  - `PathsStatusBar` — bottom status bar
- [TODO] **Lazy-Load Dialogs**: Code-split the editor overlay, export dialog, and import dialog
- [TODO] **Virtualized Node Rendering**: For APIs with 100+ operation nodes, render only visible nodes using React Flow's built-in viewport culling
- [TODO] **Memoize Node Components**: Wrap node components with `React.memo` and memoize expensive data transformations
- [TODO] **Debounce State Updates**: Ensure all API calls and database writes are debounced (300ms) to prevent rapid-fire updates during drag operations

---

### P8. Paths Import Enhancements 📋 PLANNED

[TODO] Importing existing OpenAPI specs into the Paths Designer should be seamless and support more source formats.

- [TODO] **Import from Existing Project Schemas**: Right-click a class on the schema canvas → "Generate CRUD Endpoints" to create paths in the Paths Designer
- [TODO] **Import Postman Collection**: Parse Postman Collection v2.1 and create paths, operations, parameters, request bodies, and responses
- [TODO] **Import Insomnia Workspace**: Parse Insomnia export and map to Paths Designer nodes
- [TODO] **Import HAR File**: Parse HTTP Archive (HAR) files from browser DevTools and reverse-engineer path definitions from recorded traffic
- [TODO] **Import from API Gateway**: Fetch endpoint definitions from AWS API Gateway, Azure APIM, or Kong and create corresponding paths
- [TODO] **Selective Import**: Choose which paths/operations to import from the source (not all-or-nothing)
- [TODO] **Merge Import**: Import into an existing Paths canvas, merging with existing operations and resolving conflicts

---

### P9. Operation Grouping & Resource View 📋 PLANNED

[TODO] Enterprise APIs with 50+ endpoints need visual organization beyond flat lists of nodes.

- [TODO] **Resource Groups**: Automatically group operations by resource (first path segment) into collapsible containers with a colored header (e.g., "Users", "Products", "Orders")
- [TODO] **Tag-Based Groups**: Alternatively group by OpenAPI tags
- [TODO] **Manual Groups**: Drag operations into custom named groups
- [TODO] **Collapsed Group View**: When collapsed, a resource group shows: resource name, operation count, HTTP method pills (e.g., "Users (5 ops) [GET] [POST] [PUT] [DELETE]")
- [TODO] **Group-Level Actions**: Right-click a group for: Expand/Collapse, Add Operation, Delete All Operations, Move Group, Set Tag, Export Group as OpenAPI fragment
- [TODO] **Nested Resources**: Show sub-resources as nested groups (e.g., `/users/{id}/posts` appears as a child group under `/users`)
- [TODO] **Resource Color Coding**: Auto-assign colors to resource groups; persist color choices

---

### P10. Integrated Mock Server 📋 PLANNED

[TODO] Frontend developers need to work against the API design before the backend is built. An integrated mock server eliminates the need for external mock tools.

- [TODO] **One-Click Mock Server**: Button in the toolbar to start a local mock server serving all defined operations
- [TODO] **Example-Based Responses**: Serve example values defined in the spec; fall back to auto-generated data from schemas
- [TODO] **Configurable Latency**: Slider to add artificial response delay (0-5000ms) for realistic testing
- [TODO] **Error Simulation**: Toggle to randomly return error responses (4xx, 5xx) at a configurable rate
- [TODO] **Request Validation**: Validate incoming requests against the defined parameters and request body schemas; return 400 with details on mismatch
- [TODO] **Mock Server URL**: Display the mock server URL (e.g., `http://localhost:4010`) in the toolbar for copying
- [TODO] **Request Log**: Show incoming requests and outgoing responses in a live log panel
- [TODO] **Dynamic Mock Rules**: Define custom response rules (e.g., "If `userId` is 999, return 404")

---

### P11. Paths Accessibility 📋 PLANNED

[TODO] Enterprise products must meet WCAG 2.1 AA accessibility standards.

- [TODO] **Keyboard-Only Navigation**: Tab/Shift+Tab to cycle through nodes; arrow keys to move selected node; Enter to open editor
- [TODO] **Screen Reader Announcements**: ARIA live regions for canvas state changes (operation added, deleted, selected)
- [TODO] **High-Contrast Method Colors**: Ensure HTTP method colors meet 4.5:1 contrast ratio in all themes
- [TODO] **Focus Ring Indicators**: Visible focus outlines on selected operation nodes for keyboard users
- [TODO] **Reduced Motion Mode**: Respect `prefers-reduced-motion` OS setting; disable edge animations and transitions
- [TODO] **Zoom with Keyboard**: `+` / `-` keys to zoom, `0` to reset
- [TODO] **Alt Text for Nodes**: All node elements have descriptive `aria-label` attributes (e.g., "GET /users operation node with 3 parameters and 2 responses")

---

### P12. Dark IDE Theme Integration 📋 PLANNED

[TODO] Developers overwhelmingly prefer dark themes. The Paths Designer should have a first-class dark mode that feels native to dark IDEs.

- [TODO] **Node Colors in Dark Mode**: Adjust HTTP method colors for dark backgrounds (lighter/more saturated variants that maintain contrast)
- [TODO] **Edge Colors in Dark Mode**: Lighter edge colors with higher opacity for visibility on dark canvas
- [TODO] **Code Previews**: Monaco editor in dark theme (VS Code Dark+, Monokai, Dracula)
- [TODO] **Sidebar Dark Theme**: Dark gradient sidebar with subtle borders instead of shadows
- [TODO] **Overlay Dark Theme**: Editor overlay with dark background, light text, colored accents for HTTP methods
- [TODO] **Toolbar Dark Theme**: Dark toolbar with light icons and subtle hover states
- [TODO] **Consistent Theming**: All new components (command palette, search overlay, context menus, tooltips) must respect the current theme
- [TODO] **Blueprint Theme for Paths**: A dedicated "API Blueprint" theme with dark navy background, cyan grid, and neon-accented nodes (developer-aesthetic)

---

### P13. OpenAPI Extension Support 📋 PLANNED

[TODO] Enterprise teams use custom `x-*` OpenAPI extensions for API gateway configuration, documentation metadata, and internal tooling.

- [TODO] **Extension Editor**: In the editor overlay, a dedicated "Extensions" tab with a key-value editor for `x-*` extensions on operations, parameters, and responses
- [TODO] **Common Extension Templates**: Pre-built templates for popular extensions:
  - [TODO] `x-rateLimit` — Rate limiting (requests/second, burst)
  - [TODO] `x-cache` — Caching configuration (TTL, vary-by)
  - [TODO] `x-internal` — Mark operation as internal-only
  - [TODO] `x-stability` — API stability level (alpha, beta, stable)
  - [TODO] `x-permissions` — Required permissions/scopes
  - [TODO] `x-codegen-request-body-name` — OpenAPI Generator hint
  - [TODO] `x-amazon-apigateway-integration` — AWS API Gateway integration
- [TODO] **Extension Visualization**: Show extension badges on operation nodes (e.g., a "Rate Limited" badge when `x-rateLimit` is set)
- [TODO] **Organization Extension Library**: Define organization-wide custom extension schemas that are available across all projects
- [TODO] **Extension Validation**: Validate extension values against their defined schemas

---

### P14. API Metrics & Analytics 📋 PLANNED

[TODO] Provide real-time analytics about the API design to help architects make informed decisions.

- [TODO] **API Surface Area Metrics**:
  - [TODO] Total paths, operations, parameters, responses
  - [TODO] Operations per HTTP method distribution (pie/bar chart)
  - [TODO] Average parameters per operation
  - [TODO] Response coverage (% of operations with 2xx, 4xx, 5xx responses)
  - [TODO] Security coverage (% of operations with security requirements)
- [TODO] **Complexity Score**: Per-operation complexity based on parameter count, response count, schema depth, and content type variety
- [TODO] **Documentation Coverage**: % of operations with descriptions, % of parameters with descriptions, % of responses with examples
- [TODO] **Naming Consistency Score**: Analysis of operationId patterns, path naming conventions, parameter naming patterns
- [TODO] **Metrics Panel**: Collapsible bottom panel or sidebar tab showing all metrics with visual charts
- [TODO] **Metrics Export**: Export metrics as a JSON/CSV report

---

### P15. Swagger UI / ReDoc Preview Panel 📋 PLANNED

[TODO] Developers want to see how their API documentation will look to consumers without leaving the designer.

- [TODO] **Embedded Preview Tab**: A tab in the bottom panel or a split-view option showing a live Swagger UI or ReDoc rendering of the current API spec
- [TODO] **Auto-Refresh**: The preview updates in real-time as the user edits operations, parameters, and responses
- [TODO] **Try It Out**: The embedded Swagger UI "Try It Out" functionality works against the integrated mock server (see P10) or a configured real server
- [TODO] **Toggle Between Swagger UI and ReDoc**: Let developers choose their preferred documentation renderer
- [TODO] **Standalone Preview URL**: Generate a shareable URL that renders the current spec as read-only API documentation (useful for sharing with stakeholders)

---

### P16. Multi-Spec Support & Microservice Coordination 📋 PLANNED

[TODO] Enterprise architectures often involve multiple microservices, each with their own OpenAPI spec. The Paths Designer should support working with multiple specs and understanding cross-service dependencies.

- [TODO] **Multi-Spec Canvas**: Display operations from multiple project versions on the same canvas, color-coded by service
- [TODO] **Cross-Service References**: Visualize when one service's operation references a schema owned by another service
- [TODO] **Service Dependency Map**: A high-level view showing which services depend on which (based on shared schemas and cross-references)
- [TODO] **Unified Search**: Search across all services' operations from a single search box
- [TODO] **Merged Export**: Export a unified OpenAPI spec that combines operations from multiple services (with namespace prefixes to avoid conflicts)
- [TODO] **Gateway View**: Show all operations as they appear through an API gateway (aggregated from multiple microservice specs)
