# Objectified - API Paths Designer: Feature Roadmap

> **Enterprise-grade Visual API Design Platform**  
> React Flow-based path definition, operation design, and OpenAPI 3.1 specification management for software engineers
> 
> **Last Updated**: December 29, 2025  
> **Version**: 2.0 - Visual OpenAPI Path Definition, Testing & Enterprise Integration  
> **Target Audience**: Software Engineers, API Architects, Platform Engineers

---

## Core Architecture & Implementation

### 1. React Flow Canvas Foundation

The Paths Designer is built on React Flow, providing an infinite canvas workspace optimized for complex API specifications. Engineers can design APIs with hundreds of endpoints while maintaining visual clarity through zoom, pan, and mini-map navigation.

#### Canvas Features ✅ PLANNED

- **Dedicated Paths Tab**: Third Studio tab with independent React Flow instance
- **Infinite Canvas**: Zoom from 10% to 500% with smooth panning
- **Mini-Map Navigation**: Bird's-eye view for large API specs (50+ paths)
- **Node Library Panel**: Draggable node types organized by category
- **Keyboard Navigation**: Vim-style hjkl movement, arrow keys, space to pan
- **Command Palette**: `Cmd/Ctrl+K` for quick actions (create path, add method, etc.)
- **Grid Snapping**: Optional alignment grid with 10/20/50px spacing
- **Selection Tools**: Multi-select with drag, `Shift+Click`, rubber band selection
- **Undo/Redo**: Full action history with `Cmd/Ctrl+Z` and `Cmd/Ctrl+Shift+Z`

| Ticket | Feature                                   |
|--------|-------------------------------------------|

---

## Visual Node System

### 2. Node Types & Visual Design

Each OpenAPI concept is represented as a distinct node type with color-coded visual identity, making API structure immediately recognizable.

#### 2.1 Path Nodes 📋 PARTIALLY IMPLEMENTED

**Visual Design**: Rounded rectangle with URL path as header, gray-blue gradient background

**Configurable Properties**: 📋 PLANNED
- 📋 Path pattern with inline variable extraction: `/users/{userId}/posts/{postId}`
- 📋 Summary and description (markdown support)
- 📋 Server overrides for multi-environment routing
- 📋 Deprecated flag with visual strikethrough
- 📋 Path tags for logical grouping
- 📋 Common parameters inherited by all operations
- 📋 External documentation links

| Ticket | Feature                                                              |
|--------|----------------------------------------------------------------------|
| #352   | Adding a path to the path canvas                                     |
| #353   | Paths should include a summary and description                       |
| #354   | Add deprecated flag to support deprecation with visual strikethrough |
| #355   | Add tags to paths for visual grouping                                |
| #356   | Add external documentation links for paths                           |

**Features**: 📋 PLANNED
- 📋 Click on `{variable}` to open inline schema editor
- 📋 Drag schema property onto variable for type binding
- 📋 Visual validation: invalid paths show red border
- 📋 Path template preview with sample values

| Ticket | Feature                                                                  |
|--------|--------------------------------------------------------------------------|
| #357   | Click on '{variable}' in path to open inline schema editor               |
| #358   | Add the ability to drag a schema property to a variable for type binding |
| #359   | Add invalid paths with a red border                                      |
| #360   | Add path template preview with sample values                             |

#### 2.2 Method Nodes (HTTP Operations) 📋 PLANNED

**Visual Design**: Color-coded badges attached to path nodes

| Method | Color  | Common Use Cases              |
|--------|--------|-------------------------------|
| GET    | Green  | Read, list, search operations |
| POST   | Blue   | Create, submit, trigger       |
| PUT    | Orange | Full resource replacement     |
| PATCH  | Purple | Partial updates               |
| DELETE | Red    | Resource deletion             |
| HEAD   | Gray   | Metadata retrieval            |
| OPTIONS| Gray   | CORS preflight                |

**Configurable Properties**:
- 📋 Operation ID (auto-generated from method + path)
- 📋 Tags for API grouping
- 📋 Summary and description
- 📋 Request body schema binding
- 📋 Response definitions (status codes + schemas)
- 📋 Parameters (query, header, cookie)
- 📋 Security requirements
- 📋 Deprecated flag
- 📋 Private flag (unexposed endpoints)
- 📋 External docs
- 📋 Custom `x-*` extensions

| Ticket | Feature                                                  |
|--------|----------------------------------------------------------|
| #361   | Add operationId auto-generation                          |
| #362   | Add tags for API Grouping                                |
| #363   | Add summary and description to HTTP Operation            |
| #364   | Add request body schema binding                          |
| #365   | Add response definitions to HTTP Operation               |
| #366   | Add parameters (query, header, cookie) to HTTP Operation |
| #367   | Add security requirements to HTTP Operation              |
| #368   | Add deprecated flag to HTTP Operation                    |
| #369   | Add private flag to HTTP Operation                       |
| #370   | Add external docs to HTTP Operation                      |
| #371   | Add custom x-* extensions to HTTP Operation              |

#### 2.3 Schema Reference Nodes 📋 PLANNED

**Visual Design**: Compact card showing schema name, type, and property count

**Purpose**: Create visual connections between schema definitions (from Schema tab) and API operations

**Features**:
- 📋 Drag schema from library panel onto canvas
- 📋 Connect to method nodes for request/response binding
- 📋 Hover to see schema preview (collapsed property tree)
- 📋 Click to navigate to schema definition in Schema tab
- Visual badge showing schema version compatibility
- 📋 Inline schema override for operation-specific modifications

| Ticket | Feature                                                                          |
|--------|----------------------------------------------------------------------------------|
| #372   | Add ability to drag schema from library panel onto canvas                        |
| #373   | Add ability to connect schema nodes to method nodes for request/response binding |
| #374   | Hover over a schema node to see a schema preview (collapsed property tree)       |
| #375   | Click to edit schema (change views)                                              |
| #376   | Inline schema override for operation-specific modifications                      |

#### 2.4 Parameter Nodes 📋 PLANNED

**Visual Design**: Small chips/tags color-coded by parameter location

| Location | Color  | Icon       |
|----------|--------|------------|
| Query    | Blue   | ? icon     |
| Path     | Green  | {} icon    |
| Header   | Purple | H icon     |
| Cookie   | Orange | 🍪 icon    |

**Configurable Properties**:
- 📋 Parameter name (with auto-suggest from common patterns)
- ✅ Location: query, path, header, cookie (fixed from dragged node)
- 📋 Schema type (string, number, boolean, array, object)
- 📋 Required flag
- 📋 Default value
- 📋 Description
- 📋 Validation rules (min/max, pattern, enum)
- 📋 Serialization style (form, spaceDelimited, pipeDelimited, deepObject)
- 📋 Explode flag for arrays/objects
- 📋 Deprecated flag

| Ticket | Feature                                                |
|--------|--------------------------------------------------------|
| #377   | Parameter name with auto-suggest from common patterns  |
| #378   | Schema type should be configurable                     |
| #379   | Add required flag to parameters                        |
| #380   | Add default value to parameters                        |
| #381   | Add description to parameters                          |
| #382   | Add validation rules to parameters                     |
| #383   | Add serialization style to parameters (default "form") |
| #384   | Add explode flag to parameters                         |
| #385   | Add deprecated flag to parameters                      |

#### 2.5 Request Body Nodes 📋 PLANNED

**Visual Design**: Input port icon with blue accent, shows content types

**Configurable Properties**:
- 📋 Content type map (application/json, multipart/form-data, etc.)
- 📋 Schema binding per content type
- 📋 Required flag
- 📋 Description
- 📋 Example values
- 📋 Encoding options (for multipart)

**Advanced Features**:
- Multiple content types per operation (JSON vs XML vs form-data)
- Polymorphic schemas with oneOf/anyOf/allOf visualization
- Discriminator configuration for union types
- File upload configuration with encoding options
- Example value editor with JSON/YAML/XML toggle

| Ticket | Feature                                   |
|--------|-------------------------------------------|
| #386   | Content type map (application/json, multipart/form-data, etc.) |
| #387   | Schema binding per content type           |
| #388   | Add required flag to request body      |
| #389   | Add description to request body          |
| #390   | Add examples to request body node |
| #391   | Add encoding options for multipart       |

#### 2.6 Response Nodes 📋 PLANNED

**Visual Design**: Output port icon, color-coded by status code family

| Status Range | Color  | Common Codes                     |
|--------------|--------|----------------------------------|
| 2XX Success  | Green  | 200 OK, 201 Created, 204 No Content |
| 3XX Redirect | Blue   | 301, 302, 304 Not Modified       |
| 4XX Client   | Yellow | 400, 401, 403, 404, 422          |
| 5XX Server   | Red    | 500, 502, 503, 504               |

**Configurable Properties**:
- 📋 Status code (100-599)
- 📋 Description (semantic suggestions per status code)
- 📋 Response headers (name, schema, description)
- 📋 Content type map with schema bindings
- 📋 Links (HATEOAS navigation)
- 📋 Examples per content type

**Advanced Features**:
- 📋 Response range patterns: 2XX, 4XX, 5XX wildcards
- 📋 Default response for catch-all error handling
- 📋 Link objects for response-driven navigation
- 📋 Header templates (pagination, rate limiting, CORS)

| Ticket | Feature                                                |
|--------|--------------------------------------------------------|
| #392   | Status code (100-599)                                  |
| #393   | Add description to response                            |
| #394   | Add response headers (name, schema, description)       |
| #395   | Add content type map with schema bindings              |
| #396   | Add links (HATEOAS navigation)                         |
| #397   | Add content-type examples to response node             |
| #398   | Add response range patterns to response nodes          |
| #399   | Add default response to HTTP Operation                 |
| #400   | Add link objects for response-driven navigation        |
| #401   | Add header templates (pagination, rate limiting, CORS) |

---

## Engineer-Focused Features

### 3. Developer Experience Enhancements

#### 3.1 Code-Level Editors 📋 PLANNED

Software engineers need precision and control. The Paths Designer provides inline editors with IDE-quality features:

**JSON Schema Editor**:
- Syntax highlighting with theme support (light/dark)
- Bracket matching and auto-closing
- Real-time validation with inline error messages
- Autocomplete for OpenAPI keywords and schema properties
- Quick reference sidebar for OpenAPI 3.1 spec

**Example Value Editor**:
- Format toggle: JSON, YAML, XML, form-data
- Syntax validation per content type
- Auto-format with `Shift+Alt+F`
- Copy example as cURL command
- Import from file or paste from clipboard

**Markdown Description Editor**:
- Live preview split view
- CommonMark + GitHub Flavored Markdown
- Code block syntax highlighting
- Link to schema definitions
- Image upload for API documentation

| Ticket | Feature                                   |
|--------|-------------------------------------------|

#### 3.2 Keyboard-First Navigation 📋 PLANNED

Optimized for engineers who prefer keyboard over mouse:

| Action                  | Shortcut           | Description                      |
|-------------------------|--------------------|----------------------------------|
| Open command palette    | `Cmd/Ctrl+K`       | Quick actions menu               |
| Create new path         | `Cmd/Ctrl+N`       | Add path node at canvas center   |
| Add GET method          | `G`                | Add GET to selected path         |
| Add POST method         | `P`                | Add POST to selected path        |
| Add parameter           | `Q` (query)        | Add query param to selected op   |
| Toggle request body     | `B`                | Add/remove request body          |
| Add 200 response        | `2`                | Add 200 OK response              |
| Add 404 response        | `4`                | Add 404 Not Found response       |
| Delete selected         | `Delete/Backspace` | Remove node with confirmation    |
| Duplicate               | `Cmd/Ctrl+D`       | Clone selected node              |
| Search/filter           | `/`                | Focus search box                 |
| Navigate canvas         | `Arrow keys`       | Pan canvas (hold Shift to zoom)  |
| Select all              | `Cmd/Ctrl+A`       | Select all nodes                 |
| Copy                    | `Cmd/Ctrl+C`       | Copy selected nodes              |
| Paste                   | `Cmd/Ctrl+V`       | Paste at cursor position         |

| Ticket | Feature                                   |
|--------|-------------------------------------------|

#### 3.3 Real-Time Validation 📋 PLANNED

Catch errors as you design, not during export:

**Validation Rules**:
- ✅ Unique operation IDs across all paths
- ✅ Valid path variable syntax: `{var}` not `<var>` or `:var`
- ✅ All path variables have corresponding parameter definitions
- ✅ Required request body has at least one content type
- ✅ Status codes are valid HTTP codes (100-599)
- ✅ Schema references point to existing schemas
- ✅ No circular dependencies in schema composition
- ✅ Security schemes referenced in operations exist in global config
- ✅ Example values conform to their schemas
- ⚠️ Warning for missing operation descriptions
- ⚠️ Warning for operations without tags
- ⚠️ Warning for deprecated operations without migration docs

**Visual Indicators**:
- Red border on nodes with errors
- Yellow border on nodes with warnings
- Error/warning badge with count
- Hover for detailed error message
- Click to jump to fix location

| Ticket | Feature                                   |
|--------|-------------------------------------------|

#### 3.4 OpenAPI Export & Import 📋 PLANNED

**Export Formats**:
- OpenAPI 3.1 JSON (prettified or minified)
- OpenAPI 3.1 YAML (with proper indentation)
- Swagger 2.0 (legacy compatibility)
- Postman Collection v2.1
- Insomnia Collection
- API Blueprint (Markdown-based)
- RAML 1.0

**Export Options**:
- Include/exclude examples
- Include/exclude descriptions
- Bundle schemas inline or use $ref links
- Add custom `x-*` extensions
- Resolve all $ref to embedded schemas (dereferencing)
- Add server URLs for multiple environments

**Import Support**:
- OpenAPI 3.0/3.1 JSON/YAML
- Swagger 2.0 JSON/YAML
- Postman Collection v2.1
- Insomnia Collection v4
- HAR (HTTP Archive) files
- cURL commands (converts to operation)

| Ticket | Feature                                       |
|--------|-----------------------------------------------|
| #425   | Improve OpenAPI Specification import handling |

### 3.5 OpenAPI Specification Output 📋 PLANNED

**Full Spec Generation** ✅ PARTIALLY IMPLEMENTED
- **Specification Components**:
    - ✅ `info` (title, version, description, contact, license, termsOfService)
    - `servers` (multiple environments with variables)
    - `paths` (all operations with full configuration)
    - `components/schemas` (existing schema support)
    - `components/parameters` (reusable parameters)
    - `components/requestBodies` (reusable request bodies)
    - `components/responses` (reusable responses)
    - `components/headers` (reusable headers)
    - `components/securitySchemes` (auth definitions)
    - `components/links` (HATEOAS links)
    - `components/callbacks` (webhooks)
    - `security` (global security requirements)
    - `tags` (tag definitions with descriptions)
    - `externalDocs` (external documentation)

| Ticket | Feature Description                                |
|--------|----------------------------------------------------|
| #424   | Update OpenAPI Generator to include missing fields |

---

## Security & Authentication

### 4. Security Scheme Integration 📋 PLANNED

#### 4.1 Global Security Schemes

Define security schemes once, apply to multiple operations:

**Supported Schemes**:
- 📋 **API Key**: Header, query, or cookie-based keys
- 📋 **HTTP**: Basic, Bearer, or custom HTTP auth
- 📋 **OAuth 2.0**: Authorization Code, Implicit, Client Credentials, Password flows
- 📋 **OpenID Connect**: Discovery URL with scopes
- 📋 **Mutual TLS**: Certificate-based authentication
- 📋 **Custom security schemes**

| Ticket | Feature Description                 |
|--------|-------------------------------------|
| #410   | Add API Keys                        |
| #411   | Add HTTP Authentication Schemes     |
| #412   | OAuth2 Security Schemes             |
| #413   | Add OpenID Connect Security Schemes |
| #414   | Add Mutual TLS Security Schemes     |
| #415   | Add Custom Security Schemes         |

**Visual Design**:
- 📋 Security scheme library panel
- 📋 Drag scheme onto method node to apply
- 📋 Visual badge showing active schemes on operations
- 📋 Scope selector for OAuth2/OIDC

| Ticket | Feature                                               |
|--------|-------------------------------------------------------|
| #416   | Security scheme library panel                         |
| #417   | Drag scheme onto method node to apply                 |
| #418   | Add visual badge to show active schemes on operations |
| #419   | Scope selector for OAuth2/OIDC                        |

#### 4.2 Operation-Level Security 📋 PLANNED

Each operation can override global defaults:

- 📋 Apply multiple security schemes (AND/OR logic)
- 📋 Configure required scopes per operation
- 📋 Mark operation as unsecured (public endpoint)
- 📋 Add security descriptions for documentation

| Ticket | Feature                                         |
|--------|-------------------------------------------------|
| #420   | Apply multiple security schemes to an operation |
| #421   | Configure required scopes per operation         |
| #422   | Mark operation as unsafe/public                 |
| #423   | Add security descriptions for documentation     |

#### 4.3 Server Definitions 📋 PLANNED

**Server Configuration** ✅ PARTIALLY IMPLEMENTED
- 📋 Multiple server definitions
- Server variables with enum values
- Environment-specific servers (dev, staging, prod)
- 📋 Server descriptions
- 📋 Relative server paths

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|
| #565   | Add ability to define multiple servers |

---

## Testing & Documentation

### 5. Integrated API Testing 📋 PLANNED (Q2 2026)

#### 5.1 Built-In API Tester

Test operations directly from the canvas without leaving the Paths Designer:

**Features**:
- Click "Test" button on any method node
- Auto-populate request from schema + examples
- Edit request body, headers, query params
- Select environment/server for testing
- Send HTTP request and view response
- Response inspector: body, headers, status, timing
- Save as test case for regression testing
- Generate cURL command from request

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

**Advanced Testing**:
- Request history with replay functionality
- Environment variables for dynamic values
- Pre-request scripts (JavaScript)
- Post-response assertions (status code, JSON path, regex)
- Collection runner for sequential operation testing
- Mock responses when server not available

| Ticket | Feature                                   |
|--------|-------------------------------------------|

#### 5.2 Mock Server Generation 📋 PLANNED (Q2 2026)

Auto-generate mock APIs for frontend development before backend is ready:

**Features**:
- One-click mock server deployment per version
- Serves example responses from operation definitions
- Randomized data generation from schemas
- Configurable response delays for latency simulation
- Error response simulation (4XX, 5XX)
- Request validation against schemas
- Mock server URL for client integration

| Ticket | Feature                                   |
|--------|-------------------------------------------|

#### 5.3 Interactive Documentation 📋 PLANNED (Q2 2026)

Auto-generated API docs with "Try It Out" functionality:

**Features**:
- ReDoc/Swagger UI-style documentation
- Generated from path definitions
- Searchable operation catalog
- Tag-based navigation
- Try It Out for all operations
- Code snippet generation (cURL, JavaScript, Python, etc.)
- Download OpenAPI spec from docs page

| Ticket | Feature                                   |
|--------|-------------------------------------------|

---

## Code Generation

### 6. SDK & Server Stub Generation 📋 PLANNED (Q2 2026)

#### 6.1 Client SDK Generation

Generate type-safe client libraries from path definitions:

**Supported Languages**:
- **TypeScript/JavaScript**: fetch, axios, or custom HTTP client
- **Python**: httpx, requests, or aiohttp
- **Java**: OkHttp, RestTemplate, or WebClient
- **C#**: HttpClient with strongly-typed models
- **Go**: net/http with generated structs
- **Rust**: reqwest with serde models

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

**SDK Features**:
- Type-safe request/response models
- Automatic serialization/deserialization
- Error handling with typed exceptions
- Retry logic with exponential backoff
- Authentication handling (API key, OAuth2, etc.)
- Request/response interceptors
- TypeScript IntelliSense support

| Ticket | Feature                                   |
|--------|-------------------------------------------|

#### 6.2 Server Stub Generation

Generate backend API stubs with routing and validation:

**Supported Frameworks**:
- **Node.js**: Express, Fastify, NestJS
- **Python**: FastAPI, Flask, Django REST
- **Java**: Spring Boot, Quarkus
- **Go**: Gin, Echo, Chi
- **Rust**: Actix-web, Rocket

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

**Generated Code Includes**:
- Route definitions mapped to operations
- Request validation middleware
- Response serialization
- OpenAPI documentation endpoint
- Health check endpoint
- Error handling middleware
- Authentication middleware stubs

| Ticket | Feature                                   |
|--------|-------------------------------------------|

---

#### Core Features

- `obj_path_canvas`: Store React Flow node positions, viewport state, and zoom level per project version
- `obj_path_edges`: Edge connections between nodes with source/target handles and edge types
- `obj_path_node_data`: Serialized node configuration data with type-specific properties
- Optimistic updates with debounced persistence (300ms delay) for smooth canvas interaction
- Undo/redo history stack with configurable depth (default: 50 operations)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Canvas snapshots for version comparison and rollback
- Collaborative editing state with real-time sync markers
- Layout algorithm persistence for auto-arrange preferences
- Node grouping and folder structures for complex APIs

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 4.3 Version Control Integration

#### Core Features

- Path definitions linked to project versions via `obj_project_versions` FK
- Change tracking: created_at, updated_at, created_by, updated_by on all path tables
- Soft delete with deleted_at for path recovery
- Version promotion: copy paths between versions with conflict detection

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Branching support: fork paths for experimental changes
- Merge conflict resolution UI for path definition conflicts
- Change diff visualization between versions
- Audit log for compliance: who changed what, when

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### OpenAPI 3.1 / JSON Schema 2020-12 Feature Coverage

**Not Yet Implemented** 📋 PLANNED (Low Priority)
- `$id`: Schema identifier for referencing
- `$schema`: JSON Schema version declaration
- `$ref`: Schema references (currently handled via class references)
- `$defs`: Reusable schema definitions
- `$anchor`: Named anchors for deep linking
- `$dynamicRef`/`$dynamicAnchor`: Dynamic references (advanced)
- `$vocabulary`: Custom vocabulary definitions
- `contentMediaType`: Media type for string content
- `contentEncoding`: Content encoding (base64, etc.)
- `contentSchema`: Schema for decoded content

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

---

## 5. Enterprise Features

### 5.1 Security Configuration

#### Core Features

- Security scheme library: OAuth2, API Key, HTTP Basic/Bearer, OpenID Connect
- Drag security nodes onto operations to apply authentication requirements
- Scope selector for OAuth2 flows with visual scope hierarchy
- Multiple security requirements with AND/OR logic visualization
- Global security defaults with per-operation override capability

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Custom security scheme extensions for proprietary auth systems
- Security requirement inheritance from parent paths
- Role-based access preview: see which roles can access which endpoints
- Security audit report generation for compliance review
- JWT claim mapping visualization for token-based auth

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 5.2 Multi-Tenant & Team Collaboration

#### Core Features

- Organization-scoped path libraries for shared endpoint patterns
- Team-level path templates: CRUD generators, pagination patterns
- Path ownership assignment with edit/view permissions
- Comment threads on paths and operations for design review
- Real-time collaboration indicators: see who's editing which path

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Path approval workflows for production API changes
- Change request system with diff preview and approver assignment
- API governance policies: naming conventions, security requirements
- Cross-project path sharing for microservice coordination
- Conflict resolution for concurrent edits with merge tools

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 5.3 API Gateway Integration

#### Core Features

- Rate limiting configuration per operation with `x-rateLimit` extensions
- Request/response transformation rules attached to operations
- Caching policy configuration with TTL and invalidation rules
- CORS configuration at path and operation level

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Kong, AWS API Gateway, Azure APIM extension export
- Circuit breaker configuration for resilience patterns
- Request validation enforcement toggles
- Backend service binding for gateway proxy configuration
- Traffic policy rules: canary, blue-green, A/B testing metadata

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

---

## 6. Testing & Validation

### 6.1 Integrated Swagger UI

#### Core Features

- Embedded Swagger UI panel within Studio for live API testing
- Real-time spec sync: changes in visual designer reflect immediately in Swagger
- Try It Out functionality with configurable base URL and auth headers
- Request/response logging with copy-to-curl capability
- Environment variable support for dynamic base URLs and auth tokens
- Response validation against defined schemas with error highlighting

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Mock server generation from OpenAPI spec for frontend development
- Request history with replay capability
- Response diff comparison between expected and actual
- Performance metrics: response time, payload size tracking
- Collection runner for sequential endpoint testing

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 6.2 Specification Validation

#### Core Features

- Real-time OpenAPI 3.1 compliance validation with inline error markers
- Missing operationId detection with auto-generation suggestions
- Unused schema detection: identify orphaned schema definitions
- Circular reference detection in schema hierarchies
- Security requirement validation: ensure all operations have security

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Custom lint rules for organization-specific conventions
- Spectral integration for industry-standard API linting
- Breaking change detection between versions
- Completeness scoring: documentation coverage percentage
- Best practices advisor: suggest improvements based on API design patterns

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 6.3 Contract Testing

#### Core Features

- Example-based request generation for each operation
- Response schema validation with detailed mismatch reporting
- Status code coverage tracking per operation
- Export test cases to Postman, Insomnia formats

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Pact contract generation for consumer-driven testing
- Dredd test generation for automated contract validation
- CI/CD integration hooks for automated testing pipelines
- Test coverage reports with gap analysis

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

---

## 7. Automatic Endpoint Generation

### 7.1 Schema-to-Endpoint Generation

#### Core Features

- Right-click schema → Generate CRUD Endpoints: creates GET, POST, PUT, DELETE paths
- Configurable path pattern: `/resources`, `/resources/{id}`, `/resources/{id}/subresources`
- Automatic request body binding to schema for POST/PUT operations
- Response schema inference: wrap in array for list endpoints, single for detail
- Standard error response generation: 400, 401, 403, 404, 500 templates
- OperationId generation following RESTful conventions: `listUsers`, `getUser`, `createUser`

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Nested resource generation: `/users/{userId}/posts` creates related endpoints
- Custom generation templates: define your own CRUD patterns
- Bulk operation generation: `POST /resources/bulk`, `DELETE /resources/bulk`
- Search endpoint generation with query parameter inference from schema
- Action endpoint generation: `POST /resources/{id}/actions/activate`
- Soft delete vs hard delete pattern selection

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 7.2 Pattern Libraries

#### Core Features

- Pagination pattern: page/limit, cursor-based, or offset-based with response envelope
- Filtering pattern: query parameter generation from schema filterable fields
- Sorting pattern: sort, order query parameters with field validation
- Error response pattern: RFC 7807 Problem Details or custom format
- Authentication patterns: Bearer token, API key, OAuth2 scope requirements

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Custom pattern creation and sharing within organization
- Industry-specific patterns: healthcare (FHIR), finance (Open Banking)
- Pattern composition: combine multiple patterns for complex operations
- Pattern versioning: track changes to organizational standards

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 7.3 Code Generation Integration

#### Core Features

- OpenAPI Generator integration for client SDK generation
- Server stub generation: Express, FastAPI, Spring Boot templates
- TypeScript type generation from OpenAPI spec
- One-click download of generated code artifacts

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Custom generator templates for proprietary frameworks
- Git integration: push generated code to repository
- Incremental generation: update only changed endpoints
- Multi-language generation in single workflow

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

---

## 8. UI/UX Design Considerations

### 8.1 Visual Design System

#### Core Features

- Consistent node styling with schema designer: same color palette, typography, shadows
- HTTP method color coding: GET (#48BB78), POST (#4299E1), PUT (#ED8936), DELETE (#F56565), PATCH (#9F7AEA)
- Status code color bands: 2XX (green), 3XX (blue), 4XX (yellow), 5XX (red)
- Iconography for node types: path (route), method (HTTP verb), schema (brackets)
- Dark mode support with accessible contrast ratios (WCAG AA)
- Responsive canvas with touch support for tablet use

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Customizable color themes for organization branding
- High contrast mode for accessibility
- Print-optimized layout for documentation export
- Presentation mode: hide toolbars for demos and reviews

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 8.2 Interaction Patterns

#### Core Features

- Drag from library panel to canvas to create nodes
- Double-click node to open configuration panel (slide-in drawer)
- Edge drawing: drag from output handle to input handle to connect
- Multi-select with Shift+click or rectangle selection
- Keyboard shortcuts: Delete (remove), Cmd+D (duplicate), Cmd+Z (undo), Cmd+G (group)
- Context menu on right-click with relevant actions
- Snap-to-grid alignment with optional grid visibility

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Auto-layout algorithms: hierarchical, force-directed, orthogonal
- Smart guides for manual alignment
- Copy/paste across browser tabs with serialization
- Gesture support: pinch-to-zoom, two-finger pan
- Command palette (Cmd+K) for quick actions

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### 8.3 React Flow Implementation

#### Core Features

- Custom node components with TypeScript type safety
- Node resize handles for adjustable container sizes
- Connection validation: prevent invalid edge connections (e.g., response to path)
- Smooth edge rendering with bezier curves and step lines
- Node grouping with collapsible containers
- Performance optimization: virtualization for 100+ nodes

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Features

- Custom edge types: labeled, animated, conditional
- Sub-flow navigation: drill into complex operations
- Background patterns: dots, lines, cross-hatch
- Fit-to-view controls with animation
- Export canvas as PNG/SVG for documentation

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

---

## 9. Visual Design Specification

This section describes the visual appearance and layout of the Paths Designer within the Studio interface, including the React Flow canvas structure, node designs, and interaction patterns.

### 9.3 Node Visual Designs

Each node type has a distinct visual appearance to enable quick identification on the canvas.

#### PathNode (Primary Container)

The PathNode serves as the top-level container for an API endpoint:

```
┌─────────────────────────────────────────────────────────────┐
│ ○ PATH                                           ⋮ ≡       │  ← Header with drag handle
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   /api/v1/users/{userId}/orders                             │  ← Path pattern (editable)
│                    ├────┘                                   │
│                    └─ {userId} detected as path variable    │
│                                                             │
│   Summary: Manage user orders                               │  ← Optional summary
│                                                             │
│   ┌─ METHODS ─────────────────────────────────────────────┐ │
│   │                                                       │ │
│   │  (Drop zone for MethodNodes)                          │ │  ← Methods attach here
│   │                                                       │ │
│   └───────────────────────────────────────────────────────┘ │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  Tags: orders, users          │  ⚠️ deprecated             │  ← Footer metadata
└─────────────────────────────────────────────────────────────┘
     │
     ○ ← Output handle for edge connections
```

#### MethodNode (HTTP Verb Container)

MethodNodes are color-coded and nest inside PathNodes:

```
GET (Green #48BB78)                    POST (Blue #4299E1)
┌────────────────────────────┐         ┌────────────────────────────┐
│ ●━━ GET ━━━━━━━━━━━━━━━━━ │         │ ●━━ POST ━━━━━━━━━━━━━━━━ │
├────────────────────────────┤         ├────────────────────────────┤
│ operationId: listUserOrders│         │ operationId: createOrder   │
│                            │         │                            │
│ ┌─ Request ──────────────┐ │         │ ┌─ Request ──────────────┐ │
│ │ (No body for GET)      │ │         │ │ ○ CreateOrderRequest   │←── Schema ref
│ └────────────────────────┘ │         │ │   application/json     │ │
│                            │         │ └────────────────────────┘ │
│ ┌─ Responses ────────────┐ │         │                            │
│ │ 200 ○ Order[]          │←── Schema │ ┌─ Responses ────────────┐ │
│ │ 401 ○ ErrorResponse    │ │  refs   │ │ 201 ○ Order            │ │
│ │ 404 ○ ErrorResponse    │ │         │ │ 400 ○ ValidationError  │ │
│ └────────────────────────┘ │         │ │ 401 ○ ErrorResponse    │ │
│                            │         │ └────────────────────────┘ │
│ 🔐 bearerAuth             │         │                            │
└────────────────────────────┘         │ 🔐 bearerAuth             │
                                       └────────────────────────────┘

PUT (Orange #ED8936)                   DELETE (Red #F56565)
┌────────────────────────────┐         ┌────────────────────────────┐
│ ●━━ PUT ━━━━━━━━━━━━━━━━━ │         │ ●━━ DELETE ━━━━━━━━━━━━━━ │
├────────────────────────────┤         ├────────────────────────────┤
│ operationId: updateOrder   │         │ operationId: deleteOrder   │
│ ...                        │         │ ...                        │
└────────────────────────────┘         └────────────────────────────┘

PATCH (Purple #9F7AEA)                 OPTIONS/HEAD (Gray #718096)
┌────────────────────────────┐         ┌────────────────────────────┐
│ ●━━ PATCH ━━━━━━━━━━━━━━━ │         │ ●━━ OPTIONS ━━━━━━━━━━━━━ │
├────────────────────────────┤         ├────────────────────────────┤
│ operationId: patchOrder    │         │ operationId: orderOptions  │
│ ...                        │         │ ...                        │
└────────────────────────────┘         └────────────────────────────┘
```

#### SchemaRefNode (Draggable from Library)

When a schema is dragged from the library panel onto the canvas or into a request/response zone:

```
┌─────────────────────────────────┐
│ { } User                    ↗️  │  ← Click to jump to Schema Designer
├─────────────────────────────────┤
│                                 │
│  id: string (uuid)              │  ← Preview of top-level properties
│  email: string (email)          │
│  name: string                   │
│  createdAt: string (date-time)  │
│  ... +3 more properties         │
│                                 │
├─────────────────────────────────┤
│  ○ ref    ○ array    ○ partial  │  ← Modifier toggles
└─────────────────────────────────┘
  │
  ○ ← Handle for connecting to Request/Response
```

#### ParameterNode

Parameters appear as compact chips that can be attached to operations:

```
Query Parameter:                    Path Parameter (auto-detected):
┌─────────────────────────────┐    ┌─────────────────────────────┐
│ ? limit                     │    │ : userId                    │
│   integer · optional        │    │   string (uuid) · required  │
│   default: 20               │    │   in: path                  │
└─────────────────────────────┘    └─────────────────────────────┘

Header Parameter:                   Cookie Parameter:
┌─────────────────────────────┐    ┌─────────────────────────────┐
│ H X-Request-ID              │    │ 🍪 session_id               │
│   string · optional         │    │   string · required         │
└─────────────────────────────┘    └─────────────────────────────┘
```

#### ResponseNode

Response nodes show status code with color coding:

```
2XX Success (Green background)      4XX Client Error (Yellow/Orange)
┌─────────────────────────────┐    ┌─────────────────────────────┐
│ 200 OK                  ✓   │    │ 400 Bad Request         ⚠️  │
├─────────────────────────────┤    ├─────────────────────────────┤
│ Content:                    │    │ Content:                    │
│ ○ application/json          │    │ ○ application/json          │
│   └─ { } User               │    │   └─ { } ValidationError    │
│                             │    │                             │
│ Headers:                    │    │ Headers:                    │
│   X-RateLimit-Remaining     │    │   (none)                    │
└─────────────────────────────┘    └─────────────────────────────┘

5XX Server Error (Red background)   Default Response (Gray)
┌─────────────────────────────┐    ┌─────────────────────────────┐
│ 500 Internal Error      ✕   │    │ default                 ∿   │
├─────────────────────────────┤    ├─────────────────────────────┤
│ Content:                    │    │ Content:                    │
│ ○ application/json          │    │ ○ application/json          │
│   └─ { } ErrorResponse      │    │   └─ { } ErrorResponse      │
└─────────────────────────────┘    └─────────────────────────────┘
```

### 9.4 Complete Canvas Example

Here's how a complete API endpoint design might appear on the canvas:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    REACT FLOW CANVAS                                     │
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │
│                                                                                          │
│  │ ┌───────────────────────────────────────────────────────────────────────────────┐ │  │
│    │ ○ PATH                                                                    ⋮ ≡ │    │
│  │ ├───────────────────────────────────────────────────────────────────────────────┤ │  │
│    │                                                                               │    │
│  │ │   /api/v1/users/{userId}                                                      │ │  │
│    │                                                                               │    │
│  │ │   ┌─────────────────────────────────────────────────────────────────────────┐ │ │  │
│    │   │                                                                         │ │    │
│  │ │   │  ┌────────────────────────┐    ┌────────────────────────┐               │ │ │  │
│    │   │  │ ●━━ GET ━━━━━━━━━━━━━ │    │ ●━━ PUT ━━━━━━━━━━━━━━ │               │ │    │
│  │ │   │  ├────────────────────────┤    ├────────────────────────┤               │ │ │  │
│    │   │  │ operationId: getUser   │    │ operationId: updateUser│               │ │    │
│  │ │   │  │                        │    │                        │               │ │ │  │
│    │   │  │ ┌─ Responses ────────┐ │    │ ┌─ Request ──────────┐ │               │ │    │
│  │ │   │  │ │ 200 ────────────┐  │ │    │ │                    │ │               │ │ │  │
│    │   │  │ │     ┌───────────┴──┴─┴────┴─┤ { } UpdateUserReq  │ │               │ │    │
│  │ │   │  │ │     │ { } User         │◀───│     app/json       │ │               │ │ │  │
│    │   │  │ │     │                  │    │ └────────────────────┘               │ │    │
│  │ │   │  │ │     │  id: string      │    │                        │             │ │ │  │
│    │   │  │ │     │  email: string   │    │ ┌─ Responses ────────┐ │             │ │    │
│  │ │   │  │ │     │  name: string    │    │ │ 200 ○──────────────┼─┘             │ │ │  │
│    │   │  │ │     │  role: enum      │    │ │ 400 ○ ValidationErr│               │ │    │
│  │ │   │  │ │     └──────────────────┘    │ │ 404 ○ NotFoundError│               │ │ │  │
│    │   │  │ │ 401 ○ ErrorResponse    │    │ └────────────────────┘               │ │    │
│  │ │   │  │ │ 404 ○ ErrorResponse    │    │                        │             │ │ │  │
│    │   │  │ └────────────────────────┘    │ 🔐 bearerAuth          │             │ │    │
│  │ │   │  │                        │    └────────────────────────┘               │ │ │  │
│    │   │  │ 🔐 bearerAuth          │                                             │ │    │
│  │ │   │  └────────────────────────┘    ┌────────────────────────┐               │ │ │  │
│    │   │                                │ ●━━ DELETE ━━━━━━━━━━━ │               │ │    │
│  │ │   │                                ├────────────────────────┤               │ │ │  │
│    │   │                                │ operationId: deleteUser│               │ │    │
│  │ │   │                                │                        │               │ │ │  │
│    │   │                                │ ┌─ Responses ────────┐ │               │ │    │
│  │ │   │                                │ │ 204 (No Content)   │ │               │ │ │  │
│    │   │                                │ │ 401 ○ ErrorResponse│ │               │ │    │
│  │ │   │                                │ │ 404 ○ ErrorResponse│ │               │ │ │  │
│    │   │                                │ └────────────────────┘ │               │ │    │
│  │ │   │                                │                        │               │ │ │  │
│    │   │                                │ 🔐 bearerAuth          │               │ │    │
│  │ │   │                                └────────────────────────┘               │ │ │  │
│    │   │                                                                         │ │    │
│  │ │   └─────────────────────────────────────────────────────────────────────────┘ │ │  │
│    │                                                                               │    │
│  │ ├───────────────────────────────────────────────────────────────────────────────┤ │  │
│    │  Tags: users                    │  Path Params: userId (uuid)                 │    │
│  │ └───────────────────────────────────────────────────────────────────────────────┘ │  │
│                                                                                          │
│  │                                                                                   │  │
│     ┌─ FLOATING SCHEMA REFERENCES ─────────────────────────────────────────────────┐    │
│  │  │                                                                              │ │  │
│     │  ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐ │    │
│  │  │  │ { } User        ↗️  │   │ { } UpdateUserReq↗️  │   │ { } ErrorResponse↗️ │ │ │  │
│     │  ├─────────────────────┤   ├─────────────────────┤   ├─────────────────────┤ │    │
│  │  │  │ id: string (uuid)  │   │ email?: string      │   │ code: string        │ │ │  │
│     │  │ email: string      │   │ name?: string       │   │ message: string     │ │    │
│  │  │  │ name: string       │   │ role?: enum         │   │ details?: object    │ │ │  │
│     │  │ role: enum         │   │                     │   │                     │ │    │
│  │  │  │ createdAt: date    │   │                     │   │                     │ │ │  │
│     │  └──────────○─────────┘   └──────────○─────────┘   └──────────○─────────┘ │    │
│  │  │             │                        │                        │            │ │  │
│     │             │     ┌──────────────────┘                        │            │    │
│  │  │             │     │     ┌─────────────────────────────────────┘            │ │  │
│     │             ▼     ▼     ▼                                                  │    │
│  │  │        (Edges connect to response/request schema slots above)              │ │  │
│     │                                                                              │    │
│  │  └──────────────────────────────────────────────────────────────────────────────┘ │  │
│                                                                                          │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │
│                                                                                          │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐   │
│  │ ✓ Valid  │  Zoom: 100%  │  ⊞ Grid  │  🗺️ Mini-map  │  Nodes: 8  │  Export ▼    │   │
│  └──────────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 9.5 Properties Panel (Right Side)

When a node is selected, the properties panel shows contextual configuration:

```
┌─────────────────────────────┐
│ ✕  PATH PROPERTIES          │
├─────────────────────────────┤
│                             │
│ Path Pattern                │
│ ┌─────────────────────────┐ │
│ │ /api/v1/users/{userId}  │ │
│ └─────────────────────────┘ │
│                             │
│ ─────────────────────────── │
│ PATH VARIABLES              │
│                             │
│ ┌─────────────────────────┐ │
│ │ userId                  │ │
│ │ ┌─────────────────────┐ │ │
│ │ │ Type: string      ▼ │ │ │
│ │ └─────────────────────┘ │ │
│ │ ┌─────────────────────┐ │ │
│ │ │ Format: uuid      ▼ │ │ │
│ │ └─────────────────────┘ │ │
│ │ ☑ Required              │ │
│ └─────────────────────────┘ │
│                             │
│ ─────────────────────────── │
│ METADATA                    │
│                             │
│ Summary                     │
│ ┌─────────────────────────┐ │
│ │ User management         │ │
│ └─────────────────────────┘ │
│                             │
│ Description                 │
│ ┌─────────────────────────┐ │
│ │ Endpoints for managing  │ │
│ │ individual user         │ │
│ │ accounts...             │ │
│ └─────────────────────────┘ │
│                             │
│ Tags                        │
│ ┌─────────────────────────┐ │
│ │ users ✕ │ accounts ✕    │ │
│ │ + Add tag               │ │
│ └─────────────────────────┘ │
│                             │
│ ─────────────────────────── │
│ OPTIONS                     │
│                             │
│ ☐ Deprecated                │
│ ☐ Override servers          │
│                             │
│ ─────────────────────────── │
│                             │
│ ┌─────────────────────────┐ │
│ │     🗑️ Delete Path      │ │
│ └─────────────────────────┘ │
│                             │
└─────────────────────────────┘
```

When a MethodNode is selected:

```
┌─────────────────────────────┐
│ ✕  GET OPERATION            │
├─────────────────────────────┤
│                             │
│ Operation ID                │
│ ┌─────────────────────────┐ │
│ │ getUserById             │ │
│ └─────────────────────────┘ │
│ 💡 Auto-generate            │
│                             │
│ ─────────────────────────── │
│ REQUEST                     │
│                             │
│ Parameters                  │
│ ┌─────────────────────────┐ │
│ │ + Add Query Param       │ │
│ │ + Add Header Param      │ │
│ └─────────────────────────┘ │
│                             │
│ ─────────────────────────── │
│ RESPONSES                   │
│                             │
│ ┌─────────────────────────┐ │
│ │ 200 OK              ✕   │ │
│ │   → User schema         │ │
│ ├─────────────────────────┤ │
│ │ 401 Unauthorized    ✕   │ │
│ │   → ErrorResponse       │ │
│ ├─────────────────────────┤ │
│ │ 404 Not Found       ✕   │ │
│ │   → ErrorResponse       │ │
│ ├─────────────────────────┤ │
│ │ + Add Response          │ │
│ └─────────────────────────┘ │
│                             │
│ ─────────────────────────── │
│ SECURITY                    │
│                             │
│ ┌─────────────────────────┐ │
│ │ 🔐 bearerAuth       ✕   │ │
│ │ + Add Security          │ │
│ └─────────────────────────┘ │
│                             │
│ ─────────────────────────── │
│ DOCUMENTATION               │
│                             │
│ Summary                     │
│ ┌─────────────────────────┐ │
│ │ Get user by ID          │ │
│ └─────────────────────────┘ │
│                             │
│ Description (Markdown)      │
│ ┌─────────────────────────┐ │
│ │ Returns a single user   │ │
│ │ object by their unique  │ │
│ │ identifier.             │ │
│ │                         │ │
│ │ ## Notes                │ │
│ │ - Requires auth         │ │
│ └─────────────────────────┘ │
│ 👁️ Preview                  │
│                             │
└─────────────────────────────┘
```

### 9.6 Schema Drag-and-Drop Interaction

The key interaction for binding schemas to requests and responses:

```
STEP 1: Locate schema in Library Panel
┌─────────────────────────┐
│ ▼ SCHEMAS (from lib)    │
│   ┌───────────────────┐ │
│   │ { } User      ⬚⬚  │ │ ← Drag handle appears on hover
│   └───────────────────┘ │

STEP 2: Drag schema onto canvas or directly into drop zone
                                    ┌─────────────────────────┐
         ╭─ ─ ─ ─ ─ ─ ─ ─ ╮        │ ●━━ POST ━━━━━━━━━━━━━ │
         ┆  { } User      ┆ ───▶   ├─────────────────────────┤
         ╰─ ─ ─ ─ ─ ─ ─ ─ ╯        │ ┌─ Request ───────────┐ │
               dragging             │ │ ┌─────────────────┐ │ │
                                    │ │ │  DROP SCHEMA    │ │ │ ← Drop zone highlights
                                    │ │ │  HERE           │ │ │   when schema hovers
                                    │ │ └─────────────────┘ │ │
                                    │ └─────────────────────┘ │

STEP 3: Schema reference created with edge connection
┌─────────────────────────┐         ┌─────────────────────────┐
│ { } User            ↗️  │         │ ●━━ POST ━━━━━━━━━━━━━ │
├─────────────────────────┤         ├─────────────────────────┤
│ id: string              │         │ ┌─ Request ───────────┐ │
│ email: string           │────────▶│ │ ○ User              │ │
│ name: string            │  edge   │ │   application/json  │ │
│ ...                     │         │ └─────────────────────┘ │
└─────────────────────────┘         └─────────────────────────┘
```

### 9.7 Edge Connection Types

Different edge styles represent different relationship types:

```
Schema Reference (solid line with arrow):
┌───────────┐                    ┌─────────────┐
│ { } User  │───────────────────▶│ 200 Response│
└───────────┘                    └─────────────┘

Request Body Binding (solid blue line):
┌───────────────┐                ┌─────────────┐
│ { } CreateReq │━━━━━━━━━━━━━━━▶│ POST /users │
└───────────────┘   (required)   └─────────────┘

Optional Reference (dashed line):
┌───────────┐                    ┌─────────────┐
│ { } Opts  │┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄▶│ Query Param │
└───────────┘   (optional)       └─────────────┘

Array Wrapper (line with brackets):
┌───────────┐                    ┌─────────────┐
│ { } User  │──────[  ]─────────▶│ 200 Response│
└───────────┘   (returns array)  └─────────────┘

Polymorphic (branching lines):
┌───────────┐
│ { } Cat   │──────┐
└───────────┘      │  oneOf      ┌─────────────┐
                   ├────────────▶│ 200 Response│
┌───────────┐      │             └─────────────┘
│ { } Dog   │──────┘
└───────────┘
```

### 9.8 Canvas Controls and Navigation

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│  ┌─────────┐                                              ┌─────────────────┐  │
│  │ ◀ ▶ ▲ ▼ │  Pan controls                               │   MINI-MAP      │  │
│  └─────────┘                                              │  ┌───────────┐  │  │
│                                                           │  │  ▪   ▪    │  │  │
│  ┌─────────────────────────────┐                          │  │    ▪      │  │  │
│  │  ➖  100%  ➕  │ Fit │ 1:1  │  Zoom controls           │  │  ▪    ▪   │  │  │
│  └─────────────────────────────┘                          │  └───────────┘  │  │
│                                                           └─────────────────┘  │
│  KEYBOARD SHORTCUTS:                                                           │
│  ─────────────────────────────────────────────────                             │
│  Space + Drag     Pan canvas                                                   │
│  Cmd/Ctrl + Scroll    Zoom in/out                                              │
│  Cmd/Ctrl + 0     Fit to view                                                  │
│  Cmd/Ctrl + 1     Zoom to 100%                                                 │
│  Delete/Backspace Delete selected                                              │
│  Cmd/Ctrl + D     Duplicate selected                                           │
│  Cmd/Ctrl + Z     Undo                                                         │
│  Cmd/Ctrl + Shift + Z Redo                                                     │
│  Cmd/Ctrl + G     Group selected                                               │
│  Cmd/Ctrl + A     Select all                                                   │
│  Escape           Deselect all                                                 │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 9.9 Context Menus

Right-click context menus provide quick actions:

```
On PathNode:                        On MethodNode:
┌─────────────────────────┐        ┌─────────────────────────┐
│ ✏️  Edit Path            │        │ ✏️  Edit Operation       │
│ 📋 Duplicate             │        │ 📋 Duplicate             │
├─────────────────────────┤        ├─────────────────────────┤
│ ➕ Add GET               │        │ ➕ Add Response          │
│ ➕ Add POST              │        │ ➕ Add Parameter         │
│ ➕ Add PUT               │        │ 🔐 Add Security          │
│ ➕ Add DELETE            │        ├─────────────────────────┤
├─────────────────────────┤        │ 🧪 Test in Swagger       │
│ 📦 Generate All CRUD    │        │ 📄 Copy as cURL          │
├─────────────────────────┤        ├─────────────────────────┤
│ ⚠️  Mark Deprecated      │        │ ⚠️  Mark Deprecated      │
│ 🗑️  Delete               │        │ 🗑️  Delete               │
└─────────────────────────┘        └─────────────────────────┘

On SchemaRefNode:                   On Canvas (empty area):
┌─────────────────────────┐        ┌─────────────────────────┐
│ ↗️  Open in Schema Editor│        │ ➕ Add Path              │
│ 📋 Duplicate Reference   │        │ 📋 Paste                 │
├─────────────────────────┤        ├─────────────────────────┤
│ [ ] Wrap as Array       │        │ ⊞  Toggle Grid           │
│ { } Use as Partial      │        │ 🔄 Auto-arrange          │
├─────────────────────────┤        │ 🎯 Fit to View           │
│ 🔗 Disconnect            │        ├─────────────────────────┤
│ 🗑️  Remove from Canvas   │        │ 📥 Import from OpenAPI   │
└─────────────────────────┘        │ 📤 Export Selection      │
                                   └─────────────────────────┘
```

### 9.10 Visual States

Nodes display different visual states for user feedback:

```
DEFAULT STATE:                      SELECTED STATE:
┌─────────────────────────┐        ┌─────────────────────────┐
│ ○ PATH                  │        │ ○ PATH              ⬚⬚ │ ← Resize handles
├─────────────────────────┤        ╔═════════════════════════╗ ← Blue border
│ /api/v1/users           │        ║ /api/v1/users           ║
└─────────────────────────┘        ╚═════════════════════════╝

HOVER STATE:                        ERROR STATE:
┌─────────────────────────┐        ┌─────────────────────────┐
│ ○ PATH              ═══ │ ← Drag │ ○ PATH              ⚠️  │ ← Error indicator
├─────────────────────────┤   grab ╔═════════════════════════╗ ← Red border
│ /api/v1/users           │ handle ║ /api/v1/users/{         ║ ← Invalid syntax
└─────────────────────────┘        ║ Missing closing brace   ║ ← Error tooltip
                                   ╚═════════════════════════╝

CONNECTING STATE:                   DEPRECATED STATE:
┌─────────────────────────┐        ┌─────────────────────────┐
│ { } User                │        │ ○ PATH              ⚠️  │
├─────────────────────────┤        ├─────────────────────────┤
│ id: string              │        │ /api/v1/legacy/users    │ ← Strikethrough
│ email: string       ◉───┼───▶    │ ░░░░░░░░░░░░░░░░░░░░░░░ │ ← Dimmed/grayed
└─────────────────────────┘        └─────────────────────────┘
        Active connection handle

DROP TARGET STATE:
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
  ┌─────────────────────┐   ← Dashed highlight
│ │   DROP SCHEMA HERE  │ │   appears when dragging
  │   { } ───────────▶  │     compatible node type
│ └─────────────────────┘ │
└ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
```

### 9.11 Tasks: Visual Design Implementation

#### Core Visual Tasks

- Implement three-panel Studio layout with collapsible side panels
- Create Library Panel with collapsible sections and drag handles
- Design PathNode component with header, body, and footer zones
- Design MethodNode components with HTTP verb color coding
- Design SchemaRefNode with property preview and modifier toggles
- Design ParameterNode chips for query, header, cookie, path types
- Design ResponseNode with status code color bands
- Implement Properties Panel with contextual forms per node type
- Create edge styles for different relationship types
- Implement canvas controls (zoom, pan, fit, minimap)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Advanced Visual Tasks

- Add node resize handles with minimum size constraints
- Implement multi-select visual feedback (selection rectangle)
- Create context menus for all node types
- Design visual states: default, hover, selected, error, deprecated
- Implement drop zone highlighting during drag operations
- Add keyboard shortcut overlay (triggered by `?` key)
- Create loading/saving state indicators
- Design validation error tooltips with inline positioning
- Implement dark mode color scheme for all node types
- Add animation for edge connections and node transitions

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

---

## 10. Implementation Phases

### Phase 1: Foundation (Weeks 1-4)

Establish the core infrastructure for path design with essential node types and basic canvas functionality.

- Create PathsDesigner component with React Flow integration
- Implement PathNode, MethodNode, and SchemaRefNode components
- Build database tables: `obj_paths`, `obj_path_operations`, `obj_path_parameters`
- Create node library panel with drag-and-drop functionality
- Implement basic path variable detection and configuration
- Add canvas state persistence (positions, viewport)
- Integrate with existing project version system

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### Phase 2: Request/Response (Weeks 5-8)

Complete the request/response design capabilities with full parameter and content type support.

- Implement RequestBodyNode and ResponseNode components
- Build ParameterNode for query, header, cookie, and path parameters
- Create content type management with schema binding
- Add response status code library with presets
- Implement configuration panels for all node types
- Add undo/redo functionality with history stack
- Build OpenAPI export with paths integration

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### Phase 3: Testing & Validation (Weeks 9-12)

Integrate testing capabilities and specification validation for developer productivity.

- Embed Swagger UI panel with real-time spec sync
- Implement OpenAPI 3.1 validation with inline error markers
- Add Try It Out functionality with environment support
- Create auto-generation from schemas (CRUD endpoints)
- Build security scheme library and assignment
- Add request/response logging with history
- Implement pattern libraries for common API patterns

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

---

# Completed

## 🗄️ Data Model & Persistence

### 7. Database Schema ✅ FINISHED

### 9.1 Studio Layout Structure ✅ FINISHED

### 9.2 Library Panel Structure ✅ FINISHED

*This roadmap positions Objectified UI as a comprehensive visual API design platform,
bridging the gap between schema definition and full OpenAPI specification authoring while
maintaining the visual, developer-centric design philosophy established in the schema designer.*