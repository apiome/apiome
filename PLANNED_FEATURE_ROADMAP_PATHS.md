# Objectified - API Paths Designer: Feature Roadmap

> **Enterprise-grade Visual API Design Platform**  
> React Flow-based path definition, operation design, and OpenAPI 3.1 specification management for software engineers
> 
> **Last Updated**: December 30, 2025  
> **Version**: 2.0 - Visual OpenAPI Path Definition, Testing & Enterprise Integration  
> **Target Audience**: Software Engineers, API Architects, Platform Engineers

---

## Core Architecture & Implementation

### 1. React Flow Canvas Foundation

The Paths Designer is built on React Flow, providing an infinite canvas workspace optimized for complex API
specifications. Engineers can design APIs with hundreds of endpoints while maintaining visual clarity through
zoom, pan, and mini-map navigation.

#### Canvas Features ✅ PARTIALLY IMPLEMENTED

- ✅ **Dedicated Paths Tab**: Third Studio tab with independent React Flow instance
- ✅ **Infinite Canvas**: Zoom from 10% to 500% with smooth panning
- ✅ **Mini-Map Navigation**: Bird's-eye view for large API specs (50+ paths)
- **Node Library Panel**: Draggable node types organized by category
- **Grid Snapping**: Optional alignment grid with 10/20/50px spacing
- **Selection Tools**: Multi-select with drag, `Shift+Click`, rubber band selection

| Ticket | Feature                                   |
|--------|-------------------------------------------|

---

## Visual Node System

### 2. Node Types & Visual Design

Each OpenAPI concept is represented as a distinct node type with color-coded visual identity, making API 
structure immediately recognizable.

#### 2.1 Path Nodes 📋 PARTIALLY IMPLEMENTED

**Visual Design**: Rounded rectangle with URL path as header, gray-blue gradient background

**Configurable Properties**: ✅ PARTIALLY IMPLEMENTED
- ✅ Path pattern with inline variable extraction: `/users/{userId}/posts/{postId}`
- ✅ Summary and description (markdown support with Monaco Editor)
- 📋 Server overrides for multi-environment routing
- ✅ Deprecated flag with visual strikethrough and warning badge
- ✅ Path tags for logical grouping (multi-select from project-defined tags)
- 📋 Common parameters inherited by all operations
- ✅ External documentation links

**Features**: 📋 PLANNED
- ✅ Click on `{variable}` to open inline schema editor
- ✅ Drag schema property onto variable for type binding
- 📋 Visual validation: invalid paths show red border
- 📋 Path template preview with sample values

| Ticket | Feature                                                                  |
|--------|--------------------------------------------------------------------------|
| #359   | Add invalid paths with a red border                                      |
| #360   | Add path template preview with sample values                             |

#### 2.2 Method Nodes (HTTP Operations) 📋 PLANNED

**Visual Design**: Color-coded badges attached to path nodes

| Method   | Color  | Common Use Cases              |
|----------|--------|-------------------------------|
| GET      | Green  | Read, list, search operations |
| POST     | Blue   | Create, submit, trigger       |
| PUT      | Orange | Full resource replacement     |
| PATCH    | Purple | Partial updates               |
| DELETE   | Red    | Resource deletion             |
| HEAD     | Gray   | Metadata retrieval            |
| OPTIONS  | Gray   | CORS preflight                |

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
- ✅ Schema type (string, number, boolean, array, object)
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

| Ticket | Feature                                                        |
|--------|----------------------------------------------------------------|
| #386   | Content type map (application/json, multipart/form-data, etc.) |
| #387   | Schema binding per content type                                |
| #388   | Add required flag to request body                              |
| #389   | Add description to request body                                |
| #390   | Add examples to request body node                              |
| #391   | Add encoding options for multipart                             |

#### 2.6 Response Nodes 📋 PLANNED

**Visual Design**: Output port icon, color-coded by status code family

| Status Range | Color  | Common Codes                        |
|--------------|--------|-------------------------------------|
| 2XX Success  | Green  | 200 OK, 201 Created, 204 No Content |
| 3XX Redirect | Blue   | 301, 302, 304 Not Modified          |
| 4XX Client   | Yellow | 400, 401, 403, 404, 422             |
| 5XX Server   | Red    | 500, 502, 503, 504                  |

**Configurable Properties**:
- ✅ Status code (100-599)
- ✅ Description (auto-populated from status code, configurable)
- 📋 Response headers (name, schema, description)
- 📋 Content type map with schema bindings
- 📋 Links (HATEOAS navigation)
- 📋 Examples per content type

| Ticket | Feature                                                |
|--------|--------------------------------------------------------|
| #394   | Add response headers (name, schema, description)       |
| #395   | Add content type map with schema bindings              |
| #396   | Add links (HATEOAS navigation)                         |
| #397   | Add content-type examples to response node             |

**Advanced Features**:
- 📋 Response range patterns: 2XX, 4XX, 5XX wildcards
- 📋 Default response for catch-all error handling
- 📋 Link objects for response-driven navigation
- 📋 Header templates (pagination, rate limiting, CORS)

| Ticket | Feature                                                |
|--------|--------------------------------------------------------|
| #398   | Add response range patterns to response nodes          |
| #399   | Add default response to HTTP Operation                 |
| #400   | Add link objects for response-driven navigation        |
| #401   | Add header templates (pagination, rate limiting, CORS) |

#### 3.4 OpenAPI Export & Import 📋 PLANNED

**Import Support**:
- OpenAPI 3.0/3.1 JSON/YAML
- Swagger 2.0 JSON/YAML
- Postman Collection v2.1
- Insomnia Collection v4
- HAR (HTTP Archive) files
- cURL commands (converts to operation)

| Ticket | Feature                                             |
|--------|-----------------------------------------------------|
| #425   | Improve OpenAPI Specification import handling       |
| #566   | Add OpenAPI importing to capture and generate paths |

### 3.5 OpenAPI Specification Output 📋 PLANNED

**Full Spec Generation** ✅ PARTIALLY IMPLEMENTED
- **Specification Components**:
    - ✅ `info` (title, version, description, contact, license, termsOfService)
    - `servers` (multiple environments with variables)
    - ✅ `paths` (all operations with full configuration)
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
- ✅ **API Key**: Header, query, or cookie-based keys (#410)
- ✅ **HTTP**: Basic, Bearer, or custom HTTP auth
- ✅ **OAuth 2.0**: Authorization Code, Implicit, Client Credentials, Password flows
- 📋 **OpenID Connect**: Discovery URL with scopes
- 📋 **Mutual TLS**: Certificate-based authentication
- 📋 **Custom security schemes**

| Ticket | Feature Description                 |
|--------|-------------------------------------|
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

## 9. Visual Design Specification

This section describes the visual appearance and layout of the Paths Designer within the Studio interface, including the React Flow canvas structure, node designs, and interaction patterns.

### 9.3 Node Visual Designs

Each node type has a distinct visual appearance to enable quick identification on the canvas.

#### PathNode (Primary Container)

The PathNode serves as the top-level container for an API endpoint:

```
┌─────────────────────────────────────────────────────────────┐
│ ○ PATH                                           ⋮ ≡        │  ← Header with drag handle
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
│  Tags: orders, users          │  ⚠️ deprecated              │  ← Footer metadata
└─────────────────────────────────────────────────────────────┘
     │
     ○ ← Output handle for edge connections
```

#### 9.3.2 SchemaRefNode (Draggable from Library)

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

### 9.4 Complete Canvas Example

Here's how a complete API endpoint design might appear on the canvas:

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    REACT FLOW CANVAS                                    │
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐ │
│                                                                                         │
│  │ ┌───────────────────────────────────────────────────────────────────────────────┐ │  │
│    │ ○ PATH                                                                    ⋮ ≡ │    │
│  │ ├───────────────────────────────────────────────────────────────────────────────┤ │  │
│    │                                                                               │    │
│  │ │   /api/v1/users/{userId}                                                      │ │  │
│    │                                                                               │    │
│  │ │   ┌─────────────────────────────────────────────────────────────────────────┐ │ │  │
│    │   │                                                                         │ │    │
│  │ │   │  ┌────────────────────────┐    ┌────────────────────────┐               │ │ │  │
│    │   │  │ ●━━ GET ━━━━━━━━━━━━━  │    │ ●━━ PUT ━━━━━━━━━━━━━━ │               │ │    │
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
         ╭─ ─ ─ ─ ─ ─ ─ ─ ╮         │ ●━━ POST ━━━━━━━━━━━━━  │
         ┆  { } User      ┆ ───▶    ├─────────────────────────┤
         ╰─ ─ ─ ─ ─ ─ ─ ─ ╯         │ ┌─ Request ───────────┐ │
               dragging             │ │ ┌─────────────────┐ │ │
                                    │ │ │  DROP SCHEMA    │ │ │ ← Drop zone highlights
                                    │ │ │  HERE           │ │ │   when schema hovers
                                    │ │ └─────────────────┘ │ │
                                    │ └─────────────────────┘ │

STEP 3: Schema reference created with edge connection
┌─────────────────────────┐         ┌─────────────────────────┐
│ { } User            ↗️  │         │ ●━━ POST ━━━━━━━━━━━━━  │
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
│ { } Opts  │┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄▶ │ Query Param │
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
│  │ ◀ ▶ ▲ ▼ │  Pan controls                                │   MINI-MAP      │  │
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
│ ✏️  Edit Path           │        │ ✏️  Edit Operation      │
│ 📋 Duplicate            │        │ 📋 Duplicate            │
├─────────────────────────┤        ├─────────────────────────┤
│ ➕ Add GET              │        │ ➕ Add Response         │
│ ➕ Add POST             │        │ ➕ Add Parameter        │
│ ➕ Add PUT              │        │ 🔐 Add Security         │
│ ➕ Add DELETE           │        ├─────────────────────────┤
├─────────────────────────┤        │ 🧪 Test in Swagger      │
│ 📦 Generate All CRUD    │        │ 📄 Copy as cURL         │
├─────────────────────────┤        ├─────────────────────────┤
│ ⚠️  Mark Deprecated     │        │ ⚠️  Mark Deprecated     │
│ 🗑️  Delete              │        │ 🗑️  Delete              │
└─────────────────────────┘        └─────────────────────────┘

On SchemaRefNode:                   On Canvas (empty area):
┌─────────────────────────┐        ┌─────────────────────────┐
│ ↗️  Open in Schema Editor│       │ ➕ Add Path             │
│ 📋 Duplicate Reference   │       │ 📋 Paste                │
├─────────────────────────┤        ├─────────────────────────┤
│ [ ] Wrap as Array       │        │ ⊞  Toggle Grid          │
│ { } Use as Partial      │        │ 🔄 Auto-arrange         │
├─────────────────────────┤        │ 🎯 Fit to View          │
│ 🔗 Disconnect           │        ├─────────────────────────┤
│ 🗑️  Remove from Canvas  │        │ 📥 Import from OpenAPI  │
└─────────────────────────┘        │ 📤 Export Selection     │
                                   └─────────────────────────┘
```

### 9.10 Visual States

Nodes display different visual states for user feedback:

```
DEFAULT STATE:                      SELECTED STATE:
┌─────────────────────────┐        ┌─────────────────────────┐
│ ○ PATH                  │        │ ○ PATH              ⬚⬚  │ ← Resize handles
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

---

# Completed

## 🗄️ Data Model & Persistence

### 7. Database Schema ✅ FINISHED

### 9.1 Studio Layout Structure ✅ FINISHED

### 9.2 Library Panel Structure ✅ FINISHED

**Configurable Properties**:
- ✅ Operation ID (auto-generated from method + path)
- ✅ Tags for API grouping
- ✅ Summary and description
- ✅ Request body schema binding
- ✅ Response definitions (status codes + schemas)
- ✅ Parameters (query, header, cookie)
- ✅ Security requirements
- ✅ Deprecated flag
- ✅ Private flag (unexposed endpoints)
- ✅ External docs
- ✅ Custom `x-*` extensions

*This roadmap positions Objectified UI as a comprehensive visual API design platform,
bridging the gap between schema definition and full OpenAPI specification authoring while
maintaining the visual, developer-centric design philosophy established in the schema designer.*
