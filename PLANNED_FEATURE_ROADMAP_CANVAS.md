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

#### Visual Feedback
- ✅ **Dropzone highlighting**: Visual cues for valid drop targets
- 📋 [TODO] **Ghost preview**: Show preview while dragging
- ✅ **Invalid drop indicator**: Clear feedback for invalid drops
- ✅ **Snap indicators**: Show snap points during drag

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|
| #478   | Show ghost preview of node while dragging        |

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
- ✅ Group-level operations:
  - ✅ Move entire group with one drag
  - ✅ Delete all classes in a group
- ✅ Named groups with descriptions and metadata
- ✅ Visual styling options:
  - ✅ Rounded rectangle containers with subtle shadows
  - ✅ Dashed or solid borders with custom colors
  - ✅ Background color/opacity customization
  - ✅ Optional group icons from icon library
- ✅ Group object is drag-and-drop to the canvas

| Ticket | Feature                                                             |
|--------|---------------------------------------------------------------------|
| #154   | Collapsible groups to reduce canvas clutter                         |
| #155   | Nested groups for hierarchical organization                         |
| #156   | Group-level operations: move, delete, export, duplicate, bulk edit  |

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
- ✅ **Node Borders** (#342):
  - ✅ Border thickness (1, 1.5, 2, 3, 4, 5px)
  - ✅ Border style (solid, dashed, dotted)
  - 📋 [TODO] Shadow effects (drop shadow, inner shadow)
- ✅ **Node Label Styling** (#343):
  - ✅ Font size (10–20px) and font family (Default, System, Serif, Mono, Inter)
  - ✅ Bold / Italic
  - ✅ Position (left, center, right)
  - ✅ Multi-line (wrap class name)

---

### 4.1 Smart Canvas Features

**Intelligent Layout Suggestions** ✅ PARTIALLY IMPLEMENTED
- [TODO] Rating system for suggestions (thumbs up/down to improve)
- [TODO] Machine learning from user preferences

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
  - [TODO] Unload off-screen nodes
  - [TODO] Garbage collect unused elements
  - ✅ Memory profiling tools

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
- ✅ **Relationship graphs**: Visual dependency maps
- 📋 [TODO] **Timeline views**: Schema evolution over time

| Ticket | Feature Description                          |
|--------|----------------------------------------------|
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
  - ✅ Customizable DPI (72, 150, 300, 600)
  - 📋 [TODO] Export dimensions in pixels or cm/inches
- **Selective Export**:
  - [TODO] Export only selected nodes
  - ✅ Export current viewport
  - ✅ Export specific groups (#404)
  - ✅ Export entire canvas
- **Export Options**:
  - ✅ Export wizard interface (replaces dropdown)
  - ✅ Include/exclude UI elements
  - ✅ Include/exclude grid
  - [TODO] Include/exclude annotations
  - [TODO] Include/exclude hidden nodes
  - ✅ Background color/transparency toggle
  - ✅ Add timestamp and metadata
- **Batch Export**:
  - [TODO] Export all groups separately
  - [TODO] Export each layout snapshot
  - [TODO] Export multiple formats at once
- **Animated Export**:
  - [TODO] Export layout transitions as animated GIF
  - [TODO] Export canvas walkthrough as video (WebM, MP4)
  - [TODO] Adjustable frame rate and duration
  - [TODO] Add narration (audio recording)

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

#### Schema Metrics Dashboard 📋 PLANNED
- 📋 [TODO] Trend indicators (improving/declining metrics)

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

#### Edge/Relationship Styling ✅ IMPLEMENTED
- ✅ Different line styles for relationship types:
  - ✅ Solid for direct references
  - ✅ Dashed for optional references
  - ✅ Dotted for weak references
  - ✅ Double lines for bidirectional
- ✅ Edge colors customizable
- ✅ Edge labels (show property name on relationship)
- ✅ Edge routing options:
  - ✅ Straight lines
  - ✅ Curved (Bezier)
  - ✅ Orthogonal (right angles)
  - ✅ Smart routing (avoid node overlap)
- ✅ Arrow styles: Standard, Diamond, Circle, Open arrow
- ✅ Animated edges (flowing dots for data flow)
- ✅ **Edge hover effects**: Tooltip (relationship label, source → target) and visual highlighting (thicker stroke, glow)

**Canvas Analysis** ✅ IMPLEMENTED
- **Schema Metrics**:
  - ✅ Total classes, properties, relationships
  - ✅ Average properties per class
  - ✅ Most connected classes (hubs)
  - ✅ Isolated classes (no relationships)
  - ✅ Deepest dependency chains
  - ✅ Circular dependencies count
- **Layout Quality Score**:
  - ✅ Edge crossing count (lower is better)
  - ✅ Node spacing uniformity
  - ✅ Layout symmetry
  - ✅ Visual balance
- **Suggestions**:
  - ✅ "Reduce edge crossings by switching to hierarchical layout"
  - ✅ "Group these 5 classes - they're all related"
  - ✅ "Class X is isolated - consider adding relationships"
  - ✅ "Large clusters detected - consider splitting into groups"

#### Focus Mode ✅ IMPLEMENTED
- ✅ Isolate selected classes and immediate relationships
- ✅ Blur/dim non-focused nodes
- ✅ Show only 1st-degree connections (or 2nd, 3rd degree)
- ✅ Expand focus incrementally
- ✅ Focus on group (show only group members)

### 4.1 Smart Canvas Features

**Intelligent Layout Suggestions** ✅ PARTIALLY IMPLEMENTED
- ✅ "Auto-organize" button with multiple suggestions
- ✅ Preview suggestions before applying

### 7. Canvas Performance ✅ IMPLEMENTED

#### Level of Detail (LOD) ✅ IMPLEMENTED
- ✅ Simplified nodes when zoomed out >200%
- ✅ Hide property details at high zoom, show only class names
- ✅ Dynamic detail based on zoom level
- ✅ Fade transitions between LOD levels
- ✅ Show property references even when nodes are collapsed

#### Schema Metrics Dashboard 📋 PLANNED
- ✅[Real-time metrics overlay on canvas:
  - ✅ Total classes, properties, relationships count
  - ✅ Schema complexity score
  - ✅ Documentation coverage percentage
  - ✅ Naming convention compliance
- ✅ Per-node metrics badges (property count, relationship count)
- ✅ Heatmap visualization (#560):
  - ✅ By complexity (more complex = warmer color)
  - ✅ By change frequency (recently modified = highlighted)
  - ✅ By usage/reference count
  - ✅ By documentation completeness

### 10. Schema Visualization & Analytics

#### Dependency Visualization 🚧 PARTIAL
- ✅ Interactive dependency graph overlay on canvas
- ✅ Highlight circular dependencies with warning indicators
- ✅ Show dependency depth levels (1st, 2nd, 3rd degree)
- ✅ "Impact Analysis" mode: Show all affected classes when changing one
- ✅ Upstream/downstream dependency toggles
- ✅ Dependency path highlighting (click to trace full chain)
- ✅ Dependency metrics per class (in-degree, out-degree, betweenness) (#553)
