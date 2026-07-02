# Apiome: Database Data Storage - Feature Roadmap

> Enterprise-level data storage for Apiome using an event-sourced architecture. Every stored data instance is tied to a frozen schema capture, mutated through an append-only event log (CREATE/UPDATE/DELETE), and materialized into a high-speed snapshot for O(1) reads. The database offering extends from core instance lifecycle management through relational linking, batch processing, time-travel queries, AI-powered semantic search, and optional Redis/MongoDB enterprise offloading.
>
> **Revenue Model**: Core instance storage and REST API included in all tiers; batch job workers, vector search, natural language queries, advanced audit exports, and enterprise offloading (Redis/MongoDB) are Pro/Enterprise-gated; time-series reconstruction and Spark-accelerated pipelines are Enterprise-only.
>
> **Tech Stack**: Python 3.11+ (FastAPI, asyncpg), PostgreSQL 15+ (pgvector, RLS, partitioning, GIN indexes), Redis (snapshot cache), MongoDB (delta offloading, interim migration store), Apache Spark, JSON Schema (jsonschema/fastjsonschema), OpenAPI 3.1, NextJS App Router (query builder UI), React Flow (relationship graph)

---

## MVP Definition

- Schema capture: freeze/immute the full version schema and individual class schemas; generate integrity fingerprint
- JSON Schema validation engine supporting draft-07/2020-12; validate instance data before every write
- Instance lifecycle: CREATE (full data + snapshot), UPDATE (delta via JSON Patch + snapshot merge), DELETE (soft-delete + tombstone event), Restore
- Optimistic locking: version-based conflict detection; reject stale updates with 409
- Full CRUD REST API for schema captures, instances, instance history, snapshots, and bulk operations (OpenAPI 3.1)
- Cursor-based pagination, JSONB filtering (`filter[data.field][op]=value`), and sort for all list endpoints
- API key authentication: scoped per tenant, per version, with read/write/delete/admin scopes and audit logging
- Append-only audit log for all data operations with user identification, timestamp, before/after values

---

## Epic 1 (#2178): Core Storage Engine & Instance Lifecycle

### Summary Table

| #   | Title                           | Description                                                                                         | Labels                                                 | MVP | Parallel |
|-----|---------------------------------|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------|-----|----------|
| 1.1 (#2179) | Schema Capture & Freezing       | Freeze version schema into immutable captures; individual class schemas; integrity fingerprint       | `enhancement`, `mvp`, `database`, `rest`               | Yes | No       |
| 1.2 (#2180) | JSON Schema Validation Engine   | Validate instance data against class JSON Schema; caching; custom error messages; draft-07/2020-12  | `enhancement`, `mvp`, `database`                       | Yes | No       |
| 1.3 (#2181) | Instance CREATE & Snapshot Init | Create instance + event record (CREATE) + initial snapshot; auto-increment version; vector hook     | `enhancement`, `mvp`, `database`, `rest`               | Yes | Yes      |
| 1.4 (#2182) | Instance UPDATE & Snapshot Merge | Compute JSON Patch delta; validate merged result; update snapshot; increment version               | `enhancement`, `mvp`, `database`, `rest`               | Yes | Yes      |
| 1.5 (#2183) | Instance DELETE & Restoration   | Soft-delete: tombstone event, deactivate snapshot; Restore: rebuild snapshot from event log         | `enhancement`, `mvp`, `database`, `rest`               | Yes | Yes      |
| 1.6 (#2184) | Optimistic Locking              | Version-based conflict detection; reject stale updates (409); merge conflict resolution strategies  | `enhancement`, `mvp`, `database`                       | Yes | Yes      |
| 1.7 (#2185) | Batch Import & Export           | Bulk import CSV/JSON/JSONL/Parquet with mapping, validation, and progress tracking; bulk export     | `enhancement`, `database`, `rest`                      | No  | Yes      |
| 1.8 (#2186) | Batch Job System                | Async job lifecycle, SSE progress stream, job scheduling, webhooks, templates, and queue management | `enhancement`, `database`, `rest`                      | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#2179) — Schema Capture & Freezing

A schema capture is an immutable snapshot of a version's schema at the moment it is published or finalized. Captures provide the stable contract against which instance data is validated — no instance can be stored without a corresponding capture, and no capture can be modified after creation. The capture stores the entire version JSON Schema and individual class schemas in `schema_capture_class` rows.

The schema finalization workflow triggers on version publish: validate all class schemas are complete, compute a SHA-256 fingerprint of the canonical serialized schema, insert `schema_capture` and `schema_capture_class` rows, and mark the version as immutable. Any attempt to modify the schema after capture is rejected with 409.

```
schema_capture
┌───────────────────────────────────────────────┐
│ id               uuid_v7                      │
│ version_id       uuid FK → project_version    │
│ tenant_id        uuid                         │
│ captured_at      timestamptz                  │
│ captured_by      uuid FK → user               │
│ schema_hash      text (sha256)                │
│ full_schema      jsonb                        │
└───────────────────────────────────────────────┘

schema_capture_class
┌───────────────────────────────────────────────┐
│ id               uuid                         │
│ schema_capture_id uuid FK                     │
│ class_id         uuid                         │
│ class_name       text                         │
│ class_schema     jsonb (full JSON Schema)     │
│ schema_hash      text                         │
└───────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- `POST /versions/{version_id}/schema-capture` triggers finalization; rejects if any class schema is incomplete
- Schema capture is immutable: `PUT/PATCH` on a capture returns 405 Method Not Allowed
- Capture blocked if instances already exist and would violate the new schema (incompatibility check)
- `GET /versions/{version_id}/schema-capture` returns full schema with fingerprint
- `GET /versions/{version_id}/schema-capture/classes/{class_id}` returns the class-specific JSON Schema
- `DELETE /versions/{version_id}/schema-capture` is admin-only and blocked if any instances reference the capture

**Tech Stack:** PostgreSQL; SHA-256 fingerprint; OpenAPI 3.1 endpoints; publish lifecycle hook

Part of Epic: Core Storage Engine & Instance Lifecycle

---

#### 1.2 (#2180) — JSON Schema Validation Engine

Every data write (CREATE, UPDATE, bulk import) must validate the proposed instance data against the captured class JSON Schema before committing. Validation must be fast enough for real-time API responses (p95 <20ms for a 50-property schema) and must produce field-level error messages with JSON Pointer paths for developer-friendly error responses.

The engine supports JSON Schema draft-07 and 2020-12. It resolves `$ref` references within the captured schema (all `$ref` targets are inlined into the capture so no external resolution is needed). Schema validation results are cached by `(schema_capture_class_id, input_hash)` with a 60-second TTL to avoid re-validating identical payloads.

```
Request body:
  { "email": "not-an-email", "age": "thirty" }

Validation error response (422):
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Data validation failed",
    "details": [
      { "path": "/email", "message": "must match format \"email\"" },
      { "path": "/age",   "message": "must be integer" }
    ]
  }
}
```

**Acceptance Criteria:**
- All CREATE and UPDATE instance operations validate data against the class schema before any database write
- Validation errors return 422 with RFC 7807-style detail array including JSON Pointer paths
- `jsonschema` or `fastjsonschema` library integrated; supports `format`, `$ref`, `oneOf`, `allOf`, `anyOf`
- Schema validation cache: second call with identical `(class_schema_hash, data_hash)` returns cached result without re-evaluating
- Batch import validation validates all records before committing any; partial success mode validates per-row and collects errors
- Performance benchmark: 1,000 validation calls/second on a single worker with a 20-property schema

**Tech Stack:** Python `fastjsonschema` (pre-compiled validators); Redis validation result cache; OpenAPI 422 response schema

Part of Epic: Core Storage Engine & Instance Lifecycle

---

#### 1.3 (#2181) — Instance CREATE & Snapshot Initialization

Creating an instance produces three database rows in a single transaction: the `instance` record (metadata, tenant, class reference, is_active=true), the `instance_data` record (action=CREATE, full data JSON, version=1, actor), and the `instance_snapshot` record (current_data = the full CREATE data, last_version=1). This three-table design enables O(1) current-state reads via the snapshot while preserving the full event log for history and audit.

An optional embedding generation hook runs asynchronously post-commit: if vector search is enabled for the class, the instance data is queued for embedding generation (see Epic 6.1).

```
POST /versions/{v}/classes/{c}/instances
  body: { name, description, data: {...} }

Transaction:
  1. Validate data against class schema (Epic 1.2)
  2. INSERT instance (id, class_id, tenant_id, is_active=true, created_at)
  3. INSERT instance_data (instance_id, version=1, action=CREATE,
                           data=full_body, actor, correlation_id)
  4. INSERT instance_snapshot (instance_id, current_data=full_body,
                               last_version=1, updated_at)
  COMMIT

Response: { instance_id, version: 1, created_at }
```

**Acceptance Criteria:**
- CREATE is fully transactional; partial failures roll back all three inserts
- `instance_id` uses UUID v7 (time-ordered) for natural sort order
- `version` starts at 1 and is guaranteed monotonically increasing per instance
- Actor (user_id or API key ID) and `correlation_id` are stored on `instance_data` for forensic tracing
- Async embedding queue: if class has `embedding_enabled=true`, enqueue `(instance_id, data)` for async processing
- Response time: single instance CREATE p95 <50ms including validation

**Tech Stack:** PostgreSQL transaction; asyncpg; UUID v7; async embedding queue (Celery or asyncio task)

Part of Epic: Core Storage Engine & Instance Lifecycle

---

#### 1.4 (#2182) — Instance UPDATE & Snapshot Merge

Updating an instance computes the delta (JSON Patch per RFC 6902) between the current snapshot and the new data, validates the merged result, stores only the delta in `instance_data`, and atomically updates `instance_snapshot`. This minimizes storage for frequent small updates while preserving a complete event log.

Both full replacement (`PUT`: replace all fields) and partial update (`PATCH`: JSON Patch or JSON Merge Patch per RFC 7396) are supported. The API automatically computes the delta from the supplied input — callers do not need to compute patches themselves.

```
PUT /instances/{instance_id}
  body: { name, data: { ...complete replacement... } }
  → Computes delta = json_diff(current_snapshot, new_data)
  → INSERT instance_data(action=UPDATE, data=delta, version=N+1)
  → UPDATE instance_snapshot SET current_data = merge(current_data, delta)

PATCH /instances/{instance_id}
  body: JSON Patch array [{"op":"replace","path":"/email","value":"..."}]
  → Applies patch to current_snapshot → validates merged result
  → INSERT instance_data(action=UPDATE, data=patch, version=N+1)
  → UPDATE instance_snapshot
```

**Acceptance Criteria:**
- UPDATE is fully transactional; actor and correlation_id stored on every `instance_data` row
- Optimistic locking: `PUT/PATCH` with `If-Match: {version}` header rejects if current version differs (409 Conflict)
- Delta is stored as JSON Patch (RFC 6902) for precise field-level diffing; JSONB diff function used to compute it
- `GET /instances/{id}/history` returns delta for each UPDATE with JSON Pointer paths of changed fields
- JSON Merge Patch (`Content-Type: application/merge-patch+json`) also supported as an alternative update format
- `changed_paths` array (JSON Pointer paths) is stored alongside the delta for fast field-level filtering (aligns with Detective Epic 2.2)

**Tech Stack:** PostgreSQL JSONB diff; asyncpg; RFC 6902/7396 patch libraries; `If-Match` header validation

Part of Epic: Core Storage Engine & Instance Lifecycle

---

#### 1.5 (#2183) — Instance DELETE & Restoration

Soft-delete is the default: `DELETE /instances/{id}` sets `instance.is_active=false`, `instance.deleted_at=NOW()`, inserts an `instance_data` tombstone (action=DELETE, empty data, version=N+1), and removes or deactivates the snapshot. The full history is preserved for audit compliance. Hard-delete (`?mode=hard`) is available only to admin roles and requires an explicit confirmation token; it permanently removes `instance`, `instance_data`, and `instance_snapshot` rows and emits a Detective audit event.

Restoration (`POST /instances/{id}/restore`) clears `deleted_at`, sets `is_active=true`, and rebuilds the `instance_snapshot` by replaying all `instance_data` events in version order. The restored snapshot is validated against the current class schema; schema evolution conflicts during restoration are reported to the caller.

**Acceptance Criteria:**
- Soft-delete: `is_active=false`, tombstone event inserted, snapshot deactivated — all in one transaction
- Soft-deleted instances are excluded from list and search results by default; visible with `?include_deleted=true`
- Hard-delete: requires `X-Confirm-Delete: {confirmation_token}` header; confirmation token obtained from `POST /instances/{id}/hard-delete-confirm`
- Hard-delete emits a `HARD_DELETE` Detective audit event and cannot be undone
- Restore: rebuilds snapshot by sequential replay of all events; validates rebuilt state against current schema
- Restore returns 409 if schema has changed incompatibly; includes a list of validation errors for the caller to resolve

**Tech Stack:** PostgreSQL; asyncpg; snapshot replay function; schema re-validation on restore

Part of Epic: Core Storage Engine & Instance Lifecycle

---

#### 1.6 (#2184) — Optimistic Locking

In concurrent environments, two clients may read the same instance and attempt simultaneous updates. Without locking, the second write silently overwrites the first. Optimistic locking uses the instance version number as an `ETag`-style concurrency token: the client reads the current version, sends it in the `If-Match` header, and the server rejects the write if the version has changed since.

Conflict resolution strategies (configurable per request): **reject** (default, return 409 with the current version for the client to retry), **auto-merge** (apply non-conflicting field changes from both versions and surface conflicts only for overlapping fields), **last-write-wins** (skip the version check; for use cases where overwrite is acceptable).

**Acceptance Criteria:**
- `GET /instances/{id}` response includes `ETag: "{version}"` and `Last-Modified` headers
- `PUT/PATCH /instances/{id}` with `If-Match: {version}` returns 409 if current version does not match
- 409 response body includes: `current_version`, `your_version`, and `current_data` for the client to perform a 3-way merge
- Auto-merge (`X-Conflict-Resolution: auto-merge`): merges non-overlapping changes; returns 409 only for field-level conflicts
- Last-write-wins (`X-Conflict-Resolution: last-write-wins`): skips the version check; requires explicit `write` scope
- Bulk UPDATE operations support per-record `If-Match` headers via `{ instance_id, version, data }` objects in the request body

**Tech Stack:** PostgreSQL `FOR UPDATE SKIP LOCKED`; ETags; asyncpg; atomic version check-and-increment

Part of Epic: Core Storage Engine & Instance Lifecycle

---

#### 1.7 (#2185) — Batch Import & Export

**Bulk import:** Multi-step workflow: upload file (CSV/JSON/JSONL/Excel/Parquet), preview detected columns with sample data and suggested mappings, configure column-to-property mappings with transform functions (date parsing, type coercion, string concatenation), validate all records in dry-run before committing, execute import as an async job with progress tracking. Supports partial success mode (commit successes, log errors) or all-or-nothing transactional mode.

**Import templates:** Save mapping configurations as reusable templates with template versioning for schema changes. Auto-suggest mappings from column name similarity to property names.

**Bulk export:** Configure export: class IDs, JSONB filters, field selection, format (JSON/JSONL/CSV/Excel/Parquet), compression, include/exclude history and metadata. Async job produces a signed S3 download URL (24h expiry). Scheduled/automated exports with cron-style scheduling.

**Bulk operations:** Query-based bulk UPDATE and bulk DELETE with preview mode, progress tracking, atomic transactions, and rollback support. Audit logging for all bulk operations.

**Acceptance Criteria:**
- Upload endpoint: `POST /batch/import/upload` accepts multipart/form-data; auto-detects format from content or extension
- Preview: returns first 10 rows with column detection and mapping suggestions based on string similarity
- Import mapping: column transforms support parse_date (with format string), type_cast, string_trim, value_map (lookup table)
- Dry-run validation: `POST /batch/import/validate` validates all records without committing; returns per-row error report
- Import job: SSE progress stream at `GET /batch/jobs/{id}/progress/stream`; includes records_processed, records_succeeded, records_failed
- Export job: produces signed download URL; manifest file with row counts and SHA-256 checksum
- Bulk UPDATE: `POST /bulk/update` with query filter and transformation rules; `preview=true` mode returns affected count and sample rows without executing

**Tech Stack:** S3-compatible file storage; Pandas/Polars for file parsing; Parquet via PyArrow; async job queue

Part of Epic: Core Storage Engine & Instance Lifecycle

---

#### 1.8 (#2186) — Batch Job System

The batch job system provides a unified lifecycle for all async operations: import, export, transform, validate, delete, and migration steps. Jobs are submitted via REST, tracked via polling or SSE, and notify via webhooks on completion/failure.

**Job lifecycle:** pending → queued → running → (paused) → completed | failed | cancelled. Jobs support priority (low/normal/high), scheduled execution (`scheduled_at`), retry on failure (`POST /jobs/{id}/retry`), and cancellation. A queue status API shows tenant queue depth, estimated wait time, and worker capacity.

**Scheduling:** Create recurring batch jobs with cron expressions and timezone support. Manual trigger available via `POST /schedules/{id}/trigger`. Execution history per schedule.

**Templates:** Save job configurations as named templates; instantiate with parameter overrides. Useful for standard nightly exports or recurring data quality checks.

**Webhooks:** Register webhook endpoints for job lifecycle events (`job.started`, `job.progress`, `job.completed`, `job.failed`). HMAC-SHA256 signatures verify webhook authenticity. Email notifications as an alternative delivery channel.

**Acceptance Criteria:**
- `POST /batch/jobs` accepts all documented `job_type` values; returns `job_id` and `estimated_duration`
- `GET /batch/jobs/{id}/status` returns structured progress JSON with `percent_complete`, `records_processed`, `records_total`, and `current_phase`
- SSE stream at `GET /batch/jobs/{id}/progress/stream` emits progress events every 2 seconds
- Webhooks: retry with exponential backoff (1m, 5m, 30m, 2h) on delivery failure; max 5 retries; failure logged
- Schedule: `POST /batch/schedules` with cron_expression and timezone; next execution shown in response
- Template execution: `POST /batch/templates/{id}/execute` with `parameter_overrides`; returns new `job_id`
- Queue status: `GET /batch/queue/status` returns pending/running counts, estimated wait, and worker capacity

**Tech Stack:** Celery or asyncio task queue; PostgreSQL job state table; SSE; HMAC-SHA256 webhooks

Part of Epic: Core Storage Engine & Instance Lifecycle

---

## Epic 2 (#2187): Relationships, Search & Query

### Summary Table

| #   | Title                            | Description                                                                                         | Labels                                           | MVP | Parallel |
|-----|----------------------------------|-----------------------------------------------------------------------------------------------------|--------------------------------------------------|-----|----------|
| 2.1 (#2188) | Link Definitions & $ref Extraction | Define relationship types; auto-extract from JSON Schema $ref; cardinality and cascade config     | `enhancement`, `database`, `rest`                | No  | No       |
| 2.2 (#2189) | Instance Linking & Traversal     | Create/validate/delete links; cardinality enforcement; link traversal (incoming/outgoing/all)       | `enhancement`, `database`, `rest`                | No  | Yes      |
| 2.3 (#2190) | Full-Text & JSONB Search         | GIN-indexed JSONB containment; full-text on text fields; boolean DSL; faceted search; autocomplete  | `enhancement`, `database`, `rest`                | No  | No       |
| 2.4 (#2191) | Ad-hoc Query Engine              | Visual and API query builder: filters, joins, aggregations, sorting, pagination; saved queries      | `enhancement`, `database`, `rest`                | No  | Yes      |
| 2.5 (#2192) | Natural Language Query Interface | Plain English → SQL translation via LLM; query intent recognition; query suggestions; safety guards | `enhancement`, `database`, `rest`                | No  | Yes      |
| 2.6 (#2193) | Query Security & Governance      | Row-level security; column masking for PII; query policies (timeout, max rows, cost); audit log     | `enhancement`, `database`                        | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#2188) — Link Definitions & $ref Extraction

Link definitions describe relationship types between schema classes: which class is the source, which is the target, the cardinality (one-to-one, one-to-many, many-to-many), direction (unidirectional or bidirectional), and cascade behavior (cascade delete, restrict, set-null, no-action). They are stored in the `link_def` table and referenced by the `link` table (actual instance links).

The `$ref` extraction engine parses class schemas for `$ref` entries pointing to other classes within the same capture, auto-generates `link_def` entries from those references, and handles nested `$ref` in arrays and objects. Circular reference detection prevents infinite loops during extraction. A relationship graph is generated from all link definitions for the visualization layer (Epic 5.1).

```
schema class: Order
  properties:
    customer: { "$ref": "#/$defs/Customer" }  → link_def: Order → Customer (one-to-one)
    items:    { type: "array", items: { "$ref": "#/$defs/OrderItem" } }
              → link_def: Order → OrderItem (one-to-many)
```

**Acceptance Criteria:**
- `link_def` table: `id`, `schema_capture_id`, `source_class_id`, `target_class_id`, `name`, `cardinality` enum, `direction` enum, `cascade_behavior` enum, `metadata` JSONB
- `$ref` extraction job runs automatically on schema capture creation; processes all class schemas
- Circular references are detected and logged; a warning is emitted but the capture is not blocked
- Manual `POST /versions/{v}/link-definitions` allows creating additional link definitions beyond auto-extracted ones
- `DELETE /link-definitions/{id}` is blocked if any links exist referencing the definition
- UI: link definitions shown as a table in the version detail view with cardinality and cascade icons

**Tech Stack:** Python JSON Schema `$ref` parser; PostgreSQL; asyncpg; OpenAPI 3.1 endpoints

Part of Epic: Relationships, Search & Query

---

#### 2.2 (#2189) — Instance Linking & Traversal

The `link` table stores actual relationships between instance pairs: `t1` (source instance), `t2` (target instance), `link_def_id`, optional `t3` (junction data JSONB for many-to-many relationship attributes), timestamps, and soft-delete support. Link creation validates: both instances exist and are active, both instances match the classes defined in `link_def`, and cardinality constraints are not violated (e.g., a one-to-one link cannot be created if source already has a link of this type).

Cascade operations: when an instance is soft-deleted and the relevant `link_def` has `cascade_behavior=cascade`, all links where that instance is `t1` are also soft-deleted. Traversal APIs allow navigating the link graph from any instance: `GET /instances/{id}/links/outgoing`, `GET /instances/{id}/links/incoming`, `GET /instances/{id}/links/all`.

**Acceptance Criteria:**
- `POST /links` validates instances, link_def class types, and cardinality before inserting
- Cardinality validation: one-to-one link creation returns 409 if source already has a link of the same type
- Cascade soft-delete: when an instance with `cascade` links is deleted, `DELETE /instances/{id}` cascades to linked instances (with audit trail)
- Traversal: `GET /instances/{id}/links/outgoing` returns paginated list of linked target instances with resolved summary fields
- Bulk link creation: `POST /links/bulk` accepts array of link objects; validates and inserts all in one transaction
- Detective audit event emitted on link CREATE, UPDATE (t3 changes), and DELETE

**Tech Stack:** PostgreSQL; asyncpg; cardinality enforcement in application layer; OpenAPI 3.1

Part of Epic: Relationships, Search & Query

---

#### 2.3 (#2190) — Full-Text & JSONB Search

The search engine exposes structured JSONB queries and full-text search across instance snapshots. JSONB containment queries use GIN indexes for fast sub-document matching. Full-text search on text fields within JSONB uses `tsvector`/`tsquery` with per-class text-field configuration. Search results support ranking and scoring, highlighted matching terms, and faceted aggregations by JSONB field values.

The search API accepts a query DSL supporting: field-specific searches, boolean combinations (AND/OR/NOT), range queries for numeric and date fields, JSONB path operators (`data.address.city = "Seattle"`), and full-text with fuzzy matching. Cursor-based pagination handles large result sets. Autocomplete suggests field values as the user types.

```
POST /versions/{v}/classes/{c}/instances/search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "data.status": "active" } },
        { "range": { "data.total": { "gte": 100 } } }
      ],
      "should": [
        { "full_text": { "fields": ["data.name", "data.description"], "query": "enterprise" } }
      ]
    }
  },
  "sort": [{ "data.created_at": "desc" }],
  "limit": 50,
  "cursor": "...",
  "facets": ["data.status", "data.category"]
}
```

**Acceptance Criteria:**
- GIN index on `instance_snapshot.current_data` created at schema capture time; index includes class-specific configured paths
- Full-text: `tsvector` column maintained with text field values from configurable per-class field list
- Boolean DSL: `must` (AND), `should` (OR, boost), `must_not` (NOT); nestable
- Range queries support numeric, date (ISO 8601), and string (lexicographic) ranges
- Faceted aggregations: `facets` array returns counts per unique value for each specified JSONB path
- Autocomplete: `POST /search/suggest?q=sea&field=data.city` returns top-10 matching values from GIN index
- Benchmark: 1M-row snapshot search with 3 filter conditions completes in <100ms at p95

**Tech Stack:** PostgreSQL GIN index (JSONB); `tsvector`; asyncpg; cursor-based pagination

Part of Epic: Relationships, Search & Query

---

#### 2.4 (#2191) — Ad-hoc Query Engine

The ad-hoc query engine provides both a REST API and a visual query builder UI for constructing and executing structured queries against instance snapshots. The API accepts a query definition object (class, filters, joined classes via links, field selection, aggregations, sort, limit, offset) and executes it against the snapshot tables with tenant isolation via RLS.

**Filter builder:** All comparison operators (=, ≠, >, <, ≥, ≤), string operators (contains, starts_with, ends_with, regex), array operators (contains, overlaps, is_empty), null checks, date range pickers, AND/OR logic with nested groups. **Join builder:** Join across linked classes using `link_def` relationships; supports inner and left joins; multi-hop traversal. **Aggregation builder:** GROUP BY, COUNT/SUM/AVG/MIN/MAX, HAVING clause, window functions (running totals, rankings), pivot table generation. **Saved queries:** Save with name, description, tags, and parameterization; organize in folders; query versioning; sharing with team members (view/edit/execute permissions).

**Acceptance Criteria:**
- `POST /versions/{v}/query` executes a query definition and returns paginated results
- Query definition supports all documented filter operators; invalid operator returns 400 with clear error
- Multi-hop joins: query crossing 3 linked classes executes in <500ms for datasets up to 100K instances
- Aggregation: `POST /versions/{v}/query/aggregate` with `group_by`, `aggregations`, and `having` returns grouped results
- Natural language query: `POST /versions/{v}/query/natural` translates "find all orders over $100" to a filter query; shows the generated query for transparency
- Saved queries: `POST /queries` stores query definition; `POST /queries/{id}/execute` runs it with optional parameter overrides
- Query execution history: last 50 queries per user logged with timing and row count

**Tech Stack:** PostgreSQL dynamic query builder (asyncpg); EXPLAIN ANALYZE for query plan; Radix UI filter builder

Part of Epic: Relationships, Search & Query

---

#### 2.5 (#2192) — Natural Language Query Interface

Natural language queries translate plain English user input into structured query DSL and SQL. The system uses an LLM provider (OpenAI, Anthropic, or local Ollama) with schema-aware prompting: the class names, property names, and data types from the schema capture are included in the system prompt to ground the translation.

**Query intent recognition:** Detect query type (retrieval, aggregation, comparison, trend), extract target class names from context, parse filter conditions (dates as "last week / yesterday / Q4", numeric comparisons, negations), and understand relationship traversal ("find all orders for customer X"). **Suggestions & autocomplete:** Suggest queries based on schema structure (e.g., "Show all Customers created this week"), autocomplete class and property names, show example queries per class, display recent and popular queries. **Safety:** Generated SQL is parameterized (no injection); max result limit enforced; queries run against read-only replica.

**Acceptance Criteria:**
- `POST /query/natural` accepts `{ query: "Find all orders over $100 created this month" }` and returns both the translated structured query and the results
- Translation shows the generated query definition for user review before executing ("Here's what I understood…")
- Ambiguous queries trigger a clarification response ("Did you mean Customer or ClientAccount?")
- All generated queries are parameterized; SQL injection is impossible through the translation layer
- Query results capped at 1,000 rows by default; max configurable per tenant up to 10,000
- LLM provider is configurable per tenant; local Ollama endpoint supported for data-sovereignty tenants

**Tech Stack:** OpenAI/Anthropic/Ollama API; schema-aware prompt engineering; parameterized asyncpg; read replica routing

Part of Epic: Relationships, Search & Query

---

#### 2.6 (#2193) — Query Security & Governance

**Row-level security (RLS):** PostgreSQL RLS policies enforce tenant isolation on all queries automatically. Cross-tenant query prevention is tested in CI. **Column masking:** Sensitive fields (configurable per class, e.g., SSN, credit card) are masked in query results for users without the `data:sensitive` permission; masked values are replaced with `[REDACTED]`. **Query policies:** Maximum execution time per tenant tier (default 30s, Enterprise: 120s); maximum result set size; rate limiting (requests per minute per API key); blocked query patterns (e.g., queries without any filter on large tables); required filters for large classes (configurable). **Audit log:** All query executions logged with: user/API key, query hash, class accessed, row count returned, execution time, timestamp. Query audit log queryable via Detective API.

**Acceptance Criteria:**
- RLS policies verified in integration tests: API key from tenant A cannot retrieve data from tenant B (returns 0 results, not an error)
- Column masking: configurable per-class via `POST /classes/{id}/field-policies` with `{ field: "ssn", mask: true, visible_to: ["data:sensitive"] }`
- Query timeout: queries exceeding the tenant timeout limit are cancelled and return 408 with the timeout value
- Required filter: classes with `required_filter=true` in their policy reject queries without at least one JSONB filter
- Query audit: `GET /audit/query-log?since=&class_id=` returns paginated query log entries for users with `detective:read`
- Sensitive field masking is applied after RLS and before result serialization; masked field values never appear in logs

**Tech Stack:** PostgreSQL RLS; asyncpg; query policy middleware; audit log table (append-only)

Part of Epic: Relationships, Search & Query

---

## Epic 3 (#2194): History, Integrity & Performance

### Summary Table

| #   | Title                          | Description                                                                                              | Labels                                         | MVP | Parallel |
|-----|--------------------------------|----------------------------------------------------------------------------------------------------------|------------------------------------------------|-----|----------|
| 3.1 (#2195) | Instance History API           | Paginated event history; point-in-time reconstruction; version range queries; state at timestamp         | `enhancement`, `mvp`, `database`, `rest`       | Yes | No       |
| 3.2 (#2196) | Audit Trail & Compliance       | Append-only audit log; GDPR reports; compliance exports; retention policies; anomaly detection           | `enhancement`, `database`, `rest`              | No  | Yes      |
| 3.3 (#2197) | Transaction Management         | ACID compliance; savepoints; deadlock retry; distributed transaction coordination                        | `enhancement`, `mvp`, `database`               | Yes | Yes      |
| 3.4 (#2198) | Referential Integrity          | Validate links reference active instances; orphan detection; scheduled integrity check jobs              | `enhancement`, `database`                      | No  | Yes      |
| 3.5 (#2199) | Performance & Indexing         | Automatic index management; JSONB path indexes; query analysis; Redis snapshot cache; snapshot maintenance| `enhancement`, `database`                      | No  | Yes      |
| 3.6 (#2200) | Time-Audited Queries           | As-of timestamp queries; version-specific queries; change event queries; bi-temporal support; time travel UI | `enhancement`, `database`, `rest`          | No  | Yes      |
| 3.7 (#2201) | Time-Series Queries & Background Processing | Background async time-series query engine; checkpoint caching; parallel reconstruction; scheduled queries | `enhancement`, `database`, `rest`  | No  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#2195) — Instance History API

The instance history API exposes the full event log for a given instance with rich filtering and optional state reconstruction. It is the primary data source for the Detective panel (Detective Epic 4.1) and supports compliance workflows.

**Endpoints:** `GET /instances/{id}/history` returns all `instance_data` events, newest first, with cursor-based pagination. Filters: `?actor_id=`, `?action=CREATE|UPDATE|DELETE`, `?path=/field/path` (events touching a specific JSON Pointer path), `?since=`, `?until=`. `GET /instances/{id}/history/{version}` returns the specific event for that version (full data for CREATE, delta for UPDATE). `GET /instances/{id}/history/at?timestamp=` reconstructs and returns the instance state at a specific ISO 8601 timestamp by replaying all events up to that moment. `GET /instances/{id}/history/range?from={v1}&to={v2}` returns all events in a version range.

**Acceptance Criteria:**
- History API returns events in reverse-chronological order (newest first); cursor-based pagination
- `include_diff=true` query parameter computes a field-level diff for each UPDATE event; adds ≤100ms to response
- Point-in-time reconstruction (`/at?timestamp=`): replays events up to the given timestamp; handles schema version changes by returning the raw data without re-validating against a potentially incompatible new schema
- Path filter (`?path=/billing/amount`): uses the `changed_paths` GIN index from 1.4 for fast filtering
- Response includes: `event_id`, `version`, `action`, `actor_display`, `occurred_at`, `changed_paths` (for UPDATE), and optionally `diff`
- Benchmark: 1,000-version history paginated at 50/page returns first page in <50ms

**Tech Stack:** PostgreSQL; asyncpg; JSON event replay for point-in-time; `changed_paths` GIN index

Part of Epic: History, Integrity & Performance

---

#### 3.2 (#2196) — Audit Trail & Compliance

A comprehensive audit log captures all data operations with full context: user identification, API key, session token hash, client IP (hashed for GDPR), operation type, timestamp, before/after values, and query context. The log is append-only (INSERT-only PostgreSQL role; see Detective Epic 1.3 for architecture).

**GDPR compliance:** Data access reports list all instances and events associated with a specific data subject (identified by a field value, e.g., `email`). Right-to-erasure verification confirms data has been purged. **Compliance exports:** Filter audit log by date range, user, operation type; export as CSV or JSON with tamper-evident checksum (aligns with Detective Epic 5.3). **Retention policies:** Configurable retention periods per tenant tier; partitioned tables enable efficient partition-level archival to S3 before purge. **Anomaly detection:** Rule-based heuristics flag unusual access patterns (high-volume reads, off-hours deletes) — this complements Detective Epic 5.2.

**Acceptance Criteria:**
- All CREATE/UPDATE/DELETE/BULK/QUERY operations produce an audit log entry within the same transaction
- Audit log table is INSERT-only at the application DB role level; integrity verified by integration test
- GDPR report: `POST /audit/gdpr-report` with `{ subject_field: "email", subject_value: "user@example.com" }` returns all data and events
- Right-to-erasure: `POST /audit/erasure-verification` confirms all data for a subject has been purged or pseudonymized
- Compliance export: `POST /audit/export` with time range and filters; async job produces signed download URL
- Anomaly detection: configurable thresholds; anomaly events surfaced in Detective UI

**Tech Stack:** PostgreSQL partitioned audit table; asyncpg; S3-compatible archival; Detective integration

Part of Epic: History, Integrity & Performance

---

#### 3.3 (#2197) — Transaction Management

All data operations must meet ACID guarantees. This issue formalizes transaction management across the storage engine, including savepoint support for complex multi-step operations, automatic rollback on validation failures, deadlock detection and retry, and transaction timeout configuration.

For distributed scenarios (e.g., writing to both PostgreSQL and Redis cache in a single logical operation), the system follows a two-phase commit pattern where PostgreSQL is always the authoritative source: PostgreSQL commits first, then cache is updated. If cache update fails, a background job reconciles by re-reading from PostgreSQL.

**Acceptance Criteria:**
- All single-instance operations (CREATE, UPDATE, DELETE) run in a single PostgreSQL transaction; any failure rolls back all changes
- Bulk operations use PostgreSQL savepoints: each batch of 1,000 rows uses a savepoint; failure rolls back the current batch without affecting prior batches (in partial-success mode)
- Deadlock detection: asyncpg catches `DeadlockDetected` errors and retries up to 3 times with 50ms jitter
- Transaction timeout: configurable per tenant (default 30s); long-running transactions are cancelled and return 408
- Cache consistency: Redis snapshot cache is updated after successful PostgreSQL commit; cache update failures trigger an async reconciliation job
- Integration tests verify ACID properties: concurrent conflicting writes, validation failures mid-transaction, rollback on cache failure

**Tech Stack:** PostgreSQL ACID transactions; asyncpg savepoints; exponential backoff retry; Redis cache reconciliation

Part of Epic: History, Integrity & Performance

---

#### 3.4 (#2198) — Referential Integrity

While PostgreSQL foreign keys enforce basic referential integrity within a table, Apiome's data model links instances across schema classes stored in JSONB. Application-level referential integrity ensures: link records reference only existing active instances, linked instances cannot be deleted without addressing their links (configurable per `link_def.cascade_behavior`), and orphaned link records (links whose instance has been deleted) are detected and cleaned up.

Scheduled integrity check jobs run off-peak and emit reports listing: orphaned links (link references a deleted instance), violated cardinality constraints (more links than allowed by `link_def.cardinality`), and dangling `$ref` values in instance data (a `$ref` field pointing to a non-existent instance ID). Repair tools expose APIs to clean up detected violations.

**Acceptance Criteria:**
- `POST /links` validates both instances are active before inserting; returns 422 with specific error if either is deleted
- Cascade delete: when an instance with `cascade` links is soft-deleted, linked instances are also soft-deleted in the same transaction
- Restrict delete: when an instance is targeted by a `restrict` link, `DELETE /instances/{id}` returns 409 with a list of blocking links
- Integrity check job: runs every night off-peak; result stored in `integrity_check_results` table; accessible via `GET /integrity-checks/latest`
- Repair API: `POST /integrity-checks/repair` with `{ orphan_links: true }` removes orphaned links and emits an audit event
- Dashboard: integrity check results surfaced in the database management UI with count of each violation type

**Tech Stack:** PostgreSQL; asyncpg; scheduled Celery task; integrity check results table

Part of Epic: History, Integrity & Performance

---

#### 3.5 (#2199) — Performance & Indexing

**Automatic index management:** Analyze query patterns (slow query log) and suggest indexes; auto-create indexes for common JSONB path queries when traffic warrants; monitor index usage and flag unused indexes for cleanup. UI for configuring indexed JSONB paths per class. **JSONB path indexes:** Expression indexes on specific JSON paths (e.g., `((current_data->>'email'))` for email-based queries); index impact analysis before creation; index maintenance scheduling during low-traffic windows.

**Query optimization:** EXPLAIN ANALYZE integration in the query API (`?explain=true`); query plan caching; automatic query rewriting for performance (e.g., pushing filters before joins); read replica routing for read queries; connection pooling with PgBouncer. **Redis snapshot cache:** Cache `instance_snapshot` by `(tenant_id, instance_id)` with configurable TTL per class; write-through on UPDATE; invalidation on DELETE; cache warming for frequently accessed snapshots; Redis Cluster support. **Snapshot maintenance:** Periodic consistency checks (aligns with Detective Epic 5.1); rebuild corrupted snapshots from event log; snapshot compression for large JSONB objects; archive old deactivated snapshots to cold storage.

**Acceptance Criteria:**
- Slow query log: queries exceeding 100ms are logged with EXPLAIN output; accessible via `GET /performance/slow-queries`
- Index suggestion: after analyzing slow query log, `GET /performance/index-suggestions` returns ranked index recommendations
- Redis cache: `GET /instances/{id}` checks Redis before PostgreSQL; cache hit rate metric exposed at `GET /metrics/cache-hit-rate`
- Read replica routing: all `GET /instances`, `GET /snapshots`, and `POST /query` requests route to the read replica; writes always go to primary
- Snapshot consistency check: weekly job comparing snapshot against event replay for sample of instances; mismatches emitted as Detective alerts
- Connection pool: PgBouncer with `pool_mode=transaction`; pool size tuned to 10 connections per worker process

**Tech Stack:** PostgreSQL EXPLAIN ANALYZE; PgBouncer; Redis Cluster; expression indexes; asyncpg; Celery

Part of Epic: History, Integrity & Performance

---

#### 3.6 (#2200) — Time-Audited Queries (Historical Data Access)

Time-audited queries allow users to query data as it existed at any historical point. They extend the ad-hoc query builder (Epic 2.4) with temporal filter controls and build on the event reconstruction capability from Epic 3.1.

**As-of timestamp queries:** Query all instances of a class as of a specific timestamp — reconstruct each instance's state from its event log up to that moment. Date picker UI in the query builder for AS-OF selection. **Version-specific queries:** Browse instance version history within a query; select version range for analysis; aggregate across version history. **Change event queries:** Query specific action types (CREATE/UPDATE/DELETE), filter by actor, find all changes to specific JSON Pointer paths, identify bulk operations. **Historical range analysis:** Count changes per time period, identify high-change instances, detect change patterns. **Bi-temporal support:** Distinguish valid time (when data was true) vs transaction time (when it was recorded); combined bi-temporal queries; temporal aggregations (moving averages, period-over-period comparisons). **Time travel UI:** Visual timeline navigation with scrubbing; play/pause animation of data changes; visual diff between time points.

**Acceptance Criteria:**
- `POST /query` with `{ "as_of": "2026-01-15T00:00:00Z" }` reconstructs all instances as of that timestamp
- AS-OF query performance: reconstruction for 1,000 instances each with ≤50 events completes in <10 seconds
- Change event query: `{ "action": "DELETE", "since": "2026-01-01", "actor_id": "..." }` returns all matching tombstone events
- Bi-temporal: instance create/update/delete operations accept optional `valid_time_start` and `valid_time_end` fields; queries can filter by both valid time and transaction time
- Time travel UI: timeline scrubber shows snapshot data at each second-granularity position; plays at 10x real time

**Tech Stack:** PostgreSQL event replay; temporal tables (if using PostgreSQL 16); asyncpg; React timeline component

Part of Epic: History, Integrity & Performance

---

#### 3.7 (#2201) — Time-Series Queries & Background Processing

Time-series queries reconstruct instance states at multiple time buckets across a range (e.g., daily instance counts or hourly average values over a month). These are computationally expensive and must run as background jobs with progress tracking, cost estimation, and result caching.

**Query definition:** Start/end timestamps, time granularity (minute/hour/day/week/month), target schema classes, aggregation functions per time bucket, configurable sampling for large datasets, sliding window parameters. **State reconstruction:** Apply event sequence (CREATE→UPDATE→DELETE) chronologically per bucket boundary; handle delta/patch application; track lifecycle across time range. **Cost estimation:** Estimate completion time based on instance count × event density before execution; display estimate to user with confidence interval. **Background processing:** Async submission returning request ID; dedicated worker pool; progress monitoring (percent complete, current processing timestamp, events/second); checkpoint/resume for long-running jobs. **Result storage:** Persist completed results with configurable TTL; paginated retrieval; streaming download; scheduled recurring queries with dependency chains. **Reconstruction caching:** Cache reconstructed states at checkpoint intervals (every 10,000 events); reuse cached states for overlapping queries; LRU eviction; parallel reconstruction across instances.

**Acceptance Criteria:**
- `POST /queries/time-series` submits a time-series query; returns `{ request_id, estimated_duration_seconds }` within 2 seconds
- Cost estimation within ±30% of actual duration for 80% of queries based on historical performance data
- Progress stream: `GET /queries/{request_id}/progress` returns `{ percent_complete, events_processed, current_bucket, estimated_remaining_s }`
- Checkpoint resume: if a worker fails mid-query, the job resumes from the last checkpoint; no double-processing
- Result retrieval: `GET /queries/{request_id}/result` returns paginated time-bucket rows; `?format=csv` returns CSV download
- Scheduled time-series: `POST /batch/schedules` with `job_type=time_series` and cron; results emailed or pushed to webhook on completion
- Parallel reconstruction: 100-instance 30-day time-series query on daily granularity completes in <60 seconds

**Tech Stack:** Celery workers; PostgreSQL checkpoint table; reconstruction caching in Redis; asyncpg; SSE progress

Part of Epic: History, Integrity & Performance

---

## Epic 4 (#2202): API Surface & Multi-Tenancy

### Summary Table

| #   | Title                          | Description                                                                                           | Labels                                           | MVP | Parallel |
|-----|--------------------------------|-------------------------------------------------------------------------------------------------------|--------------------------------------------------|-----|----------|
| 4.1 (#2203) | API Key Authentication         | Per-tenant API keys: scopes, expiration, rotation, revocation, usage tracking, breach notification    | `enhancement`, `mvp`, `database`, `rest`         | Yes | No       |
| 4.2 (#2204) | REST API Standards             | Consistent response format, pagination (cursor + offset), filtering/sorting syntax, HTTP status codes | `enhancement`, `mvp`, `database`, `rest`         | Yes | Yes      |
| 4.3 (#2205) | OpenAPI Documentation & SDKs   | Auto-generated OpenAPI 3.1 spec; Swagger UI + ReDoc; Python SDK with ORM-like interface              | `enhancement`, `database`, `rest`                | No  | Yes      |
| 4.4 (#2206) | Multi-Tenancy & Isolation       | PostgreSQL RLS; row-level security policies; resource quotas; tenant-based table partitioning        | `enhancement`, `mvp`, `database`                 | Yes | Yes      |
| 4.5 (#2207) | Monitoring & Observability      | Operational metrics; health checks; structured logging; Prometheus; ELK/Datadog integration          | `enhancement`, `database`                        | No  | Yes      |

### Detailed Issue Descriptions

#### 4.1 (#2203) — API Key Authentication

API keys are the primary authentication mechanism for programmatic access to the database offering. Keys are generated per tenant, scoped to specific access levels, and stored as hashed values (bcrypt or PBKDF2). Each key has a configurable expiration date, optional IP allowlist, and version-scoped access control.

**Key lifecycle:** Generate (returns the plaintext key once; never retrievable again), rotate (generate a new key atomically; old key remains valid for a configurable grace period), revoke (immediate invalidation), and list (show all keys for the tenant with metadata but not plaintext). **Scopes:** `read` (GET operations), `write` (CREATE/UPDATE), `delete` (DELETE/restore), `admin` (schema operations, batch job management, bulk deletes). **Version-scoped access:** Keys can be restricted to specific `version_id`(s); wildcard access (`*`) grants access to all versions. **Security:** Rate limiting per key; usage tracking (requests/day, last used timestamp); suspicious activity detection (IP change, unusual volume); breach notification webhook.

**Acceptance Criteria:**
- `POST /api-keys` generates a key and returns the plaintext once; subsequent `GET /api-keys/{id}` returns only metadata and masked suffix
- Keys are stored as PBKDF2-hashed values with salt; plaintext is never stored
- `X-API-Key` header is the authentication mechanism; `Authorization: Bearer` as alternative
- Scope enforcement: write-scoped key attempting DELETE returns 403 with scope explanation
- Key rotation: `POST /api-keys/{id}/rotate` creates a new key and starts a 24-hour grace period for the old key
- Usage analytics: `GET /api-keys/{id}/usage?since=&granularity=day` returns daily request counts by endpoint

**Tech Stack:** PBKDF2 key storage; PostgreSQL; FastAPI middleware; rate limiter (Redis token bucket)

Part of Epic: API Surface & Multi-Tenancy

---

#### 4.2 (#2204) — REST API Standards

Consistent API conventions across all database endpoints reduce integration friction and enable generic client tooling.

**Response format:** All responses: `{ "success": true, "data": {...}, "meta": {...} }`. Errors: `{ "success": false, "error": { "code": "VALIDATION_ERROR", "message": "...", "details": [{...}] } }`. **Pagination:** Cursor-based (`cursor`, `limit` max 100; response includes `next_cursor`, `has_more`) as the default for all list endpoints. Offset-based (`page`, `limit`) as an alternative. **Filtering:** `?filter[field][op]=value` syntax; operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `starts_with`, `in`, `not_in`. JSONB path filtering: `?filter[data.address.city][eq]=Seattle`. **Sorting:** `?sort=field:asc,field2:desc`; multiple sort keys. **HTTP status codes:** Standardized across all endpoints (200 OK, 201 Created, 204 No Content, 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 409 Conflict, 422 Unprocessable Entity, 429 Too Many Requests, 500 Internal Server Error).

**Acceptance Criteria:**
- All list endpoints support both cursor-based and offset-based pagination
- Filter syntax: `?filter[data.email][contains]=@acme.com` correctly filters JSONB field
- All 422 responses include a `details` array with JSON Pointer paths for invalid fields
- Consistent `X-Request-Id` response header on every response for support tracing
- Rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` on all responses
- OpenAPI 3.1 spec includes examples for every filter/sort/pagination combination

**Tech Stack:** FastAPI; asyncpg; Pydantic response models; OpenAPI 3.1 examples

Part of Epic: API Surface & Multi-Tenancy

---

#### 4.3 (#2205) — OpenAPI Documentation & SDKs

Auto-generated OpenAPI 3.1 specification covering all database API endpoints, updated in CI on every merge. Swagger UI and ReDoc embedded in the product at `/api/v1/docs` and `/api/v1/redoc`. Code samples in Python, JavaScript/TypeScript, and cURL for each endpoint.

**Python SDK:** Pythonic client library for all database operations. Async/await support (asyncio). Connection pooling. Automatic retry with exponential backoff. Type hints for IDE IntelliSense. ORM-like interface: class-based model definitions generated from schema captures; lazy loading for linked instances; query builder with method chaining (`.filter(status="active").sort("created_at").limit(50).execute()`); automatic validation before save; change tracking (dirty fields); relationship traversal helpers.

**Acceptance Criteria:**
- OpenAPI 3.1 spec is auto-generated from FastAPI route definitions; CI fails if spec is outdated
- Spec includes all request/response schemas, error schemas, authentication requirements, and examples
- Python SDK: `pip install apiome-db` installs the client; `from apiome_db import Instance` imports the base class
- ORM interface: `Order.filter(data__total__gte=100).sort("-created_at").execute()` returns a list of `Order` instances
- Async: all SDK methods have both sync and async variants (`instance.save()` and `await instance.save_async()`)
- SDK ships with Jupyter notebook examples demonstrating common workflows

**Tech Stack:** FastAPI auto-generation; openapi-generator-cli for SDK; Pydantic; pytest for SDK tests

Part of Epic: API Surface & Multi-Tenancy

---

#### 4.4 (#2206) — Multi-Tenancy & Isolation

PostgreSQL Row-Level Security (RLS) enforces tenant isolation at the database level, ensuring that even if application-level filtering is bypassed, tenant A cannot read tenant B's data. RLS policies are applied to all data tables (`instance`, `instance_data`, `instance_snapshot`, `link`, `audit_log`).

**Resource quotas:** Instance count limits, storage size limits, and API rate limits configurable per tenant tier. Quota usage monitoring and dashboard. Quota exceeded notifications (email + in-app) and upgrade workflow. **Data partitioning:** Large tables (`instance_data`, `audit_log`) partitioned by `tenant_id` and `created_at` for query performance and partition-level data migration. Automatic partition creation. Tenant data migration tools for moving tenants between database clusters. **Tenant impersonation:** Support admins can impersonate a tenant for troubleshooting (audited access; limited to read-only).

**Acceptance Criteria:**
- RLS policies: `SET LOCAL app.current_tenant_id = '{tenant_id}'` in every connection; all queries automatically scoped
- Integration test: API key from tenant A cannot retrieve data from tenant B even with direct SQL injection attempts in filter values
- Quota enforcement: when a tenant exceeds their instance count limit, `POST /instances` returns 402 with a quota exceeded message and upgrade link
- Partition pruning: `EXPLAIN` output for a tenant-scoped query shows partition pruning (only the tenant's partition is scanned)
- Tenant impersonation: `POST /admin/impersonate/{tenant_id}` creates a time-limited (30min) impersonation session; all actions during the session are logged with the admin actor

**Tech Stack:** PostgreSQL RLS; table partitioning; asyncpg connection pool with tenant context; quota enforcement middleware

Part of Epic: API Surface & Multi-Tenancy

---

#### 4.5 (#2207) — Monitoring & Observability

**Operational metrics:** Prometheus-compatible metrics endpoint at `/metrics`: instance counts by class and tenant, operation rates (create/update/delete per second), query latency percentiles (p50/p95/p99), error rates by operation type, storage usage trends, active connection counts. **Health checks:** `/health` endpoint with checks for: database connectivity, schema validation service, snapshot consistency, replication lag (if read replica), disk space, and connection pool exhaustion. **Structured logging:** JSON-formatted log entries at all log levels with correlation IDs, sensitive data masking, log aggregation integration (ELK stack, Datadog, Grafana Loki), configurable retention policies.

**Acceptance Criteria:**
- Prometheus endpoint `/metrics` returns all documented metrics in Prometheus text format
- `GET /health` returns 200 with `{ status: "healthy", checks: { db: "ok", validation: "ok", ... } }` or 503 if any check fails
- All API logs include `correlation_id`, `tenant_id`, `request_duration_ms`, and `operation_type`; no plaintext API key values in logs
- Datadog integration: sending logs to Datadog via the Datadog agent is documented and tested; metric dashboards are provided
- Alert rules: Prometheus alerting rules provided for `error_rate > 1%`, `p99_latency > 500ms`, `disk_usage > 80%`, `replication_lag > 30s`

**Tech Stack:** Prometheus client (Python); structlog; OpenTelemetry tracing; ELK/Datadog integration docs

Part of Epic: API Surface & Multi-Tenancy

---

## Epic 5 (#2208): Visual Tools (Query Builder, Relationship Graphs)

### Summary Table

| #   | Title                            | Description                                                                                           | Labels                                        | MVP | Parallel |
|-----|----------------------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------------|-----|----------|
| 5.1 (#2209) | Relationship Graph Visualization | Schema-level graph: classes as nodes, $ref as edges; cardinality labels; interactive zoom/pan/filter  | `enhancement`, `database`                     | No  | No       |
| 5.2 (#2210) | Instance Data Graphs             | Data volume per class; link distribution (edge thickness by count); orphan/hub detection; Sankey flow | `enhancement`, `database`                     | No  | Yes      |
| 5.3 (#2211) | Visual Query Builder UI          | Drag-and-drop query construction; filter/join/aggregation builder; results viewer with inline editing  | `enhancement`, `database`                     | No  | Yes      |
| 5.4 (#2212) | Time Travel UI                   | Visual timeline scrubber; snapshot animation; diff between time points; bi-temporal controls           | `enhancement`, `database`                     | No  | Yes      |
| 5.5 (#2213) | Query Results & Visualization    | Tabular results viewer; chart types (bar/line/pie/scatter/heatmap); pivot table; export; dashboard pin | `enhancement`, `database`                     | No  | Yes      |
| 5.6 (#2214) | Graph Export & Sharing           | PNG/SVG/PDF/GraphML/Mermaid export; shareable graph URLs; collaborative annotations; version permalinks| `enhancement`, `database`, `rest`             | No  | Yes      |

### Detailed Issue Descriptions

#### 5.1 (#2209) — Relationship Graph Visualization

The schema-level graph visualizes all schema classes as nodes in a force-directed canvas (React Flow), with `$ref` relationships shown as directed edges. This gives architects an at-a-glance overview of the data model's structure and relationship density.

**Node design:** Each class node shows the class name, instance count (from snapshot table), and schema version. Node size is proportional to instance count (log scale). **Edge design:** Directed arrows with cardinality labels (1, N, M:N); edge thickness proportional to link count between classes. **Depth control:** Multi-level depth slider (1–3+ hops); visual distinction between depth levels via opacity gradient; collapse/expand per node. **Interactive controls:** Click to view class schema detail drawer; hover to highlight connected relationships; filter by class name or relationship type; multi-select for path analysis. **Layout algorithms:** Force-directed (organic), hierarchical (tree-like), circular (hub-and-spoke), grid; user-adjustable parameters; save layout preferences per user.

**Acceptance Criteria:**
- Graph renders all classes from the schema capture as nodes; edges from link definitions
- Instance count shown as node label; updates in real-time as data changes (polling every 30s)
- Depth slider 1–3: depth 1 shows only direct neighbors of the selected class; depth 2 shows neighbors-of-neighbors
- Click node → drawer shows class name, property count, instance count, top 5 properties by type
- Graph export: `GET /versions/{v}/relationship-graph?format=graphml` returns GraphML; `?format=mermaid` returns Mermaid syntax
- Filter by relationship type: toggle to show/hide specific `link_def` types from the graph

**Tech Stack:** React Flow; D3.js force layout; Radix UI drawer; GraphML/Mermaid exporters

Part of Epic: Visual Tools

---

#### 5.2 (#2210) — Instance Data Graphs

Instance data graphs extend the schema-level view (Epic 5.1) with runtime data dimensions: actual instance counts, link volumes, and data density heat maps. This helps operators identify data hotspots, orphaned instances, and over-connected hub instances.

**Data volume visualization:** Node size proportional to instance count with trend indicators (growing/stable/declining arrows). Compare counts across schema captures. Time-based animation of data growth. **Link distribution view:** Edge thickness proportional to actual link count between class pairs; hover shows count and avg links per instance; click to drill down to individual links. **Orphan and hub detection:** Highlight instances with zero links (orphans) and instances with unusually high link counts (hubs) — surface in a side panel with instance IDs. **Sankey diagram:** Flow width proportional to link counts; bi-directional; interactive filtering by source/target class. **Graph analytics:** Relationship statistics (total count by type, avg per instance, most/least connected); graph metrics dashboard (degree distribution, clustering coefficient, path length); anomaly highlighting.

**Acceptance Criteria:**
- Data volume graph: node sizes reflect actual instance counts (queried live from snapshot table); updates on page load
- Link distribution: edge thickness reflects link count; hover tooltip shows count and "avg X links/instance"
- Orphan detection: "Find Orphans" button returns list of instance IDs with zero links; accessible via `GET /instances?filter[link_count][eq]=0`
- Hub detection: "Find Hubs" button returns instances with link count >2 standard deviations above the class mean
- Sankey diagram: toggleable from the graph toolbar; shows top 10 link flows by volume
- Graph metrics dashboard: shows degree distribution as histogram chart and graph density as a percentage

**Tech Stack:** React Flow; D3.js Sankey; statistical aggregation queries; Recharts for metrics dashboard

Part of Epic: Visual Tools

---

#### 5.3 (#2211) — Visual Query Builder UI

The visual query builder is a canvas-based interface for constructing queries without writing code. Users drag schema class nodes onto the canvas, connect them via their link relationships, configure filters per class, and specify output fields and aggregations.

**Canvas:** Drag schema classes from a sidebar onto the canvas; connect classes via their link relationships (edges auto-suggest from link definitions); configure join type per edge (inner/left); preview the effective SQL before execution. **Filter builder:** Visual condition editor per node: comparison operators, string operators, array operators, null checks, date pickers, numeric sliders; AND/OR logic with nested groups; save filter presets for reuse. **Aggregation builder:** GROUP BY with field selection; aggregation function selector (COUNT/SUM/AVG/MIN/MAX); HAVING clause builder; window functions; pivot table configuration. **Results viewer:** Sortable/filterable results table; column resizing and reordering; freeze columns; cell-level JSONB expansion; inline editing (with write scope); copy cell/row/table. **Query controls:** Execute with progress indicator; cancel; explain plan viewer; execution history; performance metrics per query.

**Acceptance Criteria:**
- Visual query builder accessible from the database offering navigation; opens as a full-page canvas
- Dragging a class node onto the canvas automatically renders its properties in a filter sidebar
- Connecting two class nodes via a link edge automatically configures the join using the matching `link_def`
- Filter builder: all documented operators available; invalid filter combinations show inline validation error
- Execute: runs the query and renders results in the table viewer below the canvas; shows row count and execution time
- EXPLAIN: "Explain" button renders the query plan as a readable tree structure

**Tech Stack:** React Flow (query canvas); TanStack Table (results viewer); PostgreSQL EXPLAIN; Radix UI filter controls

Part of Epic: Visual Tools

---

#### 5.4 (#2212) — Time Travel UI

The time travel UI extends the visual query builder with temporal controls, allowing users to scrub through time and observe how data changed.

**Timeline scrubber:** A horizontal timeline spanning the selected date range with a draggable cursor. Moving the cursor updates the query results to show the reconstructed state at that timestamp. **Snapshot animation:** Play button animates the cursor from start to end at configurable speed (1×, 2×, 5×, 10× time acceleration). Pause at any point. **Diff between time points:** Select two timestamps by holding Shift+click; the results viewer switches to diff mode showing added (green), removed (red), and changed (yellow) rows between the two points. **Bookmarks:** Mark significant timestamps on the timeline (e.g., "after migration", "before incident"). Annotations and timeline markers. **Historical query builder:** Extends the filter builder with `AS OF` timestamp selector, `BETWEEN` clause for version ranges, and version selector integration.

**Acceptance Criteria:**
- Timeline scrubber: dragging cursor updates query results within 2 seconds for up to 1,000 instances
- Diff mode: when two timestamps are selected, the results table shows row-level add/remove/change status
- Play animation: results update smoothly at ≥2 frames per second in 10× mode for up to 100-instance queries
- Bookmarks: user can add a named bookmark at the current cursor position; bookmarks persist in user preferences
- `AS OF` filter: available in both visual builder and API; generates correct PostgreSQL event replay query

**Tech Stack:** React timeline component; React Flow temporal extension; event reconstruction API (Epic 3.6)

Part of Epic: Visual Tools

---

#### 5.5 (#2213) — Query Results & Visualization

**Results viewer:** TanStack Table with sortable/filterable columns, column resizing and reordering, freeze columns, virtual scroll for large result sets (>1,000 rows), cell-level JSONB inspection (click to expand nested object), inline editing with write permission confirmation, copy cell/row/table as JSON or CSV. **Results visualization:** Auto-suggest visualizations based on detected data types (date column + numeric column → line chart); chart types: bar, line, pie, scatter, heatmap, pivot table; multiple visualizations pinnable side-by-side; summary statistics cards (count, min/max/avg/p50/p95 for numeric fields). **Export:** CSV, JSON, JSONL, Excel, Parquet; streaming large exports (no memory limit); scheduled recurring exports; secure download links with expiry.

**Acceptance Criteria:**
- Results table renders up to 10,000 rows with virtual scroll; no rendering lag >200ms for row navigation
- Auto-suggest: when results contain a timestamp column and a numeric column, a line chart is auto-suggested
- All 6 chart types render correctly; each chart is interactive (hover for values, click to drill down)
- Dashboard pin: "Pin to Dashboard" button saves the query and visualization to the tenant's data dashboard (see Analytics roadmap)
- Export: `POST /query/export` initiates an async export; returns job_id; `?format=parquet` produces Parquet with correct schema
- Scheduled export: `POST /batch/schedules` with `job_type=query_export` and a saved query ID; runs on cron schedule

**Tech Stack:** TanStack Table; Recharts; PyArrow (Parquet); async export job; S3 download link

Part of Epic: Visual Tools

---

#### 5.6 (#2214) — Graph Export & Sharing

**Export formats:** PNG/SVG/PDF (2x resolution; handles hidden; 40px padding), GraphML (compatible with yEd, Gephi), GEXF (for Gephi temporal graphs), JSON graph data (nodes and edges as arrays), Mermaid diagram syntax (entity-relationship style). Configurable export resolution and metadata inclusion. **Shareable graph views:** Generate shareable URLs to specific graph views (with zoom level, selected nodes, and filter state encoded in the URL); embed graphs in external documentation (iframe embed code); version-specific graph permalinks. **Collaborative annotations:** Add text annotations to graph nodes and edges; share annotations with team members per RBAC; annotations persist per version.

**Acceptance Criteria:**
- PNG export: 2x resolution, transparent background option, anti-aliased edges; generates in <5 seconds for up to 100-node graphs
- GraphML export: valid GraphML 1.1; importable into yEd without errors
- Mermaid export: `GET /relationship-graph?format=mermaid` returns valid Mermaid `erDiagram` or `graph TD` syntax
- Shareable URL: encodes view state in base64 URL query parameter; loads the same graph view on re-open
- Annotations: `POST /relationship-graph/annotations` with `{ class_id, text, position }` stores annotation; visible to all project members

**Tech Stack:** html-to-image; GraphML generator; Mermaid syntax generator; URL state encoding

Part of Epic: Visual Tools

---

## Epic 6 (#2215): AI/Vector Features & Enterprise Offloading

### Summary Table

| #   | Title                              | Description                                                                                             | Labels                                        | MVP | Parallel |
|-----|------------------------------------|---------------------------------------------------------------------------------------------------------|-----------------------------------------------|-----|----------|
| 6.1 (#2216) | Vector Embedding Generation        | Auto-embed on CREATE/UPDATE; multiple models; batch embedding for imports; versioning; cost tracking     | `enhancement`, `database`                     | No  | No       |
| 6.2 (#2217) | Semantic Similarity Search         | KNN via pgvector; cosine/Euclidean/inner product; hybrid text+vector; configurable thresholds           | `enhancement`, `database`, `rest`             | No  | Yes      |
| 6.3 (#2218) | Cross-Class Semantic Linking       | Discover relationships via embedding similarity; auto-link suggestions; semantic clustering; outlier detection | `enhancement`, `database`                | No  | Yes      |
| 6.4 (#2219) | AI-Powered Data Discovery          | NL data search; intelligent classification; duplicate detection; AI-assisted entry; RAG interface        | `enhancement`, `database`                     | No  | Yes      |
| 6.5 (#2220) | Enterprise Delta Offloading (MongoDB) | Sync instance_data deltas to MongoDB; CDC pipeline; compound indexes; sharding by tenant_id         | `enhancement`, `database`                     | No  | No       |
| 6.6 (#2221) | Redis Snapshot Caching             | Write-through Redis cache for instance_snapshot; delta sequence caching; query result caching; TTL      | `enhancement`, `database`                     | No  | Yes      |
| 6.7 (#2222) | Hybrid Query Execution             | Query router: Redis → MongoDB → PostgreSQL fallback; cross-store joins; consistency management          | `enhancement`, `database`                     | No  | Yes      |
| 6.8 (#2223) | Data Lifecycle Management          | Tiered storage (hot/warm/cold/archive); cross-region replication; tenant data isolation; operational tools | `enhancement`, `database`                  | No  | Yes      |

### Detailed Issue Descriptions

#### 6.1 (#2216) — Vector Embedding Generation

Vector embeddings enable semantic search and similarity features. When vector search is enabled for a schema class, every CREATE and UPDATE of an instance triggers asynchronous embedding generation: a configurable set of text fields from the instance data are concatenated, sent to the configured embedding model (OpenAI `text-embedding-3-small`, Cohere, or a locally-hosted model via Ollama), and the resulting vector is stored in a `pgvector` column on the `instance_snapshot` table.

**Configuration:** Per-class configuration specifying which fields to embed and which model to use. Multiple embedding models can be configured (e.g., different models for different field types). **Batch embedding:** Bulk imports queue embedding generation for all imported instances; a batch embedding job processes these in groups of 100. **Versioning:** When the embedding model changes, all instances must be re-embedded; an incremental re-embedding job runs in the background. **Cost tracking:** For external model APIs, track token counts and estimated cost per tenant; cost dashboard in the admin UI.

**Acceptance Criteria:**
- `POST /versions/{v}/classes/{id}/embedding-config` enables embedding for a class with `{ fields: ["name", "description"], model: "openai/text-embedding-3-small" }`
- Embedding generation: async task queued after successful instance CREATE/UPDATE; vector stored within 5 seconds for p95
- Batch embedding job: processes 1,000 instances/minute per worker on a standard compute instance
- Re-embedding job: triggered when `embedding-config` model is changed; runs off-peak; progress tracked in batch job system
- Cost tracking: `GET /admin/embedding-costs?since=&tenant_id=` returns monthly cost estimates by tenant and model
- pgvector column: `embedding vector(1536)` (dimension matches the configured model); HNSW index created automatically on column creation

**Tech Stack:** pgvector PostgreSQL extension; OpenAI/Cohere/Ollama embedding APIs; Celery async tasks; HNSW index

Part of Epic: AI/Vector Features & Enterprise Offloading

---

#### 6.2 (#2217) — Semantic Similarity Search

K-nearest neighbor (KNN) search via pgvector finds instances semantically similar to a query — by text query (embedded at search time) or by example instance (use that instance's stored embedding). Configurable distance metrics: cosine (default, best for text), Euclidean, inner product.

**Hybrid search:** Combine semantic similarity with traditional JSONB filters — e.g., "find the 10 most similar Orders to this one, but only among Orders with status=active and total>100". The hybrid query applies JSONB filters first (via index), then runs KNN on the filtered set. **Similarity scoring:** Return normalized similarity scores (0–1) alongside results; explain which fields contributed to similarity. **Real-time similarity:** As-you-type similarity suggestions in the data browser; debounced embedding of the partial query.

**Acceptance Criteria:**
- `POST /versions/{v}/search/similar` with `{ query: "enterprise customer with multiple products", class_id, k: 10 }` returns top-10 similar instances with scores
- Hybrid search: `{ query_embedding: [...], filters: { "data.status": "active" }, k: 10 }` applies filters before KNN
- HNSW index: `SELECT *, 1 - (embedding <=> query_vec) AS score FROM snapshots ORDER BY embedding <=> query_vec LIMIT 10` executes in <100ms for 1M-row tables
- Similarity threshold: `?min_similarity=0.8` excludes results below the threshold; calibrated thresholds documented per model
- "More like this" button in the data browser triggers a similarity search using the current instance's embedding

**Tech Stack:** pgvector `<=>` cosine operator; HNSW index; hybrid filter + KNN query; embedding cache

Part of Epic: AI/Vector Features & Enterprise Offloading

---

#### 6.3 (#2218) — Cross-Class Semantic Linking

The similarity engine can discover meaningful relationships between instances across different classes that do not yet have explicit link definitions. This feature surfaces AI-suggested links for human review, enabling data stewards to build richer relationship graphs without manually inspecting every instance pair.

**Suggested links:** Background job computes pairwise cosine similarity between embeddings of different classes (e.g., Customer and Opportunity) above a configurable threshold; suggested links are stored in a `suggested_link` table for review. **Semantic clustering:** Automatically cluster instances within a class by embedding similarity using k-means or DBSCAN; cluster labels and sizes shown in the data graph. **Outlier detection:** Instances with no similar matches (cosine similarity <0.3 with all other instances) are flagged as outliers — potential data entry errors or unique records requiring attention.

**Acceptance Criteria:**
- Suggested link job: `POST /batch/jobs` with `job_type=suggest_links` and `{ source_class_id, target_class_id, threshold: 0.8 }` generates suggestions
- `GET /suggested-links?source_class_id=&reviewed=false` lists pending suggested links with similarity scores
- Accept/reject: `POST /suggested-links/{id}/accept` creates a real link; `POST /suggested-links/{id}/reject` dismisses it
- Clustering: `POST /versions/{v}/classes/{id}/cluster` with `{ n_clusters: 5, algorithm: "kmeans" }` assigns cluster labels; stored in `instance_snapshot.cluster_id`
- Outlier detection: `GET /versions/{v}/classes/{id}/outliers?threshold=0.3` returns instances with no similar neighbors

**Tech Stack:** pgvector batch similarity; scikit-learn k-means (for clustering); PostgreSQL suggested_link table

Part of Epic: AI/Vector Features & Enterprise Offloading

---

#### 6.4 (#2219) — AI-Powered Data Discovery

**Natural language data search:** Users describe what they want in plain English ("find all inactive customers in Seattle with orders over $500"); the system converts the query to a vector + filter combination using the same LLM infrastructure as the query builder (Epic 2.5) plus semantic embedding of the query for vector retrieval. **Intelligent data classification:** Auto-categorize instances using the similarity engine; suggest tags based on content similarity to other tagged instances; data quality scoring per instance (completeness, format validity, uniqueness). **Duplicate/near-duplicate detection:** Find instances with high cosine similarity (>0.95) that may represent the same real-world entity; surface for deduplication workflow. **AI-assisted data entry:** Auto-complete field values based on similar existing instances; suggest property values from patterns; validate entries against learned constraints (unusual values flagged). **RAG interface:** Chat-based data exploration using Retrieval-Augmented Generation — vector search finds relevant context instances, which are fed to the LLM for accurate natural language responses grounded in actual data.

**Acceptance Criteria:**
- NL data search: `POST /search/natural` with `{ query: "enterprise customers in Seattle" }` returns relevant instances using hybrid search
- Quality scoring: `GET /instances/{id}/quality-score` returns `{ completeness: 0.85, format_validity: 1.0, uniqueness_score: 0.92, overall: 0.92 }`
- Duplicate detection: `POST /batch/jobs` with `job_type=find_duplicates` and `{ threshold: 0.95 }` produces a report of duplicate pairs
- RAG chat: `POST /chat` with `{ messages: [{ role: "user", content: "How many orders did we receive last month?" }] }` returns an LLM response grounded in actual query results with source citations
- AI data entry: field autocomplete suggestions appear within 500ms of user typing in the data entry form

**Tech Stack:** LLM API (OpenAI/Anthropic/Ollama); pgvector hybrid search; quality scoring functions; RAG pipeline

Part of Epic: AI/Vector Features & Enterprise Offloading

---

#### 6.5 (#2220) — Enterprise Delta Offloading (MongoDB)

For tenants with high-volume time-series query workloads, offloading `instance_data` deltas to MongoDB enables faster temporal reconstruction by taking advantage of MongoDB's document store and sharding capabilities. This is an opt-in Enterprise tier feature.

**CDC pipeline:** Change Data Capture from PostgreSQL `instance_data` table to MongoDB using logical replication (Debezium or a custom replication slot consumer). Each `instance_data` row is replicated as a MongoDB document with compound indexes optimized for time-series reconstruction queries. **Document schema:** `{ _id: composite(tenant_id, instance_id, version), tenant_id, instance_id, schema_class_id, version, action, data, timestamp, user_id, metadata }`. **Sharding:** Shard by `tenant_id` for horizontal scale; compound indexes on `(instance_id, version)` and `(schema_class_id, timestamp)`. **Sync pipeline health:** Lag monitoring (PostgreSQL → MongoDB delay in milliseconds); alerting on lag >10 seconds; sync status dashboard; bulk initial sync for new tenants.

**Acceptance Criteria:**
- CDC pipeline replicates every new `instance_data` row to MongoDB within 5 seconds (99th percentile)
- MongoDB document schema matches the defined structure; document validation rules enforced at collection level
- Compound index on `(instance_id, version)` supports single-instance history queries in <10ms for 10K-version histories
- Sync lag metric: `GET /metrics/mongodb-sync-lag` returns current lag in milliseconds
- Bulk initial sync job: `POST /batch/jobs` with `job_type=mongodb_initial_sync` migrates existing `instance_data` rows in batches of 10,000
- Fallback: if MongoDB is unavailable, time-series queries fall back to PostgreSQL with a warning header `X-Query-Fallback: postgresql`

**Tech Stack:** Debezium or PostgreSQL logical replication; MongoDB Atlas; MongoDB Spark Connector; sync lag monitoring

Part of Epic: AI/Vector Features & Enterprise Offloading

---

#### 6.6 (#2221) — Redis Snapshot Caching

Redis is used as a write-through cache for current instance snapshots, providing sub-millisecond read latency for hot instances. This complements the PostgreSQL read replica routing (Epic 3.5) with an additional caching tier for the most frequently accessed data.

**Snapshot caching:** Key: `tenant:{tenant_id}:instance:{instance_id}:snapshot`. Value: compressed JSON of `current_data` + `last_version`. Write-through: every UPDATE writes to both PostgreSQL and Redis atomically. Invalidation: DELETE clears the Redis key. TTL per class (configurable, default 300 seconds). Redis Cluster support for horizontal scale. Memory usage monitoring per tenant. **Delta sequence caching:** Cache the N most recent `instance_data` events in Redis Lists for fast history access; automatic eviction of older events to MongoDB. **Query result caching:** Cache expensive query results by query hash; automatic invalidation on relevant data changes; partial result caching for paginated queries; hit rate monitoring.

**Acceptance Criteria:**
- `GET /instances/{id}` checks Redis before PostgreSQL; cache hit returns response in <5ms; cache miss returns in <50ms
- Write-through: cache is updated atomically within the same request handler that writes to PostgreSQL; no consistency window
- TTL: expired cache entries are transparently re-populated from PostgreSQL on next read
- Cache invalidation: `DELETE /instances/{id}` removes the Redis key within the same transaction
- Memory monitoring: `GET /metrics/redis-memory?tenant_id=` returns used memory and TTL distribution per tenant
- Query result cache: enabled for queries where `cache_ttl` is specified in the query request body; invalidated on any mutation to the queried class within the TTL window

**Tech Stack:** Redis Cluster; aioredis; write-through cache middleware; Redis memory monitoring

Part of Epic: AI/Vector Features & Enterprise Offloading

---

#### 6.7 (#2222) — Hybrid Query Execution

The hybrid query router determines the optimal data source for each query based on query type and data currency requirements. This provides a unified query interface across Redis, MongoDB, and PostgreSQL.

**Query router:** Analyze the query type: snapshot (current state) → try Redis first; time-series → route to MongoDB; point-in-time → route to MongoDB or PostgreSQL based on lag. Fallback chain: Redis → MongoDB → PostgreSQL with circuit breakers for unavailable sources. **Cross-store joins:** Federated query joining data across Redis (latest snapshots), MongoDB (delta history), and PostgreSQL (source of truth and link tables); result merging and deduplication; consistency guarantees documented per query type. **Consistency management:** Eventual consistency model for offloaded data with configurable consistency levels per query (`strong`, `bounded_staleness`, `eventual`); read-your-writes guarantee available with additional latency (route read to PostgreSQL if write was in last 10 seconds); consistency monitoring dashboard; manual consistency repair via `POST /admin/consistency-repair`.

**Acceptance Criteria:**
- Query router: current-state snapshot queries transparently use Redis when available; query response includes `X-Data-Source: redis|mongodb|postgresql` header
- Time-series queries: automatically routed to MongoDB when CDC lag <10 seconds; falls back to PostgreSQL otherwise
- Cross-store join: `POST /query` joining snapshot data (Redis) with link data (PostgreSQL) executes correctly and returns consistent results
- Consistency level: queries with `{ "consistency": "strong" }` always route to PostgreSQL primary regardless of Redis/MongoDB availability
- Circuit breaker: if MongoDB returns errors for 5 consecutive queries, route falls back to PostgreSQL and emits an alert; auto-retry MongoDB after 30 seconds

**Tech Stack:** Python query router; asyncio circuit breaker; Redis/MongoDB/PostgreSQL query adapters; consistency level middleware

Part of Epic: AI/Vector Features & Enterprise Offloading

---

#### 6.8 (#2223) — Data Lifecycle Management

Enterprise tenants require structured data lifecycle management across storage tiers, multi-region replication, and operational tooling.

**Tiered storage strategy:** Hot tier: Redis (recent snapshots, active queries); Warm tier: MongoDB (delta history, time-series data); Cold tier: PostgreSQL (source of truth, audit trail); Archive tier: S3/GCS (long-term retention past configured period). Automatic data movement between tiers based on access recency and age policies. Cost optimization recommendations based on access patterns. **Data replication & backup:** Cross-region MongoDB replication via replica sets; Redis persistence (AOF + RDB); Point-in-time recovery for PostgreSQL; backup scheduling and retention; disaster recovery procedures with documented RTO/RPO; backup verification via test restores. **Tenant data isolation:** Separate MongoDB databases per tenant (optional, Enterprise-only); Redis key namespacing by tenant; encryption at rest per tenant (AES-256); configurable data residency (EU, US, APAC); tenant offboarding workflow with complete data purge and confirmation bundle. **Operational tools:** Manual cache invalidation; force sync from PostgreSQL to MongoDB; data verification/repair; performance tuning recommendations; capacity planning tools with 90-day usage projections; cost analysis reports by tier and tenant.

**Acceptance Criteria:**
- Tiered storage policy configurable via `PATCH /tenants/{id}/storage-policy` with retention days per tier
- Archive job: automatically archives cold-tier data to S3 on a nightly schedule; `GET /storage/archive-status` shows archive lag
- Backup verification: monthly automated test restore job; emits alert if restore fails
- Data residency: `data_residency_region` tenant config field enforces that all writes go to databases in that region
- Tenant offboarding: `POST /admin/tenants/{id}/offboard` purges all data across all tiers; generates a deletion receipt with timestamps and checksums; complete within 72 hours

**Tech Stack:** MongoDB replica sets; Redis AOF persistence; S3-compatible archive; PostgreSQL pg_basebackup; asyncio offboarding job

Part of Epic: AI/Vector Features & Enterprise Offloading
