# Canvas improvements roadmap

## 🎨 Canvas Improvements (CONSOLIDATED)

> **Purpose**: All canvas-related features consolidated in one place for focused development.
> **Priority**: 🔴 High - Critical for visual schema design experience
> **Timeline**: Q1-Q2 2026
> **Status**: Mix of ✅ Implemented, 🚧 Partial, 📋 Planned

---

### 1. Canvas Layout & Organization

#### Save & Load Layouts ✅ IMPLEMENTED (Basic), 📋 PLANNED (Advanced)
- 📋 **Auto Layout Algorithms**: 8 algorithms (hierarchical TB/LR/BT/RL, force-directed, circular, grid, layered)
- ✅ Save current canvas arrangement
- ✅ Save and load groups with layouts
- ✅ **Layout Controls**: Compact button with dropdown menu
- ✅ **Database Table**: Create a database table to store layouts
- 📋 Multiple saved layouts per version:
    - "Development Layout" - organized for development work
    - "Presentation Layout" - clean arrangement for stakeholder demos
    - "Logical Layout" - grouped by business domain
    - "Dependency Layout" - organized by relationships
- 📋 Auto-save layout changes every 30 seconds (configurable)
- 📋 Version control for layouts (track layout history)
- 📋 Default layout setting per user or per team
- 📋 Export layout as JSON for sharing
- 📋 Import layouts from other versions/projects
- ✅ Add simple orthagonal edge routing after auto-layout

| Ticket | Feature                                       |
|--------|-----------------------------------------------|
| #564   | Re-introduce canvas auto-layout algorithms    |
| #163   | Multiple saved layouts per version            |
| #164   | Auto-save layout changes (tuneable interval)  |
| #165   | Version control for layouts                   |
| #166   | Default layout setting per user or per team   |
| #167   | Export/import layouts as JSON                 |
| #314   | Canvas snapshots                              |
| #315   | Canvas auto-save of layout                    |
| #316   | Export/import canvas layouts                  |

#### Layout Snapshots 📋 PLANNED
- 📋 Take quick snapshots of current layout
- 📋 Thumbnail preview of each snapshot
- 📋 Restore any snapshot with one click
- 📋 Compare two snapshots side-by-side
- 📋 Snapshot gallery view with search/filter
- 📋 Auto-snapshots before major changes
- 📋 Snapshot metadata: timestamp, author, description

| Ticket | Feature                                           |
|--------|---------------------------------------------------|
| #168   | Take quick snapshots of current layout            |
| #169   | Thumbnail preview of each snapshot                |
| #170   | Restore any snapshot with one click               |
| #171   | Compare two snapshots side-by-side                |
| #172   | Snapshot gallery view with search/filter          |
| #173   | Snapshot metadata: timestamp, author, description |

#### Layout Sharing 📋 PLANNED
- 📋 Share layout configurations with team members
- 📋 "Pin" layout as team default
- 📋 Layout permissions (view, edit, delete)
- 📋 Layout comments and annotations
- 📋 Layout versioning with diff viewer

| Ticket | Feature                                       |
|--------|-----------------------------------------------|
| #174   | Share layout configurations with team members |
| #175   | "Pin" layout as team default                  |
| #176   | Layout permissions (view, edit, delete)       |
| #177   | Layout comments and annotations               |
| #178   | Layout versioning with diff viewer            |

#### Navigation & Controls ✅ PARTIALLY COMPLETE
- ✅ **Minimap**: Bird's-eye view with viewport highlighting (bottom-right)
- ✅ **Zoom Controls**: Mouse wheel, zoom to fit, zoom presets (25%-200%)
  - Zoom to selection (fit selected nodes)
  - Zoom presets: 25%, 50%, 100%, 150%, 200%
  - Zoom slider in toolbar
- ✅ **Pan & Drag**: Middle-click or space+drag, smooth panning
  - Pan with middle mouse button or space+drag
  - Pan to edges on node drag
- 📋 **Global Search** (Cmd+F): Find classes with highlighting
- **Search Focus Mode**: Dim everything except search results
- **Canvas Bookmarks**: Named bookmarks with thumbnails, keyboard shortcuts (Cmd+1-9)
- **Canvas Layers**: Background, Node, Edge, Annotation, UI layers with toggle/lock
- **Node Visibility**: Hide/show nodes, "ghosts mode" for hidden nodes
- 📋 **Focus Mode**: Isolate selected classes and relationships, blur non-focused

| Ticket | Feature Description                                          |
|--------|--------------------------------------------------------------|
| #317   | Add the ability to search for classes inside the canvas view |
| #318   | Canvas search focus mode                                     |

---

### 2. Canvas Navigation & Controls

#### Search & Focus 📋 PLANNED
- 📋 Global search box (`Cmd+F`) to find classes
- 📋 Search as you type with highlighting
- 📋 Click result to focus and zoom to class on canvas
- 📋 "Focus Mode": Dim everything except search results
  - Isolate selected classes and immediate relationships
  - Blur/dim non-focused nodes
  - Show only 1st-degree connections (or 2nd, 3rd degree)
  - Expand focus incrementally
  - Focus on group (show only group members)
  - Exit focus mode (Esc key)
- 📋 Search history (recent searches)
- 📋 Search filters: by type, group, properties
- 📋 Regex search support
- 📋 Search within property names/descriptions

| Ticket | Feature                                              |
|--------|------------------------------------------------------|
| #186   | Clicking a class in the sidebar focuses it on canvas |
| #187   | Regex search support                                 |
| #188   | Search within property names/descriptions            |
| #194   | Search highlighting on canvas                        |
| #195   | Focus mode - dim non-matching results                |
| #196   | Search history with clear option                     |

#### Node Visibility Controls 📋 PLANNED
- 📋 Hide/show individual nodes
- 📋 Hide all nodes except selected
- 📋 Hide by criteria:
  - Hide all empty classes (no properties)
  - Hide all classes without relationships
  - Hide deprecated classes
  - Hide by group membership
- 📋 "Ghosts mode": Show hidden nodes as semi-transparent
- 📋 Quick restore hidden nodes

| Ticket | Feature Description            |
|--------|--------------------------------|
| #481   | Hide/show individual nodes     |
| #482   | Hide all nodes except selected |
| #483   | Hide by criteria               |
| #484   | "Ghosts mode" for hidden nodes |
| #485   | Quick restore hidden nodes     |

#### Focus Mode 📋 PLANNED
- 📋 Isolate selected classes and immediate relationships
- 📋 Blur/dim non-focused nodes
- 📋 Show only 1st-degree connections (or 2nd, 3rd degree)
- 📋 Expand focus incrementally
- 📋 Focus on group (show only group members)
- 📋 Exit focus mode with Esc key

| Ticket | Feature Description                        |
|--------|--------------------------------------------|
| #486   | Isolate selected classes and relationships |
| #487   | Blur/dim non-focused nodes                 |
| #488   | Show only Nth-degree connections           |
| #489   | Expand focus incrementally                 |
| #490   | Focus on group members                     |
| #491   | Exit focus mode with Esc key               |

#### Visual Feedback
- 📋 **Dropzone highlighting**: Visual cues for valid drop targets
- 📋 **Ghost preview**: Show preview while dragging
- 📋 **Invalid drop indicator**: Clear feedback for invalid drops
- 📋 **Snap indicators**: Show snap points during drag

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
- 📋 Collapsible groups to reduce canvas clutter
  - Click to collapse: shows only group title and count
  - Expand/collapse all groups with keyboard shortcut
  - Remember collapsed state per user
- 📋 Nested groups for hierarchical organization (max 3 levels)
- 📋 Group-level operations:
  - ✅ Move entire group with one drag
  - 📋 Delete all classes in a group
- ✅ Named groups with descriptions and metadata
- ✅ Visual styling options:
  - ✅ Rounded rectangle containers with subtle shadows
  - ✅ Dashed or solid borders with custom colors
  - 📋 Group headers with collapse/expand icons
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
- 📋 **Node Icons**:
  - Built-in icon library (1000+ icons)
  - Custom icon upload
  - Icons from icon packs (Font Awesome, Material Icons)
  - Icon position (left, center, badge)
- 📋 **Node Sizing**:
  - Auto-size based on content
  - Fixed size (small, medium, large, extra-large)
  - Custom width and height
  - Size by property count
  - Compact mode (show only class name)
- 📋 **Node Shapes**:
  - Rectangle (default), Rounded rectangle
  - Circle/ellipse, Hexagon, Diamond
  - Custom SVG shapes
- 📋 **Node Borders**:
  - Border thickness (1-5px)
  - Border style (solid, dashed, dotted)
  - Shadow effects (drop shadow, inner shadow)

| Ticket | Feature Description               |
|--------|-----------------------------------|
| #340   | Add custom node icons for styling |
| #341   | Custom node sizing                |
| #342   | Add node border configuration     |
| #343   | Add custom node label styling     |

#### Edge/Relationship Styling 📋 PLANNED
- ✅ Different line styles for relationship types:
  - ✅ Solid for direct references
  - ✅ Dashed for optional references
  - ✅ Dotted for weak references
  - ✅ Double lines for bidirectional
- ✅ Edge colors customizable
- 📋 Edge labels (show property name on relationship)
- ✅ Edge routing options:
  - ✅ Straight lines
  - ✅ Curved (Bezier)
  - ✅ Orthogonal (right angles)
  - ✅ Smart routing (avoid node overlap)
- 📋 Arrow styles: Standard, Diamond, Circle, Open arrow
- 📋 Animated edges (flowing dots for data flow)

| Ticket | Feature Description                   |
|--------|---------------------------------------|
| #347   | Adds edge arrow styles                |
| #348   | Adds animation to edges               |
| #349   | Adds edge hover effects               |

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
- 📋 Custom theme creator with full color control
- 📋 Save and share custom themes
- 📋 Theme marketplace

| Ticket | Feature                                                            |
|--------|--------------------------------------------------------------------|
| #185   | Custom Colors: Per-class color picker, color by group, stereotypes |

#### Canvas Background 📋 PLANNED
- 📋 Background options (solid color, grid pattern, custom image, gradient, textures)
- 📋 Background opacity and blur

| Ticket | Feature Description                  |
|--------|--------------------------------------|
| #329   | Add background options to the canvas |
| #330   | Add background opacity and blur      |

---

### 4.1 Smart Canvas Features

**Intelligent Layout Suggestions** ✅ PARTIALLY IMPLEMENTED
- ✅ "Auto-organize" button with multiple suggestions (8 layout algorithms)
- 📋 Preview suggestions before applying
- Rating system for suggestions (thumbs up/down to improve)
- Machine learning from user preferences

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|
| #471   | Preview layout suggestions before applying       |

**Canvas Analysis** ✅ PARTIALLY IMPLEMENTED
- **Schema Metrics**:
  - ✅ Total classes, properties, relationships
  - 📋 Average properties per class
  - 📋 Most connected classes (hubs)
  - 📋 Isolated classes (no relationships)
  - 📋 Deepest dependency chains
  - 📋 Circular dependencies count
- **Layout Quality Score**:
  - 📋 Edge crossing count (lower is better)
  - 📋 Node spacing uniformity
  - 📋 Layout symmetry
  - 📋 Visual balance
- **Suggestions**:
  - 📋 "Reduce edge crossings by switching to hierarchical layout"
  - 📋 "Group these 5 classes - they're all related"
  - 📋 "Class X is isolated - consider adding relationships"
  - 📋 "Large clusters detected - consider splitting into groups"

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
  - Canvas split into chunks/tiles
- **Level of Detail (LOD)**: ✅ IMPLEMENTED
  - ✅ When zoomed out >200%, show simplified nodes
  - ✅ At high zoom, hide property details, show only class names
  - ✅ Dynamic detail based on zoom level
  - ✅ Fade transitions between LOD levels
  - Show canvas node detail for properties that reference others even when collapsed
  - ✅ Level of detail toggling mode
- **Caching**:
  - ✅ Cache rendered node SVG/Canvas elements
  - ✅ Cache layout calculations
  - ✅ Cache relationship paths
  - ✅ Invalidate cache only on changes
- **Web Workers**:
  - Layout calculations in background thread
  - Node rendering in worker (OffscreenCanvas)
  - Relationship path calculations async
  - Non-blocking canvas operations
- **Request Animation Frame**:
  - ✅ Smooth 60fps animations
  - ✅ Batch DOM updates
  - ✅ Throttle mouse move events
- **Memory Management**:
  - 📋 Lazy load node properties
  - Unload off-screen nodes
  - Garbage collect unused elements
  - 📋 Memory profiling tools

| Ticket | Feature Description                                          |
|--------|--------------------------------------------------------------|
| #199   | Show property references even when class nodes are collapsed |
| #475   | Lazy loading of node properties                              |
| #476   | Memory profiling tooling                                     |

---

### 5. Annotations & Documentation

#### Presentation Mode 📋 PLANNED
- 📋 Full-screen canvas mode with hidden UI
  - 📋 Hide all toolbars and UI
  - 📋 Slide-show of bookmarked areas
  - 📋 Presentation notes (speaker view)
  - 📋 Timer and slide counter
  - 📋 Presenter controls (keyboard shortcuts)

| Ticket | Feature Description                  |
|--------|--------------------------------------|
| #517   | Full-screen presentation mode        |

#### Charts & Metrics ✅ PARTIALLY COMPLETE
- ✅ **Quality score gauge**: Visual score indicator (0-100)
- ✅ **Complexity charts**: Schema complexity visualization
- 📋 **Relationship graphs**: Visual dependency maps
- 📋 **Timeline views**: Schema evolution over time

| Ticket | Feature Description                          |
|--------|----------------------------------------------|
| #322   | Display the relationship graph for a schema  |
| #323   | Timeline view of schema changes over time    |

---

### 7. Canvas Performance

#### Level of Detail (LOD) 📋 PARTIALLY IMPLEMENTED
- ✅ Simplified nodes when zoomed out >200%
- ✅ Hide property details at high zoom, show only class names
- ✅ Dynamic detail based on zoom level
- ✅ Fade transitions between LOD levels
- 📋 Show property references even when nodes are collapsed

| Ticket | Feature                                                      |
|--------|--------------------------------------------------------------|
| #199   | Show property references even when class nodes are collapsed |

---

### 8. Canvas Export

#### Export Options 📋 PLANNED

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
- **High-Resolution Export**:
  - 📋 1x (default), 2x, 4x, 8x resolution
  - 📋 Customizable DPI (72, 150, 300, 600)
  - 📋 Export dimensions in pixels or cm/inches
- **Selective Export**:
  - Export only selected nodes
  - 📋 Export current viewport
  - 📋 Export specific groups
  - 📋 Export entire canvas
- **Export Options**:
  - 📋 Include/exclude UI elements
  - 📋 Include/exclude grid
  - Include/exclude annotations
  - Include/exclude hidden nodes
  - Background color/transparency
  - 📋 Add watermark
  - 📋 Add timestamp and metadata
- **Batch Export**:
  - Export all groups separately
  - Export each layout snapshot
  - Export multiple formats at once
- **Animated Export**:
  - Export layout transitions as animated GIF
  - Export canvas walkthrough as video (WebM, MP4)
  - Adjustable frame rate and duration
  - Add narration (audio recording)

| Ticket | Feature Description                        |
|--------|--------------------------------------------|
| #402   | Adds resolution specifications for exports |
| #403   | Export the current viewport                |
| #404   | Export specific groups                     |
| #405   | Export entire canvas                       |
| #406   | Include/exclude UI elements                |
| #407   | Include/exclude grid                       |
| #408   | Export option to add watermark             |
| #409   | Add timestamp and metadata                 |

---

### Canvas Keyboard Shortcuts Reference

| Shortcut               | Action               |
|------------------------|----------------------|
| `Cmd/Ctrl + Z`         | Undo                 |
| `Cmd/Ctrl + Shift + Z` | Redo                 |
| `Cmd/Ctrl + F`         | Search canvas        |
| `Cmd/Ctrl + H`         | Toggle history panel |
| `M`                    | Toggle minimap       |
| `Cmd/Ctrl + 1-9`       | Jump to bookmark     |
| `Space + Drag`         | Pan canvas           |
| `Scroll`               | Zoom in/out          |
| `Esc`                  | Exit focus mode      |
| `Delete`               | Delete selected      |
| `Cmd/Ctrl + G`         | Group selected nodes |
| `Cmd/Ctrl + Shift + G` | Ungroup              |

---

### 10. Schema Visualization & Analytics

#### Dependency Visualization 📋 PLANNED
- 📋 Interactive dependency graph overlay on canvas
- 📋 Highlight circular dependencies with warning indicators
- 📋 Show dependency depth levels (1st, 2nd, 3rd degree)
- 📋 "Impact Analysis" mode: Show all affected classes when changing one
- 📋 Upstream/downstream dependency toggles
- 📋 Dependency path highlighting (click to trace full chain)
- 📋 Dependency metrics per class (in-degree, out-degree, betweenness)

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
- 📋 Real-time metrics overlay on canvas:
  - 📋 Total classes, properties, relationships count
  - 📋 Schema complexity score
  - 📋 Documentation coverage percentage
  - 📋 Naming convention compliance
- 📋 Per-node metrics badges (property count, relationship count)
- 📋 Heatmap visualization:
  - 📋 By complexity (more complex = warmer color)
  - 📋 By change frequency (recently modified = highlighted)
  - 📋 By usage/reference count
  - 📋 By documentation completeness
- 📋 Trend indicators (improving/declining metrics)

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

### 11. Developer Productivity Features

#### Code Preview Integration 📋 PLANNED
- Hover over class to preview generated code (TypeScript, Python, Java, etc.)
- 📋 Split view: Canvas + Code side by side
- 📋 Real-time code generation as schema changes
- Code syntax highlighting with language selector
- Copy code snippets directly from preview
- Jump to relevant code section from class property

| Ticket | Feature                                     |
|--------|---------------------------------------------|
| #599   | Add side-by-side canvas and code view       |
| #600   | Real-time code generation as schema changes |

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
