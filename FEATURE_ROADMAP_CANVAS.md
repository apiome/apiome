# Canvas improvements roadmap

## 🎨 Canvas Improvements (CONSOLIDATED)

> **Purpose**: All canvas-related features consolidated in one place for focused development.
> **Priority**: 🔴 High - Critical for visual schema design experience
> **Timeline**: Q1-Q2 2026
> **Status**: Mix of ✅ Implemented, 🚧 Partial, 📋 Planned

---

### Quick Reference - Canvas Feature Status

| Category                    | Implemented  | Partial  | Planned  |
|-----------------------------|--------------|----------|----------|
| Layout & Organization       | 2            | 0        | 6        |
| Navigation & Controls       | 4            | 0        | 8        |
| Node Grouping               | 0            | 0        | 10       |
| Visual Customization        | 1            | 0        | 15       |
| Annotations                 | 0            | 0        | 12       |
| Undo/Redo                   | 0            | 0        | 8        |
| Performance                 | 6            | 0        | 4        |
| Export                      | 9            | 0        | 6        |
| Collaboration               | 0            | 0        | 5        |
| **Enterprise (NEW)**        |              |          |          |
| Schema Visualization        | 0            | 0        | 11       |
| Developer Productivity      | 0            | 0        | 15       |
| Governance & Compliance     | 0            | 0        | 11       |
| Large Schema Optimization   | 0            | 0        | 12       |
| Integration & Extensibility | 0            | 0        | 13       |
| Accessibility & i18n        | 0            | 0        | 10       |
| **TOTAL**                   | **22**       | **0**    | **146**  |

---

### 1. Canvas Layout & Organization

#### Save & Load Layouts 📋 PLANNED
- ✅ Save current canvas arrangement
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

| Ticket | Feature                                      |
|--------|----------------------------------------------|
| [#163] | Multiple saved layouts per version           |
| [#164] | Auto-save layout changes (tuneable interval) |
| [#165] | Version control for layouts                  |
| [#166] | Default layout setting per user or per team  |
| [#167] | Export/import layouts as JSON                |

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
| [#168] | Take quick snapshots of current layout            |
| [#169] | Thumbnail preview of each snapshot                |
| [#170] | Restore any snapshot with one click               |
| [#171] | Compare two snapshots side-by-side                |
| [#172] | Snapshot gallery view with search/filter          |
| [#173] | Snapshot metadata: timestamp, author, description |

#### Layout Sharing 📋 PLANNED
- 📋 Share layout configurations with team members
- 📋 "Pin" layout as team default
- 📋 Layout permissions (view, edit, delete)
- 📋 Layout comments and annotations
- 📋 Layout versioning with diff viewer

| Ticket | Feature                                       |
|--------|-----------------------------------------------|
| [#174] | Share layout configurations with team members |
| [#175] | "Pin" layout as team default                  |
| [#176] | Layout permissions (view, edit, delete)       |
| [#177] | Layout comments and annotations               |
| [#178] | Layout versioning with diff viewer            |

---

### 2. Canvas Navigation & Controls

#### Search & Focus 📋 PLANNED
- 📋 Global search box (`Cmd+F`) to find classes
- 📋 Search as you type with highlighting
- 📋 Click result to focus and zoom to class on canvas
- 📋 "Focus Mode": Dim everything except search results
- 📋 Search history (recent searches)
- 📋 Search filters: by type, group, properties
- 📋 Regex search support
- 📋 Search within property names/descriptions

| Ticket | Feature                                              |
|--------|------------------------------------------------------|
| [#186] | Clicking a class in the sidebar focuses it on canvas |
| [#187] | Regex search support                                 |
| [#188] | Search within property names/descriptions            |
| [#194] | Search highlighting on canvas                        |
| [#195] | Focus mode - dim non-matching results                |
| [#196] | Search history with clear option                     |

#### Canvas Bookmarks 📋 PLANNED
- 📋 Bookmark important canvas areas with names
- 📋 Named bookmarks (e.g., "Core Models", "New Features")
- 📋 Bookmarks sidebar with quick navigation
- 📋 Keyboard shortcuts for bookmarks (`Cmd+1-9`)
- 📋 Share bookmarks with team
- 📋 Bookmark thumbnails
- 📋 Organize bookmarks in folders

| Ticket | Feature                                       |
|--------|-----------------------------------------------|

#### Canvas Layers 📋 PLANNED
- 📋 Separate visual layers for different content:
    - **Background Layer**: Grid (dots vs. lines), shapes
    - **Node Layer**: Class nodes
    - **Edge Layer**: Relationships/references
    - **Annotation Layer**: Sticky notes, labels (drawer on right side like Lucidchart)
    - **UI Layer**: Selection boxes, handles
- 📋 Toggle layers on/off
- 📋 Lock layers to prevent editing
- 📋 Reorder layer z-index
- 📋 Per-layer opacity control

| Ticket | Feature                                       |
|--------|-----------------------------------------------|

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
- 📋 Visibility history

#### Focus Mode 📋 PLANNED
- 📋 Isolate selected classes and immediate relationships
- 📋 Blur/dim non-focused nodes
- 📋 Show only 1st-degree connections (or 2nd, 3rd degree)
- 📋 Expand focus incrementally
- 📋 Focus on group (show only group members)
- 📋 Exit focus mode with Esc key

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
    - Delete all classes in a group
    - Export group as separate schema file
    - Duplicate entire group with all classes
    - Apply bulk property changes to all classes in group
- ✅ Named groups with descriptions and metadata
- ✅ Visual styling options:
    - ✅ Rounded rectangle containers with subtle shadows
    - ✅ Dashed or solid borders with custom colors
    - 📋 Group headers with collapse/expand icons
    - ✅ Background color/opacity customization
    - ✅ Optional group icons from icon library

| Ticket | Feature                                                            |
|--------|--------------------------------------------------------------------|
| [#154] | Collapsible groups to reduce canvas clutter                        |
| [#155] | Nested groups for hierarchical organization                        |
| [#156] | Group-level operations: move, delete, export, duplicate, bulk edit |
| [#285] | Ungroup nodes by deleting the group                                |

#### Group Templates 📋 PLANNED
- 📋 Pre-defined group structures for common patterns:
    - REST Resource Group (Create, Read, Update, Delete classes)
    - Authentication Group (User, Token, Session, Role)
    - E-commerce Group (Product, Cart, Order, Payment)
    - Audit Group (Event, Log, History)
- 📋 Save custom groups as reusable templates
- 📋 Share group templates across projects/tenants

| Ticket | Feature                                         |
|--------|-------------------------------------------------|
| [#159] | Pre-defined group templates for common patterns |
| [#160] | Save and share custom group templates           |
| [#161] | Share group templates across projects/tenants   |

---

### 4. Visual Customization

#### Node Styling 📋 PLANNED
- 📋 **Custom Colors**:
    - Per-class color picker
    - Color by group
    - Color by stereotype (entity, service, DTO)
    - Color gradients for nodes
    - Color themes (Material, Pastel, Corporate)
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

| Ticket | Feature                                               |
|--------|-------------------------------------------------------|


#### Edge/Relationship Styling 📋 PLANNED
- 📋 Different line styles for relationship types:
    - Solid for direct references
    - Dashed for optional references
    - Dotted for weak references
    - Double lines for bidirectional
- 📋 Edge colors customizable
- 📋 Edge thickness (1-5px)
- 📋 Edge labels (show property name on relationship)
- 📋 Edge routing options:
    - Straight lines
    - Curved (Bezier)
    - Orthogonal (right angles)
    - Smart routing (avoid node overlap)
- 📋 Arrow styles: Standard, Diamond, Circle, Open arrow
- 📋 Animated edges (flowing dots for data flow)

#### Canvas Themes 📋 PLANNED
- 📋 Pre-built themes:
  - 📋 Light mode (default)
  - 📋 Dark mode
  - 📋 High contrast
  - 📋 Blueprint (blue grid on dark)
  - 📋 Whiteboard (minimal)
  - 📋 Solarized
  - 📋 Nord
  - 📋 Darcula
- 📋 Custom theme creator with full color control
- 📋 Save and share custom themes
- 📋 Theme marketplace

| Ticket | Feature                                                            |
|--------|--------------------------------------------------------------------|
| #309   | Custom color themes to choose from                                 |
| [#185] | Custom Colors: Per-class color picker, color by group, stereotypes |

#### Grid & Alignment 📋 PLANNED
- 📋 **Grid Snapping**: Snap nodes to grid, adjustable grid size
- 📋 **Alignment Tools**: Align edges, centers, distribute evenly
- 📋 **Smart Guides**: Show alignment guides during drag
- 📋 **Rulers**: Horizontal/vertical ruler bars with custom guide lines

#### Canvas Background 📋 PLANNED
- 📋 Solid color, Grid pattern, Custom image upload
- 📋 Gradient backgrounds, Texture patterns
- 📋 Background opacity and blur
- 📋 Infinite canvas scrolling

---

### 5. Annotations & Documentation

#### Sticky Notes 📋 PLANNED
- 📋 Add sticky notes anywhere on canvas
- 📋 Color-coded notes (yellow, blue, green, pink, orange)
- 📋 Markdown support in notes
- 📋 Resize notes, pin to nodes (move with node)
- 📋 Note templates (TODO, QUESTION, IMPORTANT, REVIEW)
- 📋 Note threading (reply to notes)
- 📋 @mention team members in notes
- 📋 Note search across canvas
- 📋 Convert notes to tasks

#### Arrows & Shapes 📋 PLANNED
- 📋 Draw arrows between any points
- 📋 Shapes: Rectangles, Circles, Lines, Polygons, Freehand
- 📋 Shape styling: Fill, border, shadows
- 📋 Use cases: Highlight regions, swim lanes, visual separators

#### Text Labels 📋 PLANNED
- 📋 Free-form text anywhere on canvas
- 📋 Rich text formatting, rotation
- 📋 Link text to URLs

#### Presentation Mode 📋 PLANNED
- 📋 Full-screen canvas mode with hidden UI
- 📋 Slide-show of bookmarked areas
- 📋 Presentation notes (speaker view)
- 📋 Timer and slide counter
- 📋 Laser pointer mode
- 📋 Recording mode (capture as video)

---

### 6. Undo/Redo System

#### Comprehensive Undo Buffer 📋 PLANNED
- 📋 Track all canvas and schema modifications
- 📋 Configurable history depth (default 50, max 500)
- 📋 Actions tracked:
    - Class: Create, delete, rename, move, resize
    - Property: Add, edit, delete, reorder
    - Relationship: Create, delete, modify
    - Canvas Layout: Node positioning, group changes
    - Group: Create, delete, rename, collapse/expand
    - Visual: Color, size, style modifications
    - Annotations: Notes, shapes, labels

#### Undo/Redo UI 📋 PLANNED
- 📋 Keyboard shortcuts: `Cmd+Z` (Undo), `Cmd+Shift+Z` (Redo)
- 📋 Toolbar buttons with dropdown showing last 10 actions
- 📋 Click any action to undo/redo to that point

#### History Panel 📋 PLANNED
- 📋 Dedicated history panel (toggle with `Cmd+H`)
- 📋 Chronological list with visual timeline view
- 📋 Filter by action type, search history
- 📋 Before/after previews for each action
- 📋 Jump to any point in history

#### Advanced Features 📋 PLANNED
- 📋 Selective undo: Undo specific actions without undoing everything
- 📋 Branch history for collaborative editing
- 📋 Persistent history across browser sessions
- 📋 Server-side backup and sync across devices

---

### 7. Canvas Performance

#### Level of Detail (LOD) ✅ IMPLEMENTED
- ✅ Simplified nodes when zoomed out >200%
- ✅ Hide property details at high zoom, show only class names
- ✅ Dynamic detail based on zoom level
- ✅ Fade transitions between LOD levels
- 📋 Show property references even when nodes are collapsed

| Ticket | Feature                                                      |
|--------|--------------------------------------------------------------|
| [#199] | Show property references even when class nodes are collapsed |

#### Web Workers 📋 PLANNED
- 📋 Layout calculations in background thread
- 📋 Node rendering in worker (OffscreenCanvas)
- 📋 Non-blocking canvas operations

---

### 8. Canvas Export

#### Export Options 📋 PLANNED
- 📋 High-resolution: 1x, 2x, 4x, 8x with customizable DPI
- 📋 Selective export: Selected nodes, viewport, specific groups, entire canvas
- 📋 Include/exclude: UI elements, grid, annotations, hidden nodes
- 📋 Background color/transparency, watermark, timestamp

#### Batch & Animated Export 📋 PLANNED
- 📋 Export all groups separately
- 📋 Export each layout snapshot
- 📋 Export multiple formats at once
- 📋 Animated GIF of layout transitions
- 📋 Video export (WebM, MP4) with narration

| Ticket | Feature                                      |
|--------|----------------------------------------------|

---

### 9. Canvas Collaboration (Real-Time)

#### Real-Time Cursors 📋 PLANNED
- 📋 See teammates' cursors with names and colors
- 📋 Cursor follows as they move
- 📋 Hide/show cursors toggle

#### Live Edits 📋 PLANNED
- 📋 See changes as teammates make them
- 📋 Smooth animations for remote changes
- 📋 Change indicators (flash highlight)

#### Locked Nodes 📋 PLANNED
- 📋 Lock icon on nodes being edited by others
- 📋 "Being edited by [Name]" tooltip
- 📋 Auto-lock/unlock mechanisms

#### Conflict Resolution 📋 PLANNED
- 📋 Operational Transform for concurrent edits
- 📋 Conflict warnings before saving
- 📋 "Yours vs Theirs" comparison UI

#### Chat Overlay 📋 PLANNED
- 📋 Quick chat widget without leaving canvas
- 📋 @mention teammates with canvas link
- 📋 Emoji reactions, message history

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

## Implemented Features Summary

---

## 🏢 Enterprise Canvas Features (NEW)

> **Purpose**: Enterprise-grade canvas capabilities for large teams and complex schemas
> **Priority**: 🔴 High - Critical for enterprise adoption
> **Timeline**: Q2-Q3 2026

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

| Ticket | Feature |
|--------|---------|

#### Schema Metrics Dashboard 📋 PLANNED
- 📋 Real-time metrics overlay on canvas:
  - Total classes, properties, relationships count
  - Schema complexity score
  - Documentation coverage percentage
  - Naming convention compliance
- 📋 Per-node metrics badges (property count, relationship count)
- 📋 Heatmap visualization:
  - By complexity (more complex = warmer color)
  - By change frequency (recently modified = highlighted)
  - By usage/reference count
  - By documentation completeness
- 📋 Trend indicators (improving/declining metrics)

| Ticket | Feature |
|--------|---------|

#### Version Comparison View 📋 PLANNED
- 📋 Side-by-side canvas comparison of two versions
- 📋 Diff highlighting:
  - Green for added classes/properties
  - Red for removed classes/properties
  - Yellow for modified classes/properties
- 📋 Animated transition between versions
- 📋 "Time travel" slider to scrub through version history
- 📋 Change summary panel with statistics
- 📋 Filter diff by change type

| Ticket | Feature |
|--------|---------|

---

### 11. Developer Productivity Features

#### Code Preview Integration 📋 PLANNED
- 📋 Hover over class to preview generated code (TypeScript, Python, Java, etc.)
- 📋 Split view: Canvas + Code side by side
- 📋 Real-time code generation as schema changes
- 📋 Code syntax highlighting with language selector
- 📋 Copy code snippets directly from preview
- 📋 Jump to relevant code section from class property

| Ticket | Feature |
|--------|---------|

#### Quick Actions & Command Palette 📋 PLANNED
- 📋 `Cmd+K` / `Ctrl+K` command palette for all canvas actions
- 📋 Fuzzy search for classes, properties, actions
- 📋 Recent actions history in palette
- 📋 Contextual actions based on selection
- 📋 Custom action shortcuts configuration
- 📋 Action categories: Navigate, Edit, View, Export, Layout

| Ticket | Feature |
|--------|---------|

#### Schema Templates & Snippets 📋 PLANNED
- 📋 Drag-and-drop schema templates onto canvas:
  - CRUD Resource (Create, Read, Update, Delete, List)
  - Authentication Set (User, Session, Token, Role, Permission)
  - Pagination Response (items, total, page, pageSize, hasMore)
  - Error Response (code, message, details, timestamp)
  - Audit Trail (id, action, actor, timestamp, changes)
- 📋 Custom template creation from selected classes
- 📋 Template variables with auto-fill prompts
- 📋 Template marketplace integration
- 📋 Team-shared template library

| Ticket | Feature |
|--------|---------|

#### Inline Documentation 📋 PLANNED
- 📋 Rich markdown editor in property tooltips
- 📋 Code examples in documentation with syntax highlighting
- 📋 Documentation templates per property type
- 📋 Auto-generate documentation from property schema
- 📋 Documentation coverage indicators on nodes
- 📋 Bulk documentation editing mode

| Ticket | Feature |
|--------|---------|

---

### 12. Enterprise Governance & Compliance

#### Access Control Visualization 📋 PLANNED
- 📋 Visual indicators for permission levels:
  - 🔓 Open (full access)
  - 🔒 Read-only (view only)
  - 🚫 Restricted (no access, greyed out)
  - ⚠️ Pending approval
- 📋 Owner badges on classes/groups
- 📋 Team assignment visualization
- 📋 Permission inheritance from groups to classes

| Ticket | Feature |
|--------|---------|

#### Audit Trail Overlay 📋 PLANNED
- 📋 "History mode" showing change timeline on canvas
- 📋 Click class to see full change history
- 📋 Filter by author, date range, change type
- 📋 Animated replay of schema evolution
- 📋 Compliance annotations (who approved, when)
- 📋 Export audit reports for compliance

| Ticket | Feature |
|--------|---------|

#### Schema Standards Enforcement 📋 PLANNED
- 📋 Real-time validation indicators on canvas:
  - ✅ Compliant (green checkmark)
  - ⚠️ Warning (yellow triangle)
  - ❌ Violation (red X)
- 📋 Click indicator to see violation details and fix suggestions
- 📋 Configurable rule sets (company standards, industry standards)
- 📋 Auto-fix suggestions with one-click apply
- 📋 Standards compliance score per class and overall

| Ticket | Feature |
|--------|---------|

---

### 13. Large Schema Optimization

#### Smart Clustering 📋 PLANNED
- 📋 Automatic detection of related class clusters
- 📋 One-click collapse clusters to single node
- 📋 Cluster summary (class count, relationship count)
- 📋 Expand cluster in-place or in separate view
- 📋 Cross-cluster relationship visualization
- 📋 Machine learning-based clustering suggestions

| Ticket | Feature |
|--------|---------|

#### Multi-Canvas Views 📋 PLANNED
- 📋 Open multiple canvas tabs for same schema
- 📋 Different views: Overview, Detail, Relationships, Dependencies
- 📋 Synchronized selection across views
- 📋 Split canvas: Two views side by side
- 📋 Pin important classes to sidebar for quick access
- 📋 Recent classes list for quick navigation

| Ticket | Feature |
|--------|---------|

#### Progressive Loading 📋 PLANNED
- 📋 Load visible area first, then expand
- 📋 Skeleton placeholders for loading nodes
- 📋 Priority loading based on importance/connections
- 📋 Lazy load property details on demand
- 📋 Background loading with progress indicator
- 📋 Cancel loading for navigated-away areas

| Ticket | Feature |
|--------|---------|

---

### 14. Integration & Extensibility

#### External Tool Integration 📋 PLANNED
- 📋 Embed canvas in Confluence/Notion pages
- 📋 Slack integration for canvas snapshots
- 📋 JIRA integration: Link classes to tickets
- 📋 GitHub/GitLab: Canvas diff in PR reviews
- 📋 IDE plugins: Jump from code to canvas class
- 📋 Webhook triggers on canvas changes

| Ticket | Feature |
|--------|---------|

#### Canvas API & SDK 📋 PLANNED
- 📋 Programmatic canvas manipulation API
- 📋 Custom node renderers via plugins
- 📋 Event hooks (onNodeClick, onLayoutChange, etc.)
- 📋 Batch operations API for automation
- 📋 Canvas state serialization/deserialization
- 📋 Third-party visualization library integration

| Ticket | Feature |
|--------|---------|

#### Print & Documentation Generation 📋 PLANNED
- 📋 Print-optimized canvas layout
- 📋 Multi-page PDF with table of contents
- 📋 Auto-generated schema documentation site
- 📋 Include canvas diagrams in OpenAPI export
- 📋 Confluence/Wiki page auto-generation
- 📋 Custom branding/watermarks for exports

| Ticket | Feature |
|--------|---------|

---

### 15. Accessibility & Internationalization

#### Accessibility (a11y) 📋 PLANNED
- 📋 Full keyboard navigation for all canvas operations
- 📋 Screen reader support with ARIA labels
- 📋 High contrast mode with configurable colors
- 📋 Focus indicators for all interactive elements
- 📋 Reduced motion mode (respect OS preference)
- 📋 Voice control integration (basic commands)
- 📋 Tab order optimization for logical flow

| Ticket | Feature |
|--------|---------|

#### Internationalization (i18n) 📋 PLANNED
- 📋 RTL (Right-to-Left) layout support
- 📋 Localized UI elements and tooltips
- 📋 Unicode class/property name support
- 📋 Locale-aware date/time formatting
- 📋 Translated keyboard shortcut hints

| Ticket | Feature |
|--------|---------|

---

### Updated Keyboard Shortcuts Reference

| Shortcut               | Action                        |
|------------------------|-------------------------------|
| `Cmd/Ctrl + Z`         | Undo                          |
| `Cmd/Ctrl + Shift + Z` | Redo                          |
| `Cmd/Ctrl + F`         | Search canvas                 |
| `Cmd/Ctrl + K`         | Command palette               |
| `Cmd/Ctrl + H`         | Toggle history panel          |
| `Cmd/Ctrl + D`         | Toggle dependency view        |
| `Cmd/Ctrl + M`         | Toggle metrics overlay        |
| `Cmd/Ctrl + P`         | Preview generated code        |
| `M`                    | Toggle minimap                |
| `Cmd/Ctrl + 1-9`       | Jump to bookmark              |
| `Space + Drag`         | Pan canvas                    |
| `Scroll`               | Zoom in/out                   |
| `Esc`                  | Exit focus mode               |
| `Delete`               | Delete selected               |
| `Cmd/Ctrl + G`         | Group selected nodes          |
| `Cmd/Ctrl + Shift + G` | Ungroup                       |
| `Cmd/Ctrl + E`         | Quick export menu             |
| `Cmd/Ctrl + .`         | Show context menu             |
| `Tab`                  | Next node                     |
| `Shift + Tab`          | Previous node                 |
| `Arrow Keys`           | Navigate between nodes        |
| `Enter`                | Edit selected node            |

---

### Enterprise Feature Summary

| Category | Features | Priority | Timeline |
|----------|----------|----------|----------|
| Schema Visualization | Dependency graphs, Metrics, Version comparison | 🔴 High | Q2 2026 |
| Developer Productivity | Code preview, Command palette, Templates | 🔴 High | Q2 2026 |
| Governance & Compliance | Access control, Audit trail, Standards | 🔴 High | Q2 2026 |
| Large Schema Support | Smart clustering, Multi-view, Progressive loading | 🟠 Medium | Q3 2026 |
| Integration | External tools, API/SDK, Documentation | 🟠 Medium | Q3 2026 |
| Accessibility | Keyboard nav, Screen readers, i18n | 🟡 Low | Q4 2026 |

