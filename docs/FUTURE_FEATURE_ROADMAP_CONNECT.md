# Objectified: Connect - Feature Roadmap

> Universal integration hub connecting Objectified schemas to external systems, enabling real-time data synchronization, schema propagation, and event-driven architectures across the enterprise technology landscape. Connect turns Objectified into the central nervous system for data flowing between SaaS platforms, databases, messaging systems, and internal services.
>
> **Revenue Model**: Per-connector pricing (free tier: 3 connectors), usage-based data volume fees, enterprise unlimited packages
>
> **Tech Stack**: NextJS App Router, Radix UI, PostgreSQL, Redis (job queues), Kafka/NATS for event streaming, OpenAPI 3.1, Docker-based connector runtime

---

## MVP Definition

- Connector plugin architecture with lifecycle management (install, configure, enable, disable)
- Connector marketplace UI for browsing, installing, and configuring connectors
- Visual schema field mapping interface with type coercion rules
- At least 3 built-in connectors (PostgreSQL, REST/Webhook, CSV/JSON file)
- Bi-directional sync engine with configurable sync frequency
- Sync execution log with per-record success/failure tracking
- Connection health monitoring with status indicators and alerts
- REST API for all connector and sync operations (OpenAPI 3.1 documented)

---

## Epic 1: Connector Framework & Registry

### Summary Table

| #   | Title                              | Description                                                                   | Labels                                   | Parallel |
|-----|------------------------------------|-------------------------------------------------------------------------------|------------------------------------------|----------|
| 1.1 (#932) | Connector Plugin Architecture      | Define connector interface, SDK, lifecycle hooks, and sandboxed runtime        | `enhancement`, `mvp`, `connect`, `rest`  | Yes      |
| 1.2 (#933) | Connector Registry & Metadata Store| Central registry for connector definitions, versions, and configuration schemas| `enhancement`, `mvp`, `connect`, `rest`  | Yes      |
| 1.3 (#934) | Connector Marketplace UI           | Browsable marketplace for discovering, installing, and managing connectors     | `enhancement`, `mvp`, `connect`          | No       |
| 1.4 (#935) | Connection Configuration Wizard    | Step-by-step wizard for authenticating and configuring connector instances     | `enhancement`, `mvp`, `connect`          | No       |
| 1.5 (#936) | Connector Health & Monitoring      | Real-time health checks, status indicators, and alerting for active connections| `enhancement`, `mvp`, `connect`, `rest`  | Yes      |
| 1.6 (#937) | Community Connector SDK            | Public SDK and documentation for third-party connector development             | `enhancement`, `connect`                 | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#932) — Connector Plugin Architecture

The connector framework defines a standardized interface that all connectors must implement, enabling a pluggable architecture where new integrations can be added without modifying the core Connect platform. Each connector is a self-contained module that implements the `ConnectorInterface` with methods for: `authenticate()`, `testConnection()`, `discover()` (introspect remote schema), `read()` (pull data), `write()` (push data), and `subscribe()` (listen for changes).

Connectors run in isolated Docker containers with resource limits (CPU, memory, network) to prevent a misbehaving connector from affecting the platform. The connector runtime manages container lifecycle: pulling connector images, starting containers on demand, routing requests, and recycling idle containers. Communication between the Connect platform and connector containers uses gRPC for low-latency bidirectional streaming.

The connector SDK provides base classes, utility functions (pagination helpers, retry logic, rate limit handling), and a testing harness. Connector authors implement the interface methods and provide a `connector.manifest.json` describing capabilities, required configuration fields, supported operations (read-only, write-only, bi-directional), and authentication methods (OAuth2, API key, basic auth, custom).

```
┌──────────────────────────────────────────────────────────┐
│                   Connect Platform                        │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Sync Engine  │  │ Mapper Engine│  │ Event Router │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                  │            │
│  ┌──────▼─────────────────▼──────────────────▼───────┐   │
│  │              Connector Runtime (gRPC)              │   │
│  └──┬──────────┬──────────┬──────────┬───────────────┘   │
│     │          │          │          │                    │
│  ┌──▼───┐  ┌──▼───┐  ┌──▼───┐  ┌──▼───┐                │
│  │ 🐳   │  │ 🐳   │  │ 🐳   │  │ 🐳   │                │
│  │Salesf.│  │Postgr│  │Stripe│  │Custom│                │
│  └──────┘  └──────┘  └──────┘  └──────┘                │
│  Sandboxed Connector Containers                          │
└──────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- `ConnectorInterface` defined with methods: authenticate, testConnection, discover, read, write, subscribe
- `connector.manifest.json` schema defined with capabilities, config fields, auth methods, and supported operations
- Connector containers run in Docker with configurable resource limits (CPU, memory, network timeout)
- gRPC service definition for connector runtime communication with streaming support
- Connector SDK base classes handle common patterns: pagination, retry with backoff, rate limit detection
- Integration test harness validates a connector implementation against the interface contract

**Tech Stack:** Docker for connector isolation, gRPC for runtime communication, TypeScript/Node.js connector SDK, `connector.manifest.json` JSON Schema

Part of Epic: Connector Framework & Registry

---

#### 1.2 (#933) — Connector Registry & Metadata Store

The connector registry is the central catalog of all available connectors, both built-in and community-contributed. Each registry entry contains the connector manifest, version history, Docker image reference, documentation URL, author information, and usage statistics (install count, active connections). The registry supports semantic versioning for connectors, enabling controlled upgrades.

The registry API supports CRUD operations on connector entries, version publishing (with validation that the connector image exists and passes interface compliance tests), and querying with filters (category, capability, popularity). When a connector is installed by a tenant, an `installed_connector` record links the tenant to a specific connector version, tracking the installation date and configuration state.

Version management follows semver: patch versions are auto-upgraded, minor versions prompt the user, and major versions require explicit migration. A compatibility matrix tracks which connector versions work with which Connect platform versions. Deprecation notices are displayed for connectors approaching end-of-life.

**Acceptance Criteria:**
- Registry API: CRUD on connector entries at `/api/v1/connect/registry/connectors` with pagination and filtering
- Version publishing endpoint validates connector image accessibility and runs interface compliance tests
- Semantic versioning enforced with auto-upgrade policy: patch (auto), minor (prompt), major (manual)
- `installed_connector` table tracks per-tenant installations with version pinning
- Search API supports filtering by category, capabilities (read/write/subscribe), and sorting by popularity
- Deprecation flag on connector versions with visual indicator in UI and upgrade prompt

**Tech Stack:** NextJS API routes, PostgreSQL for registry metadata, Docker registry integration for image validation, OpenAPI 3.1 spec

Part of Epic: Connector Framework & Registry

---

#### 1.3 (#934) — Connector Marketplace UI

The marketplace is the primary discovery interface for connectors, designed as a familiar app-store-like experience. The main page displays featured connectors, recently added connectors, and category-based browsing (CRM, Databases, Cloud Providers, Payment, Messaging, DevOps). Each connector tile shows the logo, name, author, install count, rating, and supported operations (read/write/subscribe icons).

The connector detail page provides comprehensive information: description, screenshots/diagrams, supported features, configuration requirements, pricing tier, version history with changelogs, and user reviews. An "Install" button initiates the installation flow, which transitions to the configuration wizard (issue 1.4). For already-installed connectors, the detail page shows the active version with an "Upgrade" button if a newer version is available.

A management view lists all installed connectors for the current tenant with status indicators (connected, disconnected, error), last sync time, data volume transferred, and quick actions (configure, disable, uninstall). Uninstalling a connector requires confirmation and warns about active sync jobs that will be disrupted.

**Acceptance Criteria:**
- Marketplace grid layout with connector tiles showing logo, name, install count, and capability icons
- Category navigation using Radix UI Tabs (CRM, Databases, Cloud, Payment, Messaging, DevOps, All)
- Connector detail page with description, screenshots, version history, and Install/Upgrade button
- Search with full-text search across connector names and descriptions with typeahead
- Installed connectors management view with status, last sync, and quick actions (configure/disable/uninstall)
- Uninstall confirmation via Radix UI AlertDialog with warning about active sync disruption

**Tech Stack:** NextJS page (`app/(platform)/connect/marketplace/page.tsx`), Radix UI Tabs for categories, Radix UI AlertDialog for uninstall, Radix UI Dialog for install flow

Part of Epic: Connector Framework & Registry

---

#### 1.4 (#935) — Connection Configuration Wizard

Configuring a connector instance requires collecting authentication credentials, connection parameters, and operational settings. The wizard provides a multi-step guided flow driven by the connector's manifest: Step 1 (Authentication) collects credentials based on the connector's auth type—OAuth2 redirects to the external service for authorization, API key presents a secure input field, basic auth collects username/password. Step 2 (Connection Settings) presents connector-specific fields (e.g., database host/port/name for PostgreSQL, API endpoint URL for REST). Step 3 (Test Connection) runs the connector's `testConnection()` method and displays success or detailed error messages. Step 4 (Review & Save) summarizes the configuration for confirmation.

Credentials are encrypted at rest using AES-256 with per-tenant encryption keys. The configuration is stored as a `connection` record linking the tenant, connector version, encrypted credentials, and connection-specific settings. Connections can be edited later to update credentials or settings without recreating the entire configuration.

OAuth2 flows handle the full redirect cycle: generating the authorization URL, receiving the callback with the auth code, exchanging for tokens, and storing refresh tokens for automatic renewal. Token refresh runs proactively before expiry to prevent sync interruptions.

**Acceptance Criteria:**
- Multi-step wizard with progress indicator using Radix UI form components
- OAuth2 flow handles authorization redirect, callback, token exchange, and refresh token storage
- API key and basic auth credentials encrypted at rest using AES-256 before storage
- Test connection step executes connector's `testConnection()` and displays success/error with details
- Configuration saved as `connection` record; editable without full reconfiguration
- Wizard steps dynamically generated from connector manifest `config_fields` definition

**Tech Stack:** NextJS pages for wizard steps, Radix UI Dialog for the wizard container, encrypted credential storage in PostgreSQL, OAuth2 callback handler at `/api/v1/connect/oauth/callback`

Part of Epic: Connector Framework & Registry

---

#### 1.5 (#936) — Connector Health & Monitoring

Active connections require continuous health monitoring to detect failures before they impact data pipelines. The monitoring system runs periodic health checks against each active connection using the connector's `testConnection()` method at configurable intervals (default: every 5 minutes). Health status is tracked as a state machine: healthy → degraded (intermittent failures) → unhealthy (consecutive failures) → disconnected (manual or auto-disable after threshold).

The monitoring dashboard displays all connections in a summary view with traffic-light status indicators (green/yellow/red/gray). Each connection shows: current status, last successful check time, uptime percentage (7-day rolling), error count, and average response latency. Clicking a connection opens a detail panel with the health check history chart, recent error messages, and configuration details.

Alerting integrates with the platform's notification system: email and in-app notifications are sent when a connection transitions from healthy to degraded or unhealthy. Alert rules are configurable per connection: sensitivity (number of failures before alert), notification recipients, and quiet hours. Auto-disable activates after a configurable number of consecutive failures (default: 10) to prevent resource waste on dead connections.

**Acceptance Criteria:**
- Health check scheduler runs `testConnection()` on active connections at configurable intervals (default 5 min)
- Status state machine: healthy → degraded (2+ intermittent failures) → unhealthy (5+ consecutive) → disconnected
- Dashboard shows all connections with traffic-light status, uptime %, last check time, and error count
- Alert notifications sent on status transitions (healthy→degraded, degraded→unhealthy) via email and in-app
- Auto-disable after configurable consecutive failure threshold (default: 10) with auto-re-enable on manual test success
- Health check history API: `GET /api/v1/connect/connections/{id}/health` returns 7-day history with latency data

**Tech Stack:** Background scheduler for health checks, PostgreSQL for health history, Radix UI Table for dashboard, notification service integration, REST API for health data

Part of Epic: Connector Framework & Registry

---

#### 1.6 (#937) — Community Connector SDK

To accelerate the connector ecosystem, a public SDK enables third-party developers to build, test, and publish connectors for the Connect marketplace. The SDK ships as an npm package (`@objectified/connector-sdk`) providing TypeScript base classes, a CLI for scaffolding new connector projects, and a local testing harness that simulates the Connect runtime.

The CLI provides commands: `connector init` (scaffolds project structure with manifest, Dockerfile, and implementation stubs), `connector test` (runs the testing harness against the implementation), `connector validate` (checks manifest compliance and Docker image build), and `connector publish` (submits to the Connect registry pending review). The testing harness simulates all runtime interactions without requiring a full Connect deployment.

Documentation includes a "Build Your First Connector" tutorial walking through creating a simple REST API connector, the full interface reference with JSDoc comments, best practices for error handling and rate limiting, and example connectors for common patterns (REST API, database, message queue). A connector review process ensures published connectors meet quality and security standards.

**Acceptance Criteria:**
- npm package `@objectified/connector-sdk` with TypeScript base classes and utility functions
- CLI commands: `init`, `test`, `validate`, `publish` with documented usage
- `connector init` scaffolds: `src/index.ts`, `connector.manifest.json`, `Dockerfile`, `tests/`, and `README.md`
- Testing harness simulates all ConnectorInterface methods with configurable mock data
- Documentation site with tutorial, interface reference, best practices, and example connectors
- Publish flow includes automated validation (manifest, Docker build, interface tests) before registry submission

**Tech Stack:** TypeScript npm package, Commander.js CLI, Docker for local testing, documentation site

Part of Epic: Connector Framework & Registry

---

## Epic 2: Schema Mapping & Transformation

### Summary Table

| #   | Title                              | Description                                                                    | Labels                                   | Parallel |
|-----|------------------------------------|--------------------------------------------------------------------------------|------------------------------------------|----------|
| 2.1 (#939) | Schema Discovery & Introspection   | Auto-discover remote system schemas and present as mappable structures          | `enhancement`, `mvp`, `connect`, `rest`  | Yes      |
| 2.2 (#940) | Visual Field Mapping Interface     | Drag-and-drop UI for mapping source fields to target Objectified schema fields | `enhancement`, `mvp`, `connect`          | No       |
| 2.3 (#941) | Transformation Rules Engine        | Configurable transformation functions for type coercion, formatting, and logic | `enhancement`, `mvp`, `connect`, `rest`  | Yes      |
| 2.4 (#942) | Mapping Templates & Presets        | Reusable mapping configurations for common source/target combinations          | `enhancement`, `connect`, `rest`         | Yes      |
| 2.5 (#943) | Mapping Validation & Preview       | Validate mappings against sample data with preview of transformation results   | `enhancement`, `connect`                 | No       |

### Detailed Issue Descriptions

#### 2.1 (#939) — Schema Discovery & Introspection

When a connection is established to an external system, Connect needs to understand the remote data structure to enable mapping. Schema discovery calls the connector's `discover()` method, which returns a normalized representation of the remote system's schema: tables/objects, their fields, field types, relationships, and constraints. For databases, this means introspecting table schemas. For REST APIs, this means parsing OpenAPI specs or sampling response shapes. For SaaS platforms, this uses the platform's metadata APIs.

The discovered schema is cached locally with a refresh mechanism. When a user initiates mapping, the discovery results are presented alongside the Objectified schema in a side-by-side view. Users can trigger a re-discovery to pick up remote schema changes. The system tracks schema drift: if a previously mapped remote field changes type or is removed, a warning is surfaced on the mapping configuration.

Discovery results are stored in a normalized `discovered_schema` table with the connection ID, discovery timestamp, and the schema structure as JSON. Historical discovery snapshots enable diffing to detect changes over time.

**Acceptance Criteria:**
- Discovery endpoint `POST /api/v1/connect/connections/{id}/discover` triggers connector's `discover()` and caches results
- Normalized schema representation includes: objects/tables, fields, field types, nullable flags, relationships
- Discovery results cached with configurable TTL (default: 24 hours) and manual refresh button
- Schema drift detection compares current discovery against last mapping snapshot and flags changes
- Discovery supports pagination for systems with large schemas (1000+ tables)
- Error handling for partial discovery failures (some tables accessible, others permission-denied)

**Tech Stack:** NextJS API routes, connector `discover()` gRPC call, PostgreSQL for discovered schema cache, JSON Schema for normalized representation

Part of Epic: Schema Mapping & Transformation

---

#### 2.2 (#940) — Visual Field Mapping Interface

The field mapping UI is the core user experience of Connect, enabling users to visually define how data flows between external systems and Objectified schemas. The interface uses a two-panel layout: the left panel shows the source schema (discovered from the external system) as an expandable tree, and the right panel shows the target Objectified schema. Users create mappings by drawing lines between source and target fields via click-to-connect or drag-and-drop.

Each mapping line can have an optional transformation applied (configured via the transformation rules engine in issue 2.3). The mapping canvas shows connection lines between mapped fields with visual indicators for: direct mapping (solid line), transformed mapping (dashed line with transform icon), and unmapped required fields (red highlight on the target side). An auto-map feature suggests mappings based on field name similarity and type compatibility.

The mapping configuration is saved as a `schema_mapping` record containing an array of field mapping rules, each specifying source path, target path, transformation (if any), and whether the mapping is required. Mappings can be exported as JSON for version control and imported for reuse.

```
┌────────────────────────────────────────────────────────────┐
│                  Schema Mapping Editor                      │
├──────────────────────┬─────────────────────────────────────┤
│  Source: Salesforce   │  Target: Objectified Schema         │
│                      │                                     │
│  ▼ Contact           │  ▼ Customer                         │
│    FirstName ────────┼────▶ first_name                     │
│    LastName  ────────┼────▶ last_name                      │
│    Email     ────────┼────▶ email                          │
│    Phone     ──[T]───┼────▶ phone_number                   │
│    CreatedDate ──────┼────▶ created_at                     │
│    MailAddr   ──[T]──┼────▶ address (object)               │
│    ⚠ Title           │  ⚠ loyalty_tier  (unmapped req.)   │
│                      │                                     │
├──────────────────────┴─────────────────────────────────────┤
│  [Auto-Map]  [Clear All]  [Save]  [Test with Sample Data]  │
│  Mapped: 6/8 source · 6/7 target · 2 transforms           │
└────────────────────────────────────────────────────────────┘
                   [T] = transformation applied
```

**Acceptance Criteria:**
- Two-panel layout with source schema tree (left) and target Objectified schema tree (right)
- Click-to-connect mapping: click source field, then click target field to create mapping line
- Auto-map button suggests mappings using field name similarity (Levenshtein distance ≤ 2) and type compatibility
- Visual indicators: solid lines (direct), dashed lines with icon (transformed), red highlight (unmapped required)
- Mapping saved as JSON array of `{ source_path, target_path, transform_id, required }` rules
- Export/import mapping configuration as JSON file for version control

**Tech Stack:** NextJS page (`app/(platform)/connect/mappings/[mappingId]/edit/page.tsx`), SVG/Canvas for connection lines, Radix UI Dialog for transform configuration, tree component for schema display

Part of Epic: Schema Mapping & Transformation

---

#### 2.3 (#941) — Transformation Rules Engine

Not all field mappings are simple one-to-one copies. The transformation engine provides a library of configurable functions that convert data between source and target formats. Transformations are categorized: type coercion (string→number, date format conversion, boolean parsing), string operations (trim, uppercase, lowercase, regex replace, concatenate, split), mathematical operations (unit conversion, rounding, arithmetic), conditional logic (if/else, default values, null coalescing), and structural operations (flatten nested objects, combine fields, extract from arrays).

Each transformation is defined as a composable rule that can be chained: for example, a "Phone Number" transform might chain `trim()` → `regex_replace(strip non-digits)` → `format(+1-XXX-XXX-XXXX)`. The rule builder UI presents a visual pipeline where users add, remove, and reorder transform steps. A live preview shows the input value, each transformation step's output, and the final result.

Custom transformations can be defined using a safe expression language (a restricted JavaScript subset) for advanced use cases. Custom transforms are tenant-scoped and saved in a library for reuse. The engine validates that the transformation output type is compatible with the target field's schema type.

**Acceptance Criteria:**
- Built-in transformation categories: type coercion, string operations, math, conditional, structural
- Transform pipeline builder allowing chaining multiple transforms with configurable parameters
- Live preview showing input → step 1 output → step 2 output → final output for sample data
- Custom transform support using restricted expression language with sandboxed execution
- Transform library: save, name, and reuse transforms across mappings within tenant scope
- Output type validation: warn when transform output type doesn't match target field schema type

**Tech Stack:** NextJS page for transform builder, sandboxed expression evaluator (no eval, no access to globals), Radix UI DropdownMenu for transform type selection, Radix UI Dialog for transform configuration

Part of Epic: Schema Mapping & Transformation

---

#### 2.4 (#942) — Mapping Templates & Presets

Common integration patterns (e.g., Salesforce Contact → CRM Customer, Stripe Charge → Payment Record) benefit from pre-built mapping templates that users can apply as a starting point and customize. Templates capture the complete mapping configuration: field mappings, transformations, and sync settings for a specific source connector type and target schema pattern.

The template system supports three tiers: platform templates (maintained by Objectified, available to all tenants), community templates (contributed by users, reviewed before publishing), and tenant templates (private, created by and shared within a tenant). Templates are versioned and include metadata: description, applicable connector types, target schema requirements, and author.

When applying a template, the system matches the template's expected source schema against the actual discovered source schema, maps matching fields automatically, and highlights any template fields that don't match the actual schema for manual resolution. This handles variations between different Salesforce orgs that have custom fields, for example.

**Acceptance Criteria:**
- Template CRUD API at `/api/v1/connect/mappings/templates` with tier scope (platform/community/tenant)
- Template application endpoint that matches template against actual discovered schema and returns resolution report
- Template browser UI with filtering by connector type, target schema pattern, and tier
- Smart application: auto-match template fields to actual schema, highlight mismatches for manual resolution
- Template versioning with changelog; applying a template pins to a specific version
- Community template submission with review workflow (pending → approved → published)

**Tech Stack:** NextJS page (`app/(platform)/connect/mappings/templates/page.tsx`), Radix UI Dialog for template application, REST API with OpenAPI 3.1

Part of Epic: Schema Mapping & Transformation

---

#### 2.5 (#943) — Mapping Validation & Preview

Before activating a schema mapping for live data sync, users need confidence that the mapping produces correct results. The validation and preview system runs the complete mapping pipeline against sample data and presents a detailed preview of the transformation results, highlighting any validation errors, type mismatches, or data loss.

The preview workflow: (1) User clicks "Test with Sample Data" on the mapping editor, (2) the system fetches a configurable number of sample records from the source via the connector's `read()` method (default: 10 records), (3) applies the mapping and transformation pipeline to each record, (4) validates each transformed record against the target Objectified schema, and (5) displays results in a table showing source record, transformed result, validation status (pass/fail), and any error details.

Validation checks include: required target fields mapped, data types compatible after transformation, string length constraints met, enum values valid, and nested object structures complete. A summary banner shows overall success rate and categorized error counts. Users can fix mapping issues in the editor and re-run the preview without re-fetching source data (cached for the session).

**Acceptance Criteria:**
- "Test with Sample Data" fetches configurable number of source records (default 10, max 100)
- Full mapping and transformation pipeline applied to each sample record
- Validation against target Objectified JSON Schema with field-level error reporting
- Results table showing: source record, transformed output, pass/fail status, error details per field
- Summary banner with success rate percentage and categorized error counts (type mismatch, missing required, constraint violation)
- Cached source data for session: re-run preview after mapping edits without re-fetching

**Tech Stack:** NextJS API route for preview execution, Radix UI Table for results display, JSON Schema validation, connector `read()` for sample data

Part of Epic: Schema Mapping & Transformation

---

## Epic 3: Real-Time Data Sync & CDC

### Summary Table

| #   | Title                              | Description                                                                   | Labels                                   | Parallel |
|-----|------------------------------------|-------------------------------------------------------------------------------|------------------------------------------|----------|
| 3.1 (#945) | Sync Job Configuration & Scheduling| Define sync jobs with direction, frequency, scope, and conflict resolution     | `enhancement`, `mvp`, `connect`, `rest`  | Yes      |
| 3.2 (#946) | Batch Sync Engine                  | Pull/push data in scheduled batches with cursor-based incremental sync        | `enhancement`, `mvp`, `connect`, `rest`  | No       |
| 3.3 (#947) | Change Data Capture (CDC) Listener | Real-time change detection from source systems using CDC techniques           | `enhancement`, `connect`, `rest`         | Yes      |
| 3.4 (#948) | Conflict Resolution Engine         | Detect and resolve conflicts in bi-directional sync scenarios                 | `enhancement`, `connect`, `rest`         | No       |
| 3.5 (#949) | Sync Execution Log & Debugging     | Detailed per-record sync logs with error categorization and retry management  | `enhancement`, `mvp`, `connect`, `rest`  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#945) — Sync Job Configuration & Scheduling

A sync job defines the what, when, and how of data movement between an external system and Objectified. Each job specifies: the connection (source or target), the schema mapping to apply, sync direction (inbound, outbound, or bi-directional), sync mode (full or incremental), schedule (cron expression or manual trigger), and conflict resolution strategy (for bi-directional).

The configuration UI presents these options in a logical flow: select connection → select mapping → configure direction and mode → set schedule → configure error handling (retry count, dead letter behavior). Advanced settings include batch size (records per sync chunk), concurrency limits, and timeout thresholds. The job is saved as a `sync_job` record with all configuration and can be enabled/disabled without losing configuration.

Sync jobs support dependency chaining: Job B can be configured to start only after Job A completes successfully. This enables multi-stage pipelines where data flows through intermediate transformations. The scheduler respects tenant-level rate limits to prevent resource abuse.

**Acceptance Criteria:**
- Sync job CRUD API at `/api/v1/connect/sync-jobs` with full configuration options
- Schedule supports cron expressions and manual trigger mode
- Sync modes: full (all records every run) and incremental (cursor-based, only changes since last sync)
- Direction options: inbound (external→Objectified), outbound (Objectified→external), bi-directional
- Job dependency chaining: configure "run after" relationships between sync jobs
- Enable/disable toggle without losing configuration; disabled jobs skip scheduled runs

**Tech Stack:** NextJS API routes, cron scheduler (node-cron or pg-cron), PostgreSQL for job configuration, Radix UI form components for configuration wizard

Part of Epic: Real-Time Data Sync & CDC

---

#### 3.2 (#946) — Batch Sync Engine

The batch sync engine executes scheduled sync jobs by pulling or pushing data in chunks. For inbound sync, the engine calls the connector's `read()` method with the appropriate cursor (for incremental mode) or no cursor (for full mode), applies the schema mapping and transformations, validates each record against the target schema, and writes valid records to Objectified via the instance API. Invalid records are routed to a dead letter queue for review.

Incremental sync maintains a cursor (e.g., last modified timestamp, database sequence number, API pagination token) stored in the `sync_job_state` table. Each run picks up from the last cursor position, processing only new or changed records. Full sync compares every record and applies upsert logic based on a configurable identity key.

The engine processes records in configurable batch sizes (default: 500) with parallelism control (default: 4 concurrent batches). Backpressure handling pauses reads when the write pipeline falls behind. Progress is reported in real-time via a polling endpoint, showing records processed, records succeeded, records failed, and estimated time remaining.

**Acceptance Criteria:**
- Inbound sync: read from connector → apply mapping → validate → write to Objectified instances
- Outbound sync: read from Objectified instances → apply reverse mapping → write to connector
- Incremental sync with cursor persistence: only process records changed since last successful run
- Configurable batch size (default 500, max 5000) and parallelism (default 4, max 16 concurrent batches)
- Progress endpoint: `GET /api/v1/connect/sync-jobs/{id}/runs/{runId}/progress` returns real-time stats
- Dead letter queue for records that fail validation or write, with retry endpoint

**Tech Stack:** Background worker with job queue (Redis/BullMQ), PostgreSQL for sync state, connector `read()`/`write()` via gRPC, REST progress endpoint

Part of Epic: Real-Time Data Sync & CDC

---

#### 3.3 (#947) — Change Data Capture (CDC) Listener

For use cases requiring near-real-time data synchronization, the CDC listener detects changes in source systems as they happen rather than waiting for scheduled batch runs. CDC support varies by connector type: database connectors use log-based CDC (PostgreSQL WAL, MySQL binlog), SaaS connectors use webhooks or streaming APIs, and file-based connectors use filesystem watchers.

The CDC listener runs as a persistent process (one per active CDC-enabled connection) that receives change events, normalizes them into a standard format (operation type, record data, timestamp, sequence number), and feeds them into the sync pipeline. Events are buffered in a durable queue (Kafka or NATS JetStream) to handle bursts and downstream processing delays.

Configuration includes: which objects/tables to monitor, filtering rules (e.g., only capture changes to records matching a condition), debounce window (aggregate rapid changes within N seconds into a single event), and ordering guarantees (per-record ordering ensured via partition key). The listener tracks its position in the change stream for exactly-once processing semantics.

**Acceptance Criteria:**
- CDC listener framework with pluggable source adapters (database WAL, webhook receiver, streaming API)
- Standard change event format: `{ operation: INSERT|UPDATE|DELETE, data, timestamp, sequence, source_table }`
- Durable event queue (Kafka or NATS JetStream) between CDC listener and sync pipeline
- Object/table selection: configure which entities to monitor per connection
- Debounce configuration: aggregate changes within configurable window (default: 5 seconds)
- Position tracking for exactly-once semantics: resume from last committed position on restart

**Tech Stack:** Kafka or NATS JetStream for event queue, PostgreSQL logical replication for database CDC, webhook receiver endpoint at `/api/v1/connect/webhooks/{connectionId}`, background process for CDC listeners

Part of Epic: Real-Time Data Sync & CDC

---

#### 3.4 (#948) — Conflict Resolution Engine

Bi-directional sync introduces the possibility of conflicts: the same record modified in both systems between sync cycles. The conflict resolution engine detects conflicts by comparing record versions (timestamps, sequence numbers, or hashes) and applies the configured resolution strategy. Supported strategies include: last-write-wins (most recent timestamp), source-wins (external system takes priority), target-wins (Objectified takes priority), and manual (queue for human review).

Conflict detection works by storing the last-synced version of each record from both sides. When a sync run encounters a record that has been modified in both systems since the last sync, it flags the record as conflicted. For automatic strategies, the engine applies the strategy and logs the resolution. For manual strategy, the record is added to a conflict queue with both versions displayed side-by-side.

The conflict review UI shows queued conflicts with a side-by-side diff view of the two versions, highlighting changed fields. Reviewers can choose one version, merge fields from both, or edit the resolved version manually. Resolved conflicts are applied to both systems in the next sync run. Conflict history is retained for auditing.

**Acceptance Criteria:**
- Conflict detection by comparing last-synced versions against current versions on both sides
- Resolution strategies: `last_write_wins`, `source_wins`, `target_wins`, `manual_review`
- Strategy configurable per sync job with field-level overrides (e.g., "source_wins for price, target_wins for status")
- Manual review queue at `/connect/conflicts` showing conflicted records with side-by-side diff
- Conflict resolution applies to both systems in subsequent sync run
- Conflict history log with original versions, resolution strategy applied, resolved version, and actor

**Tech Stack:** NextJS page (`app/(platform)/connect/conflicts/page.tsx`), Radix UI Table for conflict queue, diff viewer component, PostgreSQL for conflict state tracking

Part of Epic: Real-Time Data Sync & CDC

---

#### 3.5 (#949) — Sync Execution Log & Debugging

Visibility into sync execution is critical for diagnosing issues and building trust in the integration. The execution log captures every sync run with aggregate statistics (records processed, succeeded, failed, skipped, duration) and per-record details for failed and skipped records (error message, source record data, transformation output if applicable).

The sync log UI provides a hierarchical view: a list of sync runs (sorted by most recent) with status badges (success, partial, failed), drill-down into a specific run showing aggregate stats and a filterable record-level log, and further drill-down into individual records showing the full transformation pipeline trace (source data → transform step 1 → step 2 → final output → validation result).

Error categorization groups failures by type (validation error, connection timeout, rate limit, permission denied, data conflict) to help users identify systemic issues versus one-off failures. A retry mechanism allows re-processing failed records from a specific run, either individually or in bulk. The system retains sync logs for a configurable period (default: 30 days) with older logs archived to cold storage.

**Acceptance Criteria:**
- Sync run record created for each execution with: start_time, end_time, status, record counts (processed/succeeded/failed/skipped)
- Per-record log entries for failed and skipped records with error message and categorization
- Sync log API: `GET /api/v1/connect/sync-jobs/{id}/runs` with pagination and status filter
- Run detail API: `GET /api/v1/connect/sync-jobs/{id}/runs/{runId}/records` with error_type filter
- Retry endpoint: `POST /api/v1/connect/sync-jobs/{id}/runs/{runId}/retry` reprocesses failed records
- Log retention: configurable per tenant (default 30 days), older logs archived

**Tech Stack:** NextJS page (`app/(platform)/connect/sync-logs/page.tsx`), Radix UI Table for run list and record details, PostgreSQL for log storage, background cleanup job for retention

Part of Epic: Real-Time Data Sync & CDC

---

## Epic 4: Event-Driven & Messaging Integration

### Summary Table

| #   | Title                              | Description                                                                   | Labels                                   | Parallel |
|-----|------------------------------------|-------------------------------------------------------------------------------|------------------------------------------|----------|
| 4.1 (#951) | Webhook Orchestration Engine       | Manage inbound and outbound webhooks with verification, retry, and routing    | `enhancement`, `connect`, `rest`         | Yes      |
| 4.2 (#952) | Kafka Connector                    | Produce and consume messages from Apache Kafka topics with schema validation  | `enhancement`, `connect`, `rest`         | Yes      |
| 4.3 (#953) | RabbitMQ / NATS Connectors         | Message queue connectors for RabbitMQ and NATS with queue management          | `enhancement`, `connect`, `rest`         | Yes      |
| 4.4 (#954) | Event Router & Fan-Out             | Route events from any source to multiple destinations with filtering rules    | `enhancement`, `connect`, `rest`         | No       |
| 4.5 (#955) | Event Schema Validation & DLQ      | Validate events against schemas before routing, dead-letter failed events     | `enhancement`, `connect`, `rest`         | No       |

### Detailed Issue Descriptions

#### 4.1 (#951) — Webhook Orchestration Engine

Webhooks are the simplest form of event-driven integration, and the orchestration engine provides comprehensive management for both inbound (receiving webhooks from external systems) and outbound (sending webhooks to external systems on Objectified events). Inbound webhooks are received at tenant-specific endpoints (`/api/v1/connect/webhooks/{tenantId}/{hookId}`), verified using the configured method (HMAC signature, shared secret header, IP allowlist), and routed to the appropriate processing pipeline.

Outbound webhooks are triggered by Objectified events (instance created, updated, deleted; schema published; sync completed) and delivered to configured target URLs. The delivery system implements reliability patterns: exponential backoff retry (1s, 2s, 4s, 8s, 16s up to configurable max), delivery receipt tracking, and dead letter queue for permanently failed deliveries. Each delivery attempt is logged with timestamp, HTTP status code, response body (truncated), and latency.

The webhook management UI enables creating, editing, and testing webhooks. A "Send Test" feature delivers a sample payload to the configured URL and displays the response. Webhook activity shows recent deliveries with success/failure indicators, and a replay feature allows re-sending a specific delivery for debugging.

**Acceptance Criteria:**
- Inbound webhook endpoints at `/api/v1/connect/webhooks/{tenantId}/{hookId}` with HMAC and shared-secret verification
- Outbound webhook configuration: target URL, events to trigger on, custom headers, secret for signing
- Retry with exponential backoff: 1s, 2s, 4s, 8s, 16s (max 5 attempts configurable)
- Delivery log per webhook with timestamp, HTTP status, response snippet, latency, and attempt number
- "Send Test" endpoint: `POST /api/v1/connect/webhooks/{id}/test` sends sample payload and returns response
- Replay endpoint: `POST /api/v1/connect/webhooks/{id}/deliveries/{deliveryId}/replay` re-sends specific delivery

**Tech Stack:** NextJS API routes for webhook endpoints, background worker for outbound delivery and retries, PostgreSQL for delivery log, HMAC-SHA256 for webhook signing

Part of Epic: Event-Driven & Messaging Integration

---

#### 4.2 (#952) — Kafka Connector

The Kafka connector enables bidirectional data flow between Objectified and Apache Kafka clusters. As a producer, it publishes Objectified events (schema changes, instance mutations, sync completions) to configurable Kafka topics with schema-validated payloads. As a consumer, it subscribes to Kafka topics and feeds incoming messages through the Connect mapping and transformation pipeline into Objectified.

Producer configuration includes: Kafka broker list, authentication (SASL/PLAIN, SASL/SCRAM, mTLS), topic naming pattern (e.g., `objectified.{tenant}.{schema}.{event_type}`), message serialization (JSON, Avro with Schema Registry integration), partitioning strategy (round-robin, key-based using record ID), and which Objectified events to publish. Consumer configuration adds: consumer group ID, offset management (earliest, latest, specific), concurrency (number of partitions to consume in parallel), and backpressure settings.

Schema Registry integration enables publishing Avro schemas derived from Objectified schemas to Confluent Schema Registry, ensuring downstream consumers have type-safe contracts. When Objectified schemas evolve, the connector automatically registers new Avro schema versions with compatibility checks.

**Acceptance Criteria:**
- Kafka producer publishes Objectified events to configurable topics with JSON or Avro serialization
- Kafka consumer subscribes to topics with configurable consumer group, offset management, and concurrency
- Authentication support: SASL/PLAIN, SASL/SCRAM-SHA-256, mTLS with certificate upload
- Confluent Schema Registry integration for Avro schema registration and compatibility checking
- Topic naming pattern support with template variables: `{tenant}`, `{schema}`, `{event_type}`
- Consumer lag monitoring via `GET /api/v1/connect/connectors/kafka/{id}/lag` returning per-partition lag

**Tech Stack:** KafkaJS for Node.js Kafka client, Avro serialization library, Schema Registry HTTP client, connector plugin implementing ConnectorInterface

Part of Epic: Event-Driven & Messaging Integration

---

#### 4.3 (#953) — RabbitMQ / NATS Connectors

Message queue connectors for RabbitMQ and NATS extend Connect's event-driven capabilities to organizations using these messaging systems. Each connector implements the standard ConnectorInterface with messaging-specific semantics: publish (write), subscribe (read with callback), and acknowledge (confirm processing).

The RabbitMQ connector supports: exchange/queue declaration, binding keys with routing patterns, message persistence settings, consumer prefetch count, dead letter exchange configuration, and message TTL. The NATS connector supports: subject-based messaging, NATS JetStream for persistent streams, consumer groups, and key-value store integration. Both connectors handle reconnection with configurable backoff.

Configuration UI for each connector presents protocol-specific fields organized logically. A "Topology Viewer" visualizes the current exchange/queue setup (RabbitMQ) or subject/stream layout (NATS) to help users understand message routing. Messages flowing through these connectors pass through the same mapping and transformation pipeline as other connector types.

**Acceptance Criteria:**
- RabbitMQ connector: publish to exchanges, consume from queues, support routing keys and binding patterns
- NATS connector: publish to subjects, subscribe with consumer groups, JetStream durable consumers
- Both connectors: automatic reconnection with configurable backoff, TLS support, authentication
- Message serialization: JSON by default, configurable (Avro, Protobuf, MessagePack)
- RabbitMQ topology viewer showing exchanges, queues, and bindings for the configured vhost
- Health check integration: verify broker connectivity and queue/subject accessibility

**Tech Stack:** amqplib for RabbitMQ, nats.js for NATS, connector plugin architecture, Radix UI Dialog for configuration

Part of Epic: Event-Driven & Messaging Integration

---

#### 4.4 (#954) — Event Router & Fan-Out

The event router sits at the center of Connect's event-driven architecture, receiving events from any source (webhooks, CDC listeners, message queue consumers, Objectified internal events) and routing them to one or more destinations based on configurable rules. This enables fan-out patterns where a single event triggers actions in multiple systems simultaneously.

Routing rules are defined as condition-action pairs: a condition evaluates event properties (type, source, payload fields) using a simple expression language, and the action specifies the destination (another connector, a webhook, a Kafka topic, or an Objectified schema mapping). Rules are evaluated in priority order, and multiple rules can match a single event (fan-out). A "catch-all" rule handles unmatched events.

The router supports transformation at the routing level: each rule can apply a lightweight transform to the event payload before forwarding. This enables adapting event shapes to different consumer expectations without creating separate mapping configurations. Router throughput is critical—the implementation must handle at least 10,000 events per second per tenant with sub-100ms routing latency.

**Acceptance Criteria:**
- Event routing rules: condition expression (field matching, regex, comparison operators) → destination action
- Fan-out: multiple rules can match a single event, each forwarding to a different destination
- Priority ordering: rules evaluated in configurable order; first match or all matches mode
- Per-rule lightweight transformation: rename fields, filter payload, add static fields
- Router metrics: events routed per second, routing latency (p50, p95, p99), error rate
- Rule management API: CRUD at `/api/v1/connect/event-router/rules` with dry-run testing endpoint

**Tech Stack:** In-memory rule evaluation engine, event queue (Kafka/NATS) for durability, PostgreSQL for rule storage, NextJS page for rule management UI

Part of Epic: Event-Driven & Messaging Integration

---

#### 4.5 (#955) — Event Schema Validation & DLQ

Every event flowing through the Connect event-driven pipeline should be validated against the expected schema to catch malformed data before it reaches downstream systems. The validation layer sits between event sources and the router, applying JSON Schema validation to incoming events. Events that fail validation are routed to a dead-letter queue (DLQ) rather than silently dropped or propagated with bad data.

Schema validation rules are configured per event source: each inbound webhook, CDC listener, or message queue consumer can be assigned a JSON Schema that incoming events must conform to. The schema can be an Objectified schema reference (reusing existing schema definitions) or a custom schema defined inline. Validation is optional and defaults to off for backward compatibility.

The DLQ management UI shows failed events with their validation errors, source information, and timestamp. Users can inspect the raw event payload, view the validation errors, fix the event manually, and resubmit it to the pipeline. Bulk operations support resubmitting all events that failed due to a specific error pattern (useful after fixing a schema mismatch). DLQ metrics (queue depth, failure rate, top error categories) are surfaced on the Connect dashboard.

**Acceptance Criteria:**
- Schema validation configurable per event source with JSON Schema reference or inline definition
- Validation failures routed to DLQ with: original event, validation errors, source metadata, timestamp
- DLQ management API: `GET /api/v1/connect/dlq/events` with filters for source, error type, date range
- Individual event inspection with raw payload, validation errors, and "Resubmit" action
- Bulk resubmit: `POST /api/v1/connect/dlq/resubmit` with filter criteria to batch-reprocess events
- DLQ metrics endpoint: queue depth, failure rate, top 5 error categories with counts

**Tech Stack:** JSON Schema validation library, PostgreSQL for DLQ storage, NextJS page (`app/(platform)/connect/dlq/page.tsx`), Radix UI Table for DLQ event list, REST API for DLQ management

Part of Epic: Event-Driven & Messaging Integration

---

## Parallel Work Guide

The following issues can be worked on simultaneously within and across epics:

**Epic 1 — Connector Framework & Registry:**
- Issues 1.1, 1.2, 1.5, and 1.6 can all be developed in parallel (plugin architecture, registry, monitoring, and SDK are independent)
- Issue 1.3 depends on 1.2 (marketplace UI needs registry data)
- Issue 1.4 depends on 1.1 and 1.3 (configuration wizard needs plugin architecture and marketplace)

**Epic 2 — Schema Mapping & Transformation:**
- Issues 2.1, 2.3, and 2.4 can be developed in parallel (discovery, transforms, and templates are independent)
- Issue 2.2 depends on 2.1 (mapping UI needs discovered schemas)
- Issue 2.5 depends on 2.2 and 2.3 (validation needs mappings and transforms)

**Epic 3 — Real-Time Data Sync & CDC:**
- Issues 3.1, 3.3, and 3.5 can be developed in parallel (job config, CDC listener, and logging are independent)
- Issue 3.2 depends on 3.1 (batch engine needs job configuration)
- Issue 3.4 depends on 3.2 (conflict resolution needs the sync engine)

**Epic 4 — Event-Driven & Messaging:**
- Issues 4.1, 4.2, and 4.3 can all be developed in parallel (webhooks, Kafka, and RabbitMQ/NATS are independent)
- Issue 4.4 depends on 4.1, 4.2, 4.3 (router routes events from these sources)
- Issue 4.5 depends on 4.4 (DLQ validation sits before the router)

**Cross-Epic Parallelism:**
- Epic 1 and Epic 2 can begin simultaneously (framework and mapping are complementary but independent)
- Epic 3 depends on Epic 1 (connectors) and Epic 2 (mappings) for full functionality, but issue 3.1 (job config) can start early
- Epic 4 depends on Epic 1 (connector framework) but issues 4.1-4.3 only need the plugin interface from 1.1
