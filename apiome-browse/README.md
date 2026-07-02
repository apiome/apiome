# Apiome Browse

A public-facing enterprise web application for browsing and exploring published OpenAPI specifications from Apiome.

## Features

### Core Features
- **Browse by Organization**: Navigate through tenants, projects, and versions
- **Search**: Full-text search across organizations and projects  
- **View Specifications**: Display OpenAPI, Arazzo, and JSON Schema formats
- **Version Comparison**: Side-by-side and unified diff views between versions
- **Public Access**: No authentication required - only displays published public versions

### Enterprise UI/UX
- **Sticky Navigation Bar**: Persistent navigation with quick search
- **Data Tables**: Sortable, searchable, paginated tables for all listings
- **Breadcrumb Navigation**: Visual hierarchy showing current location
- **Theme Support**: Light, Dark, and System themes for the application
- **Code Themes**: 6 color themes for specification viewing (Default, Monokai, GitHub, Dracula, Solarized, Nord)
- **Responsive Design**: Works on desktop and mobile devices

### Specification Viewer
- **Format Switching**: Toggle between OpenAPI, Arazzo, and JSON Schema
- **Line Numbers**: Toggle line number display
- **Word Wrap**: Toggle word wrapping for long lines
- **Copy/Download**: Export specifications easily
- **Theme Selector**: Choose from 6 code color themes

## Architecture

This application follows a clean architecture pattern:

- **Database Access**: Direct SQL queries to PostgreSQL using internal helpers (not exposed as REST endpoints)
- **Specification Retrieval**: Uses the existing apiome-rest API endpoints to fetch OpenAPI, Arazzo, and JSON Schema specifications
- **Server Components**: Leverages Next.js 14+ App Router with React Server Components for optimal performance

## Getting Started

### Prerequisites

- Node.js 20+
- PostgreSQL database with Apiome schema
- apiome-rest service running (for fetching specifications)

### Installation

```bash
npm install
```

### Configuration

Create a `.env.local` file based on `.env.example`:

```env
# Database configuration (for browsing tenants/projects/versions)
DATABASE_URL=postgresql://postgres:password@localhost:5432/apiome
POSTGRES_USER=postgres
POSTGRES_HOST=localhost
POSTGRES_DB=apiome
POSTGRES_PASSWORD=password
POSTGRES_PORT=5432

# REST API Base URL (for fetching specifications)
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1

# Base path for sub-path hosting (optional)
# Example: NEXT_PUBLIC_BASE_PATH=/browse
NEXT_PUBLIC_BASE_PATH=
```

### Sub-Path Hosting

To host the application at a sub-path (e.g., `https://example.com/browse/`), set the `NEXT_PUBLIC_BASE_PATH` environment variable:

```env
NEXT_PUBLIC_BASE_PATH=/browse
```

**Important Notes:**
- The path must start with `/` but not end with `/`
- You must rebuild the application after changing this value
- All internal links will automatically use the base path

**Example with Docker:**
```bash
docker build \
  --build-arg NEXT_PUBLIC_BASE_PATH=/browse \
  --build-arg NEXT_PUBLIC_REST_API_BASE_URL=https://api.example.com/v1 \
  -t apiome-browse:latest .
```

### Development

```bash
npm run dev
```

The application will be available at `http://localhost:3000` (or next available port).

### Production

```bash
npm run build
npm start
```

## Project Structure

```
apiome-browse/
├── lib/
│   └── db/
│       ├── db.ts           # Database connection pool
│       └── helper.ts       # Database query functions
├── src/
│   └── app/
│       ├── components/
│       │   ├── Search.tsx         # Search component
│       │   ├── SpecViewer.tsx     # Specification viewer
│       │   └── CompareViewer.tsx  # Version comparison tool
│       ├── search/
│       │   └── page.tsx           # Search results page
│       ├── tenant/
│       │   └── [tenantSlug]/
│       │       ├── page.tsx                         # Tenant projects list
│       │       └── [projectSlug]/
│       │           ├── page.tsx                     # Project versions list
│       │           ├── compare/
│       │           │   └── page.tsx                 # Version comparison
│       │           └── [versionSlug]/
│       │               └── page.tsx                 # Version details
│       ├── layout.tsx      # Root layout
│       └── page.tsx        # Home page (tenant list)
└── ...
```

## Features Breakdown

### 1. Tenant Listing
Browse all organizations that have published public specifications.

### 2. Project Listing
View all projects within a tenant that have published versions.

### 3. Version Listing
See all published versions of a project with changelog information.

### 4. Specification Viewer
View specifications in three formats:
- **OpenAPI 3.1.0**: Standard API schema
- **Arazzo 1.0.1**: Workflow specifications
- **JSON Schema**: Data model definitions

Features:
- Copy to clipboard
- Download as JSON
- Syntax highlighting

### 5. Version Comparison
Compare two versions side-by-side or in unified diff mode:
- **Side-by-Side**: View both versions simultaneously
- **Unified Diff**: See additions and deletions inline

### 6. Search
Full-text search across:
- Organization names and slugs
- Project names, slugs, and descriptions
- Results grouped by organization

## Database Functions

The application uses the following database helper functions (internal only, not exposed as REST endpoints):

- `getPublicTenants()`: Get all tenants with published public versions
- `getPublicProjectsForTenant(tenantSlug)`: Get projects for a tenant
- `getPublicVersionsForProject(tenantSlug, projectSlug)`: Get versions for a project
- `getPublicVersionDetails(tenantSlug, projectSlug, versionSlug)`: Get version metadata
- `searchPublicTenantsAndProjects(query)`: Full-text search
- `getPublicTenantBySlug(tenantSlug)`: Get tenant details
- `getPublicProjectBySlug(tenantSlug, projectSlug)`: Get project details

All functions filter to only return:
- `published = true`
- `visibility = 'public'`
- `deleted_at IS NULL`

## REST API Integration

The application consumes the following apiome-rest endpoints:

- `GET /v1/schema/{tenant}/{project}/{version}`: OpenAPI specification
- `GET /v1/arazzo/{tenant}/{project}/{version}`: Arazzo workflow
- `GET /v1/json/{tenant}/{project}/{version}`: JSON Schema

These endpoints are called client-side from the browser to fetch specifications.

## Important Notes

### Module Imports

The `lib` directory is at the project root, not in `src`. Use relative imports:

```typescript
// ✅ Correct (from src/app/page.tsx)
import { getPublicTenants } from "../../lib/db/helper";

// ❌ Incorrect (will cause module resolution errors)
import { getPublicTenants } from "@/lib/db/helper";
```

See [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for path reference table.

## Security

- No authentication required (public access)
- Only published public versions are accessible
- Direct database queries filtered by `published=true` and `visibility='public'`
- REST API handles private version access control

## Performance

- Server-side rendering with React Server Components
- Incremental Static Regeneration (ISR) for tenant/project listings
- Client-side caching of specifications
- Optimized database queries with proper indexing

## Documentation

- **README.md**: This file - project overview
- **GETTING_STARTED.md**: Detailed setup guide
- **FEATURES.md**: Comprehensive feature documentation
- **TROUBLESHOOTING.md**: Common issues and solutions
- **QUICK_REFERENCE.md**: Quick reference guide
- **DEPLOYMENT_CHECKLIST.md**: Pre-deployment checklist
- **IMPLEMENTATION_SUMMARY.md**: Technical implementation details

## Troubleshooting

For common issues and solutions, see [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

Quick fixes:
- **Module not found**: Use relative imports for `lib` directory
- **Port in use**: Server will auto-select next available port
- **Database connection**: Verify PostgreSQL is running and credentials are correct
- **Specifications not loading**: Ensure apiome-rest is running

## Future Enhancements

- [ ] Swagger UI integration for interactive API testing
- [ ] Advanced syntax highlighting for JSON/YAML
- [ ] Diff visualization with change summaries
- [ ] Export to multiple formats (YAML, PDF)
- [ ] Version history timeline
- [ ] API changelog generation
- [ ] RSS/Atom feeds for new versions
- [ ] OpenAPI validation and linting

## License

Part of the Apiome project.

