# Objectified: Integrations & APIs - Feature Roadmap

> Core platform integration layer providing advanced Git workflows (branch-per-version, PR-based schema review, bidirectional sync), configurable webhooks for event-driven automation, and third-party API tool connectors (Postman, Insomnia, SwaggerHub, API gateways)—making Objectified the hub of the API development workflow.
>
> **Revenue Model**: Pro tier for webhooks, Team tier for third-party connectors
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, PostgreSQL, Redis (webhook queue), Git CLI/libgit2, OAuth2 (third-party auth)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Branch-per-version Git strategy with automatic branch creation on schema version publish
- Pull request workflow for schema review with diff rendering and approval gates
- Configurable webhooks for core platform events (schema published, version created, class modified)
- Webhook delivery logs with retry and failure alerting
- Postman collection export from published schemas
- OAuth2 credential management for third-party service connections
- Integration dashboard showing connected services, webhook health, and sync status
- REST API for all integration configuration (OpenAPI 3.1 documented)

---

## Epic 1: Git Workflow Extensions

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                            | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|---------------------------------------------------|----------|
| 1.1 (#1336) | Branch-Per-Version Strategy        | Auto-create Git branches when schema versions are published                  | `enhancement`, `mvp`, `integrations`, `rest`, `ai-generated`      | Yes      |
| 1.2 (#1350) | Pull Request Schema Review         | Open PRs for schema changes with rendered diffs and approval gates           | `enhancement`, `mvp`, `integrations`, `rest`, `ai-generated`      | Yes      |
| 1.3 (#1359) | Bidirectional Git Sync Engine      | Two-way sync between Objectified schemas and Git repository files            | `enhancement`, `integrations`, `rest`, `ai-generated`             | No       |
| 1.4 (#1367) | Git Conflict Resolution UI         | Visual conflict resolution when bidirectional sync detects divergence         | `enhancement`, `integrations`, `ai-generated`                     | No       |

### Detailed Issue Descriptions

---

#### 1.1 (#1336) — Branch-Per-Version Strategy

The existing Git integration stores schema snapshots in a repository, but all versions land on a single branch. This issue introduces a branch-per-version strategy where publishing a new schema version automatically creates a dedicated Git branch named `schema/{schemaName}/v{version}`. This enables teams to use standard Git tooling—cherry-picks, diffs between branches, CI pipelines triggered per branch—against their schema history.

When a user publishes version N of a schema, the backend calls the Git provider API (or local Git CLI via libgit2 bindings) to create a branch from the current HEAD of the schema's trunk branch. The schema JSON, OpenAPI spec, and any generated artifacts are committed to this branch. A `branch_metadata` table in PostgreSQL tracks the mapping between schema versions and Git branches, including remote URL, branch name, commit SHA, and creation timestamp.

The configuration page at `/app/integrations/git/branching` uses a Radix `Switch` to enable branch-per-version globally or per-schema. A Radix `Select` allows choosing the branch naming convention (`schema/{name}/v{n}`, `release/v{n}`, or custom template). The page also displays a branch history table using Radix `Table` showing all created branches with links to the remote provider.

```
                          ┌─────────────────────┐
  Schema Published ──────▶│  Version Event Bus  │
                          └─────────┬───────────┘
                                    │
                          ┌─────────▼───────────┐
                          │  Branch Strategy     │
                          │  Engine              │
                          └─────────┬───────────┘
                                    │
                   ┌────────────────┼────────────────┐
                   ▼                ▼                ▼
           schema/user/v1   schema/user/v2   schema/user/v3
                   │                │                │
                   └────────────────┴────────────────┘
                                    │
                          ┌─────────▼───────────┐
                          │   Remote Git Repo   │
                          └─────────────────────┘
```

REST endpoints include `POST /api/v1/integrations/git/branches` (manually trigger branch creation), `GET /api/v1/integrations/git/branches` (list branches with schema/version mapping), `GET /api/v1/integrations/git/branches/{id}` (branch detail with commit history), and `PUT /api/v1/integrations/git/config` (update branching strategy configuration).

**Acceptance Criteria**
- Publishing a schema version auto-creates a Git branch following the configured naming convention
- Branch contains the schema JSON, generated OpenAPI spec, and commit metadata
- `branch_metadata` table records schema ID, version, branch name, commit SHA, and remote URL
- Branching can be enabled/disabled per-schema via the configuration UI
- Custom branch name templates support `{name}`, `{version}`, and `{date}` placeholders
- Branch creation failures are logged and surfaced in the integration dashboard with retry option

**Part of Epic: Git Workflow Extensions**

---

#### 1.2 (#1350) — Pull Request Schema Review

Schema changes in a team environment benefit from the same review discipline as code changes. This issue builds a pull request workflow where modifying a schema opens a PR on the connected Git provider (GitHub, GitLab, Bitbucket) with a rendered schema diff, reviewer assignment, and approval gates that block version publication until the PR is approved.

When a user saves a schema draft, the system creates a feature branch (`schema-review/{schemaName}/{draftId}`), commits the updated schema files, and opens a PR against the schema's trunk branch. The PR body includes a markdown-rendered diff showing added, removed, and modified fields with type information. Reviewer assignment follows the schema's configured ownership rules stored in a `schema_reviewers` table. The PR status is polled (or received via webhook from the Git provider) and reflected in the Objectified UI.

The review page at `/app/integrations/git/reviews` lists open PRs with status badges using Radix `Badge` components. Clicking a review opens a detail view at `/app/integrations/git/reviews/[reviewId]` with the schema diff rendered inline, reviewer status, and action buttons (approve, request changes, merge). A Radix `AlertDialog` confirms merge actions. The page also shows a timeline of review comments pulled from the Git provider.

REST endpoints include `POST /api/v1/integrations/git/reviews` (create review PR), `GET /api/v1/integrations/git/reviews` (list open reviews), `GET /api/v1/integrations/git/reviews/{id}` (detail with diff and comments), `POST /api/v1/integrations/git/reviews/{id}/approve` (approve), and `POST /api/v1/integrations/git/reviews/{id}/merge` (merge and publish version).

**Acceptance Criteria**
- Saving a schema draft with review enabled opens a PR on the connected Git provider
- PR body includes a rendered diff showing field additions, removals, and type changes
- Reviewer assignment follows configured schema ownership rules
- Schema version publication is blocked until the PR is approved and merged
- Review status syncs bidirectionally between the Git provider and Objectified UI
- Merge action triggers schema version publication and branch-per-version creation (if enabled)

**Part of Epic: Git Workflow Extensions**

---

#### 1.3 (#1359) — Bidirectional Git Sync Engine

The current Git integration is push-only: Objectified writes schemas to Git but does not read changes back. This issue builds a bidirectional sync engine that detects changes made directly in the Git repository (via external editors, CI pipelines, or other tools) and reconciles them with the Objectified schema store. This enables teams where some members prefer editing schema YAML/JSON in their IDE while others use the Objectified UI.

The sync engine runs on a configurable schedule (default: every 5 minutes) or can be triggered manually. It compares the HEAD commit of each tracked branch against the last-synced commit SHA stored in the `sync_state` table. When new commits are detected, the engine parses the changed schema files, validates them against Objectified's schema rules, and applies the changes as a new draft or version. Conflicts (where both Objectified and Git have diverged since the last sync) are flagged for manual resolution (see 1.4).

```
┌──────────────┐                    ┌──────────────┐
│  Objectified │◄──── Sync ────────▶│  Git Repo    │
│  Schema DB   │     Engine         │  (remote)    │
└──────┬───────┘                    └──────┬───────┘
       │                                   │
       │  ┌──────────────────────┐         │
       └──▶  sync_state table   ◀──────────┘
           │  schema_id         │
           │  last_commit_sha   │
           │  last_synced_at    │
           │  sync_direction    │
           │  conflict_status   │
           └──────────────────────┘
```

Configuration lives at `/app/integrations/git/sync` with Radix `Switch` for enabling sync, a Radix `Slider` for sync interval, and a Radix `RadioGroup` for sync direction (push-only, pull-only, bidirectional). A sync history log shows recent sync operations with status, commit range, and any validation errors.

REST endpoints include `POST /api/v1/integrations/git/sync/trigger` (manual sync), `GET /api/v1/integrations/git/sync/status` (current sync state per schema), `GET /api/v1/integrations/git/sync/history` (sync operation log), and `PUT /api/v1/integrations/git/sync/config` (update sync settings).

**Acceptance Criteria**
- External Git commits containing schema changes are detected and imported into Objectified
- Imported schemas pass validation before being applied as drafts
- Sync state table tracks last-synced commit SHA per schema to enable incremental sync
- Conflicts between Objectified edits and Git edits are detected and flagged (not silently overwritten)
- Sync interval is configurable from 1 minute to 60 minutes via the UI
- Manual sync trigger is available via both the UI button and REST API

**Part of Epic: Git Workflow Extensions**

---

#### 1.4 (#1367) — Git Conflict Resolution UI

When bidirectional sync (1.3) detects that both Objectified and the Git repository have diverged, the changes cannot be auto-merged. This issue builds a visual conflict resolution interface that presents both versions side-by-side, highlights conflicting fields, and lets the user choose which version to keep—or manually edit a merged result.

The conflict resolution page at `/app/integrations/git/conflicts/[conflictId]` displays a three-pane layout: the Objectified version (left), the Git version (right), and the merged result (center). Conflicting fields are highlighted with Radix-styled diff markers. Each conflict region offers three buttons: "Use Ours" (Objectified), "Use Theirs" (Git), or "Edit" (opens inline editor). A Radix `Progress` bar tracks the number of resolved vs. unresolved conflicts.

The conflict list page at `/app/integrations/git/conflicts` uses Radix `Table` to display all unresolved conflicts with schema name, conflict date, and field count. Conflicts older than a configurable threshold (default: 7 days) trigger an email notification to schema owners. Resolving all conflicts and clicking "Apply Resolution" commits the merged schema to both Objectified and Git, advancing the sync state.

REST endpoints include `GET /api/v1/integrations/git/conflicts` (list unresolved conflicts), `GET /api/v1/integrations/git/conflicts/{id}` (conflict detail with both versions and field-level diffs), `PUT /api/v1/integrations/git/conflicts/{id}/resolve` (submit resolution), and `POST /api/v1/integrations/git/conflicts/{id}/dismiss` (dismiss conflict, keeping current Objectified version).

**Acceptance Criteria**
- Conflicts display both versions side-by-side with field-level diff highlighting
- Users can resolve each conflict region individually (ours, theirs, or manual edit)
- Applying a resolution commits the merged schema to both Objectified DB and Git repository
- Unresolved conflicts older than the configured threshold trigger owner notifications
- Conflict list page shows count, schema name, and age for all pending conflicts
- Dismissed conflicts are recorded in the audit log with the dismissing user

**Part of Epic: Git Workflow Extensions**

---

## Epic 2: Webhooks & Event System

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                            | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|---------------------------------------------------|----------|
| 2.1 (#1383) | Webhook Configuration & CRUD API   | Create, update, and manage webhook endpoints with event subscriptions        | `enhancement`, `mvp`, `integrations`, `rest`, `ai-generated`      | Yes      |
| 2.2 (#1391) | Event Dispatch Pipeline            | Redis-backed event queue with reliable delivery and ordering guarantees      | `enhancement`, `mvp`, `integrations`, `rest`, `ai-generated`      | Yes      |
| 2.3 (#1402) | Webhook Testing & Debugging Tools  | Interactive webhook tester with payload preview and delivery simulation      | `enhancement`, `mvp`, `integrations`, `ai-generated`              | No       |
| 2.4 (#1412) | Webhook Delivery Logs & Retry      | Searchable delivery log with configurable retry policies and dead letter queue| `enhancement`, `mvp`, `integrations`, `rest`, `ai-generated`      | No       |

### Detailed Issue Descriptions

---

#### 2.1 (#1383) — Webhook Configuration & CRUD API

Webhooks allow external systems to react to Objectified platform events without polling. This issue builds the webhook configuration system where users create webhook endpoints, subscribe them to specific event types, and manage their lifecycle. Each webhook has a target URL, a secret for HMAC-SHA256 signature verification, a set of subscribed event types, and an active/paused status.

The `webhooks` table stores `id`, `tenant_id`, `name`, `url`, `secret_hash`, `events` (text array), `status` (active, paused, failed), `created_by`, `created_at`, and `updated_at`. The `webhook_events` enum includes: `schema.published`, `version.created`, `class.added`, `class.modified`, `class.deleted`, `user.invited`, `user.removed`, `apikey.used`, `apikey.created`, and `apikey.revoked`. Secrets are stored hashed; the raw secret is shown only once at creation time.

The webhook management page at `/app/integrations/webhooks` lists configured webhooks in a Radix `Table` with name, URL (truncated), subscribed event count, status badge, and last delivery timestamp. A Radix `Dialog` form handles creation with fields for name, URL, event type multi-select (Radix `Checkbox` group), and an auto-generated secret with a copy button. Editing and deleting use the same dialog pattern.

REST endpoints include `POST /api/v1/integrations/webhooks` (create), `GET /api/v1/integrations/webhooks` (list with cursor pagination), `GET /api/v1/integrations/webhooks/{id}` (detail), `PUT /api/v1/integrations/webhooks/{id}` (update URL, events, status), `DELETE /api/v1/integrations/webhooks/{id}` (delete), and `POST /api/v1/integrations/webhooks/{id}/rotate-secret` (rotate HMAC secret).

**Acceptance Criteria**
- Webhook creation returns the HMAC secret exactly once; subsequent reads return only a masked prefix
- Event type subscription supports selecting any combination of the defined platform events
- Webhook status can be toggled between active and paused without deletion
- Secret rotation generates a new secret and invalidates the previous one immediately
- List endpoint supports filtering by status and event type with cursor pagination
- All webhook mutations are recorded in the platform audit log

**Part of Epic: Webhooks & Event System**

---

#### 2.2 (#1391) — Event Dispatch Pipeline

The dispatch pipeline is the backbone that captures platform events, enqueues them to Redis, and delivers them to subscribed webhook endpoints. Reliability is critical: events must not be lost even if a webhook endpoint is temporarily unreachable. This issue builds the producer (event capture), broker (Redis queue), and consumer (HTTP delivery) components.

When a platform event occurs (e.g., a schema is published), the originating service publishes a message to a Redis Stream keyed by event type. Each message contains a standardized envelope: `event_id` (UUID), `event_type`, `timestamp`, `tenant_id`, `actor_id`, `payload` (event-specific JSON). A consumer group reads from the stream, fans out to all webhooks subscribed to that event type, and delivers via HTTP POST with the payload in the body and an `X-Objectified-Signature` header containing the HMAC-SHA256 digest.

```
┌────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  Platform   │────▶│  Redis       │────▶│  Dispatcher   │────▶│  Webhook     │
│  Event      │     │  Stream      │     │  Consumer     │     │  Endpoint    │
└────────────┘     └──────────────┘     └───────┬───────┘     └──────────────┘
                                                │
                                        ┌───────▼───────┐
                                        │  delivery_log │
                                        │  table        │
                                        └───────────────┘
```

Delivery attempts are logged in the `webhook_delivery_log` table with `webhook_id`, `event_id`, `attempt_number`, `response_status`, `response_body` (truncated to 1KB), `latency_ms`, and `delivered_at`. Successful deliveries (2xx responses) acknowledge the message in the Redis consumer group. Failed deliveries are left unacknowledged for retry processing (see 2.4).

**Acceptance Criteria**
- Platform events are published to Redis Streams within 100ms of occurrence
- Each subscribed webhook receives an HTTP POST with the event payload and HMAC signature
- The `X-Objectified-Signature` header contains a valid HMAC-SHA256 computed with the webhook's secret
- Delivery attempts are logged with status code, latency, and truncated response body
- Events are delivered in order per webhook endpoint (no parallel delivery to the same URL)
- Consumer group ensures each event is processed exactly once under normal operation

**Part of Epic: Webhooks & Event System**

---

#### 2.3 (#1402) — Webhook Testing & Debugging Tools

Configuring webhooks without a way to test them leads to frustrating trial-and-error debugging in production. This issue builds an interactive testing tool that lets users send test events to their webhook endpoints, inspect the exact payload and headers that will be delivered, and view the endpoint's response—all without waiting for a real platform event.

The testing page at `/app/integrations/webhooks/[id]/test` provides a Radix `Select` for choosing an event type, a JSON editor (pre-populated with a realistic sample payload for the selected event type), and a "Send Test" button. After delivery, the page shows the request (URL, headers including signature, body) and response (status code, headers, body) in a split-pane layout using Radix `Tabs`. A Radix `Badge` shows pass/fail based on whether the endpoint returned a 2xx status.

The page also includes a "Payload Preview" mode that renders the exact HTTP request without sending it, useful for verifying signature computation logic on the receiving end. Sample payloads are generated from actual schema data in the tenant's account (with sensitive fields redacted) to ensure realistic testing.

REST endpoints include `POST /api/v1/integrations/webhooks/{id}/test` (send test event, returns request/response details) and `GET /api/v1/integrations/webhooks/sample-payloads/{eventType}` (get sample payload for an event type).

**Acceptance Criteria**
- Test events are sent to the webhook URL with the same signature and headers as production events
- The test UI displays the full HTTP request and response for inspection
- Sample payloads are generated from real tenant data with sensitive field redaction
- Test deliveries are marked as `test: true` in the delivery log to distinguish from real events
- Payload preview mode renders the HTTP request without actually sending it
- Each event type has a realistic sample payload that matches the production schema

**Part of Epic: Webhooks & Event System**

---

#### 2.4 (#1412) — Webhook Delivery Logs & Retry

Production webhook systems need visibility into delivery history and automatic retry for transient failures. This issue builds the searchable delivery log UI and the configurable retry engine with exponential backoff, dead letter queue, and automatic webhook disabling after sustained failures.

The retry engine processes failed deliveries (non-2xx responses or timeouts) using exponential backoff: 30 seconds, 2 minutes, 10 minutes, 1 hour, 6 hours. After 5 failed attempts, the event is moved to a dead letter queue (`webhook_dead_letters` table) and the webhook's failure counter increments. When a webhook accumulates 50 consecutive failures, its status is automatically set to `failed` and the owner receives an email notification.

The delivery log page at `/app/integrations/webhooks/[id]/logs` displays a Radix `Table` with event type, delivery status (Radix `Badge`: success, retrying, failed, dead-lettered), attempt count, response code, latency, and timestamp. Filters include date range (Radix `DatePicker`), status, and event type. Clicking a row opens a Radix `Dialog` with the full request/response details. A "Retry" button on dead-lettered events re-enqueues them for delivery.

REST endpoints include `GET /api/v1/integrations/webhooks/{id}/deliveries` (paginated delivery log), `GET /api/v1/integrations/webhooks/{id}/deliveries/{deliveryId}` (detail with request/response), `POST /api/v1/integrations/webhooks/{id}/deliveries/{deliveryId}/retry` (re-enqueue dead-lettered event), and `GET /api/v1/integrations/webhooks/{id}/stats` (delivery success rate, average latency, failure count).

**Acceptance Criteria**
- Delivery log is searchable by date range, status, and event type with cursor pagination
- Failed deliveries retry with exponential backoff up to 5 attempts before dead-lettering
- Webhooks are auto-disabled after 50 consecutive failures with email notification to the owner
- Dead-lettered events can be manually retried via the UI or REST API
- Delivery stats endpoint returns success rate, average latency, and failure count over configurable windows
- Retry schedule is configurable per webhook (backoff multiplier, max attempts, timeout)

**Part of Epic: Webhooks & Event System**

---

## Epic 3: Third-Party API Connectors

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                            | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|---------------------------------------------------|----------|
| 3.1 (#1430) | Connector Framework & OAuth2 Manager| Generic connector interface with OAuth2 token lifecycle management           | `enhancement`, `mvp`, `integrations`, `rest`, `ai-generated`      | Yes      |
| 3.2 (#1440) | Postman & Insomnia Export/Sync     | Export schemas as Postman/Insomnia collections with optional live sync       | `enhancement`, `mvp`, `integrations`, `rest`, `ai-generated`      | Yes      |
| 3.3 (#1448) | SwaggerHub Integration             | Publish and sync Objectified schemas to/from SwaggerHub organizations        | `enhancement`, `integrations`, `rest`, `ai-generated`             | Yes      |
| 3.4 (#1457) | API Gateway Connectors             | Push schema-derived configurations to AWS API Gateway, Kong, and Apigee     | `enhancement`, `integrations`, `rest`, `ai-generated`             | No       |
| 3.5 (#1462) | GraphQL Gateway Bridge             | Generate GraphQL schema and resolvers from Objectified REST schemas          | `enhancement`, `integrations`, `rest`, `ai-generated`             | No       |

### Detailed Issue Descriptions

---

#### 3.1 (#1430) — Connector Framework & OAuth2 Manager

Every third-party integration in Epic 3 shares common concerns: OAuth2 authentication, credential storage, connection health checks, and a standardized sync interface. This issue builds the connector framework that all specific integrations (Postman, SwaggerHub, API gateways) plug into, along with the OAuth2 token lifecycle manager that handles authorization code flows, token refresh, and secure credential storage.

The `connectors` table stores `id`, `tenant_id`, `provider` (enum: postman, insomnia, swaggerhub, aws_apigw, kong, apigee, graphql), `name`, `status` (connected, disconnected, error), `config_json` (provider-specific settings), `created_at`, and `updated_at`. The `connector_credentials` table stores `connector_id`, `access_token_enc` (AES-256 encrypted), `refresh_token_enc`, `token_expires_at`, `scopes`, and `last_refreshed_at`. Token refresh runs proactively 5 minutes before expiration via a scheduled job.

The connectors page at `/app/integrations/connectors` shows a grid of available providers as Radix `Card` components, each with a provider logo, connection status badge, and "Connect" / "Disconnect" button. Clicking "Connect" initiates the OAuth2 flow via a popup window. Connected providers show a "Configure" link to provider-specific settings. A Radix `AlertDialog` confirms disconnection with a warning about active syncs.

```
┌─────────────────────────────────────────────────────────┐
│  Integrations > Connectors                              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  Postman    │  │  Insomnia   │  │  SwaggerHub │    │
│  │  ● Connected│  │  ○ Not      │  │  ● Connected│    │
│  │             │  │    connected│  │             │    │
│  │ [Configure] │  │  [Connect]  │  │ [Configure] │    │
│  └─────────────┘  └─────────────┘  └─────────────┘    │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  AWS API GW │  │  Kong       │  │  Apigee     │    │
│  │  ○ Not      │  │  ○ Not      │  │  ○ Not      │    │
│  │    connected│  │    connected│  │    connected│    │
│  │  [Connect]  │  │  [Connect]  │  │  [Connect]  │    │
│  └─────────────┘  └─────────────┘  └─────────────┘    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

REST endpoints include `GET /api/v1/integrations/connectors` (list connectors with status), `POST /api/v1/integrations/connectors` (initiate connection, returns OAuth2 redirect URL), `GET /api/v1/integrations/connectors/{id}` (detail with config), `PUT /api/v1/integrations/connectors/{id}` (update config), `DELETE /api/v1/integrations/connectors/{id}` (disconnect and revoke tokens), and `POST /api/v1/integrations/connectors/{id}/health` (check connection health).

**Acceptance Criteria**
- OAuth2 authorization code flow works for all supported providers with PKCE
- Access and refresh tokens are stored AES-256 encrypted at rest
- Token refresh runs proactively before expiration; expired tokens trigger re-authentication prompt
- Connector health check verifies token validity and API reachability
- Disconnecting a connector revokes tokens on the provider side when the provider supports it
- All connector operations are scoped to the tenant and recorded in the audit log

**Part of Epic: Third-Party API Connectors**

---

#### 3.2 (#1440) — Postman & Insomnia Export/Sync

Postman and Insomnia are the most popular API testing tools. This issue builds export functionality that converts published Objectified schemas into Postman Collection v2.1 and Insomnia v4 export formats, along with optional live sync that automatically pushes collection updates when schemas change.

The export engine transforms an Objectified schema into the target format: each class becomes a folder, each field with REST annotations becomes a request, and example values populate request bodies and query parameters. The generated collection includes authentication templates (Bearer token, API key) derived from the schema's security definitions. Export is available as a one-time download or as continuous sync to the user's Postman workspace or Insomnia cloud via their respective APIs.

The export page at `/app/integrations/connectors/postman/export` (and equivalent for Insomnia) uses a Radix `Select` to choose the schema, a Radix `Checkbox` group for selecting which classes to include, and Radix `RadioGroup` for export mode (download vs. live sync). A preview pane shows the generated collection structure before export. For live sync, a Radix `Select` picks the target Postman workspace and collection (fetched via the Postman API using stored OAuth2 credentials from 3.1).

REST endpoints include `POST /api/v1/integrations/postman/export` (generate and return collection JSON), `POST /api/v1/integrations/postman/sync` (push to Postman workspace), `GET /api/v1/integrations/postman/sync/status` (sync state), `POST /api/v1/integrations/insomnia/export` (generate Insomnia export), and `POST /api/v1/integrations/insomnia/sync` (push to Insomnia cloud).

**Acceptance Criteria**
- Exported Postman collections conform to Collection v2.1 format and import cleanly into Postman
- Exported Insomnia files conform to v4 export format and import cleanly into Insomnia
- Each schema class maps to a request folder with properly typed request bodies and parameters
- Live sync updates the remote collection within 60 seconds of a schema publish event
- Export supports selective class inclusion via checkbox selection
- Authentication templates are derived from the schema's OpenAPI security schemes

**Part of Epic: Third-Party API Connectors**

---

#### 3.3 (#1448) — SwaggerHub Integration

SwaggerHub is a common hub for sharing OpenAPI specs across teams. This issue builds bidirectional sync between Objectified schemas and SwaggerHub APIs, allowing teams to publish Objectified schemas to SwaggerHub for external sharing and import SwaggerHub specs into Objectified for schema management.

The sync engine translates Objectified's internal schema representation into a complete OpenAPI 3.1 document and pushes it to SwaggerHub via their API (`POST /apis/{owner}/{api}/{version}`). In the reverse direction, importing from SwaggerHub fetches the OpenAPI spec, extracts schema components, and creates corresponding Objectified classes and fields. Version mapping tracks which Objectified schema version corresponds to which SwaggerHub API version.

The SwaggerHub integration page at `/app/integrations/connectors/swaggerhub` displays connected SwaggerHub organizations (fetched via the SwaggerHub API). A Radix `Table` shows the mapping between Objectified schemas and SwaggerHub APIs with sync status. The "Publish to SwaggerHub" action uses a Radix `Dialog` to select target organization, API name, and version. The "Import from SwaggerHub" action lists available APIs for selection.

REST endpoints include `POST /api/v1/integrations/swaggerhub/publish` (push schema to SwaggerHub), `POST /api/v1/integrations/swaggerhub/import` (pull SwaggerHub API into Objectified), `GET /api/v1/integrations/swaggerhub/mappings` (list schema-to-API mappings), and `PUT /api/v1/integrations/swaggerhub/mappings/{id}` (update mapping configuration).

**Acceptance Criteria**
- Published OpenAPI documents are valid OpenAPI 3.1 and render correctly in SwaggerHub
- Importing a SwaggerHub API creates Objectified classes with correct field types and constraints
- Version mappings are maintained so re-publishing updates the correct SwaggerHub API version
- Sync conflicts (both sides changed) are flagged for manual resolution
- The integration respects SwaggerHub organization permissions and visibility settings
- Connection health is verified before sync operations with clear error messages on failure

**Part of Epic: Third-Party API Connectors**

---

#### 3.4 (#1457) — API Gateway Connectors

API gateways enforce schemas at runtime, but configuring them manually is error-prone and drifts from the source of truth. This issue builds connectors that push schema-derived configurations to AWS API Gateway, Kong, and Apigee—automatically creating or updating routes, request validators, and response models when schemas change in Objectified.

Each gateway connector translates Objectified schemas into the provider's configuration format: AWS API Gateway uses OpenAPI import with request validators and usage plans; Kong uses declarative config with request-validator and rate-limiting plugins; Apigee uses API proxy bundles with JSON-to-JSON policies. The translation layer is provider-specific but shares a common interface from the connector framework (3.1). A dry-run mode generates the configuration without applying it, allowing review before deployment.

The gateway connector page at `/app/integrations/connectors/[provider]/gateway` displays a mapping table (Radix `Table`) linking Objectified schemas to gateway routes. A "Deploy" button triggers configuration push with a Radix `AlertDialog` confirmation showing the changes that will be applied. A "Dry Run" button generates the configuration and displays it in a code viewer using Radix `ScrollArea`. Deployment history shows past pushes with status, timestamp, and diff.

REST endpoints include `POST /api/v1/integrations/gateways/{provider}/deploy` (push config to gateway), `POST /api/v1/integrations/gateways/{provider}/dry-run` (generate config without applying), `GET /api/v1/integrations/gateways/{provider}/mappings` (list schema-to-route mappings), `PUT /api/v1/integrations/gateways/{provider}/mappings/{id}` (update mapping), and `GET /api/v1/integrations/gateways/{provider}/deployments` (deployment history).

**Acceptance Criteria**
- AWS API Gateway connector creates/updates REST APIs with request validators from Objectified schemas
- Kong connector generates declarative config with request-validator plugin for each mapped route
- Apigee connector generates API proxy bundles with schema-based validation policies
- Dry-run mode generates provider-specific config without applying it to the target gateway
- Deployment history records each push with the diff, status, and any provider-side errors
- Schema changes can optionally auto-deploy to the gateway (configurable per mapping)

**Part of Epic: Third-Party API Connectors**

---

#### 3.5 (#1462) — GraphQL Gateway Bridge

Many teams operate both REST and GraphQL APIs. This issue builds a bridge that generates a GraphQL schema and resolver stubs from Objectified REST schemas, enabling teams to serve their schema-defined data via a GraphQL endpoint without maintaining a separate schema definition.

The bridge translates Objectified classes into GraphQL types, fields into GraphQL fields with appropriate scalar types, and REST endpoints into Query and Mutation definitions. Relationships between classes (via foreign key fields or explicit relations) become GraphQL connections with pagination. The generated schema includes input types for mutations and filter types for query arguments. Resolver stubs are generated as TypeScript files that proxy to the underlying REST endpoints.

The GraphQL bridge page at `/app/integrations/connectors/graphql` shows the generated GraphQL schema in a read-only code viewer with syntax highlighting. A Radix `Tabs` component switches between the schema view, resolver preview, and a live playground (embedding GraphiQL). A "Regenerate" button re-derives the GraphQL schema from the current Objectified schemas. A Radix `Switch` enables automatic regeneration on schema publish events.

REST endpoints include `POST /api/v1/integrations/graphql/generate` (generate GraphQL schema and resolvers), `GET /api/v1/integrations/graphql/schema` (retrieve current generated schema), `GET /api/v1/integrations/graphql/resolvers` (download resolver stubs as a zip), and `PUT /api/v1/integrations/graphql/config` (configure type mapping overrides and connection pagination style).

**Acceptance Criteria**
- Generated GraphQL schema compiles without errors and passes schema validation
- Objectified classes map to GraphQL types with correct scalar type translations
- Foreign key relationships generate GraphQL connections with cursor-based pagination
- Resolver stubs compile as TypeScript and correctly proxy to REST endpoints
- The embedded GraphiQL playground executes queries against the generated schema
- Automatic regeneration triggers within 30 seconds of a schema publish event

**Part of Epic: Third-Party API Connectors**

---

## Parallel Work Guide

**Epic 1 — Git Workflow Extensions**:
Issues 1.1 (Branch-Per-Version) and 1.2 (Pull Request Review) can be developed in parallel as they operate on independent Git operations—branching vs. PR creation. Issue 1.3 (Bidirectional Sync) depends on the branch metadata model from 1.1 for tracking sync state against versioned branches. Issue 1.4 (Conflict Resolution) depends directly on 1.3 for conflict detection data.

**Epic 2 — Webhooks & Event System**:
Issues 2.1 (Webhook Configuration) and 2.2 (Event Dispatch Pipeline) can be developed in parallel—one builds the configuration layer, the other builds the delivery infrastructure. Issue 2.3 (Testing Tools) depends on both 2.1 (for webhook details) and 2.2 (for the delivery mechanism). Issue 2.4 (Delivery Logs & Retry) depends on 2.2 for the delivery log table and retry queue.

**Epic 3 — Third-Party API Connectors**:
Issues 3.1 (Connector Framework), 3.2 (Postman/Insomnia), and 3.3 (SwaggerHub) can all begin in parallel—3.2 and 3.3 can stub the OAuth2 layer while 3.1 builds it, then integrate. Issue 3.4 (API Gateway Connectors) depends on 3.1 for the connector interface and credential management. Issue 3.5 (GraphQL Bridge) depends on 3.1 for connector infrastructure but is otherwise independent of other connectors.

**Cross-Epic Parallelism**: All three epics are independent and can be developed by separate teams simultaneously. Epic 2 (Webhooks) produces the event infrastructure that Epic 1 (Git Workflows) and Epic 3 (Connectors) consume for triggering syncs on schema changes—but the event types can be stubbed early, so this is not a blocking dependency. Within Epic 3, the connector framework (3.1) should be prioritized as the foundation, but UI work for individual connectors can proceed in parallel using mock credential stores.
