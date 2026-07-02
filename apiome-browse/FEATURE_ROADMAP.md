# Apiome Browse - Feature Roadmap

This document outlines the planned features, improvements, and enhancements for the Apiome Browse application. Items are organized by priority and category.

---

## 🎯 Current State (v1.0)

### Implemented Features
- ✅ Browse tenants → projects → versions hierarchy
- ✅ Search across organizations and projects
- ✅ View specifications in OpenAPI, Arazzo, and JSON Schema formats
- ✅ Monaco Editor for code viewing with syntax highlighting
- ✅ Side-by-side and unified diff comparison between versions
- ✅ Light/Dark/System theme support
- ✅ Multiple code themes (Default, Monokai, GitHub, Dracula, Solarized, Nord)
- ✅ Data tables with sorting, searching, and pagination
- ✅ Breadcrumb navigation
- ✅ Responsive design
- ✅ Docker containerization

---

## 🚀 Phase 1: Core Enhancements (High Priority)

### 1.1 API Base URL Configuration
**Status:** In Progress  
**Description:** Allow users to configure the REST API base URL through the UI settings panel, persisted in localStorage.

- [ ] Add API URL field in settings dropdown
- [ ] Validate URL format before saving
- [ ] Show connection status indicator
- [ ] Allow reset to default URL

### 1.2 Specification Validation
**Status:** Planned  
**Description:** Add real-time validation of OpenAPI specifications against the OpenAPI 3.x specification.

- [ ] Integrate OpenAPI validator library
- [ ] Show validation errors/warnings inline
- [ ] Provide "Validate" button in toolbar
- [ ] Display validation summary with error counts
- [ ] Jump to error location in editor

### 1.3 Enhanced Search
**Status:** Planned  
**Description:** Improve search capabilities with advanced filtering and better results.

- [ ] Full-text search within specification content
- [ ] Filter by date range (published date)
- [ ] Search suggestions/autocomplete
- [ ] Search history (recent searches)
- [ ] Highlight search terms in results

### 1.4 Keyboard Shortcuts
**Status:** Planned  
**Description:** Add keyboard navigation and shortcuts for power users.

- [ ] `⌘/Ctrl + K` - Quick search (global)
- [ ] `⌘/Ctrl + F` - Search within specification
- [ ] `⌘/Ctrl + G` - Go to line
- [ ] `⌘/Ctrl + D` - Download specification
- [ ] `⌘/Ctrl + C` - Copy specification
- [ ] `←/→` - Navigate between versions
- [ ] `Esc` - Close dialogs/modals
- [ ] Display keyboard shortcut help modal

---

## 🔧 Phase 2: Viewer Improvements (Medium Priority)

### 2.1 Interactive API Documentation
**Status:** Planned  
**Description:** Render specifications as interactive documentation, similar to Swagger UI or Redoc.

- [ ] Expand/collapse endpoints by tag
- [ ] Display request/response schemas
- [ ] Show example requests and responses
- [ ] "Try it out" mode with mock responses
- [ ] Copy cURL commands for endpoints
- [ ] Deep linking to specific endpoints

### 2.2 Schema Visualization
**Status:** Planned  
**Description:** Visual diagrams for understanding API structure.

- [ ] Entity relationship diagrams for schemas
- [ ] Interactive schema graph/tree view
- [ ] Dependency visualization between components
- [ ] Export diagrams as PNG/SVG
- [ ] Zoom and pan controls

### 2.3 Improved Diff View
**Status:** Planned  
**Description:** Enhance the version comparison experience.

- [ ] Semantic diff (understand OpenAPI structure)
- [ ] Highlight breaking changes in red
- [ ] Highlight new endpoints/schemas in green
- [ ] Summary of changes (added, removed, modified)
- [ ] Jump to next/previous change
- [ ] Collapsible unchanged sections
- [ ] Three-way merge view for complex comparisons

### 2.4 Code Folding & Minimap
**Status:** Planned  
**Description:** Better navigation for large specifications.

- [ ] Fold/unfold JSON objects and arrays
- [ ] Outline view showing structure
- [ ] Clickable minimap for quick navigation
- [ ] Bookmarks for important sections
- [ ] Breadcrumb showing current location in JSON

### 2.5 Multiple Format Export
**Status:** Planned  
**Description:** Export specifications in various formats.

- ✅ Download as JSON (current)
- ✅ Download as YAML [#182]
- [ ] Download as HTML documentation
- [ ] Download as PDF
- [ ] Download as Markdown
- [ ] Generate client SDKs (OpenAPI Generator integration)

---

## 🎨 Phase 3: UI/UX Enhancements (Medium Priority)

### 3.1 Favorites & Bookmarks
**Status:** Planned  
**Description:** Allow users to save frequently accessed specifications.

- [ ] Star/favorite projects and versions
- [ ] Quick access menu for favorites
- [ ] Persist favorites in localStorage
- [ ] Optional: Sync favorites with account (future)

### 3.2 Recent History
**Status:** Planned  
**Description:** Track and display recently viewed items.

- [ ] Show recently viewed specifications
- [ ] Clear history option
- [ ] Persist in localStorage
- [ ] Quick navigation from history

### 3.3 Customizable Dashboard
**Status:** Planned  
**Description:** Personalize the home page experience.

- [ ] Pin favorite organizations to top
- [ ] Customize visible columns in tables
- [ ] Set default view preferences
- [ ] Dashboard widgets (recent, favorites, stats)

### 3.4 Improved Mobile Experience
**Status:** Planned  
**Description:** Optimize for mobile and tablet devices.

- [ ] Touch-friendly navigation
- [ ] Swipe gestures for navigation
- [ ] Responsive Monaco Editor alternative for mobile
- [ ] Bottom navigation bar on mobile
- [ ] Collapsible sidebar

### 3.5 Accessibility Improvements
**Status:** Planned  
**Description:** Ensure WCAG 2.1 AA compliance.

- [ ] Screen reader support
- [ ] Keyboard-only navigation
- [ ] Focus indicators
- [ ] ARIA labels throughout
- [ ] High contrast mode
- [ ] Reduced motion option
- [ ] Accessibility audit and fixes

---

## 📊 Phase 4: Analytics & Insights (Lower Priority)

### 4.1 Usage Analytics Dashboard
**Status:** Planned  
**Description:** Insights into API specification usage.

- [ ] View counts per specification
- [ ] Popular endpoints analysis
- [ ] Download statistics
- [ ] Search analytics (popular searches)
- [ ] Time-based usage trends

### 4.2 API Change History
**Status:** Planned  
**Description:** Comprehensive changelog across versions.

- [ ] Timeline view of all changes
- [ ] Filter by change type (breaking, non-breaking)
- [ ] Notification of breaking changes
- [ ] RSS/Atom feed for changes
- [ ] Webhooks for change notifications

### 4.3 API Health Indicators
**Status:** Planned  
**Description:** Quality metrics for API specifications.

- [ ] Completeness score (descriptions, examples)
- [ ] Security analysis (auth schemes defined)
- [ ] Consistency checks
- [ ] Best practices compliance
- [ ] Comparison with industry standards

---

## 🔗 Phase 5: Integration & Extensibility (Future)

### 5.1 Embed Widget
**Status:** Planned  
**Description:** Embeddable specification viewer for external sites.

- [ ] Lightweight embed script
- [ ] Customizable appearance
- [ ] Whitelist domains
- [ ] Share links with embedded view

### 5.2 API Mocking
**Status:** Planned  
**Description:** Generate mock servers from specifications.

- [ ] One-click mock server creation
- [ ] Customizable response examples
- [ ] Proxy mode for development
- [ ] Share mock server URLs

### 5.3 CI/CD Integration
**Status:** Planned  
**Description:** Integrate with development workflows.

- [ ] GitHub/GitLab webhook integration
- [ ] Auto-publish on merge
- [ ] Breaking change detection in PRs
- [ ] Status badges for README

### 5.4 Plugin System
**Status:** Future Consideration  
**Description:** Allow third-party extensions.

- [ ] Plugin API for custom viewers
- [ ] Custom theme plugins
- [ ] Integration plugins (Postman, Insomnia)
- [ ] Analytics plugins

---

## 🛡️ Phase 6: Enterprise Features (Future)

### 6.1 Authentication & Access Control
**Status:** Future Consideration  
**Description:** Optional authentication for private specifications.

- [ ] OAuth2/OIDC integration
- [ ] SAML support
- [ ] Role-based access control
- [ ] API key authentication
- [ ] Team/group management

### 6.2 Multi-tenancy Improvements
**Status:** Future Consideration  
**Description:** Enhanced organization management.

- [ ] Custom branding per tenant
- [ ] Tenant-specific domains
- [ ] Usage quotas
- [ ] Billing integration

### 6.3 Audit Logging
**Status:** Future Consideration  
**Description:** Comprehensive audit trail.

- [ ] Track all user actions
- [ ] Export audit logs
- [ ] Compliance reporting
- [ ] Retention policies

---

## 🐛 Technical Improvements

### Performance
- [ ] Implement virtual scrolling for large specifications
- [ ] Add service worker for offline support
- [ ] Optimize bundle size with code splitting
- [ ] Implement Redis caching for database queries
- [ ] CDN integration for static assets

### Developer Experience
- [ ] Add comprehensive test suite (Jest, Playwright)
- [ ] Set up Storybook for component documentation
- [ ] Add ESLint rules for code consistency
- [ ] Create contributing guidelines
- [ ] Add API documentation with TypeDoc

### Infrastructure
- [ ] Kubernetes deployment manifests
- [ ] Helm chart for easy deployment
- [ ] Health check endpoints
- [ ] Prometheus metrics export
- [ ] Structured logging (JSON format)

---

## 📅 Release Timeline (Tentative)

| Phase   | Target      | Status         |
|---------|-------------|----------------|
| Phase 1 | Q1 2026     | 🟡 In Progress |
| Phase 2 | Q2 2026     | ⚪ Planned      |
| Phase 3 | Q2-Q3 2026  | ⚪ Planned      |
| Phase 4 | Q3 2026     | ⚪ Planned      |
| Phase 5 | Q4 2026     | ⚪ Planned      |
| Phase 6 | 2027+       | ⚪ Future       |

---

## 💡 Community Suggestions

We welcome feature requests and suggestions! Please open an issue in the repository with:
- A clear description of the feature
- Use case and benefits
- Any mockups or examples

---

## 🔄 Changelog

### December 2024
- Initial release with core browsing functionality
- Monaco Editor integration
- Version comparison with diff view
- Enterprise UI with data tables
- Theme support (light/dark/system)
- Docker containerization

---

*Last updated: December 14, 2025*

