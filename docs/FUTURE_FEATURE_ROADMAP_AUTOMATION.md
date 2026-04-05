# Objectified: Automation & Workflows - Feature Roadmap

> Event-driven automation engine that fires webhooks on schema lifecycle events, executes scheduled maintenance jobs, triggers CI/CD pipelines on publish, and orchestrates configurable approval workflows—eliminating manual steps from the API development lifecycle.
>
> **Revenue Model**: Pro tier for webhooks, Team tier for CI/CD triggers, Enterprise for approval workflows
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, PostgreSQL, Redis (job queue), BullMQ (scheduled jobs), HMAC-SHA256 (webhook signing)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Webhook registration with URL, event filters, and HMAC-SHA256 signing secrets
- Event bus that captures schema lifecycle events (created, updated, deleted, published) and dispatches to registered webhooks
- Webhook delivery with exponential-backoff retry and persistent delivery log
- Webhook testing tool to fire sample events and inspect full request/response cycle
- Scheduled schema backup job with configurable cron expressions and S3-compatible storage
- Periodic stale-schema detection with email notification to schema owners
- Approval workflow for breaking schema changes with configurable reviewer chains
- CI/CD pipeline trigger on version publish via outbound webhooks to GitHub Actions and GitLab CI

---

## Epic 1: Event-Driven Webhooks

### Summary Table

| #   | Title                              | Description                                                                 | Labels                                                  | Parallel |
|-----|------------------------------------|-----------------------------------------------------------------------------|---------------------------------------------------------|----------|
| 1.1 (#1335) | Webhook Registration Data Model    | Design database schema for webhook endpoints, event subscriptions, and secrets | `enhancement`, `mvp`, `automation`, `rest`, `ai-generated` | Yes      |
| 1.2 (#1351) | Event Bus & Dispatch Engine        | Build the internal event bus that captures lifecycle events and fans out to registered webhooks | `enhancement`, `mvp`, `automation`, `rest`, `ai-generated` | No       |
| 1.3 (#1339) | Webhook Signing & Verification     | HMAC-SHA256 request signing and consumer-side verification utilities        | `enhancement`, `mvp`, `automation`, `ai-generated`      | Yes      |
| 1.4 (#1344) | Webhook Testing & Debugging Tools  | Interactive test console for firing sample events and inspecting deliveries | `enhancement`, `mvp`, `automation`, `ai-generated`      | Yes      |
| 1.5 (#1355) | Delivery Logs & Retry Engine       | Persistent delivery log with exponential-backoff retry and dead-letter queue | `enhancement`, `mvp`, `automation`, `rest`, `ai-generated` | No       |

### Detailed Issue Descriptions

---

#### 1.1 (#1335) — Webhook Registration Data Model

The webhook subsystem requires a relational data model to store webhook endpoint registrations, the events each webhook subscribes to, signing secrets, and delivery state. The core entity is `webhook_endpoint` which stores the target URL, an optional description, a signing secret (encrypted at rest), an enabled/disabled toggle, and tenant scoping. Each endpoint subscribes to one or more event types through a `webhook_subscription` junction table.

Event types follow a dot-notation taxonomy: `schema.created`, `schema.updated`, `schema.deleted`, `version.published`, `class.added`, `class.modified`, `class.removed`, `path.created`, `path.updated`, `user.invited`, `user.removed`, `apikey.created`, `apikey.used`. The `event_type` table stores these as an extensible catalog rather than a PostgreSQL enum, allowing new event types to be added without migrations.

A `webhook_delivery` table records every dispatch attempt: the event payload, HTTP status code, response body (truncated to 4 KB), latency in milliseconds, and the attempt number. Deliveries link back to the originating `webhook_event` record, which captures the raw event data and timestamp. This separation allows the same event to be dispatched to multiple endpoints while sharing the event payload.

```
┌───────────────────┐     ┌───────────────────┐
│ webhook_endpoint  │     │  event_type       │
├───────────────────┤     ├───────────────────┤
│ id                │     │ id                │
│ tenant_id         │     │ name              │
│ url               │     │ category          │
│ description       │     │ description       │
│ signing_secret    │◀───┐└───────────────────┘
│ enabled           │    │
│ created_at        │    │  ┌────────────────────┐
│ updated_at        │    ├──│ webhook_subscription│
└───────────────────┘    │  ├────────────────────┤
                         │  │ endpoint_id        │
┌───────────────────┐    │  │ event_type_id      │
│ webhook_event     │    │  │ created_at         │
├───────────────────┤    │  └────────────────────┘
│ id                │    │
│ tenant_id         │    │
│ event_type_id     │────┘
│ payload_json      │
│ occurred_at       │
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ webhook_delivery  │
├───────────────────┤
│ id                │
│ event_id          │
│ endpoint_id       │
│ status_code       │
│ response_body     │
│ latency_ms        │
│ attempt           │
│ delivered_at      │
└───────────────────┘
```

**Acceptance Criteria**

- Database migration creates `webhook_endpoint`, `webhook_subscription`, `event_type`, `webhook_event`, and `webhook_delivery` tables with proper foreign keys and indexes
- `signing_secret` is encrypted at rest using AES-256-GCM with a server-managed key
- `event_type` table is seeded with all lifecycle event types using dot-notation (e.g., `schema.created`)
- All tables include `tenant_id` with composite indexes for tenant-scoped queries
- Cascade delete removes subscriptions when an endpoint is deleted but preserves delivery history
- OpenAPI 3.1 component schemas are defined for all webhook entities

**Part of Epic: Event-Driven Webhooks**

---

#### 1.2 (#1351) — Event Bus & Dispatch Engine

The event bus is the central nervous system of the automation product. Every schema lifecycle action in Objectified emits a structured event into the bus, which then fans it out to all matching webhook subscriptions. The bus operates as an in-process event emitter backed by a Redis stream for durability and cross-instance coordination. When any API endpoint mutates a schema, version, class, path, user, or API key, it publishes an event to the Redis stream with the event type, tenant ID, actor ID, and a JSON payload containing the before/after state.

A dispatcher worker process reads from the Redis stream using a consumer group, ensuring exactly-once processing even across multiple application instances. For each event, the dispatcher queries the `webhook_subscription` table to find all endpoints subscribed to that event type within the tenant. It then enqueues one BullMQ job per endpoint with the delivery payload. This two-stage approach—event capture to Redis stream, then fan-out via BullMQ—decouples event emission from delivery, ensuring that slow or failing webhooks cannot back-pressure the main API.

The delivery payload includes a unique event ID, the event type, a timestamp, and the full event data. The payload is signed with the endpoint's HMAC-SHA256 secret (handled by issue 1.3) and dispatched via HTTP POST with a configurable timeout (default 30 seconds). The `X-Objectified-Event` header carries the event type, and `X-Objectified-Signature` carries the computed signature.

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌────────────┐
│  API Action  │──▶│ Redis Stream │──▶│  Dispatcher  │──▶│  BullMQ    │
│  (publish)   │    │  (durable)   │    │  (consumer   │    │  (per-     │
│              │    │              │    │   group)     │    │  endpoint) │
└─────────────┘    └──────────────┘    └──────────────┘    └────────────┘
                                                                 │
                                              ┌──────────────────┤
                                              ▼                  ▼
                                        ┌──────────┐      ┌──────────┐
                                        │ Endpoint │      │ Endpoint │
                                        │    A     │      │    B     │
                                        └──────────┘      └──────────┘
```

**Acceptance Criteria**

- All schema lifecycle mutations publish events to the Redis stream with type, tenant, actor, and payload
- Dispatcher uses Redis consumer groups for exactly-once delivery across multiple instances
- Fan-out creates one BullMQ job per matching subscription with the signed payload
- Event publishing adds less than 5ms p99 latency to the originating API call
- Unsubscribed event types produce no delivery jobs
- REST API endpoints: `GET /api/v1/automation/events` (list recent events with cursor pagination), `GET /api/v1/automation/events/{id}` (event detail)

**Part of Epic: Event-Driven Webhooks**

---

#### 1.3 (#1339) — Webhook Signing & Verification

Every webhook delivery must be verifiable by the consumer to prevent spoofing. This issue implements HMAC-SHA256 signing of webhook payloads and provides a verification utility that consumers can use server-side. When a webhook endpoint is created, the system generates a cryptographically random 32-byte signing secret. The secret is displayed once to the user and stored encrypted in the database.

At delivery time, the signing module computes `HMAC-SHA256(secret, timestamp + "." + body)` where `timestamp` is the Unix epoch in seconds and `body` is the raw JSON payload. The signature is sent in the `X-Objectified-Signature` header as `t=<timestamp>,v1=<hex-digest>`. Including the timestamp prevents replay attacks; consumers should reject signatures older than a configurable tolerance (recommended: 5 minutes).

The verification SDK is published as a utility function documented in the API docs. The admin UI at `/automation/webhooks/[endpointId]/security` displays the signing secret (revealable), provides a "Rotate Secret" button that generates a new secret with a configurable grace period during which both old and new secrets are accepted, and shows sample verification code in JavaScript, Python, Go, and Ruby.

**Acceptance Criteria**

- Signing computes `HMAC-SHA256(secret, timestamp + "." + rawBody)` and sends it as `X-Objectified-Signature: t=<ts>,v1=<hex>`
- Signing secrets are 32 bytes, cryptographically random, displayed once on creation
- Secret rotation supports a grace period (default 24 hours) where both old and new secrets validate
- `POST /api/v1/automation/webhooks/{id}/rotate-secret` generates a new secret and returns it
- Verification code samples are shown in the UI for JavaScript, Python, Go, and Ruby
- Replay protection documentation recommends rejecting events with timestamps older than the configurable tolerance window

**Part of Epic: Event-Driven Webhooks**

---

#### 1.4 (#1344) — Webhook Testing & Debugging Tools

Developing webhook consumers requires a fast feedback loop. This issue builds an interactive test console that lets users fire sample events at their registered endpoints and inspect the full request/response cycle without waiting for real lifecycle events. The test console lives at `/automation/webhooks/[endpointId]/test`.

The UI presents a Radix `Select` dropdown for choosing an event type and auto-populates a realistic sample payload based on the selected type. Users can edit the payload in a JSON editor before sending. Clicking "Send Test Event" dispatches the webhook synchronously (with a 30-second timeout) and displays the HTTP status code, response headers, response body, round-trip latency, and the computed signature in a tabbed result panel using Radix `Tabs`.

A "Recent Deliveries" panel below the test console shows the last 50 deliveries for the endpoint with sortable columns: event type, status code, latency, timestamp, and attempt count. Clicking a delivery row expands an inline detail view showing the full request payload, request headers (including the signature), response body, and any error messages. Failed deliveries are highlighted with a red status badge.

The REST API backing this feature includes `POST /api/v1/automation/webhooks/{id}/test` which accepts an event type and optional payload override. The endpoint performs a synchronous delivery attempt and returns the full result. The recent deliveries list is served by `GET /api/v1/automation/webhooks/{id}/deliveries` with cursor pagination.

**Acceptance Criteria**

- Test console at `/automation/webhooks/[endpointId]/test` sends sample events and shows the full round-trip result
- Sample payloads are auto-generated for each event type with realistic data
- JSON editor allows payload customization before sending
- Result panel shows status code, headers, body, latency, and signature via Radix `Tabs`
- Recent deliveries list shows last 50 entries with sortable columns and expandable detail rows
- `POST /api/v1/automation/webhooks/{id}/test` endpoint returns synchronous delivery results

**Part of Epic: Event-Driven Webhooks**

---

#### 1.5 (#1355) — Delivery Logs & Retry Engine

Reliable webhook delivery requires automatic retries with backoff and comprehensive logging for troubleshooting. This issue builds the retry engine on top of BullMQ's built-in retry capabilities and adds a queryable delivery log with filtering and search.

The retry policy uses exponential backoff with jitter: delays of 30s, 2m, 15m, 1h, 4h for up to 5 retry attempts. Each attempt is logged as a separate `webhook_delivery` row linked to the same `webhook_event`. After exhausting all retries, the delivery is moved to a dead-letter queue and the endpoint owner is notified via email. Endpoints that fail 95% of deliveries over a 24-hour window are automatically disabled with a notification, preventing wasted compute on permanently broken consumers.

The delivery log UI at `/automation/webhooks/[endpointId]/logs` provides a filterable, paginated table with columns for event type, status (success/failed/pending/dead-lettered), attempt count, timestamp, and latency. Radix `Select` filters for status and event type sit above the table. A date range picker (Radix `Popover` with calendar) constrains the time window. Clicking a row opens a Radix `Dialog` with the full delivery details including request and response payloads.

Bulk operations enable manually retrying all dead-lettered deliveries or purging old logs beyond a retention period (configurable, default 30 days). The REST API exposes `GET /api/v1/automation/webhooks/{id}/deliveries` for listing, `POST /api/v1/automation/webhooks/{id}/deliveries/{deliveryId}/retry` for manual retry, and `DELETE /api/v1/automation/webhooks/{id}/deliveries` with date filters for purging.

**Acceptance Criteria**

- Exponential-backoff retry with jitter: 30s, 2m, 15m, 1h, 4h (5 attempts max)
- Each retry attempt is logged as a separate delivery record with the attempt number
- Dead-letter queue captures deliveries that exhaust all retries; endpoint owner is notified via email
- Endpoints with >95% failure rate over 24 hours are auto-disabled with notification
- Delivery log UI supports filtering by status, event type, and date range with cursor pagination
- Manual retry and bulk purge operations are available via REST API and UI

**Part of Epic: Event-Driven Webhooks**

---

## Epic 2: Scheduled Jobs & Periodic Tasks

### Summary Table

| #   | Title                              | Description                                                                 | Labels                                                  | Parallel |
|-----|------------------------------------|-----------------------------------------------------------------------------|---------------------------------------------------------|----------|
| 2.1 (#1390) | Job Scheduler & BullMQ Integration | Core scheduling engine with cron expressions, job registry, and BullMQ workers | `enhancement`, `mvp`, `automation`, `rest`, `ai-generated` | Yes      |
| 2.2 (#1395) | Schema Maintenance Jobs            | Scheduled backups, validation reports, and stale schema detection           | `enhancement`, `mvp`, `automation`, `ai-generated`      | No       |
| 2.3 (#1401) | Notification Digests & Reports     | Daily/weekly email digests of changes and periodic usage analytics reports  | `enhancement`, `automation`, `ai-generated`             | Yes      |
| 2.4 (#1408) | Expiration & Cleanup Monitors      | License, certificate, and deprecated endpoint expiration alerting and cleanup | `enhancement`, `automation`, `ai-generated`             | Yes      |

### Detailed Issue Descriptions

---

#### 2.1 (#1390) — Job Scheduler & BullMQ Integration

The scheduled jobs subsystem provides a centralized way to define, manage, and monitor periodic tasks within the Objectified platform. The core abstraction is a `scheduled_job` entity that stores the job name, a cron expression, the handler to invoke, a JSON configuration payload, enabled/disabled status, and the last/next run timestamps. The scheduler evaluates cron expressions using `cron-parser` and enqueues jobs into BullMQ repeatable queues.

BullMQ workers process jobs from named queues, one queue per job type. Each worker is stateless and idempotent: if a job fails mid-execution, re-running it with the same input produces the same result. Job execution results (success, failure, duration, output summary) are recorded in a `job_execution` table for audit and debugging. Failed jobs follow a retry policy configurable per job type (default: 3 retries with 60-second linear backoff).

The admin UI at `/automation/jobs` displays all registered jobs in a Radix `Table` with columns for name, cron expression, last run status, next run time, and enabled toggle. A Radix `Dialog` allows editing the cron expression, configuration payload, and retry policy. A "Run Now" button triggers an immediate one-off execution outside the cron schedule. The REST API exposes `GET /api/v1/automation/jobs`, `PUT /api/v1/automation/jobs/{id}`, and `POST /api/v1/automation/jobs/{id}/run`.

```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│  Cron          │     │   BullMQ       │     │   Worker       │
│  Scheduler     │────▶│   Repeatable   │────▶│   Process      │
│                │     │   Queue        │     │                │
└────────────────┘     └────────────────┘     └────────────────┘
        │                                            │
        ▼                                            ▼
┌────────────────┐                           ┌────────────────┐
│ scheduled_job  │                           │ job_execution  │
│ (PostgreSQL)   │                           │ (PostgreSQL)   │
└────────────────┘                           └────────────────┘
```

**Acceptance Criteria**

- Scheduled jobs are defined with cron expressions validated by `cron-parser` library
- BullMQ repeatable queues execute jobs at the specified cron intervals
- Job execution results are persisted with status, duration, output summary, and error details
- Failed jobs retry according to configurable per-job retry policy (default: 3 retries, 60s backoff)
- Admin UI at `/automation/jobs` shows all jobs with status, cron, next run, and enabled toggle
- `POST /api/v1/automation/jobs/{id}/run` triggers immediate execution and returns the job execution ID
- Jobs are scoped per tenant; no cross-tenant job execution

**Part of Epic: Scheduled Jobs & Periodic Tasks**

---

#### 2.2 (#1395) — Schema Maintenance Jobs

This issue implements the built-in maintenance job handlers that keep Objectified schemas healthy and backed up. Three core jobs ship by default: schema backup, periodic validation, and stale schema detection.

The **schema backup** job exports all published schema versions for a tenant as a versioned JSON archive and uploads it to a configurable S3-compatible storage bucket. Backups are namespaced by tenant and timestamped (e.g., `backups/{tenantId}/2026-04-02T00:00:00Z.json.gz`). Retention policies auto-delete backups older than a configurable threshold (default: 90 days). The backup job runs daily by default but the cron expression is tenant-configurable.

The **periodic validation** job re-validates all published schemas against their declared JSON Schema version and generates a report summarizing any validation issues introduced by platform updates or schema drift. Reports are stored as `validation_report` records and surfaced in the admin UI at `/automation/jobs/validation-reports`.

The **stale schema detection** job identifies schemas that have not been updated within a configurable staleness window (default: 180 days). Stale schemas are flagged in the database and their owners receive email notifications with a link to review and either update or archive the schema. The staleness threshold is tenant-configurable via `PUT /api/v1/automation/jobs/{id}` with the threshold in the configuration payload.

**Acceptance Criteria**

- Schema backup job exports all published versions as compressed JSON to S3-compatible storage
- Backup retention auto-deletes archives older than the configured threshold (default 90 days)
- Periodic validation job re-validates all published schemas and produces a summary report
- Validation reports are stored and viewable at `/automation/jobs/validation-reports`
- Stale schema detection flags schemas not updated within the staleness window (default 180 days)
- Stale schema owners receive email notification with a direct link to the schema
- All three jobs are registered by default and tenant-configurable via the jobs admin UI

**Part of Epic: Scheduled Jobs & Periodic Tasks**

---

#### 2.3 (#1401) — Notification Digests & Reports

Rather than flooding users with individual notifications for every change, this issue implements batched email digests that summarize platform activity over configurable intervals. Users subscribe to digest frequencies: daily, weekly, or none. Each digest aggregates schema changes, version publications, team member activity, and alerts from the monitoring jobs (stale schemas, validation issues, expiration warnings) into a single cohesive email.

The digest compiler runs as a scheduled BullMQ job (issue 2.1). At each interval, it queries the event stream for all events within the period, groups them by category (schemas, versions, team, alerts), and renders an HTML email using server-side React templates. The email includes deep links back to the relevant Objectified pages. Users manage their digest preferences at `/settings/notifications` using Radix `RadioGroup` for frequency selection and `Checkbox` for category opt-in/opt-out.

Usage analytics reports are a separate scheduled output for workspace administrators. A weekly report summarizes API key usage counts, most-accessed schemas, active users, and storage consumption. Reports are generated as downloadable PDFs and stored in the `analytics_report` table. The admin UI at `/automation/reports` lists generated reports with download links in a Radix `Table`.

**Acceptance Criteria**

- Users can subscribe to daily, weekly, or no email digest via `/settings/notifications`
- Digests aggregate all events from the period grouped by category (schemas, versions, team, alerts)
- Digest emails include deep links to relevant Objectified pages
- Usage analytics reports are generated weekly for workspace administrators
- Reports include API key usage, most-accessed schemas, active users, and storage metrics
- Generated reports are downloadable as PDF from `/automation/reports`

**Part of Epic: Scheduled Jobs & Periodic Tasks**

---

#### 2.4 (#1408) — Expiration & Cleanup Monitors

Proactive expiration monitoring prevents surprise outages from expired licenses, certificates, and deprecated endpoints. This issue implements monitoring jobs that scan for upcoming expirations and send tiered alerts at configurable thresholds (default: 30 days, 7 days, 1 day before expiry).

The **license expiration monitor** checks workspace license end dates and alerts workspace admins via email and in-app notification. The **certificate expiration monitor** scans TLS certificates associated with custom domain configurations and alerts when certificates approach expiry. The **deprecated endpoint cleanup reminder** identifies API paths marked as deprecated for longer than a configurable period (default: 90 days) and sends reminders to the schema owner suggesting removal or archival.

Each monitor runs as a registered scheduled job (issue 2.1) with its own cron expression and configuration. Alert state is tracked in an `expiration_alert` table to prevent duplicate notifications—once an alert fires at a threshold, it is not re-sent until the next threshold is reached or the item is renewed. The admin UI at `/automation/monitors` shows all monitored items with their expiration dates, alert status, and a color-coded Radix `Table` with status badges (green for safe, yellow for warning, red for critical).

**Acceptance Criteria**

- License expiration alerts fire at 30-day, 7-day, and 1-day thresholds via email and in-app notification
- Certificate expiration monitor scans custom domain TLS certificates and alerts at configured thresholds
- Deprecated endpoint reminders fire after the configured deprecation period (default 90 days)
- Alert deduplication prevents re-sending the same threshold alert for the same item
- Admin UI at `/automation/monitors` shows all monitored items with color-coded expiration status
- Each monitor is individually configurable for cron schedule and alert thresholds via REST API

**Part of Epic: Scheduled Jobs & Periodic Tasks**

---

## Epic 3: Workflow Automation & CI/CD

### Summary Table

| #   | Title                                  | Description                                                                 | Labels                                                  | Parallel |
|-----|----------------------------------------|-----------------------------------------------------------------------------|---------------------------------------------------------|----------|
| 3.1 (#1429) | Approval Workflow Engine               | Configurable approval chains with auto-approve rules, escalation, and notifications | `enhancement`, `automation`, `rest`, `ai-generated`     | Yes      |
| 3.2 (#1436) | CI/CD Pipeline Triggers                | Trigger external CI/CD pipelines on version publish and schema changes      | `enhancement`, `automation`, `rest`, `ai-generated`     | Yes      |
| 3.3 (#1443) | Third-Party Integration Actions        | Slack, Teams, Jira, and Linear integrations triggered by platform events    | `enhancement`, `automation`, `rest`, `ai-generated`     | Yes      |
| 3.4 (#1449) | Automated Code Generation on Publish   | Generate SDKs and client libraries automatically when a version is published | `enhancement`, `automation`, `rest`, `ai-generated`     | No       |
| 3.5 (#1456) | Trigger Action Configuration UI        | Unified dashboard for creating, editing, and managing all trigger actions   | `enhancement`, `automation`, `ai-generated`             | No       |

### Detailed Issue Descriptions

---

#### 3.1 (#1429) — Approval Workflow Engine

Breaking schema changes can cascade failures across downstream consumers. This issue builds a configurable approval workflow engine that gates schema publications behind review and approval steps, ensuring that high-impact changes receive appropriate scrutiny before going live.

An approval workflow is defined as an ordered chain of approval steps, each specifying a set of eligible approvers (by user or role), a required approval count (e.g., 2 of 3 reviewers must approve), and an optional timeout with escalation. The `approval_workflow` entity stores the chain definition; the `approval_request` entity tracks a specific workflow execution initiated when a user attempts to publish a schema version flagged for review.

Auto-approve rules allow tenants to bypass the workflow for minor changes. Rules are defined as conditions: if no fields were removed, no required fields were added, and no type changes occurred, the publish proceeds without approval. These rules are evaluated by diffing the schema against its previous version. When all changes are classified as non-breaking by the diff engine, auto-approve fires. Breaking changes always require the full approval chain.

Each step in the chain triggers email and in-app notifications to the eligible approvers. The approval request UI at `/automation/approvals/[requestId]` shows the schema diff, the approval chain progress, and action buttons (Approve, Reject, Request Changes). If no action is taken within the step timeout (default: 48 hours), the request escalates to the next level in the chain or to a configured escalation contact.

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐
│  Publish  │──▶│  Diff Engine │──▶│  Auto-Approve│──▶│ Published│
│  Request  │    │  (breaking?) │    │  Rules Check │    │          │
└──────────┘    └──────────────┘    └──────────────┘    └──────────┘
                       │                    │
                       │ breaking           │ rules fail
                       ▼                    ▼
                ┌──────────────┐    ┌──────────────┐
                │  Approval    │──▶│  Step 1:     │
                │  Request     │    │  Reviewers   │──▶ Step 2 ──▶ ...
                │  Created     │    │  Notified    │
                └──────────────┘    └──────────────┘
                                          │
                                          │ timeout
                                          ▼
                                   ┌──────────────┐
                                   │  Escalation  │
                                   └──────────────┘
```

**Acceptance Criteria**

- Approval workflows are defined as ordered chains of steps with eligible approvers and required approval counts
- Auto-approve rules bypass the workflow when all changes are non-breaking (no removed fields, no type changes)
- Email and in-app notifications fire at each step to eligible approvers
- Approval request UI shows schema diff, chain progress, and Approve/Reject/Request Changes actions
- Timeout escalation promotes the request to the next step or escalation contact after the configured period (default 48h)
- REST API: `POST /api/v1/automation/workflows`, `GET /api/v1/automation/approvals`, `POST /api/v1/automation/approvals/{id}/approve`
- Approval history is audited with actor, action, timestamp, and optional comment

**Part of Epic: Workflow Automation & CI/CD**

---

#### 3.2 (#1436) — CI/CD Pipeline Triggers

Schema changes should propagate through the deployment pipeline automatically. This issue builds outbound triggers that invoke external CI/CD systems when a schema version is published, a draft is created, or a schema is modified. Supported targets include GitHub Actions (via `repository_dispatch`), GitLab CI (via pipeline triggers), and generic webhook endpoints for Jenkins, CircleCI, and other systems.

Each trigger is configured with a target type, authentication credentials (stored encrypted), the events that activate it, and a payload template. The payload template uses Handlebars-style interpolation to inject event data: `{{schema.name}}`, `{{version.number}}`, `{{actor.email}}`, etc. A preview mode renders the template against a sample event so users can verify the payload structure before enabling the trigger.

Four built-in trigger templates ship by default: "Run Tests on Schema Change" (triggers a test suite in the target CI system), "Deploy Mock Server on Draft" (spins up a mock server from the draft schema), "Generate SDK on Release" (kicks off code generation on publish), and "Trigger Pipeline on Publish" (generic pipeline invocation). Users can clone and customize these templates or create triggers from scratch.

The admin UI at `/automation/triggers` uses a Radix `Table` for the trigger list, `Dialog` for creation/editing, and `Tabs` for switching between trigger configuration, payload template, and execution history. The REST API exposes `POST /api/v1/automation/triggers`, `PUT /api/v1/automation/triggers/{id}`, and `GET /api/v1/automation/triggers/{id}/executions`.

**Acceptance Criteria**

- Triggers support GitHub Actions (`repository_dispatch`), GitLab CI (pipeline trigger), and generic webhooks
- Trigger credentials (tokens, API keys) are stored encrypted with AES-256-GCM
- Payload templates use Handlebars-style interpolation with preview mode for verification
- Four built-in templates ship by default: test, mock deploy, SDK generation, generic pipeline
- Trigger execution history records status, response, latency, and error details
- Admin UI at `/automation/triggers` provides CRUD with tabbed layout for config, template, and history
- Triggers fire only for the configured event types and respect enabled/disabled state

**Part of Epic: Workflow Automation & CI/CD**

---

#### 3.3 (#1443) — Third-Party Integration Actions

Schema lifecycle events often need to reach team communication and project management tools. This issue builds native integrations for Slack, Microsoft Teams, Jira, and Linear that fire automatically on configured events. Each integration is a specialized trigger action with pre-built payload formatting and OAuth-based authentication.

The **Slack integration** posts formatted messages to a configured channel using the Slack Web API. Messages include the event type, schema name, actor, a summary of changes, and deep links back to Objectified. Message formatting uses Slack Block Kit for rich layout with section blocks, context elements, and action buttons. The **Microsoft Teams integration** posts Adaptive Cards to a configured incoming webhook URL with equivalent content and styling.

The **Jira integration** creates issues in a configured project when breaking changes are detected. The issue includes the schema diff, affected consumers, and a link to the approval request. Fields are mapped from the event payload to Jira fields via a configurable template. The **Linear integration** provides equivalent functionality, creating issues with labels, assignees, and linked schema references via Linear's GraphQL API.

Each integration is configured at `/automation/integrations` using a guided setup wizard (Radix `Dialog` with multi-step form). OAuth flows for Slack and Jira are handled via the standard OAuth 2.0 authorization code flow with PKCE. Teams and Linear use webhook URLs and API tokens respectively. Integration health is monitored with periodic test pings; unhealthy integrations are flagged in the admin UI with a warning badge.

**Acceptance Criteria**

- Slack integration posts Block Kit messages to configured channels via OAuth-authenticated Web API
- Teams integration posts Adaptive Cards to incoming webhook URLs
- Jira integration creates issues on breaking changes with configurable project, issue type, and field mapping
- Linear integration creates issues with labels and assignees from configurable templates
- OAuth 2.0 + PKCE flow handles Slack and Jira authentication with token refresh
- Integration health checks run periodically; unhealthy integrations display warnings in the admin UI
- All integrations respect event type filters and are individually toggleable

**Part of Epic: Workflow Automation & CI/CD**

---

#### 3.4 (#1449) — Automated Code Generation on Publish

One of the highest-value automation actions is generating client SDKs and type definitions immediately when a schema version is published. This issue builds a code generation trigger action that invokes Objectified's code generation engine (or a configured external generator) and publishes the output to a configured artifact repository or git branch.

When a version is published and a code generation trigger is active, the system enqueues a BullMQ job that: (1) fetches the published schema version, (2) runs the configured generators (TypeScript types, OpenAPI spec, JSON Schema bundle, or custom templates), (3) commits the generated output to a configured git repository branch or uploads it to an artifact store (npm registry, Maven, PyPI), and (4) records the generation result with links to the published artifacts.

The configuration UI at `/automation/triggers/[triggerId]/codegen` allows selecting which generators to run, the target repository/registry, authentication credentials, and the branch naming convention (e.g., `codegen/schema-{name}/v{version}`). A dry-run mode generates the output and displays it in the UI without publishing, allowing users to preview before enabling automatic publication.

**Acceptance Criteria**

- Code generation trigger fires automatically on version publish when enabled
- Supported generators: TypeScript types, OpenAPI 3.1 spec, JSON Schema bundle, custom templates
- Generated output is committable to a git repository branch or uploadable to npm/Maven/PyPI
- Dry-run mode generates and previews output without publishing
- Generation results record status, output artifact links, duration, and any errors
- Credentials for git and artifact registries are stored encrypted with AES-256-GCM
- Generator selection and target configuration are managed via the admin UI

**Part of Epic: Workflow Automation & CI/CD**

---

#### 3.5 (#1456) — Trigger Action Configuration UI

The trigger action configuration UI is the unified management surface for all automation actions—webhooks, CI/CD triggers, third-party integrations, approval workflows, and code generation triggers. This issue builds the top-level dashboard and the shared configuration components that tie the automation product together.

The dashboard at `/automation` presents a summary view with cards for each automation category: Webhooks (count of active endpoints, recent delivery success rate), Scheduled Jobs (count of active jobs, last failure timestamp), Triggers (count of active triggers, recent execution count), Integrations (count of connected services, health status), and Approval Workflows (count of pending approvals, average approval time). Each card links to its respective management page.

A global event timeline at `/automation/timeline` shows a chronological feed of all automation activity: webhook deliveries, job executions, trigger firings, integration messages, and approval actions. The timeline uses infinite scroll with Radix `ScrollArea` and supports filtering by category, status (success/failure), and date range using Radix `Select` and `Popover` components. Each timeline entry is expandable to show full details.

The settings page at `/automation/settings` provides tenant-level defaults: global retry policy, default webhook timeout, digest email sender address, event retention period, and feature flags for enabling/disabling entire automation categories. Settings are persisted via `PUT /api/v1/automation/settings` and loaded at application startup. The REST API also exposes `GET /api/v1/automation/settings` for reading current configuration.

**Acceptance Criteria**

- Dashboard at `/automation` shows summary cards for webhooks, jobs, triggers, integrations, and approvals
- Each card displays key metrics (counts, success rates, health status) with links to detail pages
- Global event timeline at `/automation/timeline` shows all automation activity with category and status filters
- Timeline supports infinite scroll and expandable detail entries
- Settings page at `/automation/settings` manages tenant-level defaults for retry, timeout, retention, and feature flags
- `PUT /api/v1/automation/settings` persists tenant settings; `GET /api/v1/automation/settings` returns current values
- Navigation integrates with the existing Objectified sidebar under an "Automation" section

**Part of Epic: Workflow Automation & CI/CD**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 (Event-Driven Webhooks):**
- 1.1 (Data Model), 1.3 (Signing), and 1.4 (Testing Tools) can all be developed in parallel. The data model defines the tables, signing is a standalone cryptographic module, and the testing UI can be built against mocked endpoints.
- 1.2 (Event Bus) depends on 1.1 for the `webhook_event` and `webhook_subscription` tables.
- 1.5 (Retry Engine) depends on 1.2 for the BullMQ job infrastructure and 1.1 for the `webhook_delivery` table.

**Epic 2 (Scheduled Jobs & Periodic Tasks):**
- 2.3 (Notification Digests) and 2.4 (Expiration Monitors) can be developed in parallel since they are independent job handlers.
- 2.2 (Schema Maintenance) depends on 2.1 for the job scheduler and BullMQ integration.
- 2.3 and 2.4 also depend on 2.1 for job registration but their handler logic can be developed concurrently against the job interface.

**Epic 3 (Workflow Automation & CI/CD):**
- 3.1 (Approval Engine), 3.2 (CI/CD Triggers), and 3.3 (Third-Party Integrations) are independent engines and can be built in parallel.
- 3.4 (Code Generation) depends on 3.2 for the trigger infrastructure and payload template system.
- 3.5 (Configuration UI) depends on all other Epic 3 issues being at least partially implemented, as it provides the unified dashboard surface.

**Cross-Epic Parallelism:**
- Epic 1 and Epic 2 are fully independent and can be developed by separate teams simultaneously.
- Epic 3 depends on Epic 1 (event bus, issue 1.2) for receiving lifecycle events that trigger workflows.
- Epic 2 (issue 2.1, job scheduler) is a prerequisite for Epic 3 issue 3.4 (code generation uses BullMQ jobs).
- Epic 3 issue 3.5 (dashboard UI) should be started last, after at least one issue from each epic is functional.
