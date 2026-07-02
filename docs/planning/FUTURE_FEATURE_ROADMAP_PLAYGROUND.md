# Apiome: Playground - Feature Roadmap

> Interactive sandbox environment for experimenting with schemas, APIs, and integrations without affecting production systems. Playground reduces time-to-first-experiment from hours to seconds, driving adoption and enabling safe exploration for developers, learners, and sales teams alike.
>
> **Revenue Model**: Free tier with limits (3 concurrent sessions, 30-minute TTL), paid plans for extended sessions, persistent environments, and collaboration features
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, containerized sandbox backends (Docker/Firecracker), WebSocket for real-time collaboration, REST API backed by PostgreSQL, OpenAPI 3.1 spec

---

## MVP Definition

- One-click sandbox provisioning with isolated schema environment and sample data
- Interactive schema editor with live validation and instant API preview
- Pre-populated sample datasets for common domains (e-commerce, SaaS, healthcare)
- Shareable playground links with configurable expiry
- Auto-cleanup of expired sessions with configurable TTL
- Side-by-side schema comparison for A/B experimentation
- At least 3 guided tutorial scenarios with step-by-step instructions
- Session recording and playback for demos

---

## Epic 1: Sandbox Environment Engine

### Summary Table

| #   | Title                              | Description                                                                                    | Labels                                    | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------------------------|-------------------------------------------|----------|
| 1.1 (#1200) | Environment Provisioning Service   | Backend service that spins up isolated sandbox environments on demand                          | `enhancement`, `mvp`, `playground`, `rest`| Yes      |
| 1.2 (#1201) | Sample Data Library                | Curated dataset library users can inject into their sandbox at creation time                   | `enhancement`, `mvp`, `playground`        | Yes      |
| 1.3 (#1202) | Environment Lifecycle Manager      | TTL tracking, auto-cleanup, session extension, and resource quota enforcement                  | `enhancement`, `mvp`, `playground`, `rest`| No       |
| 1.4 (#1203) | Sandbox Isolation & Security       | Network isolation, resource limits, and tenant data separation for sandbox environments        | `enhancement`, `mvp`, `playground`        | No       |
| 1.5 (#1204) | Environment Dashboard              | UI for listing, launching, and managing active sandbox sessions                                | `enhancement`, `mvp`, `playground`        | No       |

### Detailed Issue Descriptions

---

#### 1.1 (#1200) — Environment Provisioning Service

The provisioning service is the backbone of Playground. When a user clicks "New Sandbox," the service creates a fully isolated Apiome environment — complete with its own schema store, API layer, and data namespace — within seconds.

Each sandbox runs as an isolated namespace in the existing Apiome backend rather than a fully separate deployment. The provisioning service creates a temporary tenant partition with its own `sandbox_` prefixed database schema, seeds it with the platform's core tables, and returns a session token scoped to that namespace. The sandbox exposes the same REST APIs as the main platform, routed through a sandbox-aware proxy that maps the session token to the correct namespace.

The provisioning flow is asynchronous: the API returns a `201 Created` with a sandbox ID and a `status: provisioning` field. The client polls a status endpoint (or receives a WebSocket event) until the status transitions to `ready`. Target provisioning time is under 5 seconds for a basic sandbox.

The service tracks resource usage per user and per tenant to enforce quota limits (concurrent sandboxes, total storage, API call volume). Quota violations return `429 Too Many Requests` with a clear message about which limit was hit.

```
┌──────────────────────────────────────────────────────────┐
│                   Provisioning Flow                      │
│                                                          │
│   User clicks          API creates         Namespace     │
│   "New Sandbox"  ───►  sandbox record ───► provisioned   │
│                        (status: init)      (status: ready)│
│        │                     │                   │        │
│        │              ┌──────▼──────┐            │        │
│        │              │ Create DB   │            │        │
│        │              │ namespace   │            │        │
│        │              │ (sandbox_xx)│            │        │
│        │              └──────┬──────┘            │        │
│        │              ┌──────▼──────┐            │        │
│        │              │ Seed core   │            │        │
│        │              │ tables      │            │        │
│        │              └──────┬──────┘            │        │
│        │              ┌──────▼──────┐            │        │
│        │              │ Inject      │            │        │
│        │              │ sample data │            │        │
│        ▼              └──────┬──────┘            ▼        │
│   Poll status ◄──────────── Ready ──────► Return session │
│   or WebSocket               │               token       │
│                              │                           │
└──────────────────────────────────────────────────────────┘
```

**Acceptance Criteria**

- `POST /api/v1/playground/sandboxes` creates a new sandbox and returns sandbox ID with status `provisioning`
- Provisioning completes within 5 seconds for a basic sandbox (no sample data)
- `GET /api/v1/playground/sandboxes/{id}` returns current status (`provisioning`, `ready`, `error`, `expired`)
- The sandbox namespace is fully isolated from production and other sandboxes
- Quota limits are enforced per user (concurrent sandbox count) and per tenant (total storage)
- `429` response with descriptive message when quota is exceeded

**Tech Stack Callouts**

- REST: `POST /api/v1/playground/sandboxes`, `GET /api/v1/playground/sandboxes/{id}`, `DELETE /api/v1/playground/sandboxes/{id}`
- OpenAPI 3.1: `Sandbox` schema with `id`, `userId`, `tenantId`, `status`, `datasetId`, `createdAt`, `expiresAt`, `sessionToken`
- PostgreSQL: dynamic schema creation (`CREATE SCHEMA sandbox_{id}`) with template seeding
- NextJS: `app/api/v1/playground/sandboxes/route.ts`, `app/api/v1/playground/sandboxes/[id]/route.ts`

Part of Epic: Sandbox Environment Engine

---

#### 1.2 (#1201) — Sample Data Library

Starting with an empty sandbox is intimidating. The sample data library provides curated, realistic datasets that users can inject during sandbox creation. Each dataset is domain-specific and pre-validates against a matching schema set.

The library ships with 5–8 built-in datasets: e-commerce (products, orders, customers), SaaS billing (subscriptions, invoices, usage), healthcare (patients, appointments, records), social platform (users, posts, comments), and IoT (devices, readings, alerts). Each dataset includes 50–200 records with realistic relationships and covers common edge cases (nullable fields, nested objects, arrays).

Datasets are stored as versioned JSON fixtures with an accompanying manifest that describes the target schemas, record counts, and relationship map. Custom datasets can be created by users and saved to their tenant library. The data injection pipeline validates each record against its target schema before inserting it into the sandbox namespace.

Users select a dataset from a Radix UI `Select` dropdown during sandbox creation. A preview panel shows the schema structure and sample records before creation.

**Acceptance Criteria**

- At least 5 built-in datasets covering distinct domains are available at launch
- Each dataset includes 50–200 records with realistic relationships and edge cases
- Dataset selection is available during sandbox creation via a dropdown
- A preview panel shows schema structure and 3–5 sample records before injection
- Custom datasets can be created, saved, and reused within a tenant
- All records are validated against their target schemas during injection; invalid records are logged and skipped

**Tech Stack Callouts**

- Radix UI: `Select` (dataset picker), `Table` (preview records), `ScrollArea`
- REST: `GET /api/v1/playground/datasets` (list), `GET /api/v1/playground/datasets/{id}` (detail with sample records)
- OpenAPI 3.1: `SampleDataset` schema with `id`, `name`, `domain`, `schemaIds`, `recordCount`, `manifest`

Part of Epic: Sandbox Environment Engine

---

#### 1.3 (#1202) — Environment Lifecycle Manager

Sandboxes are ephemeral by design. The lifecycle manager tracks session TTLs, handles automatic cleanup of expired environments, supports session extension requests, and enforces resource budgets.

The manager runs as a background worker that polls for expired sandboxes every 60 seconds. When a sandbox's `expiresAt` timestamp has passed and no extension request is pending, the worker tears down the namespace: drops the database schema, removes any cached artifacts, and marks the sandbox record as `expired`. A 5-minute grace period after expiry allows users to request a one-time extension.

Free-tier sandboxes have a 30-minute TTL. Paid users get configurable TTLs (1 hour, 4 hours, 24 hours, persistent). Extension requests are rate-limited to prevent abuse (max 3 extensions per session). The lifecycle manager also enforces storage quotas: if a sandbox exceeds its allocated storage (50 MB free, 500 MB paid), write operations return `507 Insufficient Storage` until data is reduced.

Users see a countdown timer in the sandbox UI. At 5 minutes before expiry, a Radix UI `Toast` notification warns the user with an "Extend Session" button.

**Acceptance Criteria**

- Background worker detects and cleans up expired sandboxes within 120 seconds of expiry
- Expired namespace database schemas are dropped and sandbox status is set to `expired`
- 5-minute grace period allows one-time extension after expiry
- Free-tier TTL defaults to 30 minutes; paid tiers have configurable TTLs up to 24 hours
- Extension requests are rate-limited to 3 per session
- Storage quota enforcement returns `507` when exceeded; the sandbox remains functional for reads

**Tech Stack Callouts**

- REST: `POST /api/v1/playground/sandboxes/{id}/extend` (request extension)
- OpenAPI 3.1: `SandboxLifecycle` with `expiresAt`, `extensionsUsed`, `maxExtensions`, `storageUsedBytes`, `storageQuotaBytes`
- PostgreSQL: `DROP SCHEMA sandbox_{id} CASCADE` for cleanup
- Radix UI: `Toast` (expiry warning)

Part of Epic: Sandbox Environment Engine

---

#### 1.4 (#1203) — Sandbox Isolation & Security

Playground sandboxes must be fully isolated from production data and from each other. This is a security-critical feature that underpins the entire Playground product.

Isolation is enforced at multiple layers. At the database level, each sandbox uses a separate PostgreSQL schema with a dedicated database role that has zero access to production schemas or other sandbox schemas. At the API level, the sandbox proxy validates that every request's session token maps to a valid, non-expired sandbox and routes queries exclusively to the sandbox's namespace. At the network level, sandbox API endpoints cannot make outbound calls to production services (enforced via network policy or application-level allowlists).

Rate limiting is applied per sandbox to prevent abuse: 100 requests/minute for free tier, 1000 requests/minute for paid. CPU and memory limits are enforced at the process level if sandboxes run as containers, or via query timeout settings in PostgreSQL for namespace-based isolation.

A security audit log records all sandbox creation, access, and teardown events with actor and IP metadata.

**Acceptance Criteria**

- Sandbox database roles cannot query production schemas or other sandbox schemas (verified by automated test)
- Session tokens are validated on every API request; expired or invalid tokens return `401`
- Sandbox API endpoints cannot reach production services via outbound calls
- Per-sandbox rate limits are enforced (100 req/min free, 1000 req/min paid); `429` on violation
- Query timeout of 10 seconds prevents long-running queries from monopolizing resources
- Security audit log captures sandbox lifecycle events with actor, IP, and timestamp

**Tech Stack Callouts**

- PostgreSQL: row-level security, dedicated roles per sandbox namespace
- REST middleware: session token validation, rate limiting, query timeout enforcement
- OpenAPI 3.1: `SandboxAuditEvent` schema with `sandboxId`, `eventType`, `actorId`, `ip`, `timestamp`

Part of Epic: Sandbox Environment Engine

---

#### 1.5 (#1204) — Environment Dashboard

The dashboard is the entry point for Playground. It shows the user's active sandboxes, available datasets, and quick-launch buttons for common scenarios.

The dashboard page at `app/(dashboard)/playground/page.tsx` has three sections: "Your Sandboxes" (active sessions with status, TTL countdown, and actions), "Quick Start" (one-click buttons for popular dataset/schema combinations), and "Recent" (recently expired sandboxes that can be re-created with the same configuration).

Active sandboxes are displayed as cards with a status indicator (green dot for ready, yellow for provisioning, gray for expired), the dataset name, creation time, TTL countdown, and action buttons (Open, Extend, Delete). The "New Sandbox" button opens a Radix UI `Dialog` with dataset selection (1.2) and TTL configuration.

The dashboard refreshes sandbox statuses via polling every 10 seconds. A Radix UI `Badge` on the user's avatar or sidebar shows the count of active sandboxes.

**Acceptance Criteria**

- Dashboard shows all active sandboxes for the current user as cards with status, TTL, and actions
- "New Sandbox" dialog collects dataset selection and TTL preference
- "Quick Start" section offers 3–5 one-click launch options for popular configurations
- "Recent" section shows the last 10 expired sandboxes with a "Re-create" button
- Status auto-refreshes every 10 seconds without full page reload
- Active sandbox count badge appears in the sidebar navigation

**Tech Stack Callouts**

- Radix UI: `Dialog` (create), `Badge` (active count), `DropdownMenu` (card actions), `Progress` (TTL bar)
- NextJS: `app/(dashboard)/playground/page.tsx`
- REST: `GET /api/v1/playground/sandboxes?status=active` (list active), `GET /api/v1/playground/sandboxes?status=expired&limit=10` (recent)

Part of Epic: Sandbox Environment Engine

---

## Epic 2: Interactive Schema Editor & Experimentation

### Summary Table

| #   | Title                               | Description                                                                                 | Labels                                    | Parallel |
|-----|-------------------------------------|---------------------------------------------------------------------------------------------|-------------------------------------------|----------|
| 2.1 (#1206) | Live Schema Editor                  | In-sandbox schema editor with real-time validation and instant API preview                  | `enhancement`, `mvp`, `playground`        | Yes      |
| 2.2 (#1207) | Try-Before-Commit Workflow          | Make schema changes in the sandbox, validate them, and optionally promote to a real project  | `enhancement`, `mvp`, `playground`        | No       |
| 2.3 (#1208) | A/B Schema Comparison               | Side-by-side comparison of two schema designs with diff highlighting                         | `enhancement`, `mvp`, `playground`        | Yes      |
| 2.4 (#1209) | Performance Testing Sandbox         | Run load tests against sandbox APIs to compare schema design performance                    | `enhancement`, `playground`, `rest`       | Yes      |
| 2.5 (#1210) | Validation Playground               | Interactive panel for testing schema validation rules against sample payloads                | `enhancement`, `playground`               | Yes      |

### Detailed Issue Descriptions

---

#### 2.1 (#1206) — Live Schema Editor

The live schema editor is the primary workspace inside a sandbox session. It provides a code editor for writing schema definitions (JSON Schema / OpenAPI) with real-time validation feedback and an instant API preview panel.

The editor layout uses a three-pane design: the schema editor on the left (using Monaco Editor or CodeMirror), a validation panel in the bottom-left showing errors and warnings, and an API preview panel on the right showing the auto-generated REST endpoints, request/response examples, and a "Try It" button for each endpoint.

As the user types, the schema is validated on every keystroke (debounced to 300ms). Errors appear inline with red squiggly underlines and in the validation panel. When the schema is valid, the API preview panel updates to reflect the new endpoints. The "Try It" button sends a real request to the sandbox API and displays the response.

The editor supports multiple files (one per schema class) via Radix UI `Tabs` across the top of the editor pane. Creating a new schema class opens a tab with a starter template.

```
┌───────────────────────────────────────────────────────────┐
│  Tabs: [ User.json ] [ Order.json ] [ Product.json ] [+] │
├────────────────────────────┬──────────────────────────────┤
│                            │  API Preview                 │
│   Schema Editor (Monaco)   │                              │
│                            │  GET  /api/users             │
│   {                        │  POST /api/users             │
│     "type": "object",      │  GET  /api/users/{id}        │
│     "properties": {        │  PUT  /api/users/{id}        │
│       "name": {            │  DEL  /api/users/{id}        │
│         "type": "string"   │                              │
│       }                    │  ┌──────────────────────┐    │
│     }                      │  │  [Try It]            │    │
│   }                        │  │  Response: 200 OK    │    │
│                            │  │  { "id": 1, ... }    │    │
├────────────────────────────┤  └──────────────────────┘    │
│  Validation:               │                              │
│  ✓ Schema valid            │                              │
│  ⚠ Missing "description"  │                              │
└────────────────────────────┴──────────────────────────────┘
```

**Acceptance Criteria**

- Schema editor supports JSON Schema and OpenAPI 3.1 syntax with syntax highlighting
- Real-time validation on keystroke (300ms debounce) with inline error markers
- Validation panel lists all errors and warnings with line numbers and descriptions
- API preview panel auto-generates CRUD endpoint list from valid schemas
- "Try It" sends a real request to the sandbox API and displays the response
- Multiple schema files are managed via tabs; new schemas open from a starter template

**Tech Stack Callouts**

- Radix UI: `Tabs` (schema files), `ScrollArea`, `Badge` (error/warning counts)
- NextJS: `app/(dashboard)/playground/[sandboxId]/editor/page.tsx`
- Monaco Editor or CodeMirror for the code editing surface
- WebSocket for real-time validation feedback

Part of Epic: Interactive Schema Editor & Experimentation

---

#### 2.2 (#1207) — Try-Before-Commit Workflow

Sandboxes are great for experimentation, but the value multiplies when good experiments can be promoted to real projects. The try-before-commit workflow lets users take a schema design they're happy with and push it to an Apiome project as a new version draft.

The promotion flow starts with a "Promote to Project" button in the sandbox toolbar. This opens a Radix UI `Dialog` that asks the user to select a target project (or create a new one), choose which schema classes to promote, and write a change description. A diff view shows what will change in the target project, highlighting additions and modifications.

The promotion creates a draft version in the target project (not a published version) so the standard review and approval workflow still applies. Conflicts with existing classes in the target project are flagged with inline resolution options (keep sandbox version, keep project version, or merge manually).

This feature requires the sandbox to track the provenance of each schema class — whether it was created from scratch in the sandbox or imported from an existing project. Imported classes carry their source project and version reference for accurate diffing.

**Acceptance Criteria**

- "Promote to Project" button opens a dialog with project selection and schema class picker
- Diff view shows additions and modifications relative to the target project's current version
- Promotion creates a draft version in the target project, not a published version
- Conflicts with existing classes are flagged and offer resolution options
- Promotion records provenance: sandbox ID, user, timestamp, and change description
- Users without write access to the target project see an appropriate error message

**Tech Stack Callouts**

- Radix UI: `Dialog`, `Select` (project picker), `Checkbox` (schema class selection), `Tabs` (diff view)
- REST: `POST /api/v1/playground/sandboxes/{id}/promote` with body `{ targetProjectId, schemaClassIds[], description }`
- OpenAPI 3.1: `PromotionRequest` schema; `PromotionResult` with `draftVersionId`, `conflicts[]`

Part of Epic: Interactive Schema Editor & Experimentation

---

#### 2.3 (#1208) — A/B Schema Comparison

When exploring different schema designs, users need to compare them side by side. The A/B comparison feature lets users load two schemas (from different sandboxes, different versions, or the same sandbox before/after a change) and view a structured diff.

The comparison view uses a split-pane layout. The left pane shows Schema A, the right pane shows Schema B. Differences are highlighted inline: green for additions, red for removals, amber for modifications. A summary bar at the top shows the total count of additions, removals, and changes.

Users can switch between "Source" mode (raw JSON diff) and "Semantic" mode (property-level comparison showing type changes, added/removed fields, changed validation rules). Semantic mode is more useful for understanding the design implications; source mode is useful for precise editing.

The comparison can be initiated from the dashboard by selecting two sandboxes, or from within the editor by clicking "Compare" and choosing a comparison target.

**Acceptance Criteria**

- Split-pane view renders two schemas side by side with synchronized scrolling
- Differences are highlighted: green (added), red (removed), amber (changed)
- Summary bar shows counts of additions, removals, and modifications
- Source mode shows raw JSON diff; Semantic mode shows property-level comparison
- Users can initiate comparison from the dashboard (two sandboxes) or from the editor
- Comparison results can be exported as a markdown report

**Tech Stack Callouts**

- Radix UI: `ToggleGroup` (source/semantic mode), `Badge` (change counts), `ScrollArea`
- NextJS: `app/(dashboard)/playground/compare/page.tsx`
- REST: `POST /api/v1/playground/compare` with body `{ schemaA: { source, id }, schemaB: { source, id } }`

Part of Epic: Interactive Schema Editor & Experimentation

---

#### 2.4 (#1209) — Performance Testing Sandbox

Schema design decisions impact API performance. This feature lets users run simple load tests against their sandbox APIs to measure response times, throughput, and error rates under load.

The performance testing panel is accessible from the sandbox editor via a "Perf Test" tab. Users configure the test parameters: target endpoint, request method, payload (auto-generated from the schema or manually entered), concurrency level (1–50 concurrent users), duration (10s–60s), and ramp-up pattern (flat or linear).

The test runs server-side using a lightweight load generator. Results stream back via WebSocket and render in real time as a line chart (response time percentiles) and a summary table (total requests, success rate, p50/p95/p99 latency, throughput in req/s).

This is especially valuable when comparing two schema designs via A/B comparison (2.3) — users can run performance tests on both sandboxes and compare the results side by side.

**Acceptance Criteria**

- Users can configure endpoint, method, concurrency (1–50), duration (10s–60s), and ramp-up pattern
- The test runs server-side and streams results via WebSocket
- Real-time line chart displays response time percentiles during the test
- Summary table shows total requests, success rate, p50/p95/p99 latency, and throughput
- Results are saved and can be compared between different test runs
- Tests are rate-limited to 1 concurrent test per sandbox to prevent resource exhaustion

**Tech Stack Callouts**

- Radix UI: `Tabs` (perf test panel), `Select` (method picker), `Slider` (concurrency), `Table` (results)
- REST: `POST /api/v1/playground/sandboxes/{id}/perf-tests` (start test), `GET /api/v1/playground/sandboxes/{id}/perf-tests/{testId}` (results)
- WebSocket: real-time result streaming
- OpenAPI 3.1: `PerfTestConfig` and `PerfTestResult` schemas

Part of Epic: Interactive Schema Editor & Experimentation

---

#### 2.5 (#1210) — Validation Playground

The validation playground is a focused tool for testing schema validation rules against sample payloads. Users paste or type a JSON payload in one panel and see instant validation results in another — which fields pass, which fail, and why.

The layout is a two-column split: payload editor on the left, validation results on the right. The schema under test is selected from a Radix UI `Select` dropdown at the top. As the user edits the payload, validation runs on every keystroke (debounced) and results update in real time.

Each validation result shows the JSON Pointer path to the failing field, the rule that was violated (type mismatch, pattern failure, minimum/maximum, required field missing, etc.), the expected value, and the actual value. Results are color-coded: green for passing fields, red for failures. A "Fix Suggestions" feature offers one-click corrections for common issues (wrong type, missing required field).

This tool is useful for both schema designers (testing that their validation rules work as expected) and API consumers (understanding why their payloads are being rejected).

**Acceptance Criteria**

- Schema selector dropdown lists all schemas in the current sandbox
- Payload editor accepts JSON with syntax highlighting and bracket matching
- Validation runs on keystroke with 300ms debounce and results update in real time
- Each validation error shows JSON Pointer path, violated rule, expected value, and actual value
- Results are color-coded green (pass) and red (fail) per field
- "Fix Suggestions" offers one-click corrections for type mismatches and missing required fields

**Tech Stack Callouts**

- Radix UI: `Select` (schema picker), `ScrollArea`, `Badge` (pass/fail counts), `Tooltip` (fix suggestions)
- NextJS: `app/(dashboard)/playground/[sandboxId]/validate/page.tsx`
- JSON Schema validation library (Ajv or similar) running client-side for instant feedback

Part of Epic: Interactive Schema Editor & Experimentation

---

## Epic 3: Learning Labs & Guided Tutorials

### Summary Table

| #   | Title                              | Description                                                                                   | Labels                                    | Parallel |
|-----|------------------------------------|-----------------------------------------------------------------------------------------------|-------------------------------------------|----------|
| 3.1 (#1212) | Tutorial Scenario Library          | Curated library of step-by-step learning scenarios covering common schema design patterns      | `enhancement`, `mvp`, `playground`        | Yes      |
| 3.2 (#1213) | Step-by-Step Guide Engine          | Guided walkthrough engine with progress tracking, hints, and validation at each step           | `enhancement`, `mvp`, `playground`        | No       |
| 3.3 (#1214) | Challenge Mode                     | Timed challenges where users build schemas to match requirements with scoring                  | `enhancement`, `playground`               | Yes      |
| 3.4 (#1215) | Certification Exam Prep            | Practice exams simulating Apiome certification with graded questions and explanations      | `enhancement`, `playground`               | Yes      |
| 3.5 (#1216) | Community Scenario Submissions     | Platform for users to create, share, and rate learning scenarios                               | `enhancement`, `playground`               | No       |

### Detailed Issue Descriptions

---

#### 3.1 (#1212) — Tutorial Scenario Library

The scenario library is a browsable catalog of learning experiences, each designed to teach a specific schema design concept or workflow. Scenarios range from beginner ("Create your first schema") to advanced ("Design an event-sourced CQRS system").

Each scenario has metadata: title, difficulty level (beginner/intermediate/advanced), estimated time, concepts covered, and prerequisites. The library page at `app/(dashboard)/playground/learn/page.tsx` displays scenarios as cards organized by difficulty and topic. A filter sidebar (Radix UI `Checkbox` groups) lets users narrow by difficulty, topic (data modeling, API design, validation, relationships), and estimated time.

Scenarios are stored as structured JSON documents containing the scenario metadata, the target schema (the "answer"), the step definitions (for the guide engine, 3.2), and any sample data needed. The library ships with 8–12 built-in scenarios and is extensible via community submissions (3.5).

Clicking a scenario card launches a new sandbox pre-configured for that scenario and opens the guide engine (3.2) in the editor.

**Acceptance Criteria**

- Library page displays at least 8 scenarios as cards with title, difficulty, time estimate, and topic tags
- Scenarios are filterable by difficulty, topic, and estimated time
- Clicking a card creates a pre-configured sandbox and opens the guide engine
- Each scenario includes a description, learning objectives, and prerequisite list
- Scenario completion status is tracked per user (not started, in progress, completed)
- Completed scenarios display a checkmark badge on the card

**Tech Stack Callouts**

- Radix UI: `Checkbox` (filters), `Badge` (difficulty, completion), `ScrollArea`
- NextJS: `app/(dashboard)/playground/learn/page.tsx`, `app/(dashboard)/playground/learn/[scenarioId]/page.tsx`
- REST: `GET /api/v1/playground/scenarios` (list), `GET /api/v1/playground/scenarios/{id}` (detail)
- OpenAPI 3.1: `LearningScenario` schema with `id`, `title`, `difficulty`, `estimatedMinutes`, `topics`, `steps`, `targetSchema`

Part of Epic: Learning Labs & Guided Tutorials

---

#### 3.2 (#1213) — Step-by-Step Guide Engine

The guide engine is a sidebar overlay that walks users through a scenario one step at a time. It's the interactive teaching mechanism that turns static scenarios into hands-on learning experiences.

Each step has a title, instructional text (markdown with inline code samples), a validation condition (e.g., "the User schema has a property named `email` of type `string` with format `email`"), and optional hints. The guide renders as a vertical stepper in a Radix UI `Sheet` side panel.

The current step is highlighted. When the user's sandbox state satisfies the validation condition, the step automatically marks as complete with a satisfying green checkmark animation and the next step activates. If the user is stuck, they can click "Show Hint" (progressive hints, each more specific than the last, up to 3 per step) or "Show Solution" (reveals the exact change needed).

Progress persists across sessions — if a user closes the browser and returns to the same scenario, they resume where they left off.

**Acceptance Criteria**

- Guide renders as a vertical stepper in a side panel with step title, instructions, and status
- Steps auto-complete when the validation condition is met in the sandbox
- Progressive hints (up to 3) are available per step, each more specific than the last
- "Show Solution" reveals the exact change needed and optionally auto-applies it
- Progress persists across sessions via the backend
- The guide can be minimized/collapsed without affecting the sandbox editor

**Tech Stack Callouts**

- Radix UI: `Sheet`, `Accordion` (step details), `Button`, `Collapsible` (hints)
- REST: `GET /api/v1/playground/scenarios/{id}/progress`, `PATCH /api/v1/playground/scenarios/{id}/progress` (update step status)
- OpenAPI 3.1: `ScenarioProgress` schema with `scenarioId`, `currentStep`, `completedSteps[]`, `hintsUsed`

Part of Epic: Learning Labs & Guided Tutorials

---

#### 3.3 (#1214) — Challenge Mode

Challenge mode gamifies schema design. Users are given a set of requirements (e.g., "Design a schema for a library system that supports books, authors, members, and loans") and a time limit. Their solution is scored against multiple criteria.

Scoring evaluates: completeness (does the schema cover all required entities?), correctness (do properties have appropriate types and validation?), relationships (are references properly defined?), documentation (are descriptions present?), and elegance (minimal redundancy, consistent naming). Each criterion is scored 0–100 and a weighted average produces the final score.

The challenge UI shows the requirements panel on the left, the schema editor in the center, and a live score panel on the right that updates as the user builds. A countdown timer is displayed prominently. When time expires (or the user submits early), the final score is calculated and displayed alongside a breakdown and the reference solution.

Challenges are stored similarly to scenarios but include scoring rubrics and time limits. A leaderboard tracks the top scores per challenge (opt-in, anonymized by default).

**Acceptance Criteria**

- Challenge page displays requirements, timer, and live scoring panel
- Scoring evaluates completeness, correctness, relationships, documentation, and elegance
- Timer counts down from the configured limit; submission is automatic at expiry
- Final results show score breakdown, user's solution, and the reference solution side by side
- Leaderboard shows top 50 scores per challenge (opt-in participation)
- At least 5 challenges ship at launch covering different difficulty levels

**Tech Stack Callouts**

- Radix UI: `Progress` (timer bar), `Table` (score breakdown), `Badge` (rank)
- NextJS: `app/(dashboard)/playground/challenges/page.tsx`, `app/(dashboard)/playground/challenges/[id]/page.tsx`
- REST: `POST /api/v1/playground/challenges/{id}/submit`, `GET /api/v1/playground/challenges/{id}/leaderboard`

Part of Epic: Learning Labs & Guided Tutorials

---

#### 3.4 (#1215) — Certification Exam Prep

For users pursuing Apiome platform certification, the exam prep feature provides practice exams that simulate the real certification experience. This drives adoption of the Academy product while using Playground's infrastructure.

Practice exams consist of 20–40 questions in three formats: multiple choice, schema building (sandbox-based), and error identification (find the bug in a given schema). Each question has a time limit, and the overall exam has a total time limit. Questions are drawn from a pool and randomized.

After submission, the user receives a detailed score report: total score, pass/fail against the certification threshold, per-question breakdown with correct answers and explanations, and recommended topics for further study. Historical scores are tracked so users can see their improvement over time.

The exam UI uses a full-screen mode (hiding the sidebar navigation) to simulate a real testing environment. A question navigator sidebar shows answered/unanswered/flagged status.

**Acceptance Criteria**

- Practice exams support multiple choice, schema building, and error identification question types
- Questions are drawn from a pool and randomized for each attempt
- Full-screen exam mode hides sidebar navigation for focus
- Question navigator shows answered/unanswered/flagged status
- Score report includes total score, pass/fail, per-question breakdown, and study recommendations
- Historical scores are tracked with a progress chart showing improvement over time

**Tech Stack Callouts**

- Radix UI: `RadioGroup` (multiple choice), `Badge` (question status), `Progress` (exam timer), `Dialog` (submit confirmation)
- NextJS: `app/(dashboard)/playground/cert-prep/page.tsx`, `app/(dashboard)/playground/cert-prep/[examId]/page.tsx`
- REST: `POST /api/v1/playground/cert-exams/{id}/start`, `POST /api/v1/playground/cert-exams/{id}/submit`

Part of Epic: Learning Labs & Guided Tutorials

---

#### 3.5 (#1216) — Community Scenario Submissions

The best learning content often comes from practitioners. This feature lets users create their own learning scenarios and share them with the community, building a growing library of real-world examples.

The scenario editor provides a structured form for creating a scenario: metadata (title, difficulty, topics, estimated time), step definitions (instruction text, validation conditions, hints, solution), and the target schema. A live preview mode lets the author test their scenario in a sandbox before publishing.

Published scenarios go through a review workflow: submitted → under review → approved/rejected. Approved scenarios appear in the community section of the library. Users can rate scenarios (1–5 stars) and leave feedback. Authors can iterate on their scenarios based on feedback.

Moderation tools for platform admins allow reviewing submissions, providing feedback to authors, and removing inappropriate content.

**Acceptance Criteria**

- Scenario creation form captures all required fields (metadata, steps, target schema, hints, solutions)
- Live preview mode lets authors test their scenario in a sandbox before submitting
- Review workflow supports submitted → under review → approved/rejected statuses
- Approved scenarios appear in a "Community" tab in the scenario library
- Users can rate (1–5 stars) and comment on community scenarios
- Admin moderation panel lists pending submissions with approve/reject actions

**Tech Stack Callouts**

- Radix UI: `Tabs` (step editor), `Textarea`, `Dialog` (submit for review), `RadioGroup` (star rating)
- NextJS: `app/(dashboard)/playground/learn/create/page.tsx`
- REST: `POST /api/v1/playground/scenarios` (create), `POST /api/v1/playground/scenarios/{id}/submit-for-review`, `PATCH /api/v1/playground/scenarios/{id}/review` (approve/reject)

Part of Epic: Learning Labs & Guided Tutorials

---

## Epic 4: Collaboration & Sharing

### Summary Table

| #   | Title                               | Description                                                                                  | Labels                                    | Parallel |
|-----|-------------------------------------|----------------------------------------------------------------------------------------------|-------------------------------------------|----------|
| 4.1 (#1218) | Pair Editing with Live Cursors      | Real-time collaborative editing in sandbox with multiple cursors and presence indicators      | `enhancement`, `playground`               | Yes      |
| 4.2 (#1219) | Shareable Playground Links          | Generate public or auth-gated links to sandbox sessions for demos and collaboration           | `enhancement`, `mvp`, `playground`, `rest`| Yes      |
| 4.3 (#1220) | Session Recording & Playback        | Record a sandbox session and play it back as a video-like walkthrough                        | `enhancement`, `playground`               | No       |
| 4.4 (#1221) | Annotation & Commenting             | Leave comments anchored to specific schema elements, lines, or validation results             | `enhancement`, `playground`               | No       |
| 4.5 (#1222) | Sandbox Forking                     | Clone an existing sandbox to create a divergent copy for parallel experimentation              | `enhancement`, `playground`               | Yes      |

### Detailed Issue Descriptions

---

#### 4.1 (#1218) — Pair Editing with Live Cursors

Pair editing brings real-time collaboration to the Playground. When two or more users open the same sandbox, they see each other's cursors, selections, and edits in real time — similar to Google Docs or VS Code Live Share.

The feature uses WebSocket connections through a collaboration server that maintains the shared editor state via operational transform (OT) or CRDT-based conflict resolution. Each connected user is assigned a unique cursor color and their name appears as a floating label next to their cursor.

A presence bar at the top of the editor shows avatars of all connected users. Clicking an avatar scrolls to that user's cursor position. Users can opt into "follow mode" where their viewport automatically follows another user's cursor.

The collaboration server runs as a separate service that mediates between connected clients and the sandbox's persisted state. On disconnect, the server persists the latest state. On reconnect, the client receives a state sync and resumes editing.

**Acceptance Criteria**

- Multiple users can edit the same sandbox simultaneously with sub-200ms sync latency
- Each user's cursor and selection are visible to others with a unique color and name label
- Presence bar shows connected user avatars; clicking an avatar scrolls to their cursor
- "Follow mode" keeps one user's viewport synced to another user's cursor position
- Conflict resolution handles simultaneous edits to the same line without data loss
- State persists correctly on disconnect/reconnect

**Tech Stack Callouts**

- WebSocket: real-time cursor, selection, and edit synchronization
- Radix UI: `Avatar` (presence bar), `DropdownMenu` (user options), `Switch` (follow mode toggle)
- OT or CRDT library (e.g., Yjs) for conflict-free concurrent editing

Part of Epic: Collaboration & Sharing

---

#### 4.2 (#1219) — Shareable Playground Links

Shareable links let users send sandbox access to anyone — teammates for review, stakeholders for demos, or community members for help. Links can be configured as view-only or collaborative (edit access).

Generating a link opens a Radix UI `Dialog` with options: access level (view-only or edit), authentication requirement (public or requires Apiome login), expiry (1 hour, 24 hours, 7 days, or custom), and a maximum concurrent viewers limit (to prevent resource abuse).

The link resolves to a public page at `app/(public)/playground/shared/[token]/page.tsx` that loads the sandbox in the appropriate mode. View-only mode hides editing controls and disables mutation API calls. Edit mode enables the full editor with collaboration features (4.1).

When the link owner is not online, the shared sandbox still works for the duration of the link's TTL, using the sandbox's existing resources.

**Acceptance Criteria**

- "Share" button generates a link with configurable access level, auth requirement, expiry, and viewer limit
- View-only links render the sandbox without editing controls
- Edit links enable full editing with collaboration features
- Public links work without Apiome login; auth-gated links require login
- Expired or invalid links show a clear error page
- Link owners can revoke links at any time from the dashboard

**Tech Stack Callouts**

- Radix UI: `Dialog` (share config), `RadioGroup` (access level), `Select` (expiry), `TextField` (link display with copy button)
- NextJS: `app/(public)/playground/shared/[token]/page.tsx`
- REST: `POST /api/v1/playground/sandboxes/{id}/shares`, `DELETE /api/v1/playground/sandboxes/{id}/shares/{token}`
- OpenAPI 3.1: `PlaygroundShare` schema with `token`, `sandboxId`, `accessLevel`, `requiresAuth`, `expiresAt`, `maxViewers`

Part of Epic: Collaboration & Sharing

---

#### 4.3 (#1220) — Session Recording & Playback

Session recording captures every action in a sandbox session — edits, API calls, validation results — and produces a replayable timeline that others can watch like a video. This is invaluable for demos, tutorials, and async code review.

Recording is opt-in: users click a "Record" toggle button (Radix UI `Toggle`) in the toolbar. While recording, a red dot indicator is visible. The recorder captures timestamped events: editor changes (as OT operations), API requests/responses, validation results, and user navigation (tab switches, scroll positions).

Playback renders the sandbox in a read-only mode with a timeline scrubber at the bottom. Users can play, pause, skip forward/back, and adjust playback speed (0.5x, 1x, 2x, 4x). A table-of-contents sidebar generated from major events (schema creation, API call, error) allows jumping to key moments.

Recordings are stored as compressed event logs in object storage (S3-compatible). Large recordings are chunked and streamed during playback.

**Acceptance Criteria**

- "Record" toggle starts/stops recording with a visible red dot indicator
- Recordings capture editor changes, API calls, validation results, and navigation events
- Playback renders the sandbox in read-only mode with play/pause/skip/speed controls
- Timeline scrubber allows seeking to any point in the recording
- Table-of-contents sidebar shows major events for quick navigation
- Recordings can be shared via the same sharing mechanism as live sandboxes (4.2)

**Tech Stack Callouts**

- Radix UI: `Toggle` (record button), `Slider` (scrubber), `DropdownMenu` (speed picker), `ScrollArea` (TOC sidebar)
- REST: `POST /api/v1/playground/sandboxes/{id}/recordings/start`, `POST .../stop`, `GET /api/v1/playground/recordings/{recordingId}`
- Object storage: compressed event logs

Part of Epic: Collaboration & Sharing

---

#### 4.4 (#1221) — Annotation & Commenting

Annotations let collaborators leave contextual feedback anchored to specific locations in the sandbox: a line in the schema editor, a specific property definition, a validation error, or an API response. This turns the sandbox into a review workspace.

Comments are anchored to a target (file path + line range, property JSON path, or validation result ID) and have a body (markdown text), author, and timestamp. Comments can be threaded (replies). Resolved comments collapse but remain visible with a "Show resolved" toggle.

The UI renders comment markers as small icons in the editor gutter (for line-anchored comments) or as badges next to properties in the schema tree view. Clicking a marker opens a Radix UI `Popover` with the comment thread. A comments panel (Radix UI `Sheet`) shows all comments across the sandbox in a flat list with filters for resolved/unresolved and author.

Notifications are sent (via the platform's notification system) when a comment is added or replied to.

**Acceptance Criteria**

- Users can add comments anchored to editor lines, schema properties, or validation results
- Comments support markdown formatting and threading (replies)
- Comment markers appear in the editor gutter and schema tree view
- Clicking a marker opens the comment thread in a popover
- Comments panel lists all comments with filters for resolved/unresolved and author
- Resolving a comment collapses it; "Show resolved" toggle reveals resolved comments

**Tech Stack Callouts**

- Radix UI: `Popover` (inline thread), `Sheet` (comments panel), `Textarea`, `Avatar`, `Badge`, `Switch` (show resolved)
- REST: `POST /api/v1/playground/sandboxes/{id}/comments`, `GET /api/v1/playground/sandboxes/{id}/comments`, `PATCH .../comments/{commentId}`
- OpenAPI 3.1: `SandboxComment` schema with `id`, `anchor`, `body`, `authorId`, `parentCommentId`, `resolvedAt`

Part of Epic: Collaboration & Sharing

---

#### 4.5 (#1222) — Sandbox Forking

Forking creates an exact copy of a sandbox at its current state, allowing the user to take the experiment in a different direction without losing the original. This is the "branch" concept applied to sandbox environments.

The fork operation is a server-side copy: the API duplicates the sandbox's database namespace, copies all schema and instance data, and creates a new sandbox record with a reference to the parent. The forked sandbox has its own TTL and lifecycle, independent of the parent.

A "Fork" button in the toolbar triggers the operation. A Radix UI `Dialog` lets the user name the fork and optionally adjust the TTL. After forking, the user is redirected to the new sandbox. The parent sandbox shows a "Forks" section listing child sandboxes.

Forking is particularly useful in combination with A/B comparison (2.3): fork a sandbox, make changes in the fork, then compare the two to evaluate the divergent designs.

**Acceptance Criteria**

- "Fork" creates a complete copy of the sandbox (schemas, data, configuration) with a new ID
- The forked sandbox is independent of the parent (separate TTL, lifecycle, ownership)
- The fork records its parent reference for provenance tracking
- Fork completes within 10 seconds for sandboxes up to 50 MB
- Parent sandbox shows a list of forks with links
- Forked sandboxes can themselves be forked (up to 3 levels deep for MVP)

**Tech Stack Callouts**

- Radix UI: `Dialog` (fork options), `TextField` (fork name)
- REST: `POST /api/v1/playground/sandboxes/{id}/fork` with body `{ name, ttlMinutes }`
- OpenAPI 3.1: `SandboxFork` with `id`, `parentSandboxId`, `name`
- PostgreSQL: schema duplication via `CREATE SCHEMA ... LIKE ... INCLUDING ALL`

Part of Epic: Collaboration & Sharing

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 — Sandbox Environment Engine**
- **1.1** (Provisioning Service) and **1.2** (Sample Data Library) can be built in parallel since the data library is injected via the provisioning flow but can be developed and tested independently with a mock provisioner.
- **1.3** (Lifecycle Manager) requires 1.1 to be functional since it manages provisioned sandboxes.
- **1.4** (Isolation & Security) requires 1.1 since it secures the provisioning pipeline.
- **1.5** (Dashboard) requires 1.1 and 1.3 for listing and managing sandboxes.

**Epic 2 — Interactive Schema Editor & Experimentation**
- **2.1** (Live Schema Editor), **2.3** (A/B Comparison), **2.4** (Performance Testing), and **2.5** (Validation Playground) can all be built in parallel since they are independent editor features.
- **2.2** (Try-Before-Commit) requires 2.1 since it extends the editor with promotion capabilities.

**Epic 3 — Learning Labs & Guided Tutorials**
- **3.1** (Scenario Library) and **3.3** (Challenge Mode) and **3.4** (Certification Prep) can be built in parallel since they are independent learning experiences.
- **3.2** (Guide Engine) depends on 3.1 since it executes the scenarios defined there.
- **3.5** (Community Submissions) depends on 3.1 and 3.2 since community scenarios use the same structure and engine.

**Epic 4 — Collaboration & Sharing**
- **4.1** (Pair Editing), **4.2** (Shareable Links), and **4.5** (Sandbox Forking) can be built in parallel.
- **4.3** (Session Recording) depends on the editor (2.1) being stable since it captures editor events.
- **4.4** (Annotation & Commenting) depends on the editor (2.1) for anchor points.

**Cross-Epic Parallelism**
- All of Epic 2 can begin in parallel with Epic 1 if sandboxes are available for testing. The schema editor (2.1) can be developed against a manually provisioned sandbox before the automated provisioning service (1.1) is complete.
- Epic 3 depends on Epic 1 (sandboxes) and Epic 2 (editor) for the learning environment, but scenario content (3.1) can be authored independently.
- Epic 4 depends on Epic 2 (editor) for the collaboration surface, but shareable links (4.2) and forking (4.5) only depend on Epic 1 (sandbox management).
