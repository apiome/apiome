# Canvas Roadmap Features

These are the features to do later.

---

### 6. Undo/Redo System

#### Comprehensive Undo Buffer 📋 PLANNED
- Track all canvas and schema modifications
- Configurable history depth (default 50, max 500)
- Actions tracked:
    - Class: Create, delete, rename, move, resize
    - Property: Add, edit, delete, reorder
    - Relationship: Create, delete, modify
    - Canvas Layout: Node positioning, group changes
    - Group: Create, delete, rename, collapse/expand
    - Visual: Color, size, style modifications
    - Annotations: Notes, shapes, labels

| Ticket | Feature Description                  |
|--------|--------------------------------------|

#### Undo/Redo UI 📋 PLANNED
- Keyboard shortcuts: `Cmd+Z` (Undo), `Cmd+Shift+Z` (Redo)
- Toolbar buttons with dropdown showing last 10 actions
- Click any action to undo/redo to that point

| Ticket | Feature Description                  |
|--------|--------------------------------------|

#### History Panel 📋 PLANNED
- Dedicated history panel (toggle with `Cmd+H`)
- Chronological list with visual timeline view
- Filter by action type, search history
- Before/after previews for each action
- Jump to any point in history

| Ticket | Feature Description                  |
|--------|--------------------------------------|

#### Advanced Features 📋 PLANNED
- Selective undo: Undo specific actions without undoing everything
- Branch history for collaborative editing
- Persistent history across browser sessions
- Server-side backup and sync across devices

| Ticket | Feature Description                  |
|--------|--------------------------------------|

---

### 11. Developer Productivity Features

#### Quick Actions & Command Palette
- `Cmd+K` / `Ctrl+K` command palette for all canvas actions
- Fuzzy search for classes, properties, actions
- Recent actions history in palette
- Contextual actions based on selection
- Custom action shortcuts configuration
- Action categories: Navigate, Edit, View, Export, Layout

| Ticket | Feature |
|--------|---------|

#### Inline Documentation
- Rich markdown editor in property tooltips
- Code examples in documentation with syntax highlighting
- Documentation templates per property type
- Auto-generate documentation from property schema
- Documentation coverage indicators on nodes
- Bulk documentation editing mode

| Ticket | Feature |
|--------|---------|

---

### 12. Enterprise Governance & Compliance

#### Access Control Visualization
- Visual indicators for permission levels:
    - 🔓 Open (full access)
    - 🔒 Read-only (view only)
    - 🚫 Restricted (no access, greyed out)
    - ⚠️ Pending approval
- Owner badges on classes/groups
- Team assignment visualization
- Permission inheritance from groups to classes

| Ticket | Feature |
|--------|---------|

#### Audit Trail Overlay
- "History mode" showing change timeline on canvas
- Click class to see full change history
- Filter by author, date range, change type
- Animated replay of schema evolution
- Compliance annotations (who approved, when)
- Export audit reports for compliance

| Ticket | Feature |
|--------|---------|

#### Schema Standards Enforcement
- Real-time validation indicators on canvas:
    - ✅ Compliant (green checkmark)
    - ⚠️ Warning (yellow triangle)
    - ❌ Violation (red X)
- Click indicator to see violation details and fix suggestions
- Configurable rule sets (company standards, industry standards)
- Auto-fix suggestions with one-click apply
- Standards compliance score per class and overall

| Ticket | Feature |
|--------|---------|


---

### 13. Large Schema Optimization

#### Smart Clustering
- Automatic detection of related class clusters
- One-click collapse clusters to single node
- Cluster summary (class count, relationship count)
- Expand cluster in-place or in separate view
- Cross-cluster relationship visualization
- Machine learning-based clustering suggestions

| Ticket | Feature |
|--------|---------|

#### Multi-Canvas Views
- Open multiple canvas tabs for same schema
- Different views: Overview, Detail, Relationships, Dependencies
- Synchronized selection across views
- Split canvas: Two views side by side
- Pin important classes to sidebar for quick access
- Recent classes list for quick navigation

| Ticket | Feature |
|--------|---------|

#### Progressive Loading
- Load visible area first, then expand
- Skeleton placeholders for loading nodes
- Priority loading based on importance/connections
- Lazy load property details on demand
- Background loading with progress indicator
- Cancel loading for navigated-away areas

| Ticket | Feature |
|--------|---------|

---

### 14. Integration & Extensibility

#### External Tool Integration
- Embed canvas in Confluence/Notion pages
- Slack integration for canvas snapshots
- JIRA integration: Link classes to tickets
- GitHub/GitLab: Canvas diff in PR reviews
- IDE plugins: Jump from code to canvas class
- Webhook triggers on canvas changes

| Ticket | Feature |
|--------|---------|

#### Canvas API & SDK
- Programmatic canvas manipulation API
- Custom node renderers via plugins
- Event hooks (onNodeClick, onLayoutChange, etc.)
- Batch operations API for automation
- Canvas state serialization/deserialization
- Third-party visualization library integration

| Ticket | Feature |
|--------|---------|

#### Print & Documentation Generation
- Print-optimized canvas layout
- Multi-page PDF with table of contents
- Auto-generated schema documentation site
- Include canvas diagrams in OpenAPI export
- Confluence/Wiki page auto-generation
- Custom branding/watermarks for exports

| Ticket | Feature |
|--------|---------|

---

### 15. Accessibility & Internationalization

#### Accessibility (a11y)
- Full keyboard navigation for all canvas operations
- Screen reader support with ARIA labels
- High contrast mode with configurable colors
- Focus indicators for all interactive elements
- Reduced motion mode (respect OS preference)
- Voice control integration (basic commands)
- Tab order optimization for logical flow

| Ticket | Feature |
|--------|---------|

#### Internationalization (i18n)
- RTL (Right-to-Left) layout support
- Localized UI elements and tooltips
- Unicode class/property name support
- Locale-aware date/time formatting
- Translated keyboard shortcut hints

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

