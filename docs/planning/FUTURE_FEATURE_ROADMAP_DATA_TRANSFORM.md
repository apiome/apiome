# Apiome: Data Transform & Schema Migration - Feature Roadmap

> A dedicated migration and transformation layer that sits between stored instance data and evolving schema versions. When schemas are versioned or published, existing instance data must be migrated safely — with no silent data loss, full auditability, and support for multi-step pipelines using MongoDB as an interim store and Apache Spark for parallel execution.
>
> **Revenue Model**: Included in Pro/Enterprise tiers; Spark-backed parallel migrations and managed interim stores are Enterprise-only; migration audit retention is tier-gated.
>
> **Tech Stack**: NextJS App Router, PostgreSQL, MongoDB (interim store), Apache Spark 3.x (MongoDB Spark Connector), custom JSON Schema diff engine, OpenAPI 3.1, React Flow (visual plan UI), Radix UI

---

## MVP Definition

- Schema diff engine comparing source and target schema captures (class-level and property-level diffs)
- Property deletion policy that blocks migration when source properties have no translation rule
- Backward compatibility check preventing migration across deleted classes without explicit rules
- Translation rule definition model: property mappings, type coercion, default/null handling
- Rule authoring UI with per-class mapping editor and CRUD API
- Major version safeguard that blocks cross-major migration without a full rule set
- Visual migration step plan: ordered steps with source/target DB, interim store, transform, and verify stages
- REST API for all migration operations (OpenAPI 3.1 documented)

---

## Epic 1 (#2060): Schema Comparison & Compatibility

### Summary Table

| #   | Title                             | Description                                                                                      | Labels                                              | MVP | Parallel |
|-----|-----------------------------------|--------------------------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 1.1 (#2061) | Schema Diff Engine                | Compare source/target schema captures at class and property level; output compatibility report   | `enhancement`, `mvp`, `data-transform`, `rest`      | Yes | No       |
| 1.2 (#2062) | Column/Property Deletion Policy   | Block or warn when source properties are absent in target without explicit translation rules      | `enhancement`, `mvp`, `data-transform`              | Yes | No       |
| 1.3 (#2063) | Backward Compatibility Checks     | Prevent migration across deleted classes; integrate with versioning roadmap breaking-change check | `enhancement`, `mvp`, `data-transform`, `rest`      | Yes | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#2061) — Schema Diff Engine

The foundation of safe migration is a machine-readable comparison between two schema captures. The diff engine must classify every change at class level (added, removed, shared) and then at property level within each shared class (added, removed, renamed, type-changed). The output is a structured compatibility report: `safe` (additive only), `unsafe` (removals with no rule), or `blocked` (deleted classes with instance data and no migration rule).

Class-level diffing identifies which classes exist only in the source, only in the target, or in both. For each class present in both versions the engine performs property-level analysis — detecting added properties (target only, safe), removed properties (source only, requires a rule), and renamed or type-changed properties (detected via naming heuristics or explicit mapping annotations). Structural changes in nested object or array shapes are also flagged.

```
Source capture A                  Target capture B
┌─────────────────────┐           ┌─────────────────────┐
│ class: Order        │   DIFF    │ class: Order        │
│  id: uuid           │──────────▶│  id: uuid           │
│  customer_name: str │  removed  │  (missing)          │
│  total: float       │  changed  │  total: decimal     │
│  created_at: ts     │  retained │  created_at: ts     │
│                     │           │  status: enum (NEW) │ ← added
└─────────────────────┘           └─────────────────────┘

Output: compatibility = UNSAFE
  Removed: Order.customer_name → requires translation rule or explicit drop
  Changed:  Order.total (float → decimal) → requires type coercion rule
  Added:    Order.status → default/null handling needed
```

**Acceptance Criteria:**
- Diff engine accepts two `schema_capture_id` values and returns a structured JSON compatibility report
- Report lists all class-level and property-level changes with `change_type` enum
- Overall compatibility classifies as `safe`, `unsafe`, or `blocked`
- OpenAPI 3.1 schema for the compatibility report response
- Unit tests cover: additive-only (safe), removal without rule (unsafe), deleted class with data (blocked)

**Tech Stack:** Custom JSON Schema comparison (Python or Node); output stored in migration plan entity; OpenAPI 3.1 component schemas

Part of Epic: Schema Comparison & Compatibility

---

#### 1.2 (#2062) — Column/Property Deletion Policy

When the diff engine identifies removed properties (present in source, absent in target), the system enforces an explicit policy before any migration can proceed. Three modes are configurable per tenant or per migration plan: **strict** (blocks until a translation rule exists), **report-only** (migration proceeds but data loss is documented), and **allow-list** (only properties declared in a migration manifest are accepted as removals).

All dropped or unmapped properties are logged with instance counts and sample IDs. In strict mode, the migration plan shows an error state until the user defines a rule (map to new field, archive, or explicitly accept drop with a written reason). The audit log records every accepted data loss decision: who accepted it, when, and what reason was recorded.

**Acceptance Criteria:**
- Migration plan UI shows blocked properties requiring decisions when policy is `strict`
- Strict mode prevents migration job from starting until all blocked properties are resolved
- Report-only mode generates a "data loss report" attached to the migration run
- Audit log entry created for every "accept drop" decision with actor and reason
- API supports PATCH to set policy mode and add accepted removals with reason strings
- `GET /migration-plans/{id}/compatibility` returns the current blocking items with their resolution status

**Tech Stack:** PostgreSQL policy config per migration plan; REST API with OpenAPI 3.1 documentation

Part of Epic: Schema Comparison & Compatibility

---

#### 1.3 (#2063) — Backward Compatibility Checks

When the target schema version deletes a class that still has instance data in the source, migration is blocked until the user provides an explicit disposition. Dispositions include: map all instances of class C to another class D (requires a class-level migration rule), archive instances to a separate read-only store, or record an explicit "purge" decision with admin approval and audit trail.

This check integrates with the versioning roadmap's backward compatibility checker to surface breaking schema changes at publish time, before a migration is even planned. The result is a pre-migration gate that prevents deploying a schema version that would leave dangling instance data.

```
Blocking condition:
  class Customer (source) → DELETED in target
  instances: 14,823 rows in source DB

Resolution options:
  [A] Map Customer → LegacyContact (requires class rule)
  [B] Archive to customer_archive_YYYY_MM_DD
  [C] Accept purge — requires admin approval + reason
```

**Acceptance Criteria:**
- Migration plan creation checks for deleted classes with existing instance data; returns blocking conditions list
- Each blocking condition requires a resolution before the plan can be executed
- Class-map resolution links to a class-level migration rule in Epic 2
- Purge resolution requires a separate admin-role approval step; creates an audit event
- Version publish flow surfaces a compatibility warning when a class deletion would create a blocking migration condition

**Tech Stack:** Cross-reference instance count query at plan creation; admin approval workflow; OpenAPI 3.1 endpoints

Part of Epic: Schema Comparison & Compatibility

---

## Epic 2 (#2064): Data Translation Rules

### Summary Table

| #   | Title                    | Description                                                                               | Labels                                              | MVP | Parallel |
|-----|--------------------------|-------------------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 2.1 (#2065) | Rule Definition Model    | Per-class rule sets with property mappings, type coercions, and default/null handling     | `enhancement`, `mvp`, `data-transform`, `rest`      | Yes | No       |
| 2.2 (#2066) | Rule Authoring & Storage | UI form editor for mapping rules per class; CRUD API; versioned rule sets                 | `enhancement`, `mvp`, `data-transform`, `rest`      | Yes | Yes      |
| 2.3 (#2067) | Execution Semantics      | Ordered rule application, idempotency guarantees, and rollback strategy documentation     | `enhancement`, `data-transform`                     | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#2065) — Rule Definition Model

Translation rules are first-class entities, versioned and tied to a (source_schema_capture_id, target_schema_capture_id) pair. Each rule set contains per-class rule blocks. Within a class block, developers define: property mappings (`source_property_path` → `target_property_path` for renames or moves), transform functions (type coercion, date parsing, expression snippets), and default/null handling (what to write to target when source has no value).

Transform functions support a small expression language — string concatenation, arithmetic, conditional assignment — and optionally reference registered transform hooks (JavaScript/Python snippets for complex logic). After rules are applied, the output must validate against the target class JSON Schema; validation failures are configurable to either reject the row or route it to an error queue.

```
Rule set: capture_A → capture_B
  class: Order
    property_mappings:
      customer_name → NULL          (removed; accepted drop)
      total         → total         (coerce float → decimal)
      firstName + " " + lastName → fullName  (expression)
    defaults:
      status: "PENDING"             (new required field)
    transform_functions:
      total: CAST(value AS NUMERIC(12,2))
  class: Customer → LegacyContact
    class_map: true
    property_mappings:
      email → contact_email
      phone → contact_phone
```

**Acceptance Criteria:**
- `RuleSet` entity stored in PostgreSQL with FK to source/target captures and a version counter
- Each rule supports: `property_map`, `expression`, `default_value`, `accepted_drop`, `type_coerce`
- Rule set version increments on each update; migration runs record which version was used
- Output validation against target JSON Schema is configurable as `reject` or `error_queue`
- OpenAPI 3.1 schema for rule set, rule block, and transform function types

**Tech Stack:** PostgreSQL JSONB for rule definitions; JSON Schema validation (ajv or equivalent); expression interpreter in Node/Python

Part of Epic: Data Translation Rules

---

#### 2.2 (#2066) — Rule Authoring & Storage

The rule authoring UI provides a form-based editor where users select a source class and its properties from a dropdown, then drag/map them to target class properties. For each mapping, a transform type selector (copy, rename, expression, default, drop) opens the appropriate input. The UI is aligned with the Import roadmap's transformation rules UI to reuse component patterns.

The CRUD API exposes endpoints for creating, reading, updating, and listing rule sets by version pair. Rule sets are versioned: each save increments the version, and previous versions are retained for audit. A templates system allows saving reusable rule patterns (e.g., "rename field A → B") for reuse across version pairs.

```
POST /rule-sets
GET  /rule-sets?source_capture={id}&target_capture={id}
GET  /rule-sets/{id}
PUT  /rule-sets/{id}
POST /rule-sets/{id}/publish
GET  /rule-sets/{id}/versions
```

**Acceptance Criteria:**
- UI shows source properties alongside their diff status (removed, changed, new) from Epic 1 compatibility report
- Blocked properties from 1.2 are highlighted in red with a required indicator until resolved
- API enforces that rule sets cannot be deleted if referenced by a migration run
- Version history shows diff between versions with actor and timestamp
- Template library UI allows saving and applying common mapping patterns

**Tech Stack:** NextJS App Router, Radix UI form components, PostgreSQL, OpenAPI 3.1

Part of Epic: Data Translation Rules

---

#### 2.3 (#2067) — Execution Semantics

Rules are applied in a defined order: renames first, then type transforms, then expression evaluations, then defaults for missing values. This order is documented and configurable per rule set. Idempotency is enforced where possible — running the same rule set twice on the same source data produces the same output without double-applying transforms.

The rollback strategy preserves source data until the target is verified. The pipeline design keeps source instance snapshots intact during migration and only marks them superseded after a successful verify step. If verification fails, the target data is discarded and the source remains canonical. For MongoDB-backed pipelines (Epic 5), the interim store provides an additional rollback point.

**Acceptance Criteria:**
- Rule application order is documented in the rule set entity and UI
- Idempotent transforms are flagged as such; non-idempotent transforms warn the user
- Migration plan includes a "rollback" step definition: what data is retained, when it can be discarded
- Rollback can be triggered via API or UI after each migration step; emits a Detective audit event
- Integration tests cover re-run scenarios to verify idempotency

**Tech Stack:** Migration step state machine in PostgreSQL; rollback event via Detective audit

Part of Epic: Data Translation Rules

---

## Epic 3 (#2068): Major Version Safeguards

### Summary Table

| #   | Title                  | Description                                                                                      | Labels                                         | MVP | Parallel |
|-----|------------------------|--------------------------------------------------------------------------------------------------|------------------------------------------------|-----|----------|
| 3.1 (#2069) | Version Semantics      | Define breaking version changes; configurable migration policy (same-major, cross-major rules)   | `enhancement`, `mvp`, `data-transform`, `rest` | Yes | No       |
| 3.2 (#2070) | Blocking Conditions    | Enforce blocking until deleted classes and missing rules are resolved; full audit of overrides   | `enhancement`, `mvp`, `data-transform`         | Yes | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#2069) — Version Semantics

Schema versions are classified as major (breaking) when one or more classes are removed, properties are removed without a migration rule, or contract-breaking changes are declared in the version notes. The migration policy is configurable per tenant or per project with three modes: `allow_same_major_only` (automatic migration only within the same major version), `allow_cross_major_with_full_ruleset` (requires every affected class to have a complete rule set and no blocked compatibility items), and `allow_cross_major_with_approval` (adds an explicit admin approval step).

The policy is stored on the tenant configuration and can be overridden per migration plan by admins. Version policy configuration is exposed via API with role-gated write access.

**Acceptance Criteria:**
- Version entity has `is_major_version` boolean and a `breaking_reason` text field
- Migration plan creation checks policy and rejects cross-major attempts if policy disallows it
- Policy modes are configurable via `PATCH /tenants/{id}/migration-policy`
- `allow_cross_major_with_approval` creates an approval workflow step; migration waits for approval event
- All policy checks and overrides emit audit events

**Tech Stack:** Tenant configuration in PostgreSQL; approval workflow step; OpenAPI 3.1 policy endpoints

Part of Epic: Major Version Safeguards

---

#### 3.2 (#2070) — Blocking Conditions

All blocking conditions from Epic 1 (deleted classes with data, properties without rules) are surfaced on the migration plan as a resolved/unresolved checklist. The migration plan cannot transition to `executing` state while any blocking condition remains unresolved. Each resolution action — adding a rule, accepting a purge, or providing an admin approval — records a timestamped audit entry with actor and reason.

```
Migration plan: A → B
Blocking conditions:
  ✗ class Customer deleted (14,823 instances) — awaiting disposition
  ✗ Order.customer_name removed — no translation rule
  ✗ Cross-major version — admin approval required

  → Cannot execute until all 3 conditions resolved
```

**Acceptance Criteria:**
- `GET /migration-plans/{id}/blocking-conditions` returns each condition with its resolution status
- Plan execution API returns 422 with blocking condition list if any remain unresolved
- Audit log captures every resolution action with actor, timestamp, and reason
- UI shows checklist of blocking conditions with inline resolution flows (rule editor, disposition selector)
- Completed audit bundle (per Epic 6 / Detective export) includes blocking condition resolutions

**Tech Stack:** PostgreSQL blocking condition table; migration plan state machine; REST API

Part of Epic: Major Version Safeguards

---

## Epic 4 (#2071): Visual Migration Step Plans

### Summary Table

| #   | Title                    | Description                                                                                         | Labels                                         | MVP | Parallel |
|-----|--------------------------|-----------------------------------------------------------------------------------------------------|------------------------------------------------|-----|----------|
| 4.1 (#2072) | Migration Plan Model     | Ordered step entity: source DB, interim store, transform, verify; data-in/data-out per step         | `enhancement`, `mvp`, `data-transform`, `rest` | Yes | No       |
| 4.2 (#2073) | Visual Representation    | Flow diagram showing source → interim → transform → target with per-step status and record counts   | `enhancement`, `data-transform`                | No  | Yes      |
| 4.3 (#2074) | Runbook Integration      | One-click or API-triggered run; pause/resume between steps; rollback plan documentation              | `enhancement`, `data-transform`, `rest`        | No  | Yes      |

### Detailed Issue Descriptions

#### 4.1 (#2072) — Migration Plan Model

A migration plan is an ordered list of execution steps with defined data-in and data-out locations. Standard step types are: `export` (PostgreSQL → interim MongoDB), `transform` (apply translation rules in interim), `load` (interim MongoDB → PostgreSQL target capture), and `verify` (count/checksum comparison). Each step has a `depends_on` reference enabling parallel execution boundaries for partition-based loads.

```
Migration Plan: capture_A → capture_B

Step 1 (export)
  data_in:  PostgreSQL / instance_snapshot (capture_A)
  data_out: MongoDB / migration_xyz_raw
  status:   pending | running | completed | failed

Step 2 (transform)
  data_in:  MongoDB / migration_xyz_raw
  data_out: MongoDB / migration_xyz_transformed
  depends:  Step 1
  rule_set: rs_v3

Step 3 (load)
  data_in:  MongoDB / migration_xyz_transformed
  data_out: PostgreSQL / instance_snapshot (capture_B)
  depends:  Step 2

Step 4 (verify)
  checks:   row counts match, sha256 checksums, sample validation
  depends:  Step 3
```

**Acceptance Criteria:**
- `MigrationPlan` and `MigrationStep` entities stored in PostgreSQL with FK to rule set and schema captures
- Step entity includes: `step_type`, `data_in`, `data_out`, `depends_on`, `status`, `started_at`, `completed_at`, `error`
- API supports creating plan from compatibility report and rule set; auto-generates standard 4-step plan
- `POST /migration-plans/{id}/steps/{step_id}/run` triggers a step; returns async job reference
- OpenAPI 3.1 schemas for plan, step, and step status

**Tech Stack:** PostgreSQL; batch job system reuse (job_type: migration_export/transform/load); OpenAPI 3.1

Part of Epic: Visual Migration Step Plans

---

#### 4.2 (#2073) — Visual Representation

The visual migration plan is a read-only flow diagram (React Flow or equivalent) embedded in the UI, showing each step as a node with arrows representing data flow. Nodes are labeled with their step type (Export, Transform, Load, Verify) and colored by status (gray=pending, blue=running, green=completed, red=failed). Arrows display record counts or "N instances" labels. A per-step drawer shows duration, error details, and sample records.

```
[PostgreSQL source]──(14,823 rows)──▶[MongoDB staging]──▶[Transform]──▶[MongoDB ready]──▶[PostgreSQL target]
       ↓ status                             ↓                 ↓                ↓                    ↓
     complete                           complete           running          pending              pending
```

**Acceptance Criteria:**
- Flow diagram renders all steps from the migration plan entity; auto-updates on status changes (polling or SSE)
- Step nodes are color-coded by status with a duration label after completion
- Edge labels show record counts once steps complete
- Clicking a step opens a drawer with logs, error details, and sample row preview
- Diagram can be exported as PNG/SVG from the UI for runbook documentation

**Tech Stack:** React Flow (read-only mode); SSE or polling for live status; NextJS App Router

Part of Epic: Visual Migration Step Plans

---

#### 4.3 (#2074) — Runbook Integration

Migration plans can be triggered via the UI "Run" button or via `POST /migration-plans/{id}/run`. Dry-run mode (`?dry_run=true`) validates the rule set against a sample of source data without writing to the target. Pause is supported between steps: after each step completes, the plan enters a `paused` state awaiting manual resume — useful for spot-checking interim MongoDB data before the load step proceeds. Rollback triggers discard target data and retain the source as canonical.

**Acceptance Criteria:**
- `POST /migration-plans/{id}/run` starts execution from the first incomplete step; respects `?dry_run=true`
- `POST /migration-plans/{id}/pause` pauses after the current step completes
- `POST /migration-plans/{id}/resume` continues from the next pending step
- `POST /migration-plans/{id}/rollback` discards target instance data created in the current run; emits audit event
- Dry-run produces a preview report: estimated row counts, sample transformed records, validation failures
- All run/pause/resume/rollback actions emit Detective audit events

**Tech Stack:** PostgreSQL plan state machine; batch job system; REST API with OpenAPI 3.1

Part of Epic: Visual Migration Step Plans

---

## Epic 5 (#2075): MongoDB as Interim Database

### Summary Table

| #   | Title                           | Description                                                                                          | Labels                                      | MVP | Parallel |
|-----|---------------------------------|------------------------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 5.1 (#2076) | Interim Store Lifecycle         | Create, write, retain, and clean up MongoDB collections per migration plan                           | `enhancement`, `data-transform`             | No  | No       |
| 5.2 (#2077) | Schema in MongoDB               | Document shape, indexes, and idempotency for interim-stored instances                                | `enhancement`, `data-transform`             | No  | Yes      |
| 5.3 (#2078) | Integration with Migration Steps| Wire step types (export, transform, load) to MongoDB read/write operations                           | `enhancement`, `data-transform`, `rest`     | No  | Yes      |

### Detailed Issue Descriptions

#### 5.1 (#2076) — Interim Store Lifecycle

MongoDB is used as a decoupled staging area between the PostgreSQL source and target. For each migration plan, the lifecycle creates a dedicated database or collection namespace (e.g., `migration_run_{run_id}_raw`), writes exported source instance data as JSON documents, runs transform jobs against that collection, then loads results into the target PostgreSQL capture. After a successful verify step, a configurable retention policy (default 7 days) schedules the interim collection for cleanup.

Security requirements: MongoDB data is encrypted at rest and in transit; access is scoped to the migration service account only; PII from interim collections is excluded from retention beyond the configured window.

**Acceptance Criteria:**
- Migration export step creates a MongoDB namespace scoped to `run_id`; records namespace on the step entity
- Retention policy configurable per tenant (1–90 days); scheduled cleanup job runs nightly
- Cleanup is deferred if the plan's verify step has not completed successfully
- Admin UI shows active interim collections with size, record count, creation time, and retention deadline
- MongoDB connection credentials are stored in encrypted secrets; not logged

**Tech Stack:** MongoDB Atlas or self-hosted; official MongoDB Node.js driver; encrypted secret store

Part of Epic: MongoDB as Interim Database

---

#### 5.2 (#2077) — Schema in MongoDB

Each document in the interim collection holds: `_id` (instance_id as UUID, for idempotent re-runs), `class_id`, `source_capture_id`, `current_data` (full instance JSON), `metadata` (tenant_id, migration_run_id, export_batch_id). This structure gives transform jobs and the load step full context without querying PostgreSQL.

Indexes ensure efficient partitioned reads: compound index on `(class_id, _id)` for Spark partition reads; unique index on `_id` enforces idempotency (re-importing the same instance overwrites rather than duplicates).

**Acceptance Criteria:**
- Export step writes documents matching the defined schema; fields are validated before insert
- Unique index on `_id` is created before first write; re-exports use upsert semantics
- Spark connector can read by `class_id` partition key using the compound index
- Integration test confirms 10,000-row export produces 10,000 documents with no duplicates on re-run

**Tech Stack:** MongoDB; MongoDB Spark Connector indexes; Pydantic/Zod schema validation in export job

Part of Epic: MongoDB as Interim Database

---

#### 5.3 (#2078) — Integration with Migration Steps

The four step types map to MongoDB operations: **Step 1 (export)** reads from PostgreSQL `instance_snapshot` and writes to MongoDB; **Step 2 (transform)** reads MongoDB raw collection, applies translation rules, and writes to a transformed collection; **Step 3 (load)** reads MongoDB transformed collection and bulk-inserts into PostgreSQL target capture; **Step 4 (verify)** compares row counts and optional checksums between transformed collection and target PostgreSQL table.

Each step emits Detective audit events (per FEATURE_ROADMAP_DETECTIVE.md C4) recording the handoff: row counts, checksum aggregates, duration, and any errors.

**Acceptance Criteria:**
- Export step: reads instance_snapshot by `schema_capture_id`; writes to MongoDB in batches of 1,000
- Transform step: applies rule set in-process for ≤1M rows; delegates to Spark (Epic 6) for larger datasets
- Load step: uses PostgreSQL COPY or bulk-insert API; writes new instance and instance_snapshot rows
- Verify step: compares `COUNT(*)` and optional SHA-256 aggregate; marks plan `verified` or `failed`
- All step completion events include row counts and checksum results in Detective audit record

**Tech Stack:** PostgreSQL bulk insert; MongoDB aggregation pipeline for transforms; OpenAPI 3.1 step status

Part of Epic: MongoDB as Interim Database

---

## Epic 6 (#2079): Spark for Parallel Migration

### Summary Table

| #   | Title                           | Description                                                                              | Labels                                         | MVP | Parallel |
|-----|---------------------------------|------------------------------------------------------------------------------------------|------------------------------------------------|-----|----------|
| 6.1 (#2080) | Spark Job Design                | Partition-based data processing; MongoDB Spark Connector reads; per-partition transforms | `enhancement`, `data-transform`                | No  | No       |
| 6.2 (#2081) | Error Handling & Observability  | Failed records to error dataset; progress reported to Apiome; resource controls     | `enhancement`, `data-transform`, `rest`        | No  | Yes      |
| 6.3 (#2082) | Spark as Single Transform Engine| Unify transform and load into one Spark job; shared rule format between in-process/Spark | `enhancement`, `data-transform`                | No  | Yes      |

### Detailed Issue Descriptions

#### 6.1 (#2080) — Spark Job Design

For datasets exceeding the in-process threshold (configurable, default 1M rows), the transform step delegates to an Apache Spark job. The job reads from MongoDB using the MongoDB Spark Connector, partitions by `class_id` or `instance_id` hash, applies translation rules inside Spark UDFs (broadcasting the rule set JSON as a shared variable), validates output against the target JSON Schema, and writes results to MongoDB transformed collection or directly to PostgreSQL via JDBC.

Spark job orchestration is triggered by the migration step plan: `POST /migration-steps/{id}/run` submits the Spark job reference to the batch job system and polls status via Spark REST API, surfacing progress back to the migration step entity.

```
Spark Job: migration_transform_xyz
  Source:   MongoDB migration_run_xyz_raw
  Partition: by class_id (8 partitions)
  Transform: UDF with broadcast(rule_set_json)
  Validate:  broadcast(target_json_schema)
  Sink:      MongoDB migration_run_xyz_transformed
  Workers:   configurable (default: 4 executors, 8GB each)
```

**Acceptance Criteria:**
- Spark job is submitted when step row count exceeds in-process threshold
- Rule set is serialized to JSON and broadcast to Spark workers; UDF applies same logic as in-process engine
- Partitioning key and executor count are configurable per migration plan
- Job progress (% complete, records processed, errors) is polled and surfaced on the migration step status
- Integration test confirms 1M-row transform completes in under 10 minutes on a 4-executor cluster

**Tech Stack:** Apache Spark 3.x; MongoDB Spark Connector; JDBC sink to PostgreSQL; batch job status API

Part of Epic: Spark for Parallel Migration

---

#### 6.2 (#2081) — Error Handling & Observability

Records that fail validation or transform are written to a separate error collection (e.g., `migration_run_xyz_errors`) rather than failing the entire job. The migration run report lists error count, error categories, and sample failing records. Spark job progress (partitions complete, ETA) is reported back to Apiome via polling or callback, and surfaces on the visual migration plan diagram (Epic 4.2).

Resource controls prevent Spark jobs from overwhelming shared clusters: configurable executor count, memory per executor, and a maximum concurrent Spark jobs per tenant setting.

**Acceptance Criteria:**
- Validation failures write to `_errors` collection with: `instance_id`, `class_id`, `error_type`, `error_detail`, `raw_data`
- Migration run report includes: total_rows, success_count, error_count, error_samples (up to 10)
- Migration step status shows Spark progress percentage (updated every 5 seconds)
- `max_concurrent_spark_jobs` tenant setting enforced; excess jobs queue
- Error collection is cleaned up according to the same retention policy as interim collections

**Tech Stack:** MongoDB error collection; Spark job metrics API; tenant rate-limiting config

Part of Epic: Spark for Parallel Migration

---

#### 6.3 (#2082) — Spark as Single Transform Engine

The architecture supports using Spark for both the transform and load steps — reading from MongoDB, applying rules, and writing directly to PostgreSQL via JDBC in one job — removing the need for a separate load step. This reduces pipeline complexity and reuses Spark's partitioned throughput for the write path.

The rule format must be identical between in-process and Spark execution paths (JSON config, not code), so that small migrations can run in-process and large ones can seamlessly delegate to Spark without rule re-authoring.

**Acceptance Criteria:**
- Spark job supports `sink_type: mongodb | postgresql` configuration; `postgresql` uses JDBC with batch size 5,000
- Rule format is a plain JSON document; both in-process engine and Spark UDF consume the same format without transformation
- A migration step configured with `engine: spark` and `sink: postgresql` skips the MongoDB load step entirely
- End-to-end test covers the single-engine path from MongoDB → Spark → PostgreSQL with rule set application and row count verification

**Tech Stack:** Spark JDBC write; shared rule JSON schema; PostgreSQL JDBC driver

Part of Epic: Spark for Parallel Migration
