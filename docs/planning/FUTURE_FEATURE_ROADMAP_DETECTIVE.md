# Apiome: Data Detective & Provenance - Feature Roadmap

> Investigative and forensic capabilities that let users trace when, where, who, and how data changed across database-stored instances, ETL and transform pipelines, and related source artifacts. Detective supports detection of corruption, tampering, policy violations, and operational mistakes through a cross-cutting audit layer that connects every material change to a traceable actor, time, and channel.
>
> **Revenue Model**: Core audit trail included in Pro tier; advanced forensic UI, anomaly detection, signed export bundles, and extended retention are Enterprise-only; cross-tenant admin analytics are reserved for platform operators.
>
> **Tech Stack**: NextJS App Router, PostgreSQL (append-only partitioned audit tables), Radix UI, Monaco Editor (diff view), React Flow (lineage graph), OpenAPI 3.1, Ollama (future ML anomaly hints)

---

## MVP Definition

- Canonical Detective audit event model (envelope + typed payloads) with OpenAPI 3.1 schema and PostgreSQL DDL
- Correlation ID propagation across REST requests, import jobs, and migration workers (`X-Correlation-Id`)
- Append-only audit storage with time-partitioned PostgreSQL tables and retention policy configuration
- Actor resolution: map actor UUIDs to display names (user, API key, system) with RBAC-aware label visibility
- Instance lifecycle event enrichment: actor, correlation_id, change_reason on every CREATE/UPDATE/DELETE
- Field-level change index (JSON Pointer paths) with GIN index for fast path-based queries
- Paginated instance history REST API with cursor, actor, path, and action filters
- REST API for all Detective operations (OpenAPI 3.1 documented)

---

## Epic 1 (#2083): Foundations & Correlation Fabric

### Summary Table

| #   | Title                              | Description                                                                                      | Labels                                           | MVP | Parallel |
|-----|------------------------------------|--------------------------------------------------------------------------------------------------|--------------------------------------------------|-----|----------|
| 1.1 (#2084) | Detective Audit Event Model        | Define canonical audit event schema (envelope + typed payloads); DDL and OpenAPI components      | `enhancement`, `mvp`, `detective`, `rest`        | Yes | No       |
| 1.2 (#2085) | Correlation & Tracing Standards    | Propagate correlation_id across REST, workers, and UI actions via X-Correlation-Id header        | `enhancement`, `mvp`, `detective`                | Yes | No       |
| 1.3 (#2086) | Append-Only Audit Storage          | Time-partitioned PostgreSQL audit tables; no UPDATE/DELETE from app; retention configuration     | `enhancement`, `mvp`, `detective`, `rest`        | Yes | Yes      |
| 1.4 (#2087) | Actor Resolution & Display Policy  | Map actor_id to display names; RBAC-aware label visibility; masked API key suffixes              | `enhancement`, `mvp`, `detective`                | Yes | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#2084) — Detective Audit Event Model

Every material change in Apiome — instance mutations, import batches, migration runs, security changes — emits a Detective audit event. This issue defines the canonical event envelope shared by all sources, preventing schema fragmentation between database and ETL teams. The event shape must be stable enough to carry both structured metadata and references to large payloads stored outside the audit table.

The event envelope includes: `event_id` (UUID v7 for time-ordered sorting), `occurred_at` (UTC timestamp with microsecond precision), `tenant_id`, `project_id` (nullable for tenant-level events), `actor` object (`type`: user | api_key | system | service; `actor_id`: UUID), `correlation_id`, `causation_id` (parent event for chaining), `resource` (`type` enum + `resource_id`), `action` enum (CREATE, UPDATE, DELETE, BULK_IMPORT, MIGRATION_STEP, ROLLBACK, etc.), `payload_summary` (non-PII JSON fingerprint for indexed search), `payload_ref` (pointer to detailed blob in secure store for large payloads), `integrity` (SHA-256 of canonical serialization), and `source_context` (optional: `pipeline_run_id`, `file_fingerprint`, `line_range`).

PII redaction rules: `payload_summary` must not contain raw PII; field values are replaced with type annotations or hashes. The `actor_id` field stores only UUIDs in the audit table; display names are resolved at query time per RBAC policy (see 1.4).

```
AuditEvent
┌────────────────────────────────────────────────────────┐
│ event_id          uuid_v7      (time-ordered)          │
│ occurred_at       timestamptz                          │
│ tenant_id         uuid                                 │
│ project_id        uuid (nullable)                      │
│ actor.type        enum: user|api_key|system|service    │
│ actor.actor_id    uuid                                 │
│ correlation_id    uuid                                 │
│ causation_id      uuid (nullable, parent event)        │
│ resource.type     enum: instance|migration|import|...  │
│ resource.id       uuid                                 │
│ action            enum: CREATE|UPDATE|DELETE|...       │
│ payload_summary   jsonb (non-PII fingerprint)          │
│ payload_ref       text (nullable, secure store URI)    │
│ integrity         text (sha256 of canonical form)      │
│ source_context    jsonb (nullable)                     │
└────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- OpenAPI 3.1 component schemas defined for `AuditEvent`, `AuditActor`, `AuditResource`, and all `action` enum values
- PostgreSQL DDL creates the audit table partitioned by `occurred_at` (monthly partitions)
- Application-level database role has INSERT-only access; UPDATE and DELETE are denied at the DB role level
- SHA-256 integrity hash is computed from a canonical JSON serialization (sorted keys, no whitespace)
- Unit tests cover serialization, hash computation, and PII redaction rules for payload_summary
- `POST /audit-events` internal API (service-to-service) validates event shape before insert

**Tech Stack:** PostgreSQL partitioned tables; OpenAPI 3.1 component schemas; Node/Python SHA-256 library

Part of Epic: Foundations & Correlation Fabric

---

#### 1.2 (#2085) — Correlation & Tracing Standards

A single user action (e.g., clicking "Save" in the UI) can trigger a REST request, which spawns a background import job, which calls the migration service. Without a shared trace ID, these cannot be linked in audit views. This issue propagates `correlation_id` through every layer so investigators can reconstruct the full causal chain from a single identifier.

The HTTP gateway generates or accepts an `X-Correlation-Id` header (UUID v4) on every inbound request. If the client provides one, it is accepted; otherwise one is generated. This ID is passed through to: instance mutation handlers (stored on audit events), import job workers (stored on pipeline run entity), migration step workers, and application logs. The UI exposes the correlation ID in the request details drawer for support handoffs.

**Acceptance Criteria:**
- All REST API responses include `X-Correlation-Id` header reflecting the request's correlation ID
- Middleware generates a UUID v4 correlation ID if the request does not include one
- `correlation_id` is stored on all audit events emitted during the request lifecycle
- Background jobs accept correlation ID from the triggering request and propagate it to child events
- Application structured logs include `correlation_id` at every log statement within a request context
- UI: request details drawer in the instance panel shows the `correlation_id` for support purposes

**Tech Stack:** NextJS middleware; worker job context propagation; structured logging

Part of Epic: Foundations & Correlation Fabric

---

#### 1.3 (#2086) — Append-Only Audit Storage & Retention Hooks

The append-only guarantee is the foundational trust property of the Detective system. If audit rows can be updated or deleted by the application, forensic conclusions cannot be trusted. This issue enforces immutability at the database role level and provides a compliant lifecycle for data that must eventually be purged (GDPR right to erasure).

PostgreSQL table(s) are partitioned by `occurred_at` with monthly partitions, enabling efficient time-range queries and partition-level archival. The application database role is granted INSERT only; a separate privileged role (used only by the retention job) can DROP partitions after exporting archived data. Legal hold is implemented via a separate `audit_hold` table that blocks the retention job from purging a date range while a hold is active.

GDPR erasure interacts with audit retention through pseudonymization: when a user's account is deleted, `actor_id` values in audit rows are replaced with a deterministic pseudonym derived from a rotation key — preserving the audit chain without retaining the original PII-linked UUID.

**Acceptance Criteria:**
- Application INSERT-only role is enforced in PostgreSQL; integration test confirms UPDATE and DELETE return permission errors
- Monthly partition creation is automated (pre-created 2 months ahead by a scheduled job)
- Admin API: `GET /audit/retention-policies` lists per-tenant retention windows; `PATCH` updates them (role-gated)
- Retention job exports partitions to S3-compatible storage before dropping; emits a retention audit event
- Legal hold: `POST /audit/holds` with date range; retention job skips held partitions
- GDPR pseudonymization: `POST /audit/pseudonymize/{actor_id}` replaces all occurrences with a pseudonym; creates a pseudonymization event in a separate pseudonym audit log

**Tech Stack:** PostgreSQL partitioned tables + INSERT-only role; S3-compatible archival; Node scheduled job

Part of Epic: Foundations & Correlation Fabric

---

#### 1.4 (#2087) — Actor Resolution & Display Policy

Raw UUIDs in audit events are opaque to investigators. This issue provides resolution from `actor_id` to a human-readable display: username, email prefix, API key label (masked to last 4 characters), or service account name. Resolution is RBAC-aware: not all users may see full API key metadata or cross-tenant admin actor labels.

The resolver is a server-side lookup called at query time (not stored in the audit table), keeping audit rows free of mutable display data. An `audit:read` role can resolve to masked labels; `audit:admin` resolves to full labels including API key IDs. Display policy configuration is stored per tenant and surfaced in the Detective UI.

**Acceptance Criteria:**
- `GET /audit-events/{id}` response includes a resolved `actor_display` object alongside the raw `actor.actor_id`
- `actor_display` includes: `display_name`, `actor_type`, `masked_key_suffix` (for api_key type), `role`
- Users without `audit:admin` see only masked key suffix for API keys; full key metadata is hidden
- Resolution handles deleted actors gracefully: "Deleted User" with last known display info from a snapshot
- Unit tests cover each actor type (user, api_key, system, service) and RBAC visibility scenarios

**Tech Stack:** PostgreSQL actor snapshot table; RBAC permission check in resolver; OpenAPI 3.1 actor display schema

Part of Epic: Foundations & Correlation Fabric

---

## Epic 2 (#2088): Database Instance Forensics

### Summary Table

| #   | Title                             | Description                                                                                           | Labels                                          | MVP | Parallel |
|-----|-----------------------------------|-------------------------------------------------------------------------------------------------------|-------------------------------------------------|-----|----------|
| 2.1 (#2089) | Instance Lifecycle Event Enrichment | Attach actor, correlation_id, change_reason, and client metadata to each instance event             | `enhancement`, `mvp`, `detective`               | Yes | No       |
| 2.2 (#2090) | Field-Level Change Index          | Index JSON Pointer paths touched by each UPDATE; GIN index for path-prefix queries                    | `enhancement`, `mvp`, `detective`, `rest`       | Yes | Yes      |
| 2.3 (#2091) | Instance History API              | Paginated REST API for instance timeline with cursor, filters (actor, path, action)                   | `enhancement`, `mvp`, `detective`, `rest`       | Yes | Yes      |
| 2.4 (#2092) | Snapshot vs Event Replay          | Design and implement replay job: recompute snapshot from events; compare to stored snapshot           | `enhancement`, `detective`                      | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#2089) — Instance Lifecycle Event Enrichment

The data storage roadmap's event-sourced `instance_data` table records what changed but may lack the attribution fields needed for forensic work. This issue adds forensic metadata columns to the instance lifecycle event: `actor` (resolved type + ID from the audit correlation fabric), `correlation_id` (from the inbound request), `client` (optional: user-agent string, UI route, IP hash), `request_id` (internal request UUID), and `change_reason` (optional enum + free-text, max 500 chars, for user-provided notes on significant changes).

A backfill migration sets `actor = {type: "system", actor_id: BACKFILL_AGENT_ID}` and `change_reason = "pre-detective legacy"` for rows created before this feature ships, ensuring the history API returns complete records even for older data.

**Acceptance Criteria:**
- DDL migration adds forensic columns to the instance event/history table; columns are nullable for backward compatibility
- All CREATE/UPDATE/DELETE instance API endpoints persist `actor`, `correlation_id`, and `client` from the request context
- `change_reason` accepts free text up to 500 characters; API validates length and sanitizes HTML
- Backfill migration script runs idempotently and marks backfilled rows with a sentinel actor ID
- Emit a Detective audit event (event type: `INSTANCE_ENRICHMENT_BACKFILL`) when the backfill job completes with row count

**Tech Stack:** PostgreSQL migration; application middleware for actor/correlation injection; REST API update

Part of Epic: Database Instance Forensics

---

#### 2.2 (#2090) — Field-Level Change Index

Investigators frequently ask "show me all changes to `billing.amount` in March" — but scanning full instance event payloads for this is expensive. This issue stores a denormalized `changed_paths` array (JSON Pointer paths, e.g., `["/billing/amount", "/status"]`) on each UPDATE event row, backed by a GIN index for fast containment queries.

The change index is computed from the diff between the previous and new `current_data` JSON at write time, using a fast JSON diff library. For bulk operations, an async worker computes and writes `changed_paths` post-insert within a 5-second SLA.

**Acceptance Criteria:**
- `changed_paths text[]` column added to instance event table with GIN index
- All non-bulk UPDATE operations compute and store `changed_paths` synchronously at write time
- Bulk UPDATE operations enqueue an async diff job; `changed_paths` is populated within 5 seconds
- API filter: `GET /instances/{id}/history?path=/billing/amount` returns only events touching that path
- Index covers: exact path match, prefix match (`/billing/*`), and any-of-paths filter
- Benchmark: 1M-row GIN index query on path prefix completes in <200ms on reference hardware

**Tech Stack:** PostgreSQL GIN index on `text[]`; fast JSON diff (json-diff or equivalent); async worker for bulk

Part of Epic: Database Instance Forensics

---

#### 2.3 (#2091) — Instance History API

> **Note:** This issue is NOT a duplicate of #2195 in DATABASE. #2195 implements the core storage and indexing layer; this issue defines the Detective-layer contract (presentation, diffs, forensic filtering). Depends on #2195.

The instance history API is the primary contract for the Detective UI and third-party integrations. It provides a cursor-based paginated feed of lifecycle events for a given instance, with rich filtering support and an optional diff summary toggle.

```
GET /instances/{instance_id}/history
  ?cursor=<opaque>
  &limit=50
  &actor_id=<uuid>
  &action=UPDATE
  &path=/billing/amount
  &since=2026-01-01T00:00:00Z
  &until=2026-04-01T00:00:00Z
  &include_diff=true

Response:
{
  "events": [{ "event_id", "occurred_at", "actor_display", "action",
                "changed_paths", "diff"?: { "added": {}, "removed": {}, "changed": {} } }],
  "next_cursor": "...",
  "total_count": 1423
}
```

**Acceptance Criteria:**
- Cursor-based pagination supports forward and backward traversal; cursor is opaque and URL-safe
- All filter combinations work independently and in combination without N+1 queries
- `include_diff=true` computes a field-level diff between consecutive events; adds ≤100ms latency for p95
- Response includes `total_count` for display ("1,423 events") without full table scan (use approximate count for >10K)
- Rate limit documented in OpenAPI: 100 requests/minute per API key
- API complies with OpenAPI 3.1; example responses included for every filter combination

**Tech Stack:** PostgreSQL cursor pagination; optional diff computation; OpenAPI 3.1 with examples

Part of Epic: Database Instance Forensics

---

#### 2.4 (#2092) — Snapshot vs Event Replay

If an instance snapshot diverges from what replaying its events would produce, there is evidence of tampering or a bug. This issue designs and implements a background replay job that recomputes the expected `current_data` by applying all events in order, then diffs the result against the stored `instance_snapshot`. Mismatches emit a Detective reconciliation event with severity `critical`.

The replay job runs in two modes: **on-demand** (triggered per instance via API) and **scheduled** (sample-based, weekly scan of a configurable % of active instances per tenant).

**Acceptance Criteria:**
- `POST /instances/{instance_id}/replay-check` triggers an on-demand replay and returns a job reference
- Replay job applies all events in `occurred_at` order; handles soft deletes and schema version changes
- On mismatch: emits audit event `SNAPSHOT_MISMATCH` with `expected_hash`, `stored_hash`, `last_writer_event_id`
- On match: emits `SNAPSHOT_VERIFIED` with event count and duration
- Scheduled scan: configurable percentage (default 5%) of active instances per tenant, run weekly off-peak
- Replay results visible in Detective UI per instance with a "Last Verified" timestamp

**Tech Stack:** PostgreSQL event replay in application code; async job queue; audit event emission

Part of Epic: Database Instance Forensics

---

## Epic 3 (#2093): ETL & Migration Forensics

### Summary Table

| #   | Title                             | Description                                                                                         | Labels                                        | MVP | Parallel |
|-----|-----------------------------------|-----------------------------------------------------------------------------------------------------|-----------------------------------------------|-----|----------|
| 3.1 (#2094) | Pipeline Run Registry             | Pipeline/ETL run entity: id, status, timestamps, actor, correlation_id, input/output descriptors    | `enhancement`, `detective`, `rest`            | No  | No       |
| 3.2 (#2095) | Source File Fingerprinting        | Capture content hash, URI, and row index for each ingested record; attach to instance CREATE event  | `enhancement`, `detective`                    | No  | Yes      |
| 3.3 (#2096) | Migration Run ↔ Instance Correlation | Link migration runs to affected instance_ids; query instances by run_id                          | `enhancement`, `detective`, `rest`            | No  | Yes      |
| 3.4 (#2097) | Interim Store Handoff Auditing    | Audit handoffs between PostgreSQL and interim MongoDB: row counts, checksums, causation chain        | `enhancement`, `detective`                    | No  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#2094) — Pipeline Run Registry

A durable run record is the anchor for all ETL and migration forensics. Without it, investigators can only look at log lines — which may not be retained, may not be correlated, and cannot be linked to instance-level changes. This issue introduces a first-class `PipelineRun` entity that persists across sessions and is queryable by the Detective UI.

Fields: `run_id`, `run_type` enum (import, export, migration_step, custom), `status`, `started_at`, `completed_at`, `owning_actor`, `correlation_id`, `project_id`, `version_id`, `input_descriptors` (array of: file name, storage URI reference, content hash), `output_descriptors`, `parent_run_id` (for sub-steps). The entity is write-once for immutable fields; status and timestamps are updated as the run progresses.

**Acceptance Criteria:**
- `PipelineRun` table in PostgreSQL with FK to project and version; partitioned by `started_at`
- All import, export, and migration step handlers create a run record before processing starts
- `GET /pipeline-runs?project_id=&run_type=&since=&status=` returns paginated runs
- `GET /pipeline-runs/{id}` returns full run detail including input/output descriptors
- Run creation emits a Detective audit event; completion and failure also emit events
- `parent_run_id` links sub-steps to their parent migration plan (enabling tree view in Detective UI)

**Tech Stack:** PostgreSQL; REST API with OpenAPI 3.1; existing batch job system extended

Part of Epic: ETL & Migration Forensics

---

#### 3.2 (#2095) — Source File Fingerprinting & Row-Level Provenance

When a bad data row appears in an instance, investigators need to know: which file it came from, what row number, and whether that file has been modified since import. This issue captures `source_fingerprint` (SHA-256 of file content), `ingest_batch_id` (FK to PipelineRun), and `row_offset` (integer row/line index) for each ingested instance, stored on the instance CREATE audit event or in a sidecar provenance table.

Privacy constraint: the file content itself is not duplicated into the audit system. Only the URI reference and content hash are stored. The hash allows detecting file modification post-ingest; the URI allows cross-referencing with the customer's storage bucket.

**Acceptance Criteria:**
- Import job computes SHA-256 of the source file before processing; stores hash on the PipelineRun input descriptor
- Each ingested instance CREATE event carries `ingest_batch_id` and `row_offset` in `source_context`
- `GET /instances/{id}/provenance` returns the lineage: instance → batch → file hash → pipeline run
- Hash comparison API: given a current file URI, compare its SHA-256 to the stored hash and flag if modified
- Provenance records are included in Detective export bundles (Epic 6.1)

**Tech Stack:** SHA-256 file hashing in import job; provenance sidecar table; REST provenance API

Part of Epic: ETL & Migration Forensics

---

#### 3.3 (#2096) — Migration Run ↔ Instance Correlation

After a migration run, a post-mortem may require binding the specific rule-set version used to the concrete rows that were affected. Without this link, investigators can see that a migration ran but not which instances changed as a result. This issue writes Detective events that connect migration runs to the instance_ids they touched, with rule_set_id, version, and schema capture pair recorded.

For large migrations (>100K rows), the correlation is stored as a batch range (min/max instance_id or batch ID) with an expansion API that returns the full list on demand.

**Acceptance Criteria:**
- Migration load step emits Detective events per class batch: `migration_run_id`, `rule_set_id + version`, `schema_capture_from/to`, `instance_ids` (or range for large batches)
- `GET /migration-runs/{id}/instances?class_id=` returns all instances affected by a run (cursor-paginated)
- `GET /instances/{instance_id}/migrations` returns all migration runs that touched this instance with rule set version
- Integration test: import 50K instances, run migration, confirm all 50K are linked to the migration run

**Tech Stack:** PostgreSQL join table (migration_run ↔ instance batch); REST API; Detective audit emission

Part of Epic: ETL & Migration Forensics

---

#### 3.4 (#2097) — Interim Store Handoff Auditing

Multi-hop pipelines (PostgreSQL → MongoDB → Transform → PostgreSQL) obscure where corruption entered. This issue records a Detective handoff event at each step boundary: the row count leaving step N, the checksum aggregate, duration, and any errors, with `causation_id` chaining step N to step N+1 so the causal sequence is queryable.

Handoff events complement the migration step status (which shows operational state) with an immutable forensic record that can be queried even after the migration plan is deleted.

**Acceptance Criteria:**
- Each step completion writes a `PIPELINE_STEP_HANDOFF` Detective event with: `step_id`, `run_id`, `row_count_out`, `checksum_sha256`, `duration_ms`, `error_count`, `causation_id` (previous step's event_id)
- `GET /audit-events?correlation_id=&action=PIPELINE_STEP_HANDOFF` returns all handoffs for a run in causal order
- UI: pipeline run detail page shows handoff events in a timeline view with row count differences flagged
- Handoff events are included in auditor export bundles (Epic 6.1) for compliance reporting

**Tech Stack:** Detective audit event emission at step boundary; causal chain via causation_id

Part of Epic: ETL & Migration Forensics

---

## Epic 4 (#2098): Investigation Experience

### Summary Table

| #   | Title                          | Description                                                                                       | Labels                                        | MVP | Parallel |
|-----|--------------------------------|---------------------------------------------------------------------------------------------------|-----------------------------------------------|-----|----------|
| 4.1 (#2099) | Instance Detective Panel       | UI timeline of instance events with actor chips, expand-for-diff, date/actor/field filters        | `enhancement`, `detective`                    | No  | No       |
| 4.2 (#2100) | Side-by-Side Version Compare   | UI: select two instance versions; show structured field-level diff with JSON Pointer breadcrumbs  | `enhancement`, `detective`                    | No  | Yes      |
| 4.3 (#2101) | Lineage Mini-Graph             | Visual graph: instance → import batch → file hash → pipeline runs; click-through to run detail    | `enhancement`, `detective`                    | No  | Yes      |
| 4.4 (#2102) | Saved Investigations           | Named investigation manifests (filters + pinned entities + notes); shared per RBAC               | `enhancement`, `detective`, `rest`            | No  | Yes      |

### Detailed Issue Descriptions

#### 4.1 (#2099) — Instance "Detective" Panel (Timeline)

The Detective panel is embedded in the instance detail view as a dedicated tab, providing a chronological timeline of every lifecycle event for that instance. Non-engineers (support staff, data stewards) need a guided view that presents complex event history in a readable format without requiring knowledge of the underlying tables.

Each timeline entry shows: timestamp, actor chip (avatar + display name + actor type badge), action badge (CREATE/UPDATE/DELETE with color coding), and a collapsed preview of changed paths. Clicking an entry expands it to show the full field-level diff with JSON Pointer breadcrumbs. Filters allow narrowing by date range, actor, action type, or changed field path.

```
Timeline for instance: order_8823fa

  ▼ 2026-03-15 14:22:07  [UPDATE]  👤 alice@acme.com (UI)
    Changed: /billing/amount  $120.00 → $95.00
             /status          PENDING → CONFIRMED
    Correlation: 550e8400-e29b-41d4-a716...

  ▼ 2026-03-14 09:11:44  [UPDATE]  🔑 api-key-prod (batch-import)
    Changed: /shipping/address  (10 fields)
    Ingest batch: batch_72aa

  ─ 2026-03-10 08:00:00  [CREATE]  ⚙ system (migration)
    Migration run: mg_v2_to_v3
```

**Acceptance Criteria:**
- Detective panel renders the instance history API (Epic 2.3) response as a visual timeline
- Actor chips use RBAC-resolved display names; API key type shows masked key suffix
- Timeline supports virtual scrolling for instances with >500 events
- Date range picker, actor search, action type toggle, and path search all filter without page reload
- Accessible in light/dark mode; uses Radix UI components; no `alert()` calls
- Deep link: `?detective=open&since=2026-03-01` opens the panel pre-filtered

**Tech Stack:** NextJS App Router, Radix UI, virtual scroll; instance history API

Part of Epic: Investigation Experience

---

#### 4.2 (#2100) — Side-by-Side Version Compare

When an investigator suspects a specific change caused a problem, they need to see exactly what changed between two specific versions of an instance. This feature adds a "Compare" button to any two selected timeline entries, opening a structured diff view that highlights changes at the field level rather than showing opaque blobs.

The diff viewer uses Monaco Editor in diff mode (or a structured JSON diff component) to show added fields (green), removed fields (red), and changed values (yellow). JSON Pointer breadcrumbs above the diff allow copying the path for use in history API filters. Correlation IDs for both events are displayed for support handoff.

**Acceptance Criteria:**
- "Compare" action available from the timeline: select any two events (or event vs. current state)
- Diff view shows field-level changes with JSON Pointer paths for each changed key
- Changed value cells show `before → after` with type information
- "Copy path" button on each changed field copies the JSON Pointer to clipboard
- Correlation IDs for both events displayed with one-click copy
- Diff view is accessible (keyboard-navigable, screen reader-friendly)

**Tech Stack:** Monaco Editor diff mode or structured JSON diff component; Radix Dialog

Part of Epic: Investigation Experience

---

#### 4.3 (#2101) — Lineage Mini-Graph (Instance ↔ Runs ↔ Sources)

Tables are insufficient for multi-hop reasoning. When a field value seems wrong, investigators need to see: was it set by an import batch? Which file? Was the file modified? Which migration run touched it? This graph makes those connections visual and clickable.

The graph is a read-only React Flow canvas showing a limited node set: the target instance, its direct pipeline run ancestors (imports, migrations), and source file nodes (with hash status: verified/modified). Clicking a node opens its detail in a drawer. The graph caps at 20 nodes for performance; a "Show more" option loads additional ancestry levels.

```
[source.csv (hash: verified)] ──▶ [Import Batch batch_72aa] ──▶ [Instance order_8823fa]
                                                                         │
                            [Migration mg_v2_to_v3 (rule set v3)] ──────┘
```

**Acceptance Criteria:**
- Lineage API `GET /instances/{id}/lineage` returns a node + edge graph structure (max 20 nodes)
- Source file nodes show: URI reference, SHA-256 status (verified | modified | unknown), import date
- Pipeline run nodes show: run type, status, actor, correlation_id, row count
- Click-through: clicking any node opens its detail drawer without closing the graph
- Graph is read-only; PNG/SVG export available (optional v1.1)
- Nodes beyond the cap are summarized as a "N more ancestors" placeholder with an expand action

**Tech Stack:** React Flow (read-only); lineage REST API; Radix Sheet for detail drawer

Part of Epic: Investigation Experience

---

#### 4.4 (#2102) — Saved Investigations & Annotations

Incidents span days and involve multiple team members. Without a way to save investigation state, each session restarts from scratch. This feature allows users to create named investigations that persist their active filters, pinned entity IDs (instances, runs, files), and markdown notes — shared with project members per RBAC.

Investigators can bookmark a specific timeline view, annotate their findings, tag entities as "suspicious" or "cleared", and share the investigation manifest with teammates. Audit events are emitted for every note added or investigation modified, making the investigation activity itself auditable.

**Acceptance Criteria:**
- `POST /investigations` creates a named investigation with: `title`, `description`, `pinned_entity_refs`, `filter_state` (serialized timeline filters), `notes` (markdown)
- Investigation manifests are scoped to a project; shared with project members per `detective:read` RBAC role
- `PATCH /investigations/{id}/notes` appends a note with timestamp and actor; history is immutable (append-only)
- Detective audit event emitted on investigation create, note add, and share
- UI: investigation list in sidebar; clicking opens the timeline pre-filtered and pinned entities highlighted
- Investigations can be closed/resolved; resolved investigations are archived but readable

**Tech Stack:** PostgreSQL investigation table; Radix UI; audit event emission on all mutations

Part of Epic: Investigation Experience

---

## Epic 5 (#2103): Integrity, Anomalies & Policy Signals

### Summary Table

| #   | Title                              | Description                                                                                         | Labels                                          | MVP | Parallel |
|-----|------------------------------------|-----------------------------------------------------------------------------------------------------|-------------------------------------------------|-----|----------|
| 5.1 (#2104) | Reconciliation Reports             | Productize replay outcomes: mismatch, missing events, snapshot ahead of log; severity levels        | `enhancement`, `detective`, `rest`              | No  | No       |
| 5.2 (#2105) | Anomaly Hints (Heuristic)          | Heuristic flags: unusual actor, unusual time, burst of deletes, path rarely changed                 | `enhancement`, `detective`                      | No  | Yes      |
| 5.3 (#2106) | Integrity Checksums on Export Bundles | Export signed/hashed audit bundles: manifest + events with SHA-256 of JSONL body               | `enhancement`, `detective`, `rest`              | No  | Yes      |

### Detailed Issue Descriptions

#### 5.1 (#2104) — Reconciliation Reports & Tampering Indicators

The snapshot replay designed in Epic 2.4 produces raw results; this issue productizes those results into actionable reports with severity levels, tenant-wide scheduling, and visible status per instance in the Detective UI. Silent divergence between events and snapshots erodes trust; explicit reports make the system's integrity posture visible.

Report types: **per-instance** (on-demand), **per-class sample** (weekly random sample of N instances per class), **scheduled tenant job** (configurable frequency). Severity: `info` (small numeric drift, likely rounding), `warn` (field-level mismatch, unknown cause), `critical` (snapshot ahead of event log, missing events, hash mismatch). Critical findings emit `SNAPSHOT_MISMATCH` Detective events (see Epic 2.4) and surface on the tenant dashboard as open integrity alerts.

**Acceptance Criteria:**
- `GET /reconciliation-reports?class_id=&severity=&since=` returns paginated report results
- Tenant dashboard shows: last reconciliation run date, total instances checked, open critical alerts
- Per-instance UI: "Last verified" timestamp next to instance name; red icon for critical findings
- Scheduled job is configurable via `PATCH /tenants/{id}/detective-config` with `reconciliation_frequency` field
- Critical events trigger an in-app notification for users with `detective:admin` role

**Tech Stack:** PostgreSQL reconciliation result table; async job; in-app notification system

Part of Epic: Integrity, Anomalies & Policy Signals

---

#### 5.2 (#2105) — Anomaly Hints (Heuristic, Non-ML)

Investigators cannot review every change; heuristic signals guide their attention to the changes most worth reviewing. This issue implements a rule-based anomaly hint engine — no ML claims, no "AI verdict" copy — that flags patterns worth investigating. Flags are explanatory: each flag shows the rule that triggered it and the specific data point.

Default heuristic rules (configurable per tenant): unusual actor (first time actor A has touched class C), unusual time (action outside actor's historical active hours ±2 SD), burst of deletes (>50 DELETE events in 5 minutes from the same actor), rarely-changed path (a path touched fewer than 3 times in the past 90 days is now changed). Rule thresholds are configurable per tenant; disabled rules are stored in tenant config.

**Acceptance Criteria:**
- Anomaly hint engine runs as a post-commit hook on audit event writes; emits a `HINT` sidecar event if triggered
- Each hint includes: `rule_id`, `rule_name`, `explanation` (human-readable why), `confidence: low|medium` (never "high" to avoid overstatement), `flagged_event_id`
- Hints are visible in the Detective timeline as yellow ⚠ badges on the relevant event entries
- Rule configuration UI: `GET/PATCH /tenants/{id}/anomaly-rules` with threshold values and enable/disable
- False-positive feedback: users can dismiss a hint with a reason; dismissal rate tracked per rule for tuning
- No ML library dependency; rules are pure threshold/statistical checks on audit data

**Tech Stack:** PostgreSQL hint table; async post-insert hook; Radix UI badge components

Part of Epic: Integrity, Anomalies & Policy Signals

---

#### 5.3 (#2106) — Integrity Checksums on Export Bundles

Legal and security teams need tamper-evident audit bundles for handoffs to auditors, regulators, or external counsel. A bundle without a checksum cannot prove it has not been modified after export. This issue adds a manifest file to every audit export that lists the event_id range, record count, and SHA-256 of the JSONL body.

Optional organizational signing key integration is deferred to a later phase; the v1 implementation uses HMAC-SHA-256 with a platform-managed key so bundles can be verified by Apiome's verification endpoint without requiring customer key management.

**Acceptance Criteria:**
- Every audit export (from Epic 6.1) includes a `manifest.json` with: `event_id_min`, `event_id_max`, `record_count`, `sha256_of_body`, `exported_at`, `exported_by`, `platform_hmac`
- `POST /audit/exports/{id}/verify` accepts the manifest and JSONL body and returns a verification result
- Manifest format is documented in OpenAPI 3.1; verification endpoint is publicly documented for auditors
- HMAC key rotation: platform rotates signing keys quarterly; old keys are retained for 2 years for historical verification
- Export bundle ZIP contains: `events.jsonl`, `manifest.json`, `README.txt` with verification instructions

**Tech Stack:** Node crypto HMAC-SHA256; ZIP archive generation; OpenAPI verification endpoint

Part of Epic: Integrity, Anomalies & Policy Signals

---

## Epic 6 (#2107): Exports, Compliance & Operations

### Summary Table

| #   | Title                         | Description                                                                                          | Labels                                        | MVP | Parallel |
|-----|-------------------------------|------------------------------------------------------------------------------------------------------|-----------------------------------------------|-----|----------|
| 6.1 (#2108) | Auditor Export API            | Bulk export APIs filtered by time, resource, actor; async job + download link; JSONL and CSV formats | `enhancement`, `detective`, `rest`            | No  | No       |
| 6.2 (#2109) | Detective Permissions         | Dedicated `detective:read` and `detective:export` permissions; log access to sensitive bundles        | `enhancement`, `detective`, `rest`            | No  | Yes      |

### Detailed Issue Descriptions

#### 6.1 (#2108) — Auditor Export API (JSONL/CSV)

SIEMs, long-term archives, and compliance workflows need machine-readable streams of audit events, not UI pages. This issue provides an async bulk export API that accepts time range, resource type, and actor filters, generates a JSONL or CSV file in the background, and returns a signed download URL.

Export jobs run asynchronously because full-history exports may contain millions of events. The job tracks progress (% complete) and is queryable via the batch job API. PII warnings are embedded in the export metadata: `README.txt` in the ZIP bundle documents which fields may contain PII and how to handle them per GDPR.

```
POST /audit/exports
{
  "format": "jsonl",
  "filters": {
    "since": "2026-01-01T00:00:00Z",
    "until": "2026-04-01T00:00:00Z",
    "resource_type": "instance",
    "actor_id": "uuid-optional"
  }
}

→ { "export_job_id": "...", "status": "pending" }

GET /audit/exports/{id}
→ { "status": "completed", "download_url": "...", "expires_at": "..." }
```

**Acceptance Criteria:**
- `POST /audit/exports` accepts filters and returns a job reference immediately
- Export job processes events in batches; `GET /audit/exports/{id}` returns progress percentage
- Completed export produces a signed download URL expiring in 24 hours
- JSONL format: one event per line, UTF-8, includes resolved `actor_display` (with RBAC masking)
- CSV format: flat headers for common fields; nested JSON fields serialized as JSON strings
- ZIP bundle includes: events file + `manifest.json` (from Epic 5.3) + `README.txt`
- Rate limit: 3 concurrent export jobs per tenant; excess returns 429 with retry-after

**Tech Stack:** Async job queue; S3-compatible signed URL; batch event streaming; OpenAPI 3.1

Part of Epic: Exports, Compliance & Operations

---

#### 6.2 (#2109) — Detective Permissions & Audit of Audit Access

Reading audit data is itself sensitive: an investigator who can read audit events for any user in the tenant can construct detailed behavioral profiles. This issue introduces dedicated Detective permissions that are distinct from general data-read permissions and audits every access to sensitive export bundles.

Permission model: `detective:read` grants access to the instance timeline, pipeline run history, and lineage graph; `detective:export` additionally grants access to bulk export and bundle download. Both are separate from `data:read` so that compliance roles can be granted Detective access without broad data access. Every download of an export bundle emits a `BUNDLE_ACCESSED` Detective event with the accessor's actor_id, download timestamp, and export ID.

**Acceptance Criteria:**
- `detective:read` and `detective:export` are distinct permissions configurable in the RBAC role editor
- Instance history API, pipeline run API, and lineage API enforce `detective:read`
- Export create/download API enforces `detective:export`
- Every export bundle download emits a `BUNDLE_ACCESSED` audit event (who, when, which export)
- Permission names align with the RBAC roadmap naming conventions; migration script adds them to existing admin roles
- API returns 403 with descriptive error message when permission is missing

**Tech Stack:** RBAC middleware; audit event emission on download; OpenAPI 3.1 security schemes

Part of Epic: Exports, Compliance & Operations
