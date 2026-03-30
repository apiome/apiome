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
- ✅ Multiple saved layouts per version:
    - "Development Layout" - organized for development work
    - "Presentation Layout" - clean arrangement for stakeholder demos
    - "Logical Layout" - grouped by business domain
    - "Dependency Layout" - organized by relationships
- ✅ Auto-save layout changes every 30 seconds (configurable)
- ✅ Version control for layouts (track layout history) — #165
- ✅ Default layout setting per user or per team — #166
- ✅ Export / import layout as versioned JSON — #167
- 📋 [TODO] Add ability to save layouts with a custom name
- ✅ Add simple orthagonal edge routing after auto-layout

| Ticket | Feature                                        |
|--------|------------------------------------------------|
| #315   | Canvas auto-save of layout                     |
| #316   | Export/import canvas layouts                   |

#### Layout Snapshots ✅ BASIC (named layouts)
- ✅ PNG snapshot stored with each named layout save; thumbnail preview when picking a layout name (#314)
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
- ✅ **Timeline views**: Schema evolution over time (#323 — studio canvas schema timeline panel)

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

### 2. Canvas Navigation & Controls

#### Node Visibility Controls 📋 PLANNED
- ✅ Hide/show individual nodes
- ✅ Hide all nodes except selected
- ✅ Hide by criteria:
  - Hide all empty classes (no properties)
  - Hide all classes without relationships
  - Hide deprecated classes
  - Hide by group membership
- ✅ "Ghosts mode": Show hidden nodes as semi-transparent
- ✅ Quick restore: **Show all nodes** in View Mode clears manual hides, filters, ghosts, isolate, and focus

---

### 10. Schema Visualization & Analytics

#### Schema Metrics Dashboard 📋 PLANNED
- 📋 [TODO] Trend indicators (improving/declining metrics)

#### Visual Feedback
- ✅ **Dropzone highlighting**: Visual cues for valid drop targets
- ✅ **Ghost preview**: Show preview while dragging
- ✅ **Invalid drop indicator**: Clear feedback for invalid drops
- ✅ **Snap indicators**: Show snap points during drag
