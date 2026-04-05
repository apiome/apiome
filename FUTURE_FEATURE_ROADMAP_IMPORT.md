# Objectified: Import System - Feature Roadmap

> Enterprise-grade import system extending the existing OpenAPI importer with audit trails, approval workflows, headless CI/CD integration, scheduled sync, intelligent conflict resolution, multi-source batch import, data transformation pipelines, large-scale performance optimization, and a plugin extension system.
>
> **Revenue Model**: Basic import (single file, URL, drag-and-drop) in all tiers; enterprise features (E1–E23) gated at Pro/Enterprise; approval workflows, transformation pipelines, sandbox staging, and plugin marketplace are Enterprise-only
>
> **Tech Stack**: NextJS App Router, PostgreSQL (import history, jobs), Redis (job queue), WebSocket (import progress), Puppeteer (PDF reports), S3 (large file staging), TypeScript plugin sandbox, OpenAPI 3.1

---

## MVP Definition

- Multi-file upload (batch import multiple specification files) — #498
- AWS API Gateway import integration — #350
- Import from another Objectified project schema registry — #800
- One-click support ticket creation from import error panel — #737
- Post-import auto-actions: auto-layout, auto-connect from `$ref`, auto-tag, auto-validate
- Import review mode: highlight newly imported items; before/after comparison report
- Import History Table: searchable log of all past imports with user attribution

---

## Epic 1: Import History & Audit — #2291

### Summary Table

| #   | Title                                      | Description                                                                         | Labels                                         | MVP | Parallel | Issue |
|-----|--------------------------------------------|-------------------------------------------------------------------------------------|------------------------------------------------|-----|----------|-------|
| 1.1 | Import History Data Model                  | `import_job` table capturing all import metadata, status, source, and user          | `enhancement`, `mvp`, `import`, `rest`        | Yes | No       | #2299 |
| 1.2 | Import History Table UI                    | Searchable, sortable table of all past imports with status, duration, schema count   | `enhancement`, `mvp`, `import`                | Yes | No       | #2300 |
| 1.3 | Import Detail View                         | Click any past import to see event log, schemas imported, warnings, errors, and diff | `enhancement`, `mvp`, `import`                | Yes | No       | #2301 |
| 1.4 | Re-Import from History                     | One-click re-import from the same source with original settings pre-filled           | `enhancement`, `import`                       | No  | Yes      | #2302 |
| 1.5 | Import Comparison (Run-to-Run)             | Side-by-side comparison of two past import runs to see what changed between them    | `enhancement`, `import`                       | No  | Yes      | #2303 |
| 1.6 | Import Audit Export (CSV / JSON)           | Export full import audit log with user attribution for SOC 2 / ISO 27001 compliance | `enhancement`, `mvp`, `import`, `rest`        | Yes | Yes      | #2304 |
| 1.7 | User Attribution on Import Actions         | Every action (initiate, approve, rollback, cancel) logged with user ID, IP, timestamp | `enhancement`, `mvp`, `import`               | Yes | Yes      | #2305 |
| 1.8 | Import History Retention Policy            | Configurable retention: 30d / 90d / 1y / forever with automatic archival to S3      | `enhancement`, `import`                       | No  | Yes      | #2306 |
| 1.9 | Organization-Wide Import Dashboard         | Admin view of import activity across all projects, users, and teams                 | `enhancement`, `import`                       | No  | Yes      | #2307 |

### Detailed Issue Descriptions

#### 1.1 — Import History Data Model — #2299

Create an `import_job` table that serves as the central record for every import operation. Capture the complete lifecycle: from initiation through analysis, preview, conflict resolution, commit, and post-import validation.

```
┌──────────────────────────────────────────────────────┐
│                    import_job                        │
├──────────────────────────────────────────────────────┤
│ id              UUID PK                              │
│ tenant_id       UUID FK                              │
│ project_id      UUID FK                              │
│ version_id      UUID FK                              │
│ initiated_by    UUID FK (users)                      │
│ source_type     ENUM url|file|git|gateway|objectified│
│ source_uri      VARCHAR (URL, filename, or ref)      │
│ format          VARCHAR (openapi3|swagger2|json_schema│
│                          postman|graphql|...)        │
│ status          ENUM pending|analyzing|previewing|   │
│                      committing|complete|failed|     │
│                      rolled_back|cancelled           │
│ schema_count    INTEGER                              │
│ warning_count   INTEGER                              │
│ error_count     INTEGER                              │
│ quality_score   SMALLINT                             │
│ duration_ms     INTEGER                              │
│ event_log       JSONB  (array of {time, event, data})│
│ diff_snapshot   JSONB  (before/after schema states)  │
│ settings_json   JSONB  (import template/preset used) │
│ created_at      TIMESTAMPTZ                          │
│ completed_at    TIMESTAMPTZ                          │
└──────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Every import operation creates an `import_job` record at initiation
- `event_log` updated atomically on each state transition
- `diff_snapshot` populated at commit time for post-import comparison
- Indexes on `(tenant_id, created_at)` and `(project_id, created_at)` for dashboard queries

Part of Epic: Import History & Audit — #2291

---

## Epic 2: Import Access Control & Approval Workflows — #2292

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                       | MVP | Parallel | Issue |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|----------------------------------------------|-----|----------|-------|
| 2.1 | Role-Based Import Permissions               | Define which roles can import directly vs. require approval (configurable)         | `enhancement`, `mvp`, `import`, `security`  | Yes | No       | #2308 |
| 2.2 | Project-Level Import Lock                   | Lock a project/version against imports during release freeze                       | `enhancement`, `import`                     | No  | Yes      | #2309 |
| 2.3 | Approval Workflow for Imports               | Designated approvers must review and approve before commit; configurable           | `enhancement`, `import`                     | No  | No       | #2310 |
| 2.4 | Multi-Approver Support                      | Require N-of-M approvals before a pending import is committed                      | `enhancement`, `import`                     | No  | Yes      | #2311 |
| 2.5 | Approval Notifications                      | Email/Slack/webhook to approvers when an import is pending review                  | `enhancement`, `import`                     | No  | Yes      | #2312 |
| 2.6 | Approval SLA & Auto-Rollback                | Auto-rollback if not approved within configurable window; notify requestor         | `enhancement`, `import`                     | No  | Yes      | #2313 |
| 2.7 | Import Quotas per User / Team               | Limit imports per user/team per day; max schema count per import                   | `enhancement`, `import`                     | No  | Yes      | #2314 |
| 2.8 | Source IP Allowlisting                      | Restrict import source URLs to an admin-approved domain/IP allowlist               | `enhancement`, `import`, `security`         | No  | Yes      | #2315 |

---

## Epic 3: Headless Import API & CI/CD Integration — #2293

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                          | MVP | Parallel | Issue |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-------------------------------------------------|-----|----------|-------|
| 3.1 | REST API for Import                         | `POST /api/v1/imports` accepting spec file or URL; returns job ID                  | `enhancement`, `mvp`, `import`, `rest`         | Yes | No       | #2316 |
| 3.2 | Import Status & Results API                 | `GET /api/v1/imports/{jobId}` — poll status, progress, schema count, errors        | `enhancement`, `mvp`, `import`, `rest`         | Yes | No       | #2317 |
| 3.3 | Import Commit / Rollback API                | `POST /api/v1/imports/{jobId}/commit` and `.../rollback` for programmatic control  | `enhancement`, `import`, `rest`                | No  | Yes      | #2318 |
| 3.4 | Dry Run via API                             | `?dryRun=true` validates and returns analysis/conflict report without committing   | `enhancement`, `import`, `rest`                | No  | Yes      | #2319 |
| 3.5 | CLI Tool (objectified-cli)                  | `objectified import --file openapi.yaml --project my-api --version v2`            | `enhancement`, `import`                        | No  | No       | #2320 |
| 3.6 | GitHub Actions Template                     | Pre-built GHA workflow that imports the latest spec on push to main                | `enhancement`, `import`                        | No  | Yes      | #2321 |
| 3.7 | GitLab CI Template                          | Pre-built GitLab CI job template for automated spec import on pipeline trigger    | `enhancement`, `import`                        | No  | Yes      | #2322 |
| 3.8 | Webhook-Triggered Import                    | Register a URL; on call, auto-triggers import from configured repository/branch   | `enhancement`, `import`, `rest`                | No  | Yes      | #2323 |
| 3.9 | Multi-File Upload                           | Batch import multiple specification files in one session                           | `enhancement`, `mvp`, `import`, `rest`         | Yes | Yes      | #2324 |

### Detailed Issue Descriptions

#### 3.1 — REST API for Import — #2316

Expose a fully documented REST API that allows headless, programmatic import. The API accepts a multipart form upload or a JSON body with a URL, plus all import options available in the UI.

**OpenAPI Endpoints:**
```
POST /api/v1/imports
  Content-Type: multipart/form-data | application/json
  Body: {
    source_type: url | file | git,
    source_uri?: string,       // for URL/git
    file?: binary,             // for file upload
    project_id: UUID,
    version_id: UUID,
    template_id?: UUID,        // import preset to apply
    dry_run?: boolean,
    options?: {
      auto_layout: boolean,
      auto_connect: boolean,
      auto_validate: boolean,
      skip_on_error: boolean
    }
  }
  → 202: { job_id: UUID, status_url: string }

GET /api/v1/imports/{jobId}
  → 200: ImportJob {
      id, status, progress_percent, schema_count,
      warning_count, error_count, results_url
    }

POST /api/v1/imports/{jobId}/commit   → 200: ImportJob
POST /api/v1/imports/{jobId}/rollback → 200: ImportJob
```

**Acceptance Criteria:**
- API key authentication with `import:create` scope required
- Large file uploads (> 10MB) use chunked multipart with S3 staging
- `dry_run=true` returns full analysis including conflict report without persisting any data
- Job status updates every 2 seconds during processing; WebSocket endpoint available as alternative to polling
- `#800` (Objectified schema import) addressed when `source_type = objectified`

Part of Epic: Headless Import API & CI/CD Integration — #2293

---

## Epic 4: Import Templates & Presets — #2294

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel | Issue |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|-------|
| 4.1 | Built-In Import Templates                   | Standard OpenAPI, Minimal, Strict Mode, Migration Mode, Security Audit presets    | `enhancement`, `import`                | No  | No       | #2325 |
| 4.2 | Custom Import Presets                       | Save any import configuration as a named, reusable preset                          | `enhancement`, `import`                | No  | Yes      | #2326 |
| 4.3 | Organization-Wide Preset Sharing            | Admin-created presets shared to all projects/users in the org                     | `enhancement`, `import`                | No  | Yes      | #2327 |
| 4.4 | Preset Auto-Apply per Project               | Set a default preset per project; imports automatically use it                    | `enhancement`, `import`                | No  | Yes      | #2328 |
| 4.5 | Preset Variables                            | Parameterized presets with variables filled at import time                         | `enhancement`, `import`                | No  | Yes      | #2329 |
| 4.6 | Preset Import/Export                        | Share presets as JSON files between organizations or environments                  | `enhancement`, `import`, `rest`        | No  | Yes      | #2330 |

---

## Epic 5: Scheduled Import & Automated Sync — #2295

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel | Issue |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|-------|
| 5.1 | Scheduled Import Configuration             | Cron-like schedule (hourly/daily/weekly) to re-import from URL or Git repository  | `enhancement`, `import`, `rest`        | No  | No       | #2331 |
| 5.2 | Change Detection Before Re-Import           | Compare remote spec hash vs last import; skip if unchanged                         | `enhancement`, `import`                | No  | Yes      | #2332 |
| 5.3 | Differential Import (Incremental)           | On re-import, only process schemas that changed since last import                  | `enhancement`, `import`                | No  | No       | #2333 |
| 5.4 | Schedule Management UI                      | List, enable/disable, edit, and delete scheduled imports from management page      | `enhancement`, `import`                | No  | Yes      | #2334 |
| 5.5 | Schedule Pause on Consecutive Failures      | Auto-pause after N failures; notify admin; require manual resume                   | `enhancement`, `import`                | No  | Yes      | #2335 |
| 5.6 | Git Branch Tracking                         | Poll or webhook to re-import when new commits land on a tracked branch             | `enhancement`, `import`                | No  | Yes      | #2336 |

---

## Epic 6: Conflict Resolution & Intelligence — #2296

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel | Issue |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|-------|
| 6.1 | Conflict Resolution Panel                   | Dedicated wizard step: scrollable list of conflicts with per-conflict resolution   | `enhancement`, `mvp`, `import`         | Yes | No       | #2337 |
| 6.2 | Per-Conflict Resolution Strategies          | Keep Existing, Replace, Merge Additive, Merge Override, Rename, New Version        | `enhancement`, `mvp`, `import`         | Yes | No       | #2338 |
| 6.3 | Visual Property-Level Diff per Conflict     | Side-by-side diff with green/red/yellow property highlighting                      | `enhancement`, `import`                | No  | Yes      | #2339 |
| 6.4 | Bulk Conflict Resolution                    | "Apply to all similar conflicts" button for Replace All, Keep All Existing         | `enhancement`, `import`                | No  | Yes      | #2340 |
| 6.5 | AI-Suggested Conflict Resolutions           | LLM integration suggests best resolution strategy per conflict based on context    | `enhancement`, `import`, `ai`          | No  | Yes      | #2341 |
| 6.6 | Conflict Memory                             | Remember resolution choices per source; auto-apply on re-import                   | `enhancement`, `import`                | No  | Yes      | #2342 |
| 6.7 | Three-Way Merge View                        | When local and remote have both diverged from base import, show three-way merge   | `enhancement`, `import`                | No  | No       | #2343 |

---

## Epic 7: Data Transformation Pipeline — #2297

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel | Issue |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|-------|
| 7.1 | Transformation Rules Engine                 | Define ordered transformation rules applied to schemas during import               | `enhancement`, `import`                | No  | No       | #2344 |
| 7.2 | Property Renaming Rules                     | Regex rules to transform property names (snake_case → camelCase, strip prefixes)  | `enhancement`, `import`                | No  | Yes      | #2345 |
| 7.3 | Type Coercion Rules                         | Map external types to internal types (string:date-time → custom DateTime type)     | `enhancement`, `import`                | No  | Yes      | #2346 |
| 7.4 | Metadata Injection                          | Automatically add required fields to every imported schema (description, owner)   | `enhancement`, `import`                | No  | Yes      | #2347 |
| 7.5 | Vendor Extension Stripping                  | Optionally strip all `x-` vendor extensions to normalize schemas                  | `enhancement`, `import`                | No  | Yes      | #2348 |
| 7.6 | Transformation Preview (Before/After Diff)  | Show diff of transformation effects on schemas before committing                   | `enhancement`, `import`                | No  | Yes      | #2349 |
| 7.7 | Reusable Transformation Profiles            | Named transformation profiles; apply different profiles per project or source     | `enhancement`, `import`                | No  | Yes      | #2350 |

---

## Epic 8: Large-Scale Performance & Database Reverse-Engineering — #2298

### Summary Table

| #    | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel | Issue |
|------|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|-------|
| 8.1  | Chunked File Upload with Resume             | Split large files into chunks; resume if connection drops                          | `enhancement`, `import`                | No  | No       | #2351 |
| 8.2  | Background Import Processing                | Move import execution to background job queue; browser tab can be closed           | `enhancement`, `import`                | No  | No       | #2352 |
| 8.3  | WebSocket Import Progress                   | Real-time progress updates via WebSocket; replace polling for lower latency        | `enhancement`, `import`                | No  | Yes      | #2353 |
| 8.4  | Parallel Schema Processing                  | Batch import independent schemas in parallel rather than sequentially             | `enhancement`, `import`                | No  | Yes      | #2354 |
| 8.5  | SQL DDL Reverse-Engineering Import          | Parse `CREATE TABLE` DDL (PostgreSQL/MySQL/SQL Server) and generate schemas        | `enhancement`, `import`                | No  | No       | #2355 |
| 8.6  | Live Database Connection Import             | Connect to a live database, browse tables, select and import as schemas            | `enhancement`, `import`                | No  | No       | #2356 |
| 8.7  | Postman Collection v2.1 Import              | Parse Postman Collection JSON; extract requests, schemas, and examples             | `enhancement`, `import`                | No  | No       | #2357 |
| 8.8  | DBML / Prisma Schema Import                 | Parse DBML (dbdiagram.io) and Prisma `.prisma` files as schema sources             | `enhancement`, `import`                | No  | Yes      | #2358 |
| 8.9  | Interactive Dependency Graph in Preview     | React Flow graph showing `$ref` dependency chains during the preview step          | `enhancement`, `import`                | No  | No       | #2359 |
| 8.10 | Import Validation Rules Engine             | Custom rules that gate or block imports; quality score threshold; Spectral support | `enhancement`, `import`                | No  | No       | #2360 |
| 8.11 | Import Sandbox / Staging Mode              | Import into isolated staging area; compare vs live before one-click promotion     | `enhancement`, `import`                | No  | No       | #2361 |
| 8.12 | Importer Plugin System                     | TypeScript `IImporter` interface; plugin registry; sandboxed execution            | `enhancement`, `import`                | No  | No       | #2362 |

### Detailed Issue Descriptions

#### 8.5 — SQL DDL Reverse-Engineering Import — #2355

Parse SQL `CREATE TABLE` statements and generate Objectified schema classes. Map column types to JSON Schema types, extract `NOT NULL` as required fields, `UNIQUE` as uniqueItems, `DEFAULT` as default values, and `FOREIGN KEY` constraints as schema `$ref` relationships.

**Column Type Mapping:**
```
VARCHAR(N)     → string, maxLength: N
TEXT           → string
INTEGER/BIGINT → integer
DECIMAL/NUMERIC → number
BOOLEAN        → boolean
UUID           → string, format: uuid
TIMESTAMP      → string, format: date-time
DATE           → string, format: date
JSON/JSONB     → object (with additionalProperties: true)
```

**OpenAPI Endpoints:**
```
POST /api/v1/imports/ddl-analyze
  Body: { ddl: string, dialect: postgresql|mysql|sqlserver }
  → 200: {
      tables_detected: number,
      schemas_preview: SchemaPreview[],
      relationships_detected: number
    }
```

**Acceptance Criteria:**
- Parser handles multi-table DDL files with foreign key cross-references
- Column-to-type mapping configurable per import (override defaults)
- Foreign key constraints generate `$ref` relationships between generated schemas
- Supported dialects: PostgreSQL, MySQL 8+, SQL Server 2016+, SQLite

Part of Epic: Large-Scale Performance & Database Reverse-Engineering — #2298

---

#### 8.10 — Import Validation Rules Engine — #2360

Define organization-level validation rules that run during the analysis step and can gate or block imports. Rules have severity levels: `error` (block), `warning` (allow with notice), `info` (informational).

```typescript
interface ValidationRule {
  id: string;
  name: string;
  category: 'naming' | 'documentation' | 'security' | 'complexity';
  severity: 'error' | 'warning' | 'info';
  evaluate: (schema: SchemaDefinition) => ValidationViolation | null;
}

// Example built-in rule:
const requireDescription: ValidationRule = {
  id: 'docs/require-description',
  name: 'All schemas must have a description',
  category: 'documentation',
  severity: 'warning',
  evaluate: (schema) =>
    schema.description && schema.description.length >= 10
      ? null
      : { message: `Schema "${schema.name}" has no description`, schemaName: schema.name }
};
```

**Quality Gate Configuration:**
```
Import Validation:
  minimum_quality_score:   70   (block imports below this score)
  allow_warnings:          true
  enforce_rules: [
    'naming/pascal-case-classes',
    'docs/require-description',
    'security/no-pii-in-url-params'
  ]
```

**Acceptance Criteria:**
- Quality gate blocks commit when score < configured threshold; shows score in error
- Spectral ruleset `.spectral.yaml` can be uploaded and applied as validation rules
- Rule violations shown inline on schemas in the preview step
- Per-project rule overrides require admin approval before taking effect

Part of Epic: Large-Scale Performance & Database Reverse-Engineering — #2298
