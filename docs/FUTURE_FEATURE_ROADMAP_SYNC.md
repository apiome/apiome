# Objectified: Sync (Real-time Sync) - Feature Roadmap

> Real-time schema synchronization and conflict resolution for distributed teams and multi-region deployments—keeping schemas, instances, and environments consistent across geographies, teams, and toolchains.
>
> **Revenue Model**: Per-sync-endpoint pricing, enterprise multi-region packages
>
> **Tech Stack**: NextJS (app router), Radix UI, PostgreSQL, Redis (pub/sub, presence), WebSocket (real-time), CRDTs (Yjs/Automerge), OpenAPI 3.1, NATS/Kafka (event streaming)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- CRDT-based schema sync protocol that resolves concurrent edits without data loss
- Real-time co-editing of schema definitions with presence indicators (cursors, selections)
- Conflict detection and resolution UI for structural schema conflicts
- Environment sync between dev, staging, and production with approval gates
- Git repository bi-directional sync (push schema changes to Git, pull Git changes to Objectified)
- Sync event log with full history of sync operations and conflict resolutions
- Offline mode with automatic sync on reconnect for interrupted connections
- Sync health dashboard showing endpoint status, latency, and conflict rates

---

## Epic 1: Core Sync Engine

### Summary Table

| #   | Title                                | Description                                                                  | Labels                                 | Parallel |
|-----|--------------------------------------|------------------------------------------------------------------------------|----------------------------------------|----------|
| 1.1 (#1271) | CRDT Schema Document Model           | Define the CRDT-backed data model for schema documents                       | `enhancement`, `mvp`, `sync`           | Yes      |
| 1.2 (#1272) | Sync Protocol & Transport Layer      | WebSocket-based sync protocol with binary delta encoding                     | `enhancement`, `mvp`, `sync`, `rest`   | Yes      |
| 1.3 (#1273) | Conflict Detection & Classification  | Detect and classify conflicts by severity: auto-resolvable vs. manual        | `enhancement`, `mvp`, `sync`           | No       |
| 1.4 (#1274) | Conflict Resolution UI               | Visual interface for reviewing and resolving structural schema conflicts     | `enhancement`, `mvp`, `sync`           | No       |
| 1.5 (#1275) | Sync Event Log & Audit Trail         | Append-only log of all sync operations with correlation IDs                  | `enhancement`, `mvp`, `sync`, `rest`   | Yes      |

### Detailed Issue Descriptions

---

#### 1.1 (#1271) — CRDT Schema Document Model

Traditional last-writer-wins synchronization loses data when two editors change the same schema simultaneously. This issue defines a CRDT (Conflict-free Replicated Data Type) model for Objectified schema documents that guarantees convergence—all replicas eventually reach the same state regardless of operation order.

The model represents each schema as a Yjs `Y.Doc` containing: a `Y.Map` for schema metadata (name, version, description), a `Y.Array` of class definitions, and within each class a `Y.Map` of properties. Each property contains its type, constraints, and description as CRDT fields. This hierarchical CRDT structure allows concurrent edits to different classes or different properties within the same class to merge automatically without conflict.

Structural conflicts arise when concurrent operations affect the same field: two editors changing the same property's type, or one editor renaming a class while another adds properties to it. These conflicts are detected by the CRDT's merge logic and flagged for manual resolution (issue 1.3) rather than silently applying last-writer-wins.

The CRDT model is backed by Yjs for its mature conflict resolution, WebSocket-based sync adapter, and binary encoding efficiency. Schema documents are persisted as Yjs state vectors in PostgreSQL, allowing point-in-time reconstruction.

```
Schema Document (Y.Doc)
├── metadata (Y.Map)
│   ├── name: "payment-system"
│   ├── version: "2.1.0"
│   └── description: "..."
├── classes (Y.Array)
│   ├── [0] (Y.Map) ─── "Order"
│   │   ├── properties (Y.Map)
│   │   │   ├── id (Y.Map) { type: "string", format: "uuid" }
│   │   │   ├── total (Y.Map) { type: "number", minimum: 0 }
│   │   │   └── status (Y.Map) { type: "string", enum: [...] }
│   │   └── relationships (Y.Array)
│   ├── [1] (Y.Map) ─── "LineItem"
│   │   └── ...
│   └── [2] (Y.Map) ─── "Customer"
│       └── ...
└── _sync (Y.Map)
    ├── clock: <vector clock>
    └── peers: [...]
```

**Acceptance Criteria**

- Schema documents are represented as Yjs `Y.Doc` with nested `Y.Map` and `Y.Array` structures
- Concurrent edits to different classes within the same schema merge automatically
- Concurrent edits to different properties within the same class merge automatically
- Concurrent edits to the same property field are flagged as conflicts, not silently merged
- CRDT state vectors are persisted to PostgreSQL for durability and point-in-time reconstruction
- The CRDT model round-trips correctly: Objectified schema → CRDT → Objectified schema

**Part of Epic: Core Sync Engine**

---

#### 1.2 (#1272) — Sync Protocol & Transport Layer

The sync protocol defines how CRDT updates travel between clients and the server, and between servers in multi-region setups. This issue builds the WebSocket transport with binary delta encoding for efficient real-time synchronization.

Each client connects to the sync server via WebSocket at `wss://sync.objectified.dev/docs/{docId}`. On connection, the client sends its current state vector (a compact representation of which updates it has seen). The server responds with all updates the client is missing, encoded as a Yjs binary delta. Subsequent updates are broadcast in real-time as they arrive from other clients.

The protocol supports three message types: `sync-step-1` (client → server: state vector), `sync-step-2` (server → client: missing updates), and `update` (bidirectional: individual operations). Binary encoding uses Yjs's built-in encoding which produces compact deltas—typically 50-200 bytes per property change vs. kilobytes for a full schema JSON.

Connection resilience is built in: automatic reconnection with exponential backoff (1s, 2s, 4s, max 30s), offline queue that buffers local changes during disconnection, and full state reconciliation on reconnect. The REST API provides a fallback for environments where WebSocket is unavailable: `POST /api/v1/sync/docs/{docId}/updates` (push updates) and `GET /api/v1/sync/docs/{docId}/state` (pull current state).

**Acceptance Criteria**

- WebSocket connection syncs state vector on connect and streams updates in real-time
- Binary delta encoding keeps per-update messages under 500 bytes for typical property changes
- Automatic reconnection with exponential backoff recovers from network interruptions
- Offline queue buffers local changes and replays them on reconnect
- Full state reconciliation on reconnect guarantees convergence after extended disconnection
- REST fallback API supports push/pull sync for WebSocket-unavailable environments

**Part of Epic: Core Sync Engine**

---

#### 1.3 (#1273) — Conflict Detection & Classification

Not all concurrent edits produce conflicts, and not all conflicts are equal. This issue builds the conflict detection engine that identifies concurrent modifications to the same schema element and classifies them by severity and auto-resolvability.

The engine categorizes conflicts into three tiers: **Auto-resolvable** — concurrent additions (two people add different properties to the same class; both are kept), reordering (array element position changes), or metadata-only changes (description edits). **Review-recommended** — type changes that might be compatible (string → enum with the old value included), constraint tightening (adding a `maxLength` that doesn't invalidate existing data). **Manual-required** — incompatible type changes (integer → boolean), property deletion where another editor is modifying the property, or relationship changes that create circular references.

The engine runs on the CRDT merge output by comparing the pre-merge state of each peer with the merged result. When the merged result differs from what either peer would expect (i.e., the other peer's changes also affected the same element), a conflict record is generated.

Conflict records are stored in PostgreSQL with: `conflict_id`, `doc_id`, `element_path` (JSON Pointer to the conflicting element), `severity` (auto | review | manual), `peer_a_change` (what peer A did), `peer_b_change` (what peer B did), `merged_result` (what the CRDT produced), `resolution_status` (pending | accepted | overridden), `resolved_by`, `resolved_at`. The API exposes `GET /api/v1/sync/docs/{docId}/conflicts` for listing and `PUT /api/v1/sync/docs/{docId}/conflicts/{conflictId}/resolve` for resolution.

**Acceptance Criteria**

- Auto-resolvable conflicts (concurrent additions, metadata changes) merge silently
- Review-recommended conflicts are flagged but the CRDT merge result is applied provisionally
- Manual-required conflicts block the merged change and require explicit resolution
- Conflict records include both peers' changes, the merged result, and the element path
- The conflict API supports listing, filtering by severity, and resolution submission
- Circular reference detection flags relationship changes that would create reference loops

**Part of Epic: Core Sync Engine**

---

#### 1.4 (#1274) — Conflict Resolution UI

When conflicts require human judgment, the resolution UI provides the context and tools to make the right call. This issue builds the visual conflict resolution interface that presents each conflict with side-by-side peer views and resolution options.

The conflict resolution page lives at `/sync/conflicts/[docId]` in the NextJS app. It displays a list of pending conflicts sorted by severity (manual-required first). Clicking a conflict opens a split-view panel showing: left side (Peer A's version), right side (Peer B's version), and center (the CRDT's merged result). Differences are highlighted with color coding: green for additions, red for deletions, yellow for modifications.

```
┌──────────────────────────────────────────────────────┐
│  Conflict: Order.status type change                  │
│  Severity: Manual Required                           │
│                                                      │
│  ┌────────────┐  ┌──────────┐  ┌────────────┐       │
│  │  Peer A    │  │  Merged  │  │  Peer B    │       │
│  │            │  │          │  │            │       │
│  │  status:   │  │  status: │  │  status:   │       │
│  │  type:     │  │  type:   │  │  type:     │       │
│  │  "string"  │  │  ???     │  │  "integer" │       │
│  │            │  │          │  │            │       │
│  └────────────┘  └──────────┘  └────────────┘       │
│                                                      │
│  Resolution:                                         │
│  (•) Accept Peer A    ( ) Accept Peer B              │
│  ( ) Custom value     ( ) Defer                      │
│                                                      │
│  [Apply Resolution]                                  │
└──────────────────────────────────────────────────────┘
```

Resolution options are: "Accept Peer A" (use A's version), "Accept Peer B" (use B's version), "Custom" (enter a new value that supersedes both), or "Defer" (keep the conflict open for later). Resolutions are applied as a new CRDT update that all peers receive, ensuring convergence.

The UI uses Radix `RadioGroup` for resolution selection, `Dialog` for custom value entry, `Badge` for severity indicators, and `ScrollArea` for the conflict list. A notification badge in the main navigation shows the count of unresolved conflicts.

**Acceptance Criteria**

- Split-view displays Peer A, Peer B, and merged versions with diff highlighting
- Resolution options include Accept A, Accept B, Custom, and Defer
- Applied resolutions propagate as CRDT updates to all connected peers
- The conflict list sorts by severity with manual-required conflicts first
- A navigation badge shows the count of unresolved conflicts across all documents
- Custom resolution validates the entered value against the schema's type constraints

**Part of Epic: Core Sync Engine**

---

#### 1.5 (#1275) — Sync Event Log & Audit Trail

Every sync operation, conflict, and resolution needs to be auditable. This issue builds the append-only event log that records the complete sync history for each schema document, enabling forensic investigation and compliance reporting.

The event log captures: `sync_start` (a peer connects and begins sync), `update_received` (a CRDT update arrives from a peer), `update_applied` (the update is merged into the document), `conflict_detected` (a conflict is identified during merge), `conflict_resolved` (a resolution is applied), `sync_complete` (a sync cycle finishes), and `peer_disconnected`. Each event includes: `event_id`, `doc_id`, `peer_id`, `timestamp`, `correlation_id` (links events from the same sync cycle), and `payload` (event-specific data like delta size, conflict severity, resolution choice).

Events are stored in a time-partitioned PostgreSQL table with a retention policy (default 1 year, configurable per tenant). The log is queryable via `GET /api/v1/sync/docs/{docId}/events?from={ts}&to={ts}&type={eventType}` with cursor-based pagination.

The sync event viewer is a NextJS page at `/sync/events/[docId]` with a timeline visualization. Events are displayed chronologically with Radix `Badge` for event type, color-coded by category (green for normal operations, yellow for conflicts detected, blue for resolutions). Filtering by event type and peer uses Radix `Select` components.

**Acceptance Criteria**

- All sync lifecycle events (connect, update, conflict, resolution, disconnect) are logged
- Events include correlation IDs linking operations within the same sync cycle
- The event API supports filtering by type, time range, and peer with cursor pagination
- Time-partitioned PostgreSQL storage supports configurable retention policies
- The event timeline page renders events chronologically with type-based color coding
- Event payload includes enough detail to reconstruct the document's state at any point

**Part of Epic: Core Sync Engine**

---

## Epic 2: Multi-Region Replication

### Summary Table

| #   | Title                                | Description                                                                  | Labels                            | Parallel |
|-----|--------------------------------------|------------------------------------------------------------------------------|-----------------------------------|----------|
| 2.1 (#1277) | Active-Active Replication Mesh       | Multi-region CRDT replication with eventual consistency guarantees            | `enhancement`, `sync`             | Yes      |
| 2.2 (#1278) | Region-Aware Routing                 | Route sync connections to the nearest region for minimum latency             | `enhancement`, `sync`             | Yes      |
| 2.3 (#1279) | Latency Optimization & Edge Caching  | Edge-cached read replicas and optimistic local-first writes                  | `enhancement`, `sync`             | No       |
| 2.4 (#1280) | Replication Monitoring Dashboard     | Real-time visibility into replication lag, throughput, and health per region  | `enhancement`, `sync`             | No       |
| 2.5 (#1281) | Cross-Region Conflict Policies       | Region-specific conflict resolution policies and priority rules              | `enhancement`, `sync`             | No       |

### Detailed Issue Descriptions

---

#### 2.1 (#1277) — Active-Active Replication Mesh

Single-region sync creates a bottleneck for global teams. This issue builds an active-active replication mesh where every region is a read-write primary—there is no single leader. CRDT updates originating in any region propagate to all other regions asynchronously.

The replication mesh connects regional sync servers via a message broker (NATS JetStream). When a CRDT update arrives at any regional server, it is: (1) applied locally, (2) persisted to the regional PostgreSQL, and (3) published to the NATS stream `sync.updates.{docId}`. All other regional servers subscribe to this stream and apply received updates to their local replicas. NATS JetStream's at-least-once delivery guarantee ensures no updates are lost; CRDT idempotency ensures duplicates are harmless.

The mesh topology is configurable: **full mesh** (every region connects to every other — lowest latency, highest bandwidth) or **hub-and-spoke** (regions connect through a central hub — lower bandwidth, slightly higher latency for cross-spoke updates). The topology is configured via `PUT /api/v1/sync/replication/topology`.

Region registration is managed via `POST /api/v1/sync/regions` with fields for region ID, geographic location, NATS cluster URL, and PostgreSQL connection string. The mesh automatically adjusts when regions are added or removed.

**Acceptance Criteria**

- Updates written in Region A are visible in Region B within the configured replication lag target
- CRDT convergence is guaranteed: all regions reach the same document state eventually
- NATS JetStream provides at-least-once delivery; CRDT idempotency handles duplicates
- Full mesh and hub-and-spoke topologies are both supported and switchable
- Region addition/removal dynamically updates the mesh without downtime
- Replication lag is measured and exposed as a metric per region pair

**Part of Epic: Multi-Region Replication**

---

#### 2.2 (#1278) — Region-Aware Routing

Connecting to a distant sync server adds unnecessary latency. This issue adds region-aware routing that directs each client to the nearest regional sync server based on geographic proximity and current server health.

The routing layer uses DNS-based geographic routing (Route 53 geolocation / Cloudflare geo-steering) as the primary mechanism. When a client connects to `sync.objectified.dev`, DNS resolves to the nearest regional server. A secondary latency-probing mechanism allows the client to measure RTT to all regional endpoints and override the DNS choice if a closer (by latency, not geography) server is available.

Health-aware routing ensures that clients are not routed to a degraded region. Each regional server publishes health metrics (CPU, memory, connection count, replication lag) to a shared health store. The routing layer considers a region healthy when: CPU < 80%, replication lag < 5 seconds, and the server is accepting new connections. Unhealthy regions are removed from routing until they recover.

The client SDK automatically handles region failover: if the connected server becomes unreachable, the client reconnects to the next-nearest healthy region and resumes sync. No data is lost because the offline queue (1.2) buffers changes during the transition.

**Acceptance Criteria**

- DNS-based routing directs clients to the geographically nearest region
- Client-side latency probing overrides DNS when a lower-latency region is available
- Unhealthy regions (CPU > 80%, replication lag > 5s) are excluded from routing
- Client failover to the next-nearest region is automatic on disconnection
- Routing decisions are logged for debugging and analytics
- The routing configuration is manageable via REST API (`PUT /api/v1/sync/routing`)

**Part of Epic: Multi-Region Replication**

---

#### 2.3 (#1279) — Latency Optimization & Edge Caching

Even with region-aware routing, read latency for large schemas can be significant. This issue adds edge caching for read-heavy operations and optimistic local-first writes for write-heavy scenarios.

Edge caching deploys lightweight read-only replicas at CDN edge locations. These replicas serve `GET /api/v1/sync/docs/{docId}/state` requests with cached CRDT state, avoiding a round-trip to the regional server. Edge cache invalidation is triggered by CRDT updates via the NATS stream. Cache TTL is configurable per document; default is 5 seconds for active documents and 60 seconds for inactive ones.

Optimistic local-first writes mean the client applies CRDT updates to its local replica immediately (showing the change in the UI) and sends the update to the server asynchronously. If the server rejects the update (e.g., due to a permission check), the client rolls back the local change and displays an error. This pattern ensures the UI feels instant even on high-latency connections.

Prefetching anticipates which documents a user is likely to open next (based on navigation patterns and project membership) and begins syncing them in the background. When the user does open the document, the local replica is already up to date.

**Acceptance Criteria**

- Edge-cached reads serve CRDT state from the nearest edge location with < 50ms latency
- Edge cache invalidation propagates within the configured TTL after an update
- Optimistic local writes show changes immediately in the UI before server confirmation
- Server-rejected writes are rolled back with a visible error notification
- Prefetching syncs likely-next documents in the background without blocking the current session
- Edge cache hit rate and latency metrics are exposed for monitoring

**Part of Epic: Multi-Region Replication**

---

#### 2.4 (#1280) — Replication Monitoring Dashboard

Operations teams need real-time visibility into the replication mesh's health. This issue builds a monitoring dashboard that shows replication lag, throughput, health status, and conflict rates per region and per document.

The dashboard is a NextJS page at `/sync/monitoring` displaying a world map visualization with regional server locations. Each region shows: current connection count, replication lag to other regions (as a heat-mapped latency matrix), sync throughput (updates/second), conflict rate (conflicts/1000 updates), and health status (green/yellow/red using Radix `Badge`).

Below the map, a metrics table (Radix `Table`) lists per-document sync statistics: active peers, update frequency, last conflict, and replication lag. Documents with high conflict rates or replication lag anomalies are highlighted for investigation.

Alerting integration sends notifications when: replication lag exceeds 30 seconds between any region pair, a region's health drops to red, or conflict rate exceeds a configurable threshold. Alerts fire via email and webhook. The alerting configuration is at `/sync/monitoring/alerts` with Radix `TextField` for threshold values and `Switch` for enabling/disabling alerts.

**Acceptance Criteria**

- World map visualization shows regional servers with connection count and health status
- Latency matrix displays replication lag between every region pair with color-coded heat map
- Per-document metrics table shows peers, update frequency, conflict rate, and lag
- Alerts fire when replication lag > 30s, region health is red, or conflict rate exceeds threshold
- Alert delivery supports email and webhook channels
- Dashboard data refreshes every 10 seconds via polling or server-sent events

**Part of Epic: Multi-Region Replication**

---

#### 2.5 (#1281) — Cross-Region Conflict Policies

Different organizations have different priorities when resolving cross-region conflicts. This issue adds configurable conflict resolution policies that allow tenants to set region priorities, auto-resolution strategies, and escalation rules.

Policies are defined per document or per project: **region priority** (in a conflict, prefer the update from the higher-priority region—useful when one region is the "source of truth"), **timestamp priority** (prefer the most recent update—simple but prone to clock skew issues), **field-level rules** (some fields use region priority, others use timestamp, others always require manual resolution), and **escalation** (if a conflict is unresolved for N hours, notify a specific team or auto-apply a default resolution).

The policy configuration page is at `/sync/policies/[projectId]` with Radix `Tabs` for policy categories, `Table` for field-level rules, and `Select` for strategy selection. Policies are stored in PostgreSQL and cached in Redis for fast evaluation during conflict detection.

The REST API exposes `POST /api/v1/sync/policies` for creation, `GET /api/v1/sync/policies/{projectId}` for retrieval, and `PUT /api/v1/sync/policies/{policyId}` for updates. Policy changes are audited in the sync event log.

**Acceptance Criteria**

- Region priority policies auto-resolve conflicts in favor of the higher-priority region
- Timestamp priority policies auto-resolve in favor of the most recent update
- Field-level rules allow different strategies per schema property
- Escalation rules notify teams or auto-apply defaults after configurable timeout
- Policy changes are audited in the sync event log
- The policy UI at `/sync/policies/[projectId]` uses Radix `Tabs`, `Table`, and `Select`

**Part of Epic: Multi-Region Replication**

---

## Epic 3: Environment Promotion & Drift Detection

### Summary Table

| #   | Title                                  | Description                                                                  | Labels                            | Parallel |
|-----|----------------------------------------|------------------------------------------------------------------------------|-----------------------------------|----------|
| 3.1 (#1283) | Environment Registry & Configuration   | Define and manage dev/staging/prod environments with sync endpoints          | `enhancement`, `sync`, `rest`     | Yes      |
| 3.2 (#1284) | Promotion Workflow & Approval Gates    | Schema promotion pipeline with review, approval, and automated checks        | `enhancement`, `sync`, `rest`     | No       |
| 3.3 (#1285) | Rollback & Point-in-Time Restore       | One-click rollback to any previous environment state with safety checks      | `enhancement`, `sync`             | Yes      |
| 3.4 (#1286) | Environment Drift Detection            | Continuous comparison between environments to detect unauthorized changes    | `enhancement`, `sync`, `rest`     | No       |
| 3.5 (#1287) | Promotion History & Audit              | Complete audit trail of all promotions, approvals, and rollbacks             | `enhancement`, `sync`             | Yes      |

### Detailed Issue Descriptions

---

#### 3.1 (#1283) — Environment Registry & Configuration

Before schemas can be promoted across environments, the environments themselves must be defined. This issue builds the environment registry where tenants configure their deployment environments (dev, staging, production, etc.) with their sync endpoints and access policies.

Each environment record contains: `name` (human-readable), `slug` (unique identifier), `type` (development | staging | production | custom), `sync_endpoint` (URL of the environment's Objectified instance or sync server), `api_key` (encrypted credential for authenticating with the target environment), `promotion_order` (integer defining the promotion pipeline sequence), and `approval_policy` (who must approve promotions to this environment).

The environment configuration page is at `/sync/environments` with Radix `Table` for the environment list, `Dialog` for add/edit, and drag-and-drop reordering for the promotion pipeline sequence. The REST API exposes `POST /api/v1/sync/environments` for creation and `GET /api/v1/sync/environments` for listing.

A health check runs periodically against each environment's sync endpoint, verifying connectivity and authentication. Health status is displayed as Radix `Badge` on the environment list (green = connected, yellow = high latency, red = unreachable).

**Acceptance Criteria**

- Environments are created with name, type, sync endpoint, and API key
- Promotion order defines the pipeline sequence (dev → staging → production)
- API keys are stored encrypted and never returned in API responses
- Health checks verify connectivity to each environment's sync endpoint
- Health status displays as color-coded badges on the environment list
- Drag-and-drop reordering updates the promotion pipeline sequence

**Part of Epic: Environment Promotion & Drift Detection**

---

#### 3.2 (#1284) — Promotion Workflow & Approval Gates

Promoting a schema from dev to staging (or staging to production) must be a controlled process with reviews, automated checks, and approvals. This issue builds the promotion workflow engine.

A promotion is initiated via `POST /api/v1/sync/promotions` with `schemaId`, `fromEnvironment`, and `toEnvironment`. The engine runs pre-promotion checks: (1) schema validation passes in the target environment's context, (2) no breaking changes relative to the target environment's current schema version (or breaking changes are acknowledged), (3) all required approvals are obtained. If checks pass, the schema is synced to the target environment.

Approval gates are configurable per environment: "production" might require 2 approvals from members of the "schema-admins" team, while "staging" requires only 1. Approvers receive email and in-app notifications with a link to the promotion review page. The review page at `/sync/promotions/[promotionId]` shows the schema diff between the source and target environments, the pre-promotion check results, and approve/reject buttons.

```
Dev ──────▶ Staging ──────▶ Production
           │                │
     1 approval        2 approvals
     auto-checks       auto-checks
     schema diff       schema diff
                       breaking change
                       review
```

The promotion page uses Radix `Tabs` for switching between diff view, check results, and approval status. `Avatar` displays approver identities. `AlertDialog` confirms the promotion action.

**Acceptance Criteria**

- Promotions run pre-checks for schema validation and breaking change detection
- Approval gates require the configured number of approvals before promotion proceeds
- Approvers receive email and in-app notifications with a link to the review page
- The review page displays the schema diff, check results, and approval status
- Rejected promotions include a reason from the rejector and block the sync
- Promotions can only advance in the configured pipeline order (no skipping stages)

**Part of Epic: Environment Promotion & Drift Detection**

---

#### 3.3 (#1285) — Rollback & Point-in-Time Restore

When a promotion introduces issues in a target environment, teams need to roll back quickly. This issue builds the rollback mechanism that restores an environment to any previous schema state with safety checks.

Rollback is triggered via `POST /api/v1/sync/environments/{envId}/rollback` with `targetVersion` (a specific schema version to restore) or `targetTimestamp` (restore to the state at a point in time). Before executing, the engine runs safety checks: (1) are there active consumers using the current version that would break? (2) does the rollback create data incompatibilities with existing instance data? (3) is a follow-up promotion pending that would be invalidated?

Safety check results are presented in a Radix `AlertDialog`. Critical warnings (active consumers, data incompatibility) require explicit acknowledgment ("I understand this may break consumers"). The rollback then syncs the target version to the environment and records the action in the promotion history.

Point-in-time restore reconstructs the schema state from the CRDT event log (Epic 1, issue 1.5) by replaying events up to the specified timestamp. This handles cases where the exact version number is unknown but the team knows "it was working yesterday at 3pm."

**Acceptance Criteria**

- Version-targeted rollback restores the environment to a specific schema version
- Timestamp-targeted rollback reconstructs state from the CRDT event log
- Pre-rollback safety checks detect active consumers and data incompatibilities
- Critical warnings require explicit user acknowledgment before proceeding
- Rollback actions are recorded in the promotion history with the initiator and reason
- Rollback completes within 30 seconds for schemas with up to 100 classes

**Part of Epic: Environment Promotion & Drift Detection**

---

#### 3.4 (#1286) — Environment Drift Detection

Drift happens when an environment's schema diverges from what the promotion pipeline expects—manual edits in production, failed partial syncs, or external tools modifying the schema directly. This issue builds continuous drift detection that compares environments and alerts on unauthorized divergence.

The drift detector runs on a configurable schedule (default: every 6 hours) or on-demand via `POST /api/v1/sync/drift-check`. It compares each environment's current schema state against the last successfully promoted version. Any difference is classified as drift: **expected** (a promotion is in progress or pending), **unauthorized** (the schema changed outside the promotion pipeline), or **stale** (the environment is behind the pipeline by more than one version).

Unauthorized drift generates an alert with the specific changes detected (field additions, type changes, etc.) and the timestamp range when the drift likely occurred. The alert includes options to: "Accept drift" (update the pipeline's record to match the current state), "Revert drift" (roll back the unauthorized changes), or "Investigate" (open the sync event log filtered to the drift timeframe).

The drift dashboard at `/sync/drift` displays a matrix of environments vs. schemas with drift status indicators. Radix `Badge` components show green (in sync), yellow (expected drift), and red (unauthorized drift).

**Acceptance Criteria**

- Scheduled drift detection compares environments against the last promoted version
- Unauthorized drift (changes outside the promotion pipeline) is detected and alerted
- Drift alerts include specific changes, timestamp range, and action options
- "Accept drift" updates the pipeline record; "Revert drift" rolls back changes
- The drift matrix dashboard shows all environments × schemas with status badges
- On-demand drift checks complete within 60 seconds for up to 10 environments

**Part of Epic: Environment Promotion & Drift Detection**

---

#### 3.5 (#1287) — Promotion History & Audit

Every promotion, rollback, and drift action must be auditable. This issue builds the promotion history log that records the complete lifecycle of schema movement across environments.

The history log records: promotions (who initiated, when, from/to environments, schema version, approval chain, check results), rollbacks (who initiated, target version, safety check acknowledgments), drift detections (when detected, classification, resolution), and configuration changes (environment added/modified, approval policy changed).

The history page at `/sync/promotions/history` uses Radix `Table` with sortable columns and filters for environment, action type, date range, and initiator. Each row expands to show full details including the schema diff that was promoted. Export functionality generates CSV/JSON reports for compliance audits.

The REST API exposes `GET /api/v1/sync/promotions/history?env={envId}&action={type}&from={date}&to={date}` with cursor-based pagination.

**Acceptance Criteria**

- All promotions, rollbacks, and drift actions are logged with full metadata
- Approval chains are recorded with each approver's identity, timestamp, and decision
- The history page supports filtering by environment, action type, date range, and initiator
- Row expansion shows the full schema diff that was promoted or rolled back
- CSV and JSON exports are available for compliance reporting
- History retention follows the tenant's configured retention policy

**Part of Epic: Environment Promotion & Drift Detection**

---

## Epic 4: External System Sync

### Summary Table

| #   | Title                              | Description                                                                  | Labels                            | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|-----------------------------------|----------|
| 4.1 (#1289) | Git Repository Sync                | Bi-directional sync between Objectified schemas and Git repository files     | `enhancement`, `sync`, `rest`     | Yes      |
| 4.2 (#1290) | Database Schema Sync               | Sync Objectified schemas with database DDL (PostgreSQL, MySQL)               | `enhancement`, `sync`, `rest`     | Yes      |
| 4.3 (#1291) | ORM Model Sync                     | Keep ORM models (Prisma, TypeORM, SQLAlchemy) in sync with schemas           | `enhancement`, `sync`             | No       |
| 4.4 (#1292) | CI/CD Sync Hooks                   | Trigger sync operations from CI/CD pipelines and block deploys on drift      | `enhancement`, `sync`, `rest`     | Yes      |
| 4.5 (#1293) | Webhook & Event Stream Integration | Publish sync events to external systems via webhooks and event streams       | `enhancement`, `sync`, `rest`     | Yes      |

### Detailed Issue Descriptions

---

#### 4.1 (#1289) — Git Repository Sync

Many teams maintain schema definitions as JSON/YAML files in Git repositories. This issue builds bi-directional sync between Objectified and Git, so changes in either system propagate to the other.

The Git sync connector is configured per project via `POST /api/v1/sync/connectors/git` with: repository URL, branch, directory path (where schema files live), file format (json | yaml), authentication (SSH key or GitHub App), and sync direction (bidirectional | objectified-to-git | git-to-objectified).

**Objectified → Git**: When a schema is published in Objectified, the connector serializes it to JSON/YAML files, commits them to the configured branch, and pushes. The commit message references the Objectified version and user. **Git → Objectified**: When changes are pushed to the monitored branch (detected via webhook), the connector reads the updated schema files, validates them, and imports changes into Objectified as a new draft version.

Conflict handling for bi-directional sync uses timestamp comparison: if both systems changed since the last sync, the connector creates a merge branch in Git with the Objectified changes and opens a pull request for review rather than force-pushing. The PR includes a diff comparison and a link to the Objectified version.

```
Objectified                  Git Repository
┌──────────┐   publish       ┌──────────────┐
│  Schema  │────────────────▶│  schemas/    │
│  v2.1    │                 │  user.json   │
│          │   webhook       │  order.json  │
│          │◀────────────────│              │
└──────────┘   import draft  └──────────────┘
                  │
                  ▼
            Conflict?  ──▶  Open PR for review
```

**Acceptance Criteria**

- Schema publish in Objectified commits and pushes JSON/YAML files to the configured Git branch
- Git webhook detects pushes and imports schema changes as draft versions in Objectified
- Bi-directional conflicts create a merge PR in Git rather than force-pushing
- SSH key and GitHub App authentication methods are both supported
- Sync connector is configurable per project with directory path and file format selection
- Sync status is visible on the project settings page with last sync timestamp and error details

**Part of Epic: External System Sync**

---

#### 4.2 (#1290) — Database Schema Sync

Database tables are the runtime manifestation of schema definitions. This issue builds sync between Objectified schemas and database DDL, allowing teams to keep their data model definitions and actual database structures aligned.

The database sync connector connects to PostgreSQL or MySQL instances via `POST /api/v1/sync/connectors/database` with: connection string (encrypted), target database/schema, and sync direction. **Objectified → Database**: The connector generates DDL (CREATE TABLE, ALTER TABLE) from the schema definition and applies it to the target database (with migration safety: no destructive operations without explicit approval). **Database → Objectified**: The connector introspects the database schema and imports table structures as Objectified class definitions.

The DDL generator maps JSON Schema types to database types: `string` → `TEXT`/`VARCHAR`, `integer` → `INTEGER`/`BIGINT`, `number` → `NUMERIC`/`DOUBLE PRECISION`, `boolean` → `BOOLEAN`, `array` → `JSONB`, `object` → `JSONB` or a related table (based on relationship definitions). Constraints map to: `minLength`/`maxLength` → `CHECK`, `enum` → `CHECK` or referenced enum type, `format: email` → `CHECK` with regex.

Migration safety prevents data loss: column removal requires explicit approval, type changes that could lose data (e.g., `TEXT` → `INTEGER`) are blocked with a warning, and all generated DDL is displayed for review before execution.

**Acceptance Criteria**

- JSON Schema types map correctly to PostgreSQL and MySQL column types
- Objectified → Database sync generates safe DDL with no destructive operations by default
- Destructive operations (column removal, type narrowing) require explicit approval
- Database → Objectified introspection imports table structures as schema class definitions
- Connection strings are stored encrypted and never returned in API responses
- Generated DDL is presented for review before execution on the target database

**Part of Epic: External System Sync**

---

#### 4.3 (#1291) — ORM Model Sync

Developers interact with databases through ORMs, not raw DDL. This issue builds sync between Objectified schemas and popular ORM model definitions: Prisma (TypeScript), TypeORM (TypeScript), and SQLAlchemy (Python).

**Objectified → ORM**: The connector generates model files from schema definitions. For Prisma, it produces a `schema.prisma` file with model blocks, field types, relations, and constraints. For TypeORM, it produces TypeScript entity classes with decorators. For SQLAlchemy, it produces Python model classes with Column definitions and relationship declarations.

**ORM → Objectified**: The connector parses existing model files and imports their structure as Objectified schemas. The Prisma parser reads `.prisma` files using the Prisma schema AST. The TypeORM parser extracts decorators from TypeScript files. The SQLAlchemy parser reads model class definitions from Python files.

ORM sync is configured per project via the settings page at `/sync/connectors/orm` using Radix `Select` for ORM type, `TextField` for model file paths, and `Switch` for enabling bi-directional sync. The REST API endpoint is `POST /api/v1/sync/connectors/orm`.

When ORM models and Objectified schemas diverge, the sync reports a diff showing which fields exist in one but not the other, and which fields have type mismatches.

**Acceptance Criteria**

- Prisma model generation produces valid `.prisma` files with models, relations, and constraints
- TypeORM entity generation produces valid TypeScript classes with correct decorators
- SQLAlchemy model generation produces valid Python classes with Column definitions
- ORM → Objectified parsing correctly imports model structures from all three ORMs
- Divergence detection reports field-level differences between ORM models and schemas
- The ORM connector settings page uses Radix `Select`, `TextField`, and `Switch`

**Part of Epic: External System Sync**

---

#### 4.4 (#1292) — CI/CD Sync Hooks

Schema sync should be part of the deployment pipeline, not a manual step. This issue builds CI/CD hooks that trigger sync checks and operations from GitHub Actions, GitLab CI, and other pipeline tools.

The primary hook is a pre-deploy check: before a service deploys, the CI/CD pipeline calls `POST /api/v1/sync/checks` with the service's schema expectations (typically extracted from the codebase). The check verifies that the target environment's schema matches what the code expects. If drift is detected, the check fails and the deployment is blocked.

A GitHub Action (`@objectified/sync-check-action`) wraps this API call. It reads schema expectations from the repository (ORM models, OpenAPI specs, or explicit schema references) and calls the sync check endpoint. The action reports pass/fail as a GitHub check status with detailed drift information in the check output.

Post-deploy hooks trigger environment sync: after a successful deployment, the pipeline calls `POST /api/v1/sync/trigger` to initiate a sync from the deployment's schema to the target environment. This ensures the Objectified environment record stays current with what's actually deployed.

The hook configuration documentation is published at `/docs/ci-cd-sync`.

**Acceptance Criteria**

- Pre-deploy check verifies schema compatibility between code and target environment
- Schema drift causes the check to fail, blocking deployment with drift details
- GitHub Action wraps the check API and reports results as GitHub check status
- Post-deploy hooks trigger environment sync to update Objectified's record
- Hook endpoints are authenticated with scoped CI/CD tokens
- Configuration documentation covers GitHub Actions, GitLab CI, and generic webhook setups

**Part of Epic: External System Sync**

---

#### 4.5 (#1293) — Webhook & Event Stream Integration

External systems need to react to sync events: a monitoring tool updating when drift is detected, a Slack channel notified on promotion, or a data pipeline triggered by schema changes. This issue builds the event publishing layer for sync operations.

Webhook subscriptions are created via `POST /api/v1/sync/webhooks` with: URL, secret (for HMAC signature verification), and event filter (which event types to receive: `sync.update`, `sync.conflict`, `sync.promotion`, `sync.drift`, `sync.rollback`). Each webhook delivery includes: the event payload, a `X-Objectified-Signature` header (HMAC-SHA256 of the payload using the shared secret), and a `X-Objectified-Event` header with the event type.

Webhook delivery uses retry with exponential backoff: 3 retries at 10s, 60s, 300s intervals. Failed deliveries (non-2xx response or timeout) are logged and visible on the webhook management page. After 10 consecutive failures, the webhook is disabled and the owner is notified.

For high-volume integrations, a NATS/Kafka event stream is available at `nats://events.objectified.dev/sync.>` (or Kafka topic `objectified.sync.events`). Stream consumers can filter by event type and document ID using subject-based routing.

The webhook management page at `/sync/webhooks` uses Radix `Table` for subscription listing, `Dialog` for creation/editing, `Badge` for delivery status, and `Switch` for enable/disable toggles.

**Acceptance Criteria**

- Webhook subscriptions deliver events to configured URLs with HMAC signature verification
- Event type filtering allows subscriptions to receive only relevant events
- Retry logic sends up to 3 retries with exponential backoff on delivery failure
- Webhooks auto-disable after 10 consecutive failures with owner notification
- NATS/Kafka event streams provide a high-throughput alternative to webhooks
- The webhook management page lists subscriptions with delivery status and enable/disable toggles

**Part of Epic: External System Sync**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 (Core Sync Engine):**
- 1.1 (CRDT Model), 1.2 (Sync Protocol), and 1.5 (Event Log) can be developed in parallel. The CRDT model defines the data structure, the protocol defines the transport, and the event log is a cross-cutting concern.
- 1.3 (Conflict Detection) depends on 1.1 for the CRDT model and its merge behavior.
- 1.4 (Conflict Resolution UI) depends on 1.3 for conflict records to display.

**Epic 2 (Multi-Region Replication):**
- 2.1 (Active-Active Mesh) and 2.2 (Region-Aware Routing) can be developed in parallel—the mesh handles data replication while routing handles connection management.
- 2.3 (Latency Optimization) depends on 2.1 and 2.2 for the multi-region infrastructure.
- 2.4 (Monitoring Dashboard) depends on 2.1 for replication metrics but can be stubbed early.
- 2.5 (Conflict Policies) depends on 1.3 for the conflict detection framework.

**Epic 3 (Environment Promotion & Drift Detection):**
- 3.1 (Environment Registry), 3.3 (Rollback), and 3.5 (Promotion History) can be developed in parallel.
- 3.2 (Promotion Workflow) depends on 3.1 for environment definitions.
- 3.4 (Drift Detection) depends on 3.1 for environment endpoints and 3.2 for promotion state comparisons.

**Epic 4 (External System Sync):**
- 4.1 (Git Sync), 4.2 (Database Sync), 4.4 (CI/CD Hooks), and 4.5 (Webhook Integration) can all be developed in parallel as they are independent connectors.
- 4.3 (ORM Sync) depends on 4.2 for the database type mapping logic and can reuse its mapping tables.

**Cross-Epic Parallelism:**
- Epic 1 is the foundation; all other epics depend on it for the core sync primitives.
- Epic 2 and Epic 3 are independent of each other and can be built by separate teams once Epic 1 is complete.
- Epic 4 is independent of Epics 2 and 3 and depends only on Epic 1 for the core sync engine.
- Within Epic 1, issues 1.1 + 1.2 + 1.5 form a parallelizable foundation sprint.
