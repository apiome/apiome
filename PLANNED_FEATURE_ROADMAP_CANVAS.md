# Canvas improvements roadmap

## 🎨 Canvas Improvements (CONSOLIDATED)

> **Purpose**: All canvas-related features consolidated in one place for focused development.
> **Priority**: 🔴 High - Critical for visual schema design experience
> **Timeline**: Q1-Q2 2026
> **Status**: Mix of ✅ Implemented, 🚧 Partial, 📋 Planned

---

### 1. Canvas Layout & Organization

#### Save & Load Layouts ✅ IMPLEMENTED (Basic), 📋 PLANNED (Advanced)
- ✅ **Auto Layout Algorithms**: Top-to-Bottom (TB) and Left-to-Right (LR) hierarchical layouts implemented
- ✅ Top-to-Bottom and Left-to-Right auto-layout algorithms
- ✅ Save current canvas arrangement
- ✅ Save and load groups with layouts
- ✅ **Layout Controls**: Compact button with dropdown menu
- ✅ **Database Table**: Create a database table to store layouts
- ✅ **Auto-load Layout on First Load**: Automatically applies saved layout when canvas loads for the first time
- 📋 [TODO] Multiple saved layouts per version:
    - "Development Layout" - organized for development work
    - "Presentation Layout" - clean arrangement for stakeholder demos
    - "Logical Layout" - grouped by business domain
    - "Dependency Layout" - organized by relationships
- 📋 [TODO] Auto-save layout changes every 30 seconds (configurable)
- 📋 [TODO] Version control for layouts (track layout history)
- 📋 [TODO] Default layout setting per user or per team
- 📋 [TODO] Export layout as JSON for sharing
- 📋 [TODO] Import layouts from other versions/projects
- ✅ Add simple orthagonal edge routing after auto-layout

| Ticket | Feature                                       |
|--------|-----------------------------------------------|
| #163   | Multiple saved layouts per version            |
| #164   | Auto-save layout changes (tuneable interval)  |
| #165   | Version control for layouts                   |
| #166   | Default layout setting per user or per team   |
| #167   | Export/import layouts as JSON                 |
| #314   | Canvas snapshots                              |
| #315   | Canvas auto-save of layout                    |
| #316   | Export/import canvas layouts                  |

#### Layout Snapshots 📋 PLANNED
- 📋 [TODO] Take quick snapshots of current layout
- 📋 [TODO] Thumbnail preview of each snapshot
- 📋 [TODO] Restore any snapshot with one click
- 📋 [TODO] Compare two snapshots side-by-side
- 📋 [TODO] Snapshot gallery view with search/filter
- 📋 [TODO] Auto-snapshots before major changes
- 📋 [TODO] Snapshot metadata: timestamp, author, description

| Ticket | Feature                                           |
|--------|---------------------------------------------------|
| #168   | Take quick snapshots of current layout            |
| #169   | Thumbnail preview of each snapshot                |
| #170   | Restore any snapshot with one click               |
| #171   | Compare two snapshots side-by-side                |
| #172   | Snapshot gallery view with search/filter          |
| #173   | Snapshot metadata: timestamp, author, description |

#### Layout Sharing 📋 PLANNED
- 📋 [TODO] Share layout configurations with team members
- 📋 [TODO] "Pin" layout as team default
- 📋 [TODO] Layout permissions (view, edit, delete)
- 📋 [TODO] Layout comments and annotations
- 📋 [TODO] Layout versioning with diff viewer

| Ticket | Feature                                       |
|--------|-----------------------------------------------|
| #174   | Share layout configurations with team members |
| #175   | "Pin" layout as team default                  |
| #176   | Layout permissions (view, edit, delete)       |
| #177   | Layout comments and annotations               |
| #178   | Layout versioning with diff viewer            |

---

### 2. Canvas Navigation & Controls

#### Node Visibility Controls 📋 PLANNED
- 📋 [TODO] Hide/show individual nodes
- 📋 [TODO] Hide all nodes except selected
- 📋 [TODO] Hide by criteria:
  - [TODO] Hide all empty classes (no properties)
  - [TODO] Hide all classes without relationships
  - [TODO] Hide deprecated classes
  - [TODO] Hide by group membership
- 📋 [TODO] "Ghosts mode": Show hidden nodes as semi-transparent
- 📋 [TODO] Quick restore hidden nodes

| Ticket | Feature Description            |
|--------|--------------------------------|
| #481   | Hide/show individual nodes     |
| #482   | Hide all nodes except selected |
| #483   | Hide by criteria               |
| #484   | "Ghosts mode" for hidden nodes |
| #485   | Quick restore hidden nodes     |

#### Focus Mode 📋 PLANNED
- ✅ Isolate selected classes and immediate relationships
- 📋 [TODO] Blur/dim non-focused nodes
- 📋 [TODO] Show only 1st-degree connections (or 2nd, 3rd degree)
- 📋 [TODO] Expand focus incrementally
- 📋 [TODO] Focus on group (show only group members)
- 📋 [TODO] Exit focus mode with Esc key

| Ticket | Feature Description                        |
|--------|--------------------------------------------|
| #487   | Blur/dim non-focused nodes                 |
| #488   | Show only Nth-degree connections           |
| #489   | Expand focus incrementally                 |
| #490   | Focus on group members                     |
| #491   | Exit focus mode with Esc key               |

#### Visual Feedback
- 📋 [TODO] **Dropzone highlighting**: Visual cues for valid drop targets
- 📋 [TODO] **Ghost preview**: Show preview while dragging
- 📋 [TODO] **Invalid drop indicator**: Clear feedback for invalid drops
- 📋 [TODO] **Snap indicators**: Show snap points during drag

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|
| #477   | Add dropzone highlighting when dragging nodes    |
| #478   | Show ghost preview of node while dragging        |
| #479   | Invalid drop indicator                           |
| #480   | Snap indicators when dragging nodes              |

---

### 3. Node Grouping & Organization

#### Group Containers 📋 PARTIALLY IMPLEMENTED
- ✅ Create visual containers to group related classes together
- ✅ Color-coded groups with custom names (e.g., "Authentication Models", "Payment Services")
- ✅ Drag and drop classes into groups to join them
- ✅ Visual highlight when dragging nodes over a group (green ring)
- ✅ Confirmation dialog when removing a class from a group (only when completely outside group bounds)
- ✅ Cancel ungroup snaps node back inside the group bounds
- ✅ Moving a group moves all contained classes together
- ✅ Nodes stay within group when partially overlapping - only ungroup when completely outside
- ✅ Grouped nodes are locked to group bounds during dragging - cannot escape unless dragged completely outside
- 📋 [TODO] Collapsible groups to reduce canvas clutter
  - 📋 [TODO] Click to collapse: shows only group title and count
  - 📋 [TODO] Expand/collapse all groups with keyboard shortcut
  - 📋 [TODO] Remember collapsed state per user
- 📋 [TODO] Nested groups for hierarchical organization (max 3 levels)
- 📋 [TODO] Group-level operations:
  - ✅ Move entire group with one drag
  - 📋 [TODO] Delete all classes in a group
- ✅ Named groups with descriptions and metadata
- ✅ Visual styling options:
  - ✅ Rounded rectangle containers with subtle shadows
  - ✅ Dashed or solid borders with custom colors
  - 📋 [TODO] Group headers with collapse/expand icons
  - ✅ Background color/opacity customization
  - ✅ Optional group icons from icon library
- ✅ Group object is drag-and-drop to the canvas

| Ticket | Feature                                                             |
|--------|---------------------------------------------------------------------|
| #154   | Collapsible groups to reduce canvas clutter                         |
| #155   | Nested groups for hierarchical organization                         |
| #156   | Group-level operations: move, delete, export, duplicate, bulk edit  |
| #285   | Ungroup nodes by deleting the group                                 |
| #515   | Delete all classes in a group                                       |
| #516   | Group headers with collapse/expand icons                            |

---

### 4. Visual Customization

#### Node Styling 📋 PLANNED
- ✅ **Custom Colors**:
  - ✅ Per-class color picker
  - ✅ Color by group
  - ✅ Color by stereotype (entity, service, DTO)
  - ✅ Color gradients for nodes
  - ✅ Color themes (Material, Pastel, Corporate)
- ✅ **Node Icons**:
  - ✅ Built-in icon library (100+ icons)
  - ✅ Icon picker with search by name/category
  - ✅ Remove icon option (show initials)
  - 📋 [TODO] Custom icon upload
  - 📋 [TODO] Icons from icon packs (Font Awesome, Material Icons)
  - 📋 [TODO] Icon position (left, center, badge)
- 📋 [TODO] **Node Sizing**:
  - 📋 [TODO] Auto-size based on content
  - 📋 [TODO] Fixed size (small, medium, large, extra-large)
  - 📋 [TODO] Custom width and height
  - 📋 [TODO] Size by property count
  - 📋 [TODO] Compact mode (show only class name)
- 📋 [TODO] **Node Shapes**:
  - 📋 [TODO] Rectangle (default), Rounded rectangle
  - 📋 [TODO] Circle/ellipse, Hexagon, Diamond
  - 📋 [TODO] Custom SVG shapes
- 📋 [TODO] **Node Borders**:
  - 📋 [TODO] Border thickness (1-5px)
  - 📋 [TODO] Border style (solid, dashed, dotted)
  - 📋 [TODO] Shadow effects (drop shadow, inner shadow)

| Ticket | Feature Description           |
|--------|-------------------------------|
| #341   | Custom node sizing            |
| #342   | Add node border configuration |
| #343   | Add custom node label styling |

#### Edge/Relationship Styling ✅ PARTIALLY IMPLEMENTED
- ✅ Different line styles for relationship types:
  - ✅ Solid for direct references
  - ✅ Dashed for optional references
  - ✅ Dotted for weak references
  - ✅ Double lines for bidirectional
- ✅ Edge colors customizable
- 📋 [TODO] Edge labels (show property name on relationship)
- ✅ Edge routing options:
  - ✅ Straight lines
  - ✅ Curved (Bezier)
  - ✅ Orthogonal (right angles)
  - ✅ Smart routing (avoid node overlap)
- ✅ Arrow styles: Standard, Diamond, Circle, Open arrow
- ✅ Animated edges (flowing dots for data flow)

| Ticket | Feature Description                   |
|--------|---------------------------------------|
| #349   | Adds edge hover effects               |

---

### 4.1 Smart Canvas Features

**Intelligent Layout Suggestions** ✅ PARTIALLY IMPLEMENTED
- ✅ "Auto-organize" button with multiple suggestions (8 layout algorithms)
- 📋 [TODO] Preview suggestions before applying
- [TODO] Rating system for suggestions (thumbs up/down to improve)
- [TODO] Machine learning from user preferences

| Ticket | Feature Description                        |
|--------|--------------------------------------------|
| #471   | Preview layout suggestions before applying |

**Canvas Analysis** ✅ PARTIALLY IMPLEMENTED
- **Schema Metrics**:
  - ✅ Total classes, properties, relationships
  - 📋 [TODO] Average properties per class
  - 📋 [TODO] Most connected classes (hubs)
  - 📋 [TODO] Isolated classes (no relationships)
  - 📋 [TODO] Deepest dependency chains
  - 📋 [TODO] Circular dependencies count
- **Layout Quality Score**:
  - 📋 [TODO] Edge crossing count (lower is better)
  - 📋 [TODO] Node spacing uniformity
  - 📋 [TODO] Layout symmetry
  - 📋 [TODO] Visual balance
- **Suggestions**:
  - 📋 [TODO] "Reduce edge crossings by switching to hierarchical layout"
  - 📋 [TODO] "Group these 5 classes - they're all related"
  - 📋 [TODO] "Class X is isolated - consider adding relationships"
  - 📋 [TODO] "Large clusters detected - consider splitting into groups"

| Ticket | Feature Description                    |
|--------|----------------------------------------|
| #472   | Add Schema Metrics view to the canvas  |
| #473   | Layout Quality Score calculation       |
| #474   | Canvas improvement suggestions         |

**Canvas Performance Optimizations** 📋 PARTIALLY IMPLEMENTED
- **Virtual Rendering**:
  - ✅ Render only visible nodes (viewport culling)
  - ✅ Node pooling and recycling
  - ✅ Progressive rendering for large schemas (1000+ nodes)
  - [TODO] Canvas split into chunks/tiles
- **Level of Detail (LOD)**: ✅ IMPLEMENTED
  - ✅ When zoomed out >200%, show simplified nodes
  - ✅ At high zoom, hide property details, show only class names
  - ✅ Dynamic detail based on zoom level
  - ✅ Fade transitions between LOD levels
  - [TODO] Show canvas node detail for properties that reference others even when collapsed
  - ✅ Level of detail toggling mode
- **Caching**:
  - ✅ Cache rendered node SVG/Canvas elements
  - ✅ Cache layout calculations
  - ✅ Cache relationship paths
  - ✅ Invalidate cache only on changes
- **Web Workers**:
  - [TODO] Layout calculations in background thread
  - [TODO] Node rendering in worker (OffscreenCanvas)
  - [TODO] Relationship path calculations async
  - [TODO] Non-blocking canvas operations
- **Request Animation Frame**:
  - ✅ Smooth 60fps animations
  - ✅ Batch DOM updates
  - ✅ Throttle mouse move events
- **Memory Management**:
  - 📋 [TODO] Lazy load node properties
  - [TODO] Unload off-screen nodes
  - [TODO] Garbage collect unused elements
  - ✅ Memory profiling tools

| Ticket | Feature Description             |
|--------|---------------------------------|
| #475   | Lazy loading of node properties |

---

### 5. Annotations & Documentation

#### Presentation Mode 📋 PLANNED
- 📋 [TODO] Full-screen canvas mode with hidden UI
  - 📋 [TODO] Hide all toolbars and UI
  - 📋 [TODO] Slide-show of bookmarked areas
  - 📋 [TODO] Presentation notes (speaker view)
  - 📋 [TODO] Timer and slide counter
  - 📋 [TODO] Presenter controls (keyboard shortcuts)

| Ticket | Feature Description                  |
|--------|--------------------------------------|
| #517   | Full-screen presentation mode        |

#### Charts & Metrics ✅ PARTIALLY COMPLETE
- ✅ **Quality score gauge**: Visual score indicator (0-100)
- ✅ **Complexity charts**: Schema complexity visualization
- 📋 [TODO] **Relationship graphs**: Visual dependency maps
- 📋 [TODO] **Timeline views**: Schema evolution over time

| Ticket | Feature Description                          |
|--------|----------------------------------------------|
| #322   | Display the relationship graph for a schema  |
| #323   | Timeline view of schema changes over time    |

---

### 8. Canvas Export

#### Export Options ✅ PARTIALLY IMPLEMENTED

**Canvas Export Options**
- **Export Formats**:
  - ✅ PNG (raster image)
  - ✅ JPG (photo quality)
  - ✅ SVG (vector, scalable)
  - ✅ PDF (document format)
  - ✅ Mermaid diagram code
  - ✅ PlantUML code
  - ✅ GraphML (for yEd, Gephi)
  - ✅ DOT (Graphviz)
  - ✅ JSON (raw data)
- **Export Wizard**: ✅ IMPLEMENTED
  - ✅ Modal dialog with sidebar for export format selection
  - ✅ Live preview of export
  - ✅ Format-specific options (resolution, quality, page size, etc.)
  - ✅ Categories: Images, Documents, Diagram Code
- **High-Resolution Export**:
  - ✅ 1x (default), 2x, 4x resolution options
  - 📋 [TODO] Customizable DPI (72, 150, 300, 600)
  - 📋 [TODO] Export dimensions in pixels or cm/inches
- **Selective Export**:
  - [TODO] Export only selected nodes
  - 📋 [TODO] Export current viewport
  - 📋 [TODO] Export specific groups
  - ✅ Export entire canvas
- **Export Options**:
  - ✅ Export wizard interface (replaces dropdown)
  - 📋 [TODO] Include/exclude UI elements
  - 📋 [TODO] Include/exclude grid
  - [TODO] Include/exclude annotations
  - [TODO] Include/exclude hidden nodes
  - ✅ Background color/transparency toggle
  - 📋 [TODO] Add watermark
  - 📋 [TODO] Add timestamp and metadata
- **Batch Export**:
  - [TODO] Export all groups separately
  - [TODO] Export each layout snapshot
  - [TODO] Export multiple formats at once
- **Animated Export**:
  - [TODO] Export layout transitions as animated GIF
  - [TODO] Export canvas walkthrough as video (WebM, MP4)
  - [TODO] Adjustable frame rate and duration
  - [TODO] Add narration (audio recording)

| Ticket | Feature Description                        |
|--------|--------------------------------------------|
| #403   | Export the current viewport                |
| #404   | Export specific groups                     |
| #406   | Include/exclude UI elements                |
| #407   | Include/exclude grid                       |
| #408   | Export option to add watermark             |
| #409   | Add timestamp and metadata                 |

---

### Canvas Keyboard Shortcuts Reference

| Shortcut               | Action               | Status |
|------------------------|----------------------|--------|
| `Cmd/Ctrl + Z`         | Undo                 | [TODO] |
| `Cmd/Ctrl + Shift + Z` | Redo                 | [TODO] |
| `Cmd/Ctrl + F`         | Search canvas        | ✅     |
| `Cmd/Ctrl + H`         | Toggle history panel | [TODO] |
| `M`                    | Toggle minimap       | [TODO] |
| `Cmd/Ctrl + 1-9`       | Jump to bookmark     | [TODO] |
| `Space + Drag`         | Pan canvas           | ✅     |
| `Scroll`               | Zoom in/out          | ✅     |
| `Esc`                  | Exit focus mode / close search | ✅ |
| `Delete`               | Delete selected      | [TODO] |
| `Cmd/Ctrl + G`         | Group selected nodes | [TODO] |
| `Cmd/Ctrl + Shift + G` | Ungroup              | [TODO] |
| `Cmd/Ctrl + C`         | Copy selected nodes  | [TODO] |
| `Cmd/Ctrl + V`         | Paste nodes          | [TODO] |
| `Cmd/Ctrl + D`         | Duplicate selected   | [TODO] |
| `Cmd/Ctrl + A`         | Select all nodes     | [TODO] |
| `Cmd/Ctrl + E`         | Open export wizard   | [TODO] |
| `Cmd/Ctrl + S`         | Save layout          | [TODO] |
| `Cmd/Ctrl + K`         | Command palette      | [TODO] |

---

### 10. Schema Visualization & Analytics

#### Dependency Visualization 📋 PLANNED
- 📋 [TODO] Interactive dependency graph overlay on canvas
- 📋 [TODO] Highlight circular dependencies with warning indicators
- 📋 [TODO] Show dependency depth levels (1st, 2nd, 3rd degree)
- 📋 [TODO] "Impact Analysis" mode: Show all affected classes when changing one
- 📋 [TODO] Upstream/downstream dependency toggles
- 📋 [TODO] Dependency path highlighting (click to trace full chain)
- 📋 [TODO] Dependency metrics per class (in-degree, out-degree, betweenness)

| Ticket | Feature                                                             |
|--------|---------------------------------------------------------------------|
| #547   | Interactive dependency graph overlay on canvas                      |
| #548   | Highlight circular dependencies with warning indicators             |
| #549   | Show dependency depth levels (1st, 2nd, 3rd degree)                 |
| #550   | "Impact Analysis" mode: Show all affected classes when changing one |
| #551   | Upstream/downstream dependency toggles                              |
| #552   | Dependency path highlighting (click to trace full chain)            |
| #553   | Dependency metrics per class (in-degree, out-degree, betweenness)   |

#### Schema Metrics Dashboard 📋 PLANNED
- 📋 [TODO] Real-time metrics overlay on canvas:
  - 📋 [TODO] Total classes, properties, relationships count
  - 📋 [TODO] Schema complexity score
  - 📋 [TODO] Documentation coverage percentage
  - 📋 [TODO] Naming convention compliance
- 📋 [TODO] Per-node metrics badges (property count, relationship count)
- 📋 [TODO] Heatmap visualization:
  - 📋 [TODO] By complexity (more complex = warmer color)
  - 📋 [TODO] By change frequency (recently modified = highlighted)
  - 📋 [TODO] By usage/reference count
  - 📋 [TODO] By documentation completeness
- 📋 [TODO] Trend indicators (improving/declining metrics)

| Ticket | Feature                                        |
|--------|------------------------------------------------|
| #554   | Real-time metrics overlay on canvas            |
| #555   | Total classes, properties, relationships count |
| #556   | Schema complexity score                        |
| #557   | Documentation coverage percentage              |
| #558   | Naming convention compliance                   |
| #559   | Per-node metrics badges                        |
| #560   | Heatmap visualization to version dashboard     |
| #561   | Trend indicators (improving/declining metrics) |

---

# Completed

**Constraint Visualization** ✅ IMPLEMENTED
- Visual indicators for constraints on canvas:
  - ✅ Required (bold border)
  - ✅ Optional (dashed border)
  - ✅ Deprecated (strikethrough with badge)
  - ✅ Validated (checkmark badge)
  - ✅ Enum indicator badge
  - ✅ Edge cardinality visualization
- ✅ Constraint tooltips on hover
- ✅ Constraint summary panel
- ✅ Tags displayed on class nodes

**Grid & Alignment:** ✅ IMPLEMENTED
- ✅ **Grid snapping** (adjustable size: 10-50px with 5px increments) - ✅ FULLY IMPLEMENTED
  - ✅ Snap-to-grid toggle (ON/OFF)
  - ✅ Grid size slider control in settings (10-50px in 5px steps)
  - ✅ Real-time grid size adjustment
  - ✅ Visual feedback with grid patterns
  - ✅ Snapping applies to node dragging and positioning
- ✅ **Grid style options** - ✅ IMPLEMENTED
  - ✅ Dots pattern (default)
  - ✅ Lines pattern (grid lines)
  - ✅ Cross pattern (crosshatch)
  - ✅ Grid style selector in StudioHeader settings
  - ✅ Real-time grid style switching
  - ✅ Persistent grid style preference (localStorage)
- ✅ Smart guides on drag
- ✅ Equal spacing tools

#### Version Comparison View ✅ COMPLETE
- ✅ Side-by-side canvas comparison of two versions
- ✅ Diff highlighting:
  - ✅ Green for added classes/properties
  - ✅ Red for removed classes/properties
  - ✅ Yellow for modified classes/properties
- ✅ Filter diff by change type (additions, removals, modifications)

#### Application Themes ✅ IMPLEMENTED
- ✅ Pre-built themes:
  - ✅ Light mode (default)
  - ✅ Dark mode
  - ✅ High contrast
  - ✅ Blueprint (blue grid on dark)
  - ✅ Whiteboard (minimal)
  - ✅ Solarized
  - ✅ Nord
  - ✅ Darcula
- ✅ Theme selector in profile menu
- ✅ Visual theme preview with color swatches
- ✅ Persistent theme selection (localStorage)
- ✅ Automatic system preference detection

#### Navigation & Controls ✅ IMPLEMENTED
- ✅ **Minimap**: Bird's-eye view with viewport highlighting (bottom-right)
- ✅ **Zoom Controls**: Mouse wheel, zoom to fit, zoom presets (25%-200%)
  - ✅ Zoom to selection (fit selected nodes)
  - ✅ Zoom presets: 25%, 50%, 100%, 150%, 200%
  - ✅ Zoom slider in toolbar
- ✅ **Pan & Drag**: Middle-click or space+drag, smooth panning
  - ✅ Pan with middle mouse button or space+drag
  - ✅ Pan to edges on node drag
- ✅ **Canvas Search** (Cmd+F): Search for classes with highlighting
  - ✅ Search box opens with Cmd+F / Ctrl+F keyboard shortcut
  - ✅ Type to filter - matching nodes highlighted
  - ✅ Non-matching nodes dimmed (search focus mode)
  - ✅ Shows count of matching nodes
  - ✅ Close with Escape key or X button
- ✅ **Search Focus Mode**: Dim everything except search results
- ✅ **Focus Mode**: Isolate selected classes and relationships, blur non-focused

#### Canvas Background ✅ IMPLEMENTED
- ✅ Background options (solid color, grid pattern, custom image, gradient, textures)
- ✅ Background opacity and blur

### 2. Canvas Navigation & Controls

#### Search & Focus ✅ IMPLEMENTED
- ✅ Global search box (`Cmd+F`) to find classes
- ✅ Search as you type with highlighting
- ✅ Matching nodes highlighted, non-matching nodes dimmed
- ✅ Click result to focus and zoom to class on canvas
- ✅ "Focus Mode": Dim everything except search results
  - ✅ Isolate selected classes and immediate relationships
  - ✅ Blur/dim non-focused nodes
  - ✅ Show only 1st-degree connections (or 2nd, 3rd degree)
  - ✅ Expand focus incrementally
  - ✅ Focus on group (show only group members)
  - ✅ Exit focus mode (Esc key)
- ✅ Search history (recent searches) with clear option
- ✅ Search filters: by type, group, properties
- ✅ Regex search support
- ✅ Search within property names/descriptions

### 7. Canvas Performance ✅ IMPLEMENTED

#### Level of Detail (LOD) ✅ IMPLEMENTED
- ✅ Simplified nodes when zoomed out >200%
- ✅ Hide property details at high zoom, show only class names
- ✅ Dynamic detail based on zoom level
- ✅ Fade transitions between LOD levels
- ✅ Show property references even when nodes are collapsed

---

---

## Suggested Enterprise Improvements

> The following features were identified by reviewing the current canvas implementation against enterprise user expectations. They are organized by priority.

### 11. Undo/Redo System 📋 PLANNED

[TODO] The canvas currently has **no undo/redo** capability. This is the single most critical missing feature for enterprise use, as any accidental class deletion, edge removal, node move, or property edit is irreversible without reloading.

- [TODO] **Undo stack** with configurable depth (default 50, max 500 operations)
- [TODO] **Tracked operations**: class create/delete/rename/move, property add/edit/delete, edge create/delete, group operations, layout changes
- [TODO] **Keyboard shortcuts**: `Cmd/Ctrl + Z` (Undo), `Cmd/Ctrl + Shift + Z` (Redo)
- [TODO] **History panel** (`Cmd/Ctrl + H`): Visual timeline of all changes with the ability to jump to any point
- [TODO] **Operation coalescing**: Rapid sequential moves of the same node are collapsed into a single undo entry
- [TODO] **Persistent undo across sessions**: Optionally persist undo stack to database so changes survive page reload

---

### 12. Command Palette 📋 PLANNED

[TODO] A quick-access command palette (like VS Code `Cmd+K`) to search and execute any canvas action by name, improving discoverability and keyboard-driven workflows.

- [TODO] **Trigger**: `Cmd/Ctrl + K` opens an overlay search box
- [TODO] **Action index**: All canvas actions searchable by name (e.g., "Save Layout", "Export as PNG", "Auto-organize", "Toggle Grid", "Create Group", "Zoom to Fit")
- [TODO] **Fuzzy matching**: Matches partial and out-of-order terms
- [TODO] **Recent actions**: Show recently used commands at the top
- [TODO] **Contextual commands**: Show different commands based on what is selected (e.g., when a node is selected, show "Delete Class", "Edit Properties", "Change Color")
- [TODO] **Keyboard navigation**: Arrow keys to move, Enter to execute, Esc to dismiss

---

### 13. Copy/Paste & Duplicate Nodes 📋 PLANNED

[TODO] Enterprise users expect standard clipboard operations on the canvas.

- [TODO] **Copy** (`Cmd/Ctrl + C`): Copy selected class nodes to an internal clipboard (including properties and schema)
- [TODO] **Paste** (`Cmd/Ctrl + V`): Paste copied nodes onto the canvas at the cursor position with de-duplicated names (e.g., "User" becomes "User (Copy)")
- [TODO] **Duplicate** (`Cmd/Ctrl + D`): In-place duplicate of selected nodes offset by a small amount
- [TODO] **Cross-version paste**: Copy a class from one version and paste into another
- [TODO] **Multi-select copy**: Copy multiple classes with their inter-relationships preserved

---

### 14. Canvas Annotations & Comments 📋 PLANNED

[TODO] No annotation or comment system exists on the canvas. Enterprise design reviews and architecture discussions require the ability to leave comments on the schema.

- [TODO] **Sticky notes**: Freeform text notes placeable anywhere on the canvas (distinct from class nodes)
- [TODO] **Pin comments to nodes**: Attach a comment bubble to a specific class or property
- [TODO] **Comment threads**: Reply to comments, mark as resolved
- [TODO] **@Mentions**: Tag team members in comments to notify them
- [TODO] **Rich text**: Markdown support in comments with code snippets
- [TODO] **Comment visibility toggle**: Show/hide all annotations without deleting them
- [TODO] **Comment export**: Include or exclude annotations when exporting canvas images

---

### 15. Canvas Bookmarks & Waypoints 📋 PLANNED

[TODO] Large schemas (50+ classes) require spatial navigation aids beyond the minimap.

- [TODO] **Bookmarks** (`Cmd/Ctrl + 1-9`): Save up to 9 named viewport positions (x, y, zoom) per version
- [TODO] **Bookmark panel**: List all bookmarks with thumbnail previews
- [TODO] **Jump to bookmark**: Smooth animated pan/zoom to bookmarked position
- [TODO] **Bookmark sharing**: Bookmarks saved per-user but shareable as deep links
- [TODO] **Auto-bookmarks**: Auto-create bookmarks for each group centroid

---

### 16. Real-Time Collaboration 📋 PLANNED

[TODO] The canvas has no multi-user collaboration support. For enterprise teams, concurrent editing is expected.

- [TODO] **Presence indicators**: Show avatar badges of users currently viewing the canvas
- [TODO] **Live cursors**: Display other users' cursor positions on the canvas in real time
- [TODO] **Operational Transform or CRDT**: Conflict-free concurrent edits to nodes, edges, and properties
- [TODO] **Change attribution**: Show who last modified each class (tooltip or badge)
- [TODO] **Conflict resolution UI**: When two users edit the same class simultaneously, present a merge dialog
- [TODO] **Activity feed**: Sidebar showing a live stream of canvas changes by all users
- [TODO] **Follow mode**: Click a user's avatar to lock your viewport to their position

---

### 17. Canvas Audit Trail 📋 PLANNED

[TODO] Enterprise compliance requires knowing who changed what and when on the canvas.

- [TODO] **Change log per class**: Every create, update, delete, move recorded with timestamp + user
- [TODO] **Change log per version**: Aggregated changelog across all classes in a version
- [TODO] **Canvas diff playback**: Step through the change history chronologically to see the canvas evolve
- [TODO] **Blame view**: Color-code nodes by last editor (who touched it most recently)
- [TODO] **Export audit trail**: CSV/JSON export of all changes for compliance reporting
- [TODO] **Retention policy**: Configurable how long audit entries are kept

---

### 18. Improved Editor Page Architecture 📋 PLANNED

[TODO] The main editor page (`page.tsx`) is approximately 5,100 lines. This hurts maintainability, code review velocity, and bundle splitting.

- [TODO] **Extract custom hooks**: Move canvas interaction handlers into dedicated hooks (`useCanvasInteractions`, `useCanvasSearch`, `useCanvasGroups`, `useCanvasLayout`, `useCanvasKeyboard`)
- [TODO] **Extract sub-components**: Break the render into smaller components (`CanvasToolbar`, `CanvasSearchPanel`, `CanvasSettingsSheet`, `CanvasStatusBar`)
- [TODO] **Lazy-load dialogs**: Code-split heavy dialogs (export wizard, settings, class edit) so they do not bloat the initial canvas bundle
- [TODO] **Reduce re-renders**: Audit `useEffect` dependency arrays and memoize expensive computations (the file has numerous large dependency arrays that likely trigger unnecessary re-renders)
- [TODO] **Performance profiling**: Add React DevTools Profiler markers for layout calculations, node rendering, and search filtering to identify bottlenecks on large canvases

---

### 19. Canvas-Level Validation & Linting 📋 PLANNED

[TODO] Provide real-time feedback on schema design quality directly on the canvas, beyond the existing quality score.

- [TODO] **Dangling reference warnings**: Highlight properties that reference non-existent classes with a red badge on the edge
- [TODO] **Circular dependency detection**: When a circular reference is created, show a warning toast and highlight the cycle on the canvas
- [TODO] **Naming convention lint**: Warn when class or property names violate configurable naming rules (e.g., PascalCase for classes, camelCase for properties)
- [TODO] **Unused class detection**: Dim or badge classes that are not referenced by any other class
- [TODO] **Required property audit**: Badge classes where required properties have no description or no type
- [TODO] **Schema complexity warnings**: Warn when a single class exceeds a configurable property count threshold (e.g., 30+ properties suggests the class should be decomposed)
- [TODO] **Lint panel**: A toggleable sidebar listing all lint warnings with click-to-navigate

---

### 20. Canvas Accessibility 📋 PLANNED

[TODO] Enterprise products are expected to meet WCAG 2.1 AA accessibility standards.

- [TODO] **Keyboard-only navigation**: Tab/Shift+Tab to cycle through nodes, arrow keys to move selected node, Enter to open edit dialog
- [TODO] **Screen reader announcements**: ARIA live regions for canvas state changes (node created, deleted, moved)
- [TODO] **High-contrast edge colors**: Ensure all edge colors meet 4.5:1 contrast ratio in both light and dark modes
- [TODO] **Focus ring indicators**: Visible focus outlines on selected nodes and edges for keyboard users
- [TODO] **Reduced motion mode**: Respect `prefers-reduced-motion` OS setting; disable edge animations and LOD transitions
- [TODO] **Zoom with keyboard**: `+` / `-` keys to zoom in/out, `0` to reset zoom

---

### 21. Canvas Import from External Tools 📋 PLANNED

[TODO] Enterprise teams migrate from existing diagramming tools. Support importing canvas layouts from common formats.

- [TODO] **Import from Draw.io / diagrams.net**: Parse `.drawio` XML and create classes + relationships on canvas
- [TODO] **Import from Lucidchart**: Parse exported JSON/CSV and map to canvas nodes
- [TODO] **Import from Mermaid**: Parse Mermaid class diagram syntax and create corresponding schema
- [TODO] **Import from PlantUML**: Parse PlantUML class diagram and create corresponding schema
- [TODO] **Import from ERD tools** (dbdiagram.io, pgModeler): Parse SQL DDL or DBML and map to classes

---

### 22. Canvas Minimap Enhancements 📋 PLANNED

[TODO] The minimap is functional but could be improved for large schemas.

- [TODO] **Group highlighting in minimap**: Color-code minimap regions by group
- [TODO] **Minimap node badges**: Show tiny color indicators for validation warnings
- [TODO] **Minimap click-to-zoom**: Click a region in the minimap to zoom into that area (currently pans only)
- [TODO] **Minimap resizable**: Allow users to resize the minimap or dock it to a sidebar
- [TODO] **Minimap toggle shortcut**: `M` key to show/hide minimap

---

### 23. Version Comparison on Canvas 📋 PLANNED

[TODO] Version comparison currently works as a side-by-side code diff. Enterprise users need a visual diff directly on the canvas.

- [TODO] **Canvas overlay diff**: Overlay two versions on the same canvas with added nodes in green, removed in red, modified in yellow
- [TODO] **Side-by-side canvas diff**: Two linked canvases (left = old version, right = new) that pan/zoom together
- [TODO] **Diff badges on nodes**: Per-class badge showing "Added", "Modified", "Removed"
- [TODO] **Property-level diff**: Expand a modified class to see which properties changed (inline green/red/yellow)
- [TODO] **Diff navigation**: "Next change" / "Previous change" buttons to jump between differences
- [TODO] **Cherry-pick merge**: Select individual changes from a diff to apply to the current version
