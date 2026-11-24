# Apiome Browse

A public-facing enterprise web application for browsing and exploring published OpenAPI specifications from Apiome.

## Features

### Core Features
- **Browse by Organization**: Navigate through tenants, projects, and versions
- **Search**: One query language over the normalized model — operations, parameters, bodies, responses, schemas, properties, version notes, tags, projects and organizations — with operators (`method:`, `path:`, `org:`, `type:`, `format:`, `after:`…), a faceted results page, a ⌘K palette and shareable URLs
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

- Node.js 26+ (the images and CI use the latest Node release)
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

# REST API Base URL the Browse *server* uses for /tenant/{slug}/agents.json and /llms.txt (optional;
# defaults to NEXT_PUBLIC_REST_API_BASE_URL). Set it when the browser-facing address is not reachable
# from the server, e.g. APIOME_REST_INTERNAL_BASE_URL=http://rest:8000/v1 in a container network.
APIOME_REST_INTERNAL_BASE_URL=

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
│   ├── db/
│   │   ├── db.ts           # Database connection pool
│   │   ├── helper.ts       # Database query functions
│   │   └── search.ts       # Runs the catalog search statement
│   └── search/             # Query language, URL state, SQL builder, anchors, highlighting (pure, tested)
├── src/
│   └── app/
│       ├── components/
│       │   ├── search/            # SearchBox, SearchPalette (⌘K), FacetRail, HitRow
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
`/search` runs one parameterized SQL statement (`lib/search/sql.ts`) built from the URL
(`lib/search/params.ts`) and the query language (`lib/search/query.ts`):

- Words, quoted phrases and `-exclusions`; filters `type:`, `method:`, `path:`, `org:`, `project:`,
  `version:`, `format:`, `paradigm:`, `tag:`, `severity:`, `after:`, `before:` (rail filters in the
  URL merge with operators typed in the box)
- One union member per kind over each project's latest published public version (or every version
  with `all=1`), ranked exact › prefix › contains plus a per-kind weight, with facet counts and a
  page computed in the same round trip
- Deep links into the version page at the operation (`#op-…`) or schema (`#schema-…`) anchor
- Changelog search (BDX-1.4): the `change` member unnests `version_changelogs.changelog_json`
  entries (one hit per entry, ranked severity first, then text); `severity:` (`breaking`,
  `warning`/`non-breaking`, `info`/`docs-only`, `lib/search/severity.ts`) narrows to it, and a hit
  opens the version's Changes tab (`?tab=changes`)
- Find in one version (BDX-1.3): the version page's find box runs `lib/search/findInVersion.ts`
  in the browser over the loaded spec — same query language, `method:` / `path:` / `type:`, `?find=`
  in the URL, `/` to focus and `↵` to jump to the next match
- `GET /api/search/suggest?q=` feeds the ⌘K palette with the same engine
- Project hits carry the card facts of the version they link to (BDX-2.2): the statement joins
  `lib/cardFacts.ts`'s facts fragment to the page's rows only
- Compare from search (BDX-2.6, `lib/search/compare.ts`): version / operation / schema hits carry a
  *Compare* tick (`c` on the cursor row); two hits of one project in two versions light up the sticky
  bar's link to `/tenant/{t}/{p}/compare?v1=<older>&v2=<newer>`. One follow-up statement
  (`runHitVersionsLookup`) returns each such hit's newest 20 project versions and whether its
  operation or schema exists in each, for the version chip's quick-switch menu; the menu's
  **Show all versions** loads the rest from `GET /api/search/hit-versions`
- Scope and caps (DBP-1.27): `org:` / `project:` are resolved inside the statement's scope, which
  starts from `apiome.browse_public_projects`; each kind is capped at 1,000 hits on its own; only
  the kinds a page lists produce rows, and the MCP catalog is searched on its own tab only

### Card facts (BDX-2.2)

Project cards, the project and version headers and project search hits show a facts line —
`42 operations · 18 schemas · Grade B · Mock · SDK · OpenAPI 3.1 · updated 3d ago` — for the latest
published public version. `lib/cardFacts.ts` holds the SQL fragment the queries in `lib/db`
splice in (the facts come back in the same statement as the rows), the line's wording and order,
and the sorts: the home rail's
`?projects=versions|operations|grade` and the organization page's **Sort** menu. The SDK flag
follows REST's public-SDK rule (`publicSdkEnabled`, project row over tenant row, default off).
`FactsLine` renders it.

The pure modules under `lib/search/` are unit-tested; `lib/db/search.ts` runs the statement.

## Database Functions

Every page and route handler reads the database through **one loader**, so a route's database cost
is one function (DBP-1.27). The loaders are internal — not exposed as REST endpoints:

| Route | Loader | Statements |
|---|---|---|
| `/` | `lib/db/helper.ts` — `getPublicTenants`, `getRecentlyPublishedVersions`, `getMostVersionedProjects`, `getNewestTenants`, `getDirectoryStats` (cached, `BROWSE_CACHE_TTL_SECONDS`) | 5 cold, 0 warm |
| `/tenant/{t}` | `loadTenantPage` | 3 |
| `/tenant/{t}/{p}` | `loadProjectPage` | 2 |
| `/tenant/{t}/{p}/{v}` | `loadVersionPage` (+ `changes.json` when the Changes tab is opened) | 1 (+1) |
| `/tenant/{t}/{p}/changelog` | `loadChangelogPage` | 3 |
| `/tenant/{t}/{p}/compare` | `loadComparePage` | 3 |
| `/tenant/{t}/{p}/changelog.xml` · `.json` | `lib/feed/changelogFeedRoute.ts` — `serveChangelogFeed` | 1 unchanged, 2 otherwise |
| `/tenant/{t}/products/{product}` | `loadProductPage` | 4 |
| `/mcp` | `getPublicMcpEndpointsByHost(page)` | 1 |
| `/mcp/{t}/{endpoint}` | `loadMcpEndpointPage` | 2 |
| `/mcp/{t}/collections/{c}` | `loadMcpCollectionPage` | 2 |
| `POST /api/try-it` | `lib/db/tryIt.ts` — `getTryItVersion` (remembered 30 s) | 1, then 0 |
| `/search` | `lib/db/search.ts` — `runCatalogSearch`, `runHitVersionsLookup` | 2 |

The `load*` functions are in `lib/db/routeLoaders.ts`. The numbers are in
`lib/db/statementBudgets.json` and enforced by `lib/__tests__/routeBudget.test.ts`, which also fails
when a route runs the same statement twice. A page and its `generateMetadata` share a loader through
React's `cache()`.

The catalog-wide reads use `apiome.browse_public_projects` (migration V431): one row per public
project, kept current by the database when a version is published, unpublished, changed or
deleted.

All reads filter to only return:
- `published = true`
- `visibility = 'public'`
- `deleted_at IS NULL` (version, project and tenant)

### When the database cannot answer

A loader returns `null` only when the thing is not public or does not exist (→ 404). When a
statement fails it throws `DatabaseUnavailableError` (`lib/db/errors.ts`), so a busy database is
never a 404:

- a route handler answers `503` with `Retry-After`;
- a page renders the error boundary (`500`);
- `src/proxy.ts` answers `503` with `Retry-After` before rendering while the pool is saturated —
  every client checked out and as many requests waiting — or for 5 seconds after a connection
  failure (`lib/db/availability.ts`).

Lists that only decorate a page (home rails, an organization's products) log and render empty.

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

See the archived [TROUBLESHOOTING.md](../docs/archive/apiome-browse/TROUBLESHOOTING.md) for the path reference table.

## Security

- No authentication required (public access)
- Only published public versions are accessible
- Direct database queries filtered by `published=true` and `visibility='public'`
- REST API handles private version access control

## Performance

- Server-side rendering with React Server Components
- A fixed number of statements per route (see [Database Functions](#database-functions))
- The directory's global reads cached in-process (`BROWSE_CACHE_TTL_SECONDS`)
- Long lists bounded: 20 versions per changelog page, 200 versions on a project page, 100 MCP
  servers per index page
- Client-side caching of specifications

## Documentation

- **README.md**: This file - project overview
- **User guide**: [Browse published specs](https://docs.apiome.dev/ship/browse-published-specs) on the documentation site
- The package's older notes (setup, features, troubleshooting, deployment checklist) are archived
  in [`docs/archive/apiome-browse/`](../docs/archive/apiome-browse/) — history, not a description
  of the product as it is (DOCS-1.14)

## Troubleshooting

For common issues and solutions, see the archived [TROUBLESHOOTING.md](../docs/archive/apiome-browse/TROUBLESHOOTING.md).

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

