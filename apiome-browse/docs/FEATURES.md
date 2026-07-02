# Apiome Browse - Feature Documentation

This document provides detailed information about the features implemented in Apiome Browse.

## Overview

Apiome Browse is a public-facing web application that allows users to explore published OpenAPI specifications without requiring authentication. It provides a hierarchical navigation structure (Tenant → Project → Version) with powerful search and comparison capabilities.

## Core Features

### 1. Hierarchical Navigation

The application follows a three-level hierarchy:

```
Tenant (Organization)
  └── Project
      └── Version
```

#### Tenant Level (`/`)
- Displays all organizations that have at least one published public version
- Shows tenant name, description, and slug
- Grid layout for easy browsing
- Click to navigate to tenant's projects

#### Project Level (`/tenant/{tenantSlug}`)
- Lists all projects within a tenant that have published public versions
- Shows project name, description, and slug
- Breadcrumb navigation back to tenants
- Click to navigate to project's versions

#### Version Level (`/tenant/{tenantSlug}/{projectSlug}`)
- Lists all published public versions of a project
- Displays version number, description, changelog, and publication date
- "Compare versions" link (if 2+ versions exist)
- Click to view version details

#### Version Details (`/tenant/{tenantSlug}/{projectSlug}/{versionSlug}`)
- Full version information
- Specification viewer with multiple formats
- Copy and download functionality
- Breadcrumb navigation

### 2. Search Functionality

**Location**: Available on home page and search results page

**Features**:
- Full-text search across organization names, slugs, project names, slugs, and descriptions
- Real-time search with URL persistence (`/search?q=query`)
- Results grouped by organization
- Shows project count for each organization
- Click-through to tenant or project pages

**Search Query Examples**:
- "payment" - finds tenants/projects with "payment" in name or description
- "api" - finds all API-related projects
- Organization slug - finds specific organization

### 3. Specification Viewer

**Location**: Version details page

**Supported Formats**:
1. **OpenAPI 3.1.0** - Standard API schema definition
2. **Arazzo 1.0.1** - Workflow specifications
3. **JSON Schema** - Data model definitions

**Features**:
- Tab-based format selection
- Syntax-highlighted JSON display
- Copy to clipboard button
- Download as JSON file
- Fetched from apiome-rest API endpoints

**REST API Endpoints Used**:
```
GET /v1/schema/{tenant}/{project}/{version}   - OpenAPI
GET /v1/arazzo/{tenant}/{project}/{version}   - Arazzo
GET /v1/json/{tenant}/{project}/{version}     - JSON Schema
```

### 4. Version Comparison Tool

**Location**: `/tenant/{tenantSlug}/{projectSlug}/compare`

**Requirements**: At least 2 published versions

**Features**:

#### Format Selection
- Compare OpenAPI, Arazzo, or JSON Schema specifications
- Same format selector as the specification viewer

#### Version Selection
- Dropdown selectors for two versions
- URL parameters persist selection (`?v1=1.0.0&v2=2.0.0`)
- Defaults to two most recent versions

#### View Modes

1. **Side-by-Side View**
   - Two panels showing versions simultaneously
   - Independent scrolling
   - Clear visual separation
   - Best for reviewing entire specifications

2. **Unified Diff View**
   - Single panel showing line-by-line differences
   - Color-coded additions (green) and deletions (red)
   - Unchanged lines shown in context
   - Best for identifying specific changes

**Usage Example**:
```
1. Navigate to project versions page
2. Click "Compare versions"
3. Select two versions to compare
4. Choose format (OpenAPI/Arazzo/JSON Schema)
5. Switch between side-by-side and unified views
```

## Data Access Patterns

### Database Queries

All database queries are server-side and filter for:
- `published = true`
- `visibility = 'public'`
- `deleted_at IS NULL`

**Key Functions** (in `lib/db/helper.ts`):

```typescript
getPublicTenants()
  - Returns: All tenants with ≥1 published public version

getPublicProjectsForTenant(tenantSlug)
  - Returns: All projects in tenant with ≥1 published public version

getPublicVersionsForProject(tenantSlug, projectSlug)
  - Returns: All published public versions for a project

getPublicVersionDetails(tenantSlug, projectSlug, versionSlug)
  - Returns: Full version metadata including tenant and project info

searchPublicTenantsAndProjects(query)
  - Returns: All matching tenants and projects
  - Search fields: tenant name/slug, project name/slug/description

getPublicTenantBySlug(tenantSlug)
  - Returns: Tenant details if it has published public versions

getPublicProjectBySlug(tenantSlug, projectSlug)
  - Returns: Project details if it has published public versions
```

### REST API Integration

Specifications are fetched client-side from apiome-rest:

```typescript
// Configuration
const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL;

// Example fetch
const response = await fetch(
  `${restApiBaseUrl}/schema/${tenantSlug}/${projectSlug}/${versionSlug}`
);
const spec = await response.json();
```

## Security & Access Control

### Public Access
- **No authentication required**
- All pages are publicly accessible
- Only published public versions are shown

### Private Versions
- Not visible in browse application
- Require API key to access via REST API
- Access control handled by apiome-rest

### Database Security
- Direct SQL queries filtered at query level
- No user input in SQL (all parameterized)
- Read-only operations

## Performance Optimizations

### Server-Side Rendering (SSR)
- All pages use React Server Components
- Data fetched on server
- Initial page load is fully rendered HTML

### Caching Strategy
- Database queries execute on each request (ensures fresh data)
- Specifications cached in browser after first load
- Static assets cached by Next.js

### Database Query Optimization
- Uses DISTINCT to avoid duplicates
- Proper JOIN order for efficiency
- Filtered at database level (not application level)
- Indexes recommended on:
  - `tenants.slug`
  - `projects.slug`
  - `versions.version_id`
  - `versions.published`
  - `versions.visibility`

## User Interface Design

### Design System
- **Framework**: Tailwind CSS
- **Color Scheme**: Zinc palette with blue accents
- **Dark Mode**: Full support via Tailwind dark mode classes
- **Typography**: System fonts (Geist Sans, Geist Mono)

### Components

#### Layout Components
- `Header`: Page header with breadcrumbs
- `Search`: Search input with submit button
- `Card`: Reusable card for tenants/projects/versions

#### Specification Components
- `SpecViewer`: Format selector + spec display
- `CompareViewer`: Version comparison tool

### Responsive Design
- Mobile-first approach
- Grid layouts adjust for screen size:
  - Mobile: 1 column
  - Tablet (sm): 2 columns
  - Desktop (lg): 3 columns

## Navigation Patterns

### Breadcrumbs
All pages include breadcrumb navigation:

```
Organizations / {Tenant} / {Project} / {Version}
```

Each segment is clickable to navigate back up the hierarchy.

### Links
- **Back links**: "← Back to..." on subpages
- **Forward links**: Click on cards to drill down
- **Cross-links**: "Compare versions" link when applicable

### URL Structure
```
/                                           - Home (tenants list)
/search?q={query}                          - Search results
/tenant/{tenantSlug}                       - Tenant projects
/tenant/{tenantSlug}/{projectSlug}         - Project versions
/tenant/{tenantSlug}/{projectSlug}/{versionSlug}                    - Version details
/tenant/{tenantSlug}/{projectSlug}/compare?v1={v1}&v2={v2}         - Compare versions
```

All URLs are shareable and bookmarkable.

## Error Handling

### Not Found (404)
Displayed when:
- Tenant slug doesn't exist or has no public versions
- Project slug doesn't exist or has no public versions
- Version slug doesn't exist or is not published/public

### API Errors
Displayed when:
- REST API is unavailable
- Specification fetch fails
- Invalid response from REST API

### Empty States
User-friendly messages for:
- No tenants/projects/versions available
- No search results
- Insufficient versions to compare

## Future Enhancement Ideas

### Near-term
- [ ] Syntax highlighting for JSON/YAML
- [ ] Swagger UI integration for interactive testing
- [ ] Export to YAML format
- [ ] Copy direct links to specifications

### Medium-term
- [ ] Advanced search filters (by tenant, date range, etc.)
- [ ] Version history timeline visualization
- [ ] API changelog auto-generation from diffs
- [ ] Markdown support in descriptions

### Long-term
- [ ] RSS/Atom feeds for new version notifications
- [ ] OpenAPI validation and linting
- [ ] Schema evolution tracking
- [ ] Breaking change detection
- [ ] Automated migration guides

## Development Guidelines

### Adding New Features

1. **Database Functions**: Add to `lib/db/helper.ts`
2. **Types**: Define in `lib/types.ts`
3. **Pages**: Create in `src/app/` following Next.js App Router conventions
4. **Components**: Create in `src/app/components/`
5. **Styles**: Use Tailwind CSS utility classes

### Code Standards

- Use TypeScript for type safety
- Use async/await for asynchronous operations
- Follow Next.js 14+ App Router patterns
- Use Server Components by default, Client Components only when needed
- Keep database queries in helper functions

### Testing Checklist

Before deploying:
- [ ] Test with no data (empty states)
- [ ] Test with single tenant/project/version
- [ ] Test with multiple tenants/projects/versions
- [ ] Test search with various queries
- [ ] Test version comparison
- [ ] Test all three specification formats
- [ ] Test on mobile, tablet, desktop
- [ ] Test dark mode
- [ ] Test with REST API unavailable
- [ ] Test 404 pages

## Deployment Considerations

### Environment Variables
Required in production:
- `DATABASE_URL` or `POSTGRES_*` variables
- `NEXT_PUBLIC_REST_API_BASE_URL`

### Database Access
- Ensure database user has SELECT permissions on `apiome.*`
- Connection pooling configured appropriately
- SSL connections recommended for production

### REST API Dependency
- Ensure apiome-rest is deployed and accessible
- Configure CORS if browse and REST API are on different domains
- Use environment-specific REST API URLs

### Performance
- Consider CDN for static assets
- Enable Next.js caching features
- Monitor database query performance
- Optimize images (if added in future)

## Support & Troubleshooting

See `GETTING_STARTED.md` for:
- Installation instructions
- Configuration guide
- Common issues and solutions
- Development tips

## License

Part of the Apiome project.

