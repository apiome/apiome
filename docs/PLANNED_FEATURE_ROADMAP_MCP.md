# Model Context Protocol (MCP) Server Roadmap

_GitHub issues filed against `KenSuenobu/objectified-commercial`._
_Epics: #2813 · #2814 · #2815 · #2816 · #2817 · #2818 · #2819 · #2820 · #2821 (`MCP-EPIC-1` … `MCP-EPIC-9`)._
_Use the `mcp` label on `KenSuenobu/objectified-commercial` to filter the
entire pack._

> **Read-only Model Context Protocol (MCP) server for Objectified**
>
> Expose the Objectified data model — tenants, projects, versions, branches,
> classes, properties, primitives, paths, operations, change reports, audit
> entries, and the rest — to MCP-aware clients (Cursor, Claude Desktop,
> ChatGPT Desktop, Continue, in-house agents) through a single, signed,
> tenant-scoped server.
>
> **Three primitive tools** drive everything:
>
> 1. `mcp.search`   — find an action by keyword, category, or resource
> 2. `mcp.describe` — return the full input/output JSON Schema for an action
> 3. `mcp.execute`  — run an action with validated arguments, get the result
>
> Every action in the registry is **read-only by default**. Mutating actions
> are gated behind Enterprise V2 and an explicit per-key write scope.
>
> **Reuses**: Linked Accounts (`odb.external_auth_providers`) and the
> existing `api_keys` table for credential issuance and tenant binding —
> the user lands on the existing Linked Accounts panel to mint an MCP
> key, then drops the generated `mcp.json` snippet into their client.
>
> **Tech stack**: TypeScript MCP server in a new `objectified-mcp/`
> package built on the official
> [`@modelcontextprotocol/sdk`](https://github.com/modelcontextprotocol/typescript-sdk),
> stdio + Streamable HTTP transports, NextJS BFF for the issuance UI,
> `objectified-rest` (FastAPI) as the upstream data source, PostgreSQL
> (`odb.api_keys`, `odb.external_auth_providers`, `odb.workflow_audit`,
> new `odb.mcp_session` and `odb.mcp_action_invocation` tables), Redis
> (rate-limit token bucket per key).
>
> **Revenue model**: MVP discovery actions (tenants, projects, versions,
> classes, properties, primitives, paths, operations, change reports, audit
> search) and the search/describe/execute primitives are available in all
> paid tiers. Write-back actions, AI-assisted query planning, the GraphQL-
> like query layer, federated MCP across tenants, and custom OPA policies
> are **Enterprise V2** (gated by the `v2-enterprise` label and roadmap
> ID `V2-MCP-*`).

---

## How to read this document

- Each epic has a **summary table** (columns: roadmap ID, title, description,
  labels, MVP, Parallel, Issue) followed by **detailed issue descriptions**
  for the highest-leverage tickets (problem, scope, technical specification,
  ASCII diagram, acceptance criteria, parallelism note).
- Tickets are listed **in implementation order** within each epic, and the
  **single-page ordered checklist** at the bottom orders them across all
  epics for execution sequencing.
- The **Issue** column points to the live GitHub issue on
  `KenSuenobu/objectified-commercial`. Each child issue is also linked
  as a native sub-issue under its epic umbrella issue.
- **MVP = Yes** items are required for the first MCP release ("MCP v1").
  **MVP = No, V2 = Yes** items are explicitly **enterprise** follow-ons; do
  not mix into the MVP burn-down.
- **Parallel = Yes** tickets can be implemented concurrently with other
  tickets in the same epic without merge conflicts on the action registry,
  database schema, or transport layer. **Parallel = No** tickets are
  dependency anchors and must be completed before later tickets in the
  epic begin.

---

## MVP Definition

The first release ("MCP v1") must:

- Run a standalone `objectified-mcp` server with stdio + Streamable HTTP
  transports, authenticated by an API key minted from the Linked Accounts
  panel — MCP-1.1, MCP-1.2, MCP-1.3
- Enforce tenant scoping, RBAC scopes, and per-key rate limits — MCP-1.4,
  MCP-1.5
- Audit every invocation through `odb.workflow_audit` (`mcp.session_started`,
  `mcp.action_executed`, `mcp.action_failed`) — MCP-1.6
- Provide the three primitive tools (`mcp.search`, `mcp.describe`,
  `mcp.execute`) backed by an in-process **action registry** — MCP-2.1,
  MCP-2.2, MCP-2.3, MCP-2.4
- Standardize cursor-based pagination and a typed error taxonomy —
  MCP-2.5, MCP-2.6
- Ship the **MVP discovery action set**: tenants, users, projects, versions,
  branches, tags, classes, properties, primitives, paths, operations,
  request/response, security schemes, servers, change reports, and audit —
  MCP-3.1, MCP-3.2, MCP-3.3, MCP-3.4, MCP-4.1, MCP-4.2, MCP-4.3, MCP-4.4,
  MCP-5.1, MCP-5.2, MCP-5.3, MCP-5.4, MCP-6.1, MCP-6.2, MCP-6.3, MCP-6.7,
  MCP-7.1, MCP-7.2
- Ship the in-ADE **MCP onboarding flow**: API-key issuance UI, connection
  wizard with copy-paste `mcp.json` snippet, action catalog browser, per-key
  activity log, revocation controls — MCP-8.1, MCP-8.2, MCP-8.3, MCP-8.4,
  MCP-8.5
- Publish a versioned documentation site for the registry and tools —
  MCP-8.6

Everything else in this document is **post-MVP** or **Enterprise V2**.

---

## Labels

**Reuse existing labels wherever possible**:

| Label              | Source                          | Use here                                                       |
|--------------------|---------------------------------|----------------------------------------------------------------|
| `enhancement`      | repo-wide                       | All feature tickets                                            |
| `mvp`              | git-like / paths / repo roadmaps | Tickets in the MVP slice                                      |
| `rest`             | repo-wide                       | Adds REST endpoints in `objectified-rest`                      |
| `database`         | repo-wide                       | Adds migrations under `objectified-db/scripts/`                |
| `ui`               | repo-wide                       | Adds UI in `objectified-ui`                                    |
| `security`         | repo-wide                       | Token handling, scope enforcement, allowlists                  |
| `governance`       | governance roadmap              | Policy / OPA hooks                                             |
| `ai`               | AI roadmap                      | LLM-assisted query planning                                    |
| `import`           | `FUTURE_FEATURE_ROADMAP_IMPORT` | Anything that exposes import-job state via MCP                 |
| `repository`       | repository roadmap              | Anything that exposes the repo connector via MCP               |

**New labels to create** (already created on `KenSuenobu/objectified-commercial`):

| Label             | Description                                                                                     |
|-------------------|-------------------------------------------------------------------------------------------------|
| `mcp`             | Anything in the MCP roadmap (umbrella)                                                          |
| `mcp-server`      | Server runtime, transport, lifecycle, container image                                           |
| `mcp-protocol`    | MCP SDK + capability negotiation + the `mcp.search` / `mcp.describe` / `mcp.execute` primitives |
| `mcp-action`      | Action registry + individual discovery / execute action implementations                         |
| `mcp-catalog`     | In-ADE catalog browser, docs site, `mcp.json` snippet generator                                 |
| `mcp-key`         | API key issuance, scopes, revocation, activity log                                              |
| `roadmap-mcp`     | Pack filter for every issue in this roadmap                                                     |

Apply at minimum: `enhancement`, `mcp`, `roadmap-mcp`, plus the topic
label (`mcp-server`, `mcp-protocol`, `mcp-action`, `mcp-catalog`,
`mcp-key`) and the surface label (`database`, `rest`, `ui`,
`security`). Add `mvp` if it is in the MVP slice. Add `v2-enterprise`
if it is gated.

---

## Architecture at a glance

```
                     ┌──────────────────────────────────────┐
                     │  MCP-aware client                    │
                     │  (Cursor · Claude Desktop · etc.)    │
                     └─────────────────┬────────────────────┘
                                       │ stdio  | Streamable HTTP
                                       ▼
                     ┌──────────────────────────────────────┐
                     │  objectified-mcp (TypeScript, MCP    │
                     │  SDK)                                │
                     │                                      │
                     │  Tools exposed to client:            │
                     │   • mcp.search   (find actions)      │
                     │   • mcp.describe (input/output spec) │
                     │   • mcp.execute  (run an action)     │
                     │                                      │
                     │  In-process:                         │
                     │   • Action Registry (200+ actions)   │
                     │   • Auth middleware (API key)        │
                     │   • Tenant + scope guard             │
                     │   • Rate limiter (Redis token bucket)│
                     │   • Audit emitter                    │
                     └─────────────────┬────────────────────┘
                                       │ HTTPS, signed
                                       │ API key in header
                                       ▼
                     ┌──────────────────────────────────────┐
                     │  objectified-rest (FastAPI)          │
                     │   read-only endpoints                │
                     └─────────────────┬────────────────────┘
                                       │
                                       ▼
                     ┌──────────────────────────────────────┐
                     │  PostgreSQL (odb.*)                  │
                     │   tenants · projects · versions      │
                     │   classes · properties · primitives  │
                     │   paths · operations · change_reports│
                     │   workflow_audit · api_keys · etc.   │
                     └──────────────────────────────────────┘
```

**Three-tool contract** (everything else hangs off the registry):

```
   client                 mcp.search { q: "list properties for class" }
     │
     ▼
   server  ──► Registry.search(q) ──► [
                  {id: "class.list_properties", category: "schema", …},
                  {id: "property.list_uses",   category: "schema", …},
                  …
              ]

   client                 mcp.describe { actionId: "class.list_properties" }
     │
     ▼
   server  ──► Registry.describe(id) ──► {
                  id, title, description, scopes,
                  inputSchema  : JSONSchema,
                  outputSchema : JSONSchema,
                  examples     : [...]
              }

   client                 mcp.execute  {
                            actionId: "class.list_properties",
                            args: { classId: "...", limit: 50 }
                          }
     │
     ▼
   server  ──► Registry.dispatch(id, args, ctx) ──►
              {
                items: [...],
                pageInfo: { nextCursor, hasMore }
              }
```

---

## Epic 1: MCP Server Foundation & Authentication — MCP-EPIC-1 (#2813)

### Summary

| Roadmap ID | Title                                            | Description                                                                                          | Labels                                                       | MVP | Parallel | Issue |
|------------|--------------------------------------------------|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------|-----|----------|-------|
| MCP-1.1    | `objectified-mcp` package + MCP SDK bootstrap    | New TypeScript package wiring `@modelcontextprotocol/sdk` server, capability negotiation, lifecycle  | `enhancement`, `mvp`, `mcp`, `mcp-server`, `mcp-protocol`    | Yes | No       | #2822 |
| MCP-1.2    | Transport adapters (stdio + Streamable HTTP)     | Stdio for desktop clients; Streamable HTTP at `/mcp` for hosted clients                              | `enhancement`, `mvp`, `mcp`, `mcp-server`                    | Yes | No       | #2823 |
| MCP-1.3    | API-key authentication via Linked Accounts       | Reuse `odb.api_keys` + `odb.external_auth_providers`; bearer in `Authorization` for HTTP, env for stdio | `enhancement`, `mvp`, `mcp`, `mcp-server`, `mcp-key`, `security` | Yes | No   | #2824 |
| MCP-1.4    | Tenant scoping + RBAC scope guard                | Resolve `tenant_id` + `scopes` from key; enforce per-action `requiredScopes`                         | `enhancement`, `mvp`, `mcp`, `mcp-server`, `security`        | Yes | Yes      | #2825 |
| MCP-1.5    | Per-key rate limits (Redis token bucket)         | Default 60 rpm / 1k rph per key; override via key metadata                                            | `enhancement`, `mvp`, `mcp`, `mcp-server`                    | Yes | Yes      | #2826 |
| MCP-1.6    | Workflow audit integration                       | Audit `mcp.session_started`, `mcp.action_executed`, `mcp.action_failed`, `mcp.session_ended`         | `enhancement`, `mvp`, `mcp`, `mcp-server`                    | Yes | Yes      | #2827 |
| MCP-1.7    | Health, readiness, version endpoints             | `/healthz`, `/readyz`, `/version` for Kubernetes; surface registry size + commit SHA                 | `enhancement`, `mvp`, `mcp`, `mcp-server`                    | Yes | Yes      | #2828 |
| MCP-1.8    | Container image + Helm/Compose descriptor        | OCI image published to ghcr.io; Compose snippet + minimal Helm chart                                 | `enhancement`, `mvp`, `mcp`, `mcp-server`                    | Yes | Yes      | #2829 |
| MCP-1.9    | OAuth2 Dynamic Client Registration (HTTP)        | RFC 7591 / RFC 8414 metadata + DCR for hosted clients that prefer OAuth over API key                 | `enhancement`, `mcp`, `mcp-server`, `security`               | No  | Yes      | #2830 |

### Detailed issues

#### MCP-1.1 — `objectified-mcp` package + MCP SDK bootstrap

**Problem**: Objectified has no MCP surface at all. Without a dedicated
package, every team that wants to point a coding agent at our data has to
re-implement REST plumbing, auth, and pagination inside their own client.
A single first-party MCP server consolidates the entire surface, makes it
auditable, and is the only entry point we have to enforce scopes, quotas,
and tenant isolation against AI clients.

**Solution / Scope**: Create a new TypeScript workspace package at
`objectified-mcp/` that wraps the official MCP SDK
(`@modelcontextprotocol/sdk`). The package exposes a single `bin` entry
point (`objectified-mcp`) that boots a server, negotiates protocol
capabilities with the client, registers the three primitive tools
(`mcp.search`, `mcp.describe`, `mcp.execute`), and advertises an empty
resources / prompts list (we do not use those MCP surfaces in v1). The
upstream HTTP client to `objectified-rest` lives in
`objectified-mcp/src/upstream/` and is the only place network calls
originate — every action implementation calls into it, never `fetch`
directly.

**Technical specification**:

```
objectified-mcp/
├── package.json
├── tsconfig.json
├── README.md
├── bin/
│   └── objectified-mcp           # node shim → src/cli.ts
└── src/
    ├── cli.ts                    # parse argv/env, choose transport
    ├── server.ts                 # MCP Server() + tool registration
    ├── tools/
    │   ├── search.ts             # mcp.search
    │   ├── describe.ts           # mcp.describe
    │   └── execute.ts            # mcp.execute
    ├── registry/
    │   ├── index.ts              # ActionRegistry singleton
    │   ├── types.ts              # ActionDescriptor, ActionContext
    │   └── actions/              # one file per action (Epic 3+)
    ├── upstream/
    │   ├── client.ts             # typed wrapper over objectified-rest
    │   ├── auth.ts               # API-key resolver
    │   └── errors.ts             # taxonomy → MCP error codes
    ├── audit/
    │   └── emit.ts               # workflow_audit writes
    └── ratelimit/
        └── tokenbucket.ts        # Redis-backed limiter
```

**Capability negotiation**:

- `tools`: enabled; lists `mcp.search`, `mcp.describe`, `mcp.execute`.
- `resources`: declared, **empty list** in v1 (we do not surface URIs).
- `prompts`: declared, **empty list** in v1.
- `roots`: ignored (server has no FS).
- `logging`: enabled at `info` by default; client can request `debug`.

**Acceptance criteria**:

- `pnpm --filter objectified-mcp build` produces a working stdio binary.
- `node bin/objectified-mcp --transport stdio` boots, accepts an
  `initialize` request from the MCP SDK test harness, and returns a
  `serverInfo` block with name, version, and capability set.
- The three primitive tools appear in the `tools/list` response with
  correct JSON schemas (validated against the MCP `Tool` schema).
- Unit tests in `objectified-mcp/tests/server.test.ts` cover boot,
  lifecycle, and shutdown.
- README documents how to run the server locally, the env vars, and the
  three primitive tools with one-line examples each.

**Parallelism**: blocks MCP-1.2, MCP-2.x, every action implementation —
must ship first.

---

#### MCP-1.3 — API-key authentication via Linked Accounts

**Problem**: MCP clients are headless; cookie-based session auth is
unavailable. We already mint API keys (`odb.api_keys`) and store linked
identities in `odb.external_auth_providers`, but those keys today can only
target REST. The MCP server needs to consume the same keys, resolve the
owning user + tenant, and refuse anything that does not match a live key.

**Solution / Scope**: Extend the existing API-key model with a `purpose`
column (`rest` | `mcp` | `both`) and a `scopes TEXT[]` column. Mint
MCP-purpose keys from a new "Generate MCP Key" affordance on the Linked
Accounts panel (UI is MCP-8.1). The MCP server reads the bearer token
from `Authorization: Bearer …` (HTTP) or the `OBJECTIFIED_MCP_KEY` env
(stdio), looks the key up via `objectified-rest`, caches the resolved
context for the lifetime of the session, and refuses every request whose
key is missing, expired, revoked, or `purpose != 'mcp'`.

**Technical specification**:

```
                ┌──────────────────────────────────────────┐
                │ Inbound MCP request (initialize / tool)  │
                └────────────────────┬─────────────────────┘
                                     │
                  ┌──────────────────▼──────────────────┐
                  │ Extract bearer token                │
                  │  HTTP : Authorization header        │
                  │  stdio: OBJECTIFIED_MCP_KEY env var │
                  └──────────────────┬──────────────────┘
                                     │
                  ┌──────────────────▼──────────────────┐
                  │ POST /v1/internal/api_keys/resolve  │
                  │  body: { token, purpose: "mcp" }    │
                  │  →    { user_id, tenant_id, scopes, │
                  │         expires_at, revoked }       │
                  └──────────────────┬──────────────────┘
                                     │
                            valid? ──┴── invalid
                              │           │
                              ▼           ▼
                   ┌─────────────┐  ┌──────────────────────┐
                   │ Cache as    │  │ Reject:              │
                   │ SessionCtx  │  │  -32001 Unauthorized │
                   │ (in-memory, │  │  with reason code    │
                   │  TTL 5 min) │  │  KEY_REVOKED |       │
                   └──────┬──────┘  │  KEY_EXPIRED |       │
                          │         │  KEY_WRONG_PURPOSE | │
                          ▼         │  KEY_NOT_FOUND       │
                ┌─────────────────┐ └──────────────────────┘
                │ Continue to     │
                │ tenant + scope  │
                │ guard (MCP-1.4) │
                └─────────────────┘
```

**Schema delta** (new migration
`objectified-db/scripts/<YYYYMMDD-HHMMSS>-mcp-keys.sql`):

```sql
ALTER TABLE odb.api_keys
  ADD COLUMN purpose VARCHAR(16) NOT NULL DEFAULT 'rest'
    CHECK (purpose IN ('rest', 'mcp', 'both')),
  ADD COLUMN scopes  TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN label   VARCHAR(120),
  ADD COLUMN last_used_at TIMESTAMPTZ;

CREATE INDEX api_keys_purpose_idx ON odb.api_keys (purpose)
  WHERE revoked_at IS NULL;
```

**Acceptance criteria**:

- A revoked key fails the very first MCP request with a deterministic,
  non-leaky error (`-32001 Unauthorized`, `reason: KEY_REVOKED`).
- An expired key fails with `reason: KEY_EXPIRED`; clock skew tolerance
  is 30 s.
- A key with `purpose='rest'` cannot authenticate to MCP; reverse is
  also true.
- Resolved `SessionCtx` is cached in-process with a 5-minute TTL keyed by
  hashed token; cache eviction on revocation arrives via a Redis pub/sub
  channel `mcp.key.revoked`.
- `last_used_at` is updated at most once per minute per key (write
  coalescing) to avoid index churn.
- Tests in `objectified-mcp/tests/auth.test.ts` cover all four reject
  reasons plus the happy path.

**Parallelism**: blocks MCP-1.4, MCP-1.5, MCP-1.6 — auth is the spine of
the server.

---

#### MCP-1.4 — Tenant scoping + RBAC scope guard

**Problem**: A single API key belongs to one tenant and a finite set of
RBAC scopes (e.g. `mcp:projects:read`, `mcp:audit:read`). Without an
enforcement point, any action could read across tenants or escalate
privileges by sniffing IDs.

**Solution / Scope**: A middleware in front of `mcp.execute` that runs
**before** dispatch:

1. Read `requiredScopes` from the `ActionDescriptor`.
2. Reject with `-32003 Forbidden` if the session lacks any required
   scope.
3. Inject `tenant_id` from the session context into every upstream REST
   call as a non-overridable header (`X-Tenant-Scope`).
4. Strip / null any field in the upstream response that does not match
   the session's `tenant_id` — defence in depth in case the upstream
   leaks.

**Acceptance criteria**:

- An action with `requiredScopes=['mcp:audit:read']` cannot be executed
  by a key without that scope; error includes the missing scope by name.
- Cross-tenant ID smuggling (passing another tenant's UUID as `projectId`)
  returns `-32004 NotFound` (not `Forbidden`) to avoid leaking existence.
- Unit tests assert that the upstream client refuses to send a request
  without `X-Tenant-Scope`.

**Parallelism**: depends on MCP-1.3; can ship in parallel with MCP-1.5
and MCP-1.6.

---

#### MCP-1.6 — Workflow audit integration

**Problem**: Every action invocation must be auditable for SOC 2 / ISO
27001 review and for after-incident forensics. AI clients can fan out
hundreds of requests per minute; the audit log is the only real evidence.

**Solution / Scope**: A small audit emitter in `objectified-mcp/src/audit/`
that posts batched rows to `objectified-rest` (`POST /v1/workflow_audit`,
which already exists). Batch size 50, flush interval 2 s, backed by an
in-memory ring buffer with a 10k-row backpressure ceiling.

**Audit action codes**:

| Code                       | Emitted on                                                  |
|----------------------------|-------------------------------------------------------------|
| `mcp.session_started`      | First request after `initialize`                            |
| `mcp.session_ended`        | Transport close or idle timeout                             |
| `mcp.action_executed`      | Successful `mcp.execute` (per call)                         |
| `mcp.action_failed`        | `mcp.execute` returned an error                             |
| `mcp.search_invoked`       | `mcp.search` (sampled at 10% to control volume)             |
| `mcp.describe_invoked`     | `mcp.describe` (sampled at 10%)                             |
| `mcp.rate_limited`         | Request rejected by limiter                                 |
| `mcp.scope_denied`         | Request rejected by scope guard                             |

**Acceptance criteria**:

- Payload includes `key_id`, `tenant_id`, `user_id`, `action_id`,
  `args_hash` (SHA-256 of the stringified args; never the args
  themselves), `duration_ms`, `result` (`ok` / error code), and
  `client_info` (MCP `clientInfo` from `initialize`).
- Args are **never** persisted in the audit row.
- Backpressure: when the ring buffer hits 10k rows, the server starts
  rejecting `mcp.execute` with `-32010 AuditBackpressure` rather than
  silently dropping audit rows.
- Tests assert that 1 000 sequential executions produce 1 000 audit
  rows (coverage, not loss).

**Parallelism**: depends on MCP-1.3; parallel with MCP-1.4, MCP-1.5.

---

## Epic 2: Core Action Framework (search / describe / execute) — MCP-EPIC-2 (#2814)

### Summary

| Roadmap ID | Title                                              | Description                                                                                          | Labels                                                | MVP | Parallel | Issue |
|------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----|----------|-------|
| MCP-2.1    | Action registry + `ActionDescriptor` type          | In-process registry, JSON-Schema-based input/output, scope + category metadata                       | `enhancement`, `mvp`, `mcp`, `mcp-action`             | Yes | No       | #2831 |
| MCP-2.2    | `mcp.search` primitive tool                        | Keyword + tag + category search across the registry; returns ranked `ActionSummary[]`                | `enhancement`, `mvp`, `mcp`, `mcp-protocol`             | Yes | No       | #2832 |
| MCP-2.3    | `mcp.describe` primitive tool                      | Returns the full `ActionDescriptor` for one action, including JSON Schemas and examples              | `enhancement`, `mvp`, `mcp`, `mcp-protocol`           | Yes | Yes      | #2833 |
| MCP-2.4    | `mcp.execute` primitive tool                       | Validates args against `inputSchema`, runs the dispatcher, normalizes errors, returns the result     | `enhancement`, `mvp`, `mcp`, `mcp-protocol`            | Yes | No       | #2834 |
| MCP-2.5    | Pagination contract (`cursor` + `limit`)           | Cursor-based pagination for every list-style action; default 50, max 200                             | `enhancement`, `mvp`, `mcp`, `mcp-action`             | Yes | Yes      | #2835 |
| MCP-2.6    | Error taxonomy (`-32xxx` codes)                    | One enum of MCP-spec-compliant error codes shared across the server                                  | `enhancement`, `mvp`, `mcp`, `mcp-action`             | Yes | Yes      | #2836 |
| MCP-2.7    | Request / response logging                         | Structured logs (`pino`), redacted args, correlation IDs, sampling                                   | `enhancement`, `mvp`, `mcp`, `mcp-server`             | Yes | Yes      | #2837 |
| MCP-2.8    | Streaming results for long-running execute calls   | Use MCP `tools/call` partial results (when available) for `audit.search` and exporter actions        | `enhancement`, `mcp`, `mcp-protocol`                   | No  | Yes      | #2838 |
| MCP-2.9    | Idempotency keys for cached results                | Optional `idempotencyKey` arg → cached response within a 60 s window                                 | `enhancement`, `mcp`, `mcp-protocol`                   | No  | Yes      | #2839 |

### Detailed issues

#### MCP-2.1 — Action registry + `ActionDescriptor` type

**Problem**: The three primitive tools are useless without a uniform,
declarative shape for the actions they dispatch. Without one type and one
registry, every action will invent its own argument convention and the
LLM-on-the-other-end will have no way to reason about it.

**Solution / Scope**: Define `ActionDescriptor` and a singleton
`ActionRegistry` that holds them. Every action lives in
`objectified-mcp/src/registry/actions/<category>/<id>.ts`, exports a
single descriptor, and registers itself at module load via a `defineAction`
helper. The registry is built **at boot**, never mutated at runtime in
v1 (no hot-reloading).

**Technical specification**:

```typescript
export type ActionId = `${string}.${string}`;
// e.g. "project.list", "class.describe", "audit.search"

export type ActionCategory =
  | 'tenant' | 'user' | 'project' | 'version' | 'branch' | 'tag'
  | 'class'  | 'property' | 'primitive' | 'group'
  | 'path'   | 'operation' | 'security' | 'server'
  | 'change_report' | 'audit' | 'repository' | 'import'
  | 'webhook' | 'merge' | 'migration';

export interface ActionDescriptor<I = unknown, O = unknown> {
  id            : ActionId;
  title         : string;
  description   : string;          // 1–3 sentences, LLM-friendly
  category      : ActionCategory;
  tags          : string[];        // free-form, used by mcp.search
  requiredScopes: string[];        // e.g. ['mcp:projects:read']
  inputSchema   : JSONSchema;      // RFC 8927-ish draft 2020-12
  outputSchema  : JSONSchema;
  examples      : Array<{ title: string; args: I; result: O }>;
  paginated     : boolean;         // hint for clients
  mutating      : boolean;         // false in v1 across the board
  handler       : (args: I, ctx: ActionContext) => Promise<O>;
}

export interface ActionContext {
  tenantId : string;
  userId   : string;
  scopes   : string[];
  requestId: string;
  upstream : UpstreamClient;
  logger   : Logger;
}
```

**Registry shape**:

```
                  ┌─────────────────────────────────┐
                  │       ActionRegistry            │
                  ├─────────────────────────────────┤
                  │  byId   : Map<ActionId, AD>     │
                  │  byTag  : Map<string, ActionId[]>│
                  │  byCat  : Map<Cat,    ActionId[]>│
                  │  search : MiniSearch (lunr-like)│
                  └────────────────┬────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ project.list    │      │ class.describe  │      │ audit.search    │
│ project.describe│      │ class.list      │      │ audit.describe  │
│ project.list_   │      │ class.list_     │      │ change_report.  │
│   versions      │      │   properties    │      │   list          │
└─────────────────┘      └─────────────────┘      └─────────────────┘
```

**Acceptance criteria**:

- `defineAction(descriptor)` validates the descriptor at boot:
  `id` matches `^[a-z_]+\.[a-z_]+$`, `requiredScopes` is non-empty,
  schemas parse as JSON Schema 2020-12.
- Boot fails loudly on duplicate IDs.
- Registry exposes `search(q)`, `describe(id)`, `dispatch(id, args, ctx)`
  — these three methods are the **only** way the primitive tools touch
  the actions.
- `mutating === true` is currently rejected at boot; v1 is read-only by
  contract.
- Snapshot test asserts the boot-time registry contains the expected
  set of MVP actions.

**Parallelism**: blocks every other ticket in this epic, blocks Epic 3+.

---

#### MCP-2.2 — `mcp.search` primitive tool

**Problem**: The LLM does not know what actions exist. We need a discovery
primitive that lets the model enumerate or narrow the registry by intent.

**Solution / Scope**: Implement `mcp.search` as a thin wrapper around
`ActionRegistry.search(q)`. Backed by an in-process `MiniSearch` (or
equivalent) index over `id`, `title`, `description`, `category`, and
`tags`. Returns ranked summaries — never the full descriptor.

**Tool signature** (advertised to the client):

```jsonc
{
  "name": "mcp.search",
  "description": "Search the Objectified action registry for a tool by keyword, category, or resource. Returns ranked summaries; call mcp.describe for the full schema before mcp.execute.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "q":        { "type": "string", "minLength": 1, "maxLength": 200 },
      "category": { "type": "string", "enum": [/* ActionCategory */] },
      "tag":      { "type": "string", "maxLength": 64 },
      "limit":    { "type": "integer", "minimum": 1, "maximum": 50, "default": 10 }
    }
  }
}
```

**Output shape**:

```jsonc
{
  "items": [
    {
      "id":          "class.list_properties",
      "title":       "List the properties of a class",
      "description": "Return all properties bound to a class in a given version, paginated.",
      "category":    "class",
      "tags":        ["schema", "properties"],
      "score":       0.91
    }
  ],
  "totalEstimated": 42
}
```

**Acceptance criteria**:

- `q` may be omitted when `category` or `tag` is supplied.
- Search is case-insensitive and tolerates one typo per token (BM25 +
  edit distance ≤ 1).
- Results are stable for a given query under the same registry build
  (deterministic tie-break by `id`).
- The tool never returns a descriptor with a scope the caller lacks —
  filter at result time.
- Tests cover: keyword match, category filter, tag filter, scope
  filtering, empty result, oversized `limit`.

**Parallelism**: depends on MCP-2.1; parallel with MCP-2.3, MCP-2.4.

---

#### MCP-2.3 — `mcp.describe` primitive tool

**Problem**: After search picks an action, the LLM needs the exact JSON
Schema of the inputs and outputs to formulate a valid `mcp.execute` call.

**Solution / Scope**: `mcp.describe({ actionId })` returns the full
`ActionDescriptor` minus the `handler` closure. JSON Schemas are
serialized as-is (draft 2020-12). Examples are included verbatim.

**Tool signature**:

```jsonc
{
  "name": "mcp.describe",
  "description": "Return the full input and output JSON Schema, scopes, and worked examples for a single action. Always call this before mcp.execute on an unfamiliar action.",
  "inputSchema": {
    "type": "object",
    "required": ["actionId"],
    "additionalProperties": false,
    "properties": {
      "actionId":      { "type": "string", "pattern": "^[a-z_]+\\.[a-z_]+$" },
      "includeExamples": { "type": "boolean", "default": true }
    }
  }
}
```

**Output**: the `ActionDescriptor` (minus `handler`), or
`-32004 NotFound` if the action does not exist or the caller lacks any
of its `requiredScopes` (treat scope failure as not-found here too, to
avoid leaking the registry).

**Acceptance criteria**:

- Output validates against the MCP `Tool` schema layer plus an
  Objectified-published `ActionDescriptor.json` schema.
- Examples are stable across releases — they live in committed JSON
  fixtures.
- Tests cover: known action, unknown action, scope-filtered action.

**Parallelism**: depends on MCP-2.1; parallel with MCP-2.2, MCP-2.4.

---

#### MCP-2.4 — `mcp.execute` primitive tool

**Problem**: Search and describe are useless without an executor. The
executor is the single point that enforces validation, scopes, rate
limits, audit, and error normalization.

**Solution / Scope**: `mcp.execute({ actionId, args, idempotencyKey? })`.
Pipeline:

```
                    ┌──────────────────────────────┐
                    │ mcp.execute(args)            │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │ 1. Resolve descriptor        │
                    │    (404 if unknown)          │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │ 2. Scope guard (MCP-1.4)     │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │ 3. Rate limit (MCP-1.5)      │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │ 4. Validate args against     │
                    │    descriptor.inputSchema    │
                    │    (Ajv, strict mode)        │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │ 5. Dispatch handler with     │
                    │    ActionContext             │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │ 6. Validate result against   │
                    │    descriptor.outputSchema   │
                    │    (dev-only; production    │
                    │     samples 1 in 1000)       │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │ 7. Audit (MCP-1.6) + return  │
                    └──────────────────────────────┘
```

**Tool signature**:

```jsonc
{
  "name": "mcp.execute",
  "description": "Run an action from the Objectified registry. Always call mcp.describe first to learn the input schema. Returns the action's typed result or a normalized error.",
  "inputSchema": {
    "type": "object",
    "required": ["actionId", "args"],
    "additionalProperties": false,
    "properties": {
      "actionId":       { "type": "string", "pattern": "^[a-z_]+\\.[a-z_]+$" },
      "args":           { "type": "object" },
      "idempotencyKey": { "type": "string", "maxLength": 64 }
    }
  }
}
```

**Acceptance criteria**:

- Invalid args fail with `-32602 InvalidParams` and a list of pointer
  paths into `args`.
- Handler exceptions are mapped to the error taxonomy (MCP-2.6); raw
  stack traces never leak to the client.
- Output validation runs at full rate in `NODE_ENV !== 'production'`
  and at 0.1% sampling in production.
- Idempotency key is honored only when MCP-2.9 lands; v1 ignores it
  with a warning.
- Tests cover: happy path, schema reject, scope reject, rate-limit
  reject, handler throws, upstream timeout.

**Parallelism**: depends on MCP-2.1; blocks every action implementation
(Epics 3–7).

---

## Epic 3: Discovery Actions — Tenancy, Users, Projects — MCP-EPIC-3 (#2815)

### Summary

| Roadmap ID | Title                                              | Description                                                                                          | Labels                                                | MVP | Parallel | Issue |
|------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----|----------|-------|
| MCP-3.1    | `tenant.list` + `tenant.describe`                  | List the tenants the key can see (typically one) and return tenant metadata                          | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | No       | #2840 |
| MCP-3.2    | `user.list` + `user.describe`                      | List users in the tenant, describe one user (no PII beyond email + display name)                     | `enhancement`, `mvp`, `mcp`, `mcp-action`, `security` | Yes | Yes  | #2841 |
| MCP-3.3    | `project.list` + `project.describe`                | List projects in the tenant; describe metadata, owners, default version                              | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2842 |
| MCP-3.4    | `project.list_versions`                            | List versions of a project ordered by `created_at`, status filter                                    | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2843 |
| MCP-3.5    | `project.list_collaborators`                       | List users + roles for a project                                                                     | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2844 |
| MCP-3.6    | `tenant.list_quotas`                               | Return tenant-level quotas (seats, storage, MCP rps) — useful for capacity questions                 | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2845 |

### Detailed issues

#### MCP-3.3 — `project.list` + `project.describe`

**Problem**: A coding agent hitting MCP for the first time needs to enumerate
projects to ground every subsequent question ("describe the latest version of
the orders-api project"). Without this pair, every other action requires the
user to paste a UUID by hand.

**Solution / Scope**: Two actions sharing one upstream call
(`GET /v1/projects` and `GET /v1/projects/{id}` in `objectified-rest`).
Both honor tenant scoping and the `mcp:projects:read` scope.

**Action descriptors**:

```jsonc
// project.list
{
  "id":          "project.list",
  "title":       "List projects",
  "description": "List all projects visible to the caller in their tenant. Supports keyword filter and cursor pagination.",
  "category":    "project",
  "tags":        ["projects", "discovery", "catalog"],
  "requiredScopes": ["mcp:projects:read"],
  "paginated":   true,
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "q":      { "type": "string", "maxLength": 200 },
      "status": { "type": "string", "enum": ["active", "archived", "all"], "default": "active" },
      "cursor": { "type": "string" },
      "limit":  { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 }
    }
  },
  "outputSchema": {
    "type": "object",
    "required": ["items", "pageInfo"],
    "properties": {
      "items": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["id", "name", "slug", "status", "createdAt"],
          "properties": {
            "id":          { "type": "string", "format": "uuid" },
            "name":        { "type": "string" },
            "slug":        { "type": "string" },
            "description": { "type": "string" },
            "status":      { "type": "string", "enum": ["active", "archived"] },
            "defaultVersionId": { "type": "string", "format": "uuid", "nullable": true },
            "createdAt":   { "type": "string", "format": "date-time" }
          }
        }
      },
      "pageInfo": {
        "type": "object",
        "required": ["hasMore"],
        "properties": {
          "nextCursor": { "type": "string" },
          "hasMore":    { "type": "boolean" }
        }
      }
    }
  }
}

// project.describe
{
  "id":          "project.describe",
  "title":       "Describe a project",
  "description": "Return full metadata for a single project, including counts of versions, classes, and paths.",
  "category":    "project",
  "tags":        ["projects", "discovery"],
  "requiredScopes": ["mcp:projects:read"],
  "inputSchema": {
    "type": "object",
    "required": ["projectId"],
    "properties": {
      "projectId": { "type": "string", "format": "uuid" }
    }
  },
  "outputSchema": { /* full project + counts */ }
}
```

**Acceptance criteria**:

- Cursor is opaque base64 of `{lastId, lastCreatedAt}` — never a raw
  offset.
- `q` performs case-insensitive substring match on `name`, `slug`, and
  `description`.
- `project.describe` includes counts (`versionsCount`, `classesCount`,
  `pathsCount`) computed in the upstream view, not by the MCP server.
- Cross-tenant `projectId` returns `-32004 NotFound`.
- Worked examples in the descriptor cover: list active, list archived,
  describe by ID.

**Parallelism**: depends on MCP-2.1; parallel with MCP-3.2, MCP-3.4.

---

## Epic 4: Discovery Actions — Versions, Branches, Tags — MCP-EPIC-4 (#2816)

### Summary

| Roadmap ID | Title                                              | Description                                                                                          | Labels                                                | MVP | Parallel | Issue |
|------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----|----------|-------|
| MCP-4.1    | `version.describe`                                 | Return version metadata, status, owning project, default branch, current head SHA                    | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2846 |
| MCP-4.2    | `version.list_branches`                            | Branches under a version, with head pointers                                                         | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2847 |
| MCP-4.3    | `version.list_tags`                                | Tags on a version, with annotations                                                                  | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2848 |
| MCP-4.4    | `version.list_change_reports`                      | List `change_reports` rows tied to a version                                                         | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2849 |
| MCP-4.5    | `version.diff`                                     | Diff two versions (or two revisions of one version) at the schema level                              | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2850 |
| MCP-4.6    | `branch.list_revisions`                            | Revisions on a branch (history walk)                                                                 | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2851 |
| MCP-4.7    | `tag.describe`                                     | Single-tag metadata + downstream effects (which classes/paths are pinned)                            | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2852 |
---

## Epic 5: Discovery Actions — Schema Model — MCP-EPIC-5 (#2817)

### Summary

| Roadmap ID | Title                                              | Description                                                                                          | Labels                                                | MVP | Parallel | Issue |
|------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----|----------|-------|
| MCP-5.1    | `class.list` + `class.describe`                    | List classes in a version; describe metadata, parent, properties count                               | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | No       | #2853 |
| MCP-5.2    | `class.list_properties`                            | Properties bound to a class (resolved from `class_properties`)                                       | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2854 |
| MCP-5.3    | `property.list` + `property.describe`              | All properties in a version + per-property detail (type, primitive, validators)                      | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2855 |
| MCP-5.4    | `primitive.list` + `primitive.describe`            | Catalog of primitives shipped with Objectified                                                       | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2856 |
| MCP-5.5    | `class_template.list` + `class_template.describe`  | Class templates the user can derive from                                                             | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2857 |
| MCP-5.6    | `property_template.list` + `property_template.describe` | Property templates                                                                              | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2858 |
| MCP-5.7    | `group.list` + `group.describe`                    | Class groups (`groups` + `group_classes`)                                                            | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2859 |
| MCP-5.8    | `class.list_dependents`                            | Reverse lookup: which other classes / paths reference this class                                     | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2860 |
| MCP-5.9    | `class.export_jsonschema`                          | Export a single class as standalone JSON Schema (Draft 2020-12)                                      | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2861 |

### Detailed issues

#### MCP-5.1 — `class.list` + `class.describe`

**Problem**: Classes are the centre of gravity of the Objectified data
model. Every meaningful agent question ("what fields does the Order class
have", "which paths return a Customer") starts here. Without these two
actions, the rest of the schema-side surface is unreachable.

**Solution / Scope**: Two actions backed by the existing
`/v1/versions/{vid}/classes` and `/v1/classes/{id}` endpoints in
`objectified-rest`. `class.describe` returns the full class envelope
(metadata + property handles + tags + group memberships) but **not** the
fully resolved JSON Schema — that is MCP-5.9.

**Tree of related discovery calls**:

```
                  project.list
                       │
                       ▼
                  project.describe ── projectId
                       │
                       ▼
                  project.list_versions
                       │
                       ▼
                  version.describe ── versionId
                       │
       ┌───────────────┼────────────────┬─────────────────┐
       ▼               ▼                ▼                 ▼
   class.list     path.list      version.list_   version.list_tags
       │              │            change_reports
       ▼              ▼
   class.describe  path.describe
       │
       ▼
   class.list_properties      class.export_jsonschema
       │                          │
       ▼                          ▼
   property.describe         <Draft 2020-12 JSON Schema document>
```

**Acceptance criteria**:

- `class.list` accepts `versionId` (required), optional `q`, optional
  `groupId`, optional `tag`, cursor, limit.
- Each item returns `{ id, name, slug, description, baseClassId,
  propertiesCount, tags, updatedAt }`.
- `class.describe` adds `properties: [{ id, name, primitiveId,
  required, deprecated }]` (lightweight handles, not full property docs).
- Cross-version IDs return `-32004 NotFound` even if the class exists
  in another version.
- Tests cover: list + filter + paginate, describe by ID, deprecated
  classes are surfaced behind `includeDeprecated: true`.

**Parallelism**: blocks MCP-5.2, MCP-5.3, MCP-5.8, MCP-5.9 — must ship
first inside this epic.

---

#### MCP-5.9 — `class.export_jsonschema`

**Problem**: An agent often wants the raw, fully-resolved JSON Schema for
a class (to feed into a code generator, validator, or test harness).
Walking property-by-property over MCP would be expensive and lossy.

**Solution / Scope**: Reuse the existing JSON Schema generator
(`objectified-rest/src/app/jsonschema_generator.py`) behind a new
read-only endpoint `GET /v1/classes/{id}/jsonschema?draft=2020-12` and
expose it through MCP. Output is the standalone JSON Schema document plus
`$id`, `$schema`, and `$comment` lines naming the source class.

**Output shape** (truncated):

```json
{
  "$schema":  "https://json-schema.org/draft/2020-12/schema",
  "$id":      "https://objectified.dev/schemas/orders/order/v3",
  "$comment": "Generated by Objectified MCP from class 5d…",
  "title":    "Order",
  "type":     "object",
  "required": ["id", "lineItems", "totalCents"],
  "properties": {
    "id":         { "type": "string", "format": "uuid" },
    "lineItems":  { "type": "array", "items": { "$ref": "#/$defs/LineItem" } },
    "totalCents": { "type": "integer", "minimum": 0 }
  },
  "$defs": {
    "LineItem": { "type": "object", "properties": { /* … */ } }
  }
}
```

**Acceptance criteria**:

- `draft` argument accepts `2020-12` (default), `2019-09`, `7`.
- Recursive class references collapse to `$defs` with deterministic
  names.
- Deprecated properties surface with `deprecated: true`.
- The handler caches the generated schema for 60 s keyed by
  `(classId, classUpdatedAt, draft)`.
- Tests assert the output validates as JSON Schema using `ajv` with the
  selected draft.

**Parallelism**: depends on MCP-5.1; parallel with MCP-5.2 and MCP-5.3.

---

## Epic 6: Discovery Actions — API Surface (Paths, Operations, Servers, Security) — MCP-EPIC-6 (#2818)

### Summary

| Roadmap ID | Title                                              | Description                                                                                          | Labels                                                | MVP | Parallel | Issue |
|------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----|----------|-------|
| MCP-6.1    | `path.list` + `path.describe`                      | List paths in a version, describe one path                                                           | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2862 |
| MCP-6.2    | `path_operation.describe`                          | Method + operation on a path: parameters, request body, responses                                    | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2863 |
| MCP-6.3    | `path_operation.list_parameters` + `.list_responses`| Decoupled accessors so an LLM can fetch only what it needs                                          | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2864 |
| MCP-6.4    | `version.export_openapi`                           | Export a version as OpenAPI 3.1 (reuse existing exporter)                                            | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2865 |
| MCP-6.5    | `version.export_asyncapi`                          | Export a version's AsyncAPI 3.x surface (when present)                                               | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2866 |
| MCP-6.6    | `version.export_arazzo`                            | Export Arazzo workflows for a version                                                                | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2867 |
| MCP-6.7    | `security_scheme.list` + `server.list`             | Security schemes and servers attached to a version                                                   | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2868 |

### Detailed issues

#### MCP-6.4 — `version.export_openapi`

**Problem**: An LLM often wants the entire OpenAPI document for a version,
either to drive code generation or to compare against a published artifact.
Reconstructing the document path-by-path over MCP is wasteful.

**Solution / Scope**: Reuse the existing OpenAPI exporter (already used by
the publication change report and the import pipeline) behind a
read-only `GET /v1/versions/{id}/export?format=openapi-3.1` endpoint and
expose it via `version.export_openapi`. The result is returned as a
single JSON document (YAML conversion is a client concern).

**Acceptance criteria**:

- `format` arg accepts `openapi-3.0` and `openapi-3.1`.
- Documents larger than 5 MB return `-32011 ResultTooLarge` with a hint
  to call `version.export_openapi_chunk` (a future ticket); v1 just
  refuses with a clear message rather than silently truncating.
- The handler caches per `(versionId, versionUpdatedAt, format)` for 60 s.
- Tests assert the output validates against the OpenAPI 3.1 meta-schema.

---

## Epic 7: Discovery Actions — Operational & Audit — MCP-EPIC-7 (#2819)

### Summary

| Roadmap ID | Title                                              | Description                                                                                          | Labels                                                | MVP | Parallel | Issue |
|------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----|----------|-------|
| MCP-7.1    | `audit.search` + `audit.describe`                  | Search `odb.workflow_audit` by actor, action, time window; describe one row                          | `enhancement`, `mvp`, `mcp`, `mcp-action`, `security` | Yes | Yes  | #2869 |
| MCP-7.2    | `change_report.list` + `change_report.describe`    | Browse change reports; describe one report (full diff snapshot)                                      | `enhancement`, `mvp`, `mcp`, `mcp-action`          | Yes | Yes      | #2870 |
| MCP-7.3    | `migration_plan.list` + `migration_plan.describe`  | Migration plans + their rules                                                                        | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2871 |
| MCP-7.4    | `merge_session.list` + `merge_session.describe`    | Merge sessions + conflicts                                                                           | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2872 |
| MCP-7.5    | `repository.list` + `repository.describe`          | Surface registered repositories from the Repository roadmap                                          | `enhancement`, `mcp`, `mcp-action`, `repository`   | No  | Yes      | #2873 |
| MCP-7.6    | `webhook_subscription.list`                        | Push-webhook subscriptions on the tenant                                                             | `enhancement`, `mcp`, `mcp-action`                 | No  | Yes      | #2874 |
| MCP-7.7    | `data_record.search`                               | Search `odb.data_record` for live data tied to a class                                               | `enhancement`, `mcp`, `mcp-action`, `v2-enterprise`| No  | Yes      | #2875 |

### Detailed issues

#### MCP-7.1 — `audit.search` + `audit.describe`

**Problem**: AI agents and human operators both want to ask "who changed
the Order class on Tuesday and why" or "show me every failed publish in
the last hour." Without an MCP-friendly query over `workflow_audit`, the
only option is the existing UI, which is not addressable by an agent.

**Solution / Scope**: Two actions backed by the existing
`GET /v1/workflow_audit` endpoint with extended filters. `audit.search`
is paginated and capped at a 90-day window for non-enterprise tenants.

**Action descriptor (excerpt)**:

```jsonc
{
  "id":          "audit.search",
  "title":       "Search workflow audit log",
  "description": "Search the tenant-wide workflow audit log by actor, action code, target object, time window, and result.",
  "category":    "audit",
  "tags":        ["audit", "compliance", "history"],
  "requiredScopes": ["mcp:audit:read"],
  "paginated":   true,
  "inputSchema": {
    "type": "object",
    "required": ["from", "to"],
    "properties": {
      "from":     { "type": "string", "format": "date-time" },
      "to":       { "type": "string", "format": "date-time" },
      "actor":    { "type": "string", "description": "user_id (UUID) or email" },
      "action":   { "type": "string", "examples": ["class.created", "version.published"] },
      "objectId": { "type": "string", "format": "uuid" },
      "result":   { "type": "string", "enum": ["ok", "error", "any"], "default": "any" },
      "cursor":   { "type": "string" },
      "limit":    { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 }
    }
  }
}
```

**ASCII layout of a single audit row in the result**:

```
┌──────────────────────────────────────────────────────────────────────┐
│ audit row                                                            │
├──────────────────────────────────────────────────────────────────────┤
│ id           UUID                                                    │
│ ts           2026-04-22T17:42:11.318Z                                │
│ tenant_id    UUID                                                    │
│ actor_id     UUID  (user_id, or null for system / mcp-key)           │
│ actor_kind   "user" | "api_key" | "mcp_key" | "system"               │
│ action       "class.created"                                         │
│ object_kind  "class"                                                 │
│ object_id    UUID                                                    │
│ result       "ok"                                                    │
│ ip / ua      …                                                       │
│ summary      "Created class 'Order' in version v3 of orders-api"     │
└──────────────────────────────────────────────────────────────────────┘
```

**Acceptance criteria**:

- Time window cannot exceed 90 days (non-enterprise) or 365 days
  (enterprise); larger windows return `-32602 InvalidParams`.
- Default sort: `ts DESC`; cursor encodes `(ts, id)` for deterministic
  paging.
- Output never includes raw before/after diffs (those live in
  `change_reports`); the row carries an `objectRef` the caller can
  follow via `change_report.describe`.
- Tests cover: no filters, actor filter, action prefix filter
  (`action: "class."`), 90-day cap rejection, pagination across 5 pages.

**Parallelism**: depends on MCP-2.1; parallel with the rest of Epic 7.

---

## Epic 8: ADE UI — MCP Onboarding & Catalog — MCP-EPIC-8 (#2820)

### Summary

| Roadmap ID | Title                                              | Description                                                                                          | Labels                                                | MVP | Parallel | Issue |
|------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----|----------|-------|
| MCP-8.1    | MCP API-key issuance UI                            | "Generate MCP Key" affordance on the Linked Accounts panel; scope picker; one-time reveal            | `enhancement`, `mvp`, `mcp`, `mcp-key`, `ui`          | Yes | No       | #2876 |
| MCP-8.2    | Connection wizard (`mcp.json` snippet)             | Generate a copy-paste snippet for Cursor / Claude Desktop / ChatGPT Desktop / generic                | `enhancement`, `mvp`, `mcp`, `mcp-catalog`, `ui`      | Yes | No       | #2877 |
| MCP-8.3    | Action catalog browser                             | In-ADE searchable browser over the live action registry                                              | `enhancement`, `mvp`, `mcp`, `mcp-catalog`, `ui`      | Yes | Yes      | #2878 |
| MCP-8.4    | Per-key activity log                               | Show audit rows scoped to a single MCP key                                                           | `enhancement`, `mvp`, `mcp`, `mcp-key`, `ui`          | Yes | Yes      | #2879 |
| MCP-8.5    | Per-tenant disable / revocation controls           | Tenant admin can revoke any key, disable MCP entirely, or freeze a category                          | `enhancement`, `mvp`, `mcp`, `mcp-key`, `ui`, `security` | Yes | Yes  | #2880 |
| MCP-8.6    | Documentation site                                 | `/docs/mcp` rendered from the registry; published per release                                        | `enhancement`, `mvp`, `mcp`, `mcp-catalog`            | Yes | Yes      | #2881 |
| MCP-8.7    | Postman / Bruno collection export                  | Export the registry as a Postman v2.1 / Bruno collection for non-MCP clients                         | `enhancement`, `mcp`, `mcp-catalog`                   | No  | Yes      | #2882 |

### Detailed issues

#### MCP-8.2 — Connection wizard (`mcp.json` snippet)

**Problem**: The single biggest friction point for a new MCP user is the
client-side config file. Every client expects a slightly different shape;
copy-pasting a UUID into the wrong key field is a five-minute support
ticket.

**Solution / Scope**: A wizard inside the ADE that, after a key is
issued, walks the user through (1) picking a target client, (2) choosing
a transport, (3) optionally scoping by project, and (4) revealing a
copy-button-ready snippet for that client.

**ASCII wireframe**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ADE › Account › Linked Accounts › MCP Keys                              │
├─────────────────────────────────────────────────────────────────────────┤
│  Active MCP keys                                              [+ New ▾] │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ ● cursor-laptop       scope: read · last used 2m ago    [Revoke]│    │
│  │ ● claude-desktop      scope: read · last used 4h ago    [Revoke]│    │
│  │ ● ci-runner           scope: read · audit  · never used [Revoke]│    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────  Connect a new MCP client  ─────────────────────────┐
  │ Step 1 / 4 · Client                                                  │
  │                                                                       │
  │   ◉  Cursor                                                           │
  │   ○  Claude Desktop                                                   │
  │   ○  ChatGPT Desktop                                                  │
  │   ○  Continue                                                         │
  │   ○  Generic (raw mcp.json)                                           │
  │                                                                       │
  │                                                  [ Cancel ] [ Next ▶ ]│
  ├───────────────────────────────────────────────────────────────────────┤
  │ Step 2 / 4 · Transport                                                │
  │                                                                       │
  │   ◉  Streamable HTTP   https://mcp.objectified.dev   (recommended)    │
  │   ○  stdio             (run a local copy of objectified-mcp)          │
  │                                                                       │
  │                                          [ ◀ Back ] [ Cancel ] [ ▶ ]  │
  ├───────────────────────────────────────────────────────────────────────┤
  │ Step 3 / 4 · Scopes                                                   │
  │                                                                       │
  │   ☑ mcp:projects:read                                                 │
  │   ☑ mcp:schema:read                                                   │
  │   ☑ mcp:paths:read                                                    │
  │   ☑ mcp:audit:read                                                    │
  │   ☐ mcp:data:read       (V2 — requires Enterprise)                    │
  │   ☐ mcp:write:*         (V2 — requires Enterprise)                    │
  │                                                                       │
  │                                          [ ◀ Back ] [ Cancel ] [ ▶ ]  │
  ├───────────────────────────────────────────────────────────────────────┤
  │ Step 4 / 4 · Snippet                                                  │
  │                                                                       │
  │   This key will be shown ONCE. Save it somewhere safe.                │
  │   ┌───────────────────────────────────────────────────────────┐       │
  │   │ {                                                         │       │
  │   │   "mcpServers": {                                         │       │
  │   │     "objectified": {                                      │       │
  │   │       "url": "https://mcp.objectified.dev",               │       │
  │   │       "headers": {                                        │       │
  │   │         "Authorization":                                  │       │
  │   │           "Bearer mcp_live_4f9c…revealed_once…"           │       │
  │   │       }                                                   │       │
  │   │     }                                                     │       │
  │   │   }                                                       │       │
  │   │ }                                                         │       │
  │   └───────────────────────────────────────────────────────────┘       │
  │                                                                       │
  │   [ Copy snippet ]   [ Download mcp.json ]   [ I've saved it ✓ ]      │
  └───────────────────────────────────────────────────────────────────────┘
```

**Per-client snippet templates**:

| Client            | Target file path (informational)                                | Wraps key in    |
|-------------------|------------------------------------------------------------------|-----------------|
| Cursor            | `~/.cursor/mcp.json`                                            | `mcpServers`    |
| Claude Desktop    | `~/Library/Application Support/Claude/claude_desktop_config.json` | `mcpServers`  |
| ChatGPT Desktop   | `~/Library/Application Support/ChatGPT/mcp.json`                | `mcpServers`    |
| Continue          | `~/.continue/config.json` → `mcpServers` block                  | `mcpServers`    |
| Generic           | raw `mcp.json`                                                  | `mcpServers`    |

**Acceptance criteria**:

- The token is rendered exactly once; closing the wizard discards the
  cleartext (UI state only, never sent to telemetry).
- Snippet generator is a pure function — covered by snapshot tests for
  every supported client.
- Stdio variant generates an `npx -y @objectified/mcp` command and a
  `OBJECTIFIED_MCP_KEY` env entry.
- Scopes selection is constrained by the caller's RBAC; an Editor cannot
  mint an `mcp:audit:read` key.
- Playwright spec `e2e/mcp-key-wizard.spec.ts` covers the four-step
  happy path with a mocked key-issuance endpoint.

**Parallelism**: depends on MCP-8.1; parallel with MCP-8.3, MCP-8.4,
MCP-8.5, MCP-8.6.

---

## Epic 9: Enterprise V2 — MCP-EPIC-9 (#2821)

### Summary

| Roadmap ID   | Title                                              | Description                                                                                          | Labels                                                | MVP | Parallel | Issue |
|--------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----|----------|-------|
| V2-MCP-9.1   | Write-back actions (gated)                         | `class.create`, `property.add`, `version.publish`, `tag.create` — gated on `mcp:write:*`             | `enhancement`, `mcp`, `mcp-protocol`, `v2-enterprise`, `security` | No | No  | #2883 |
| V2-MCP-9.2   | AI-assisted query planning                         | Optional helper that takes natural language and proposes an action chain (search→describe→execute)   | `enhancement`, `mcp`, `ai`, `v2-enterprise`           | No  | Yes      | #2884 |
| V2-MCP-9.3   | GraphQL-like query layer                           | One MCP action `graph.query` accepting a GraphQL document over the discovery surface                 | `enhancement`, `mcp`, `v2-enterprise`                 | No  | Yes      | #2885 |
| V2-MCP-9.4   | Federated MCP across tenants                       | A single key can list multiple tenants the user belongs to and switch active tenant per call         | `enhancement`, `mcp`, `mcp-server`, `v2-enterprise`   | No  | No       | #2886 |
| V2-MCP-9.5   | Custom OPA policies per action                     | Hook OPA into the dispatch pipeline: per-action allow/deny rules in the tenant's policy bundle       | `enhancement`, `mcp`, `governance`, `v2-enterprise`   | No  | Yes      | #2887 |
| V2-MCP-9.6   | Bulk export actions                                | `version.export_bundle`, `tenant.export_audit_window` — large, streamed payloads                     | `enhancement`, `mcp`, `mcp-protocol`, `v2-enterprise`  | No  | Yes      | #2888 |
| V2-MCP-9.7   | Self-hosted MCP companion                          | Deployment recipe + signed image for customers running MCP inside their own VPC                      | `enhancement`, `mcp`, `mcp-server`, `v2-enterprise`   | No  | Yes      | #2889 |
| V2-MCP-9.8   | Custom action SDK                                  | Tenant-defined actions registered through a signed plug-in bundle                                    | `enhancement`, `mcp`, `mcp-action`, `v2-enterprise`   | No  | No       | #2890 |

### Detailed issues

#### V2-MCP-9.2 — AI-assisted query planning

**Problem**: A coding agent typically issues one request at a time and
cannot easily compose multi-step plans across `mcp.search`, `mcp.describe`,
and `mcp.execute`. For non-power users, this leads to "I don't know what
to ask" failures.

**Solution / Scope**: Add an optional fourth tool, `mcp.plan`, gated
behind the Enterprise tier and the `mcp:plan:read` scope. It accepts a
natural-language query, runs it through the local Ollama cluster (per
`PLANNED_FEATURE_ROADMAP_AI.md`) with a constrained system prompt, and
returns an **executable plan** as a list of `mcp.execute` calls — the
client decides whether to run them.

**ASCII flow**:

```
            client                 mcp.plan { q: "How many breaking
              │                                changes shipped to the
              │                                orders-api last week?" }
              ▼
   ┌──────────────────────────────────────┐
   │ Guardrails (per AI roadmap):         │
   │  - PII filter on the question        │
   │  - Action allowlist (read-only)      │
   └──────────────────┬───────────────────┘
                      │
                      ▼
   ┌──────────────────────────────────────┐
   │ Ollama prompt: "Given this registry  │
   │ subset, produce a plan as JSON …"    │
   │ Inject: registry summaries           │
   │         tenant/project context       │
   └──────────────────┬───────────────────┘
                      │
                      ▼
   ┌──────────────────────────────────────┐
   │ Validate JSON plan against           │
   │ Plan.json schema; reject hallucinated│
   │ action IDs                           │
   └──────────────────┬───────────────────┘
                      │
                      ▼
   {
     "plan": [
       { "actionId": "project.list",       "args": { "q": "orders-api" } },
       { "actionId": "project.list_versions","args": { "projectId": "$1.items[0].id" } },
       { "actionId": "version.list_change_reports",
         "args": { "versionId": "$2.items[0].id",
                   "from": "2026-04-15T00:00Z",
                   "to":   "2026-04-22T00:00Z",
                   "kind": "breaking" } }
     ],
     "rationale": "..."
   }
```

**Acceptance criteria**:

- `mcp.plan` is opt-in per tenant and disabled by default.
- The planner can only reference action IDs present in the live
  registry; references to unknown IDs are rejected at validation.
- The plan is **never executed** by the planner — it is returned to the
  caller for review.
- All prompts and responses pass through Guardrails.ai per the AI
  roadmap.
- Audit row `mcp.plan_proposed` records the question hash, the model,
  the rejected/accepted result, and the plan length.

---

## Cross-cutting: integration & test plan

| Area              | Existing assets                               | Add inside the listed issues                                  |
|-------------------|-----------------------------------------------|---------------------------------------------------------------|
| Auth / API keys   | `odb.api_keys`, `LINKED_ACCOUNTS_*` docs      | Reuse for token storage; extend with `purpose` + `scopes`     |
| Workflow audit    | `objectified-rest/docs/WORKFLOW_AUDIT_API.md` | Add `mcp.*` action codes (MCP-1.6)                            |
| Schema generator  | `objectified-rest/src/app/jsonschema_generator.py` | Reuse for MCP-5.9                                        |
| OpenAPI exporter  | `objectified-rest/scripts/generate_openapi.py` | Reuse for MCP-6.4                                            |
| AsyncAPI / Arazzo | `objectified-rest/src/app/arazzo_generator.py` | Reuse for MCP-6.5 / MCP-6.6 once Repository roadmap lands    |
| Repository data   | `PLANNED_FEATURE_ROADMAP_REPOSITORY.md`       | Surface read-only via MCP-7.5                                 |
| AI / Ollama       | `PLANNED_FEATURE_ROADMAP_AI.md`               | Used only by V2-MCP-9.2                                       |
| Governance        | `PLANNED_FEATURE_ROADMAP_GOVERNANCE.md`       | Hook into V2-MCP-9.5 (custom OPA)                             |

**E2E coverage to add inside the issues (not stand-alone tickets)**:

- `e2e/mcp-key-wizard.spec.ts` (MCP-8.1, MCP-8.2)
- `e2e/mcp-stdio-handshake.spec.ts` (MCP-1.1, MCP-1.2)
- `e2e/mcp-search-describe-execute.spec.ts` (MCP-2.x against a seeded tenant)
- `e2e/mcp-scope-enforcement.spec.ts` (MCP-1.4)
- `e2e/mcp-rate-limit.spec.ts` (MCP-1.5)
- `e2e/mcp-audit-emission.spec.ts` (MCP-1.6, MCP-7.1)

---

## Single-page ordered checklist (implementation order)

The following is the **execution order** across all epics. Items with the
same number-prefix can be parallelized across developers because their
**Parallel** flag is `Yes`. Items marked `(MVP)` are required for the
MCP v1 release; `(V2)` items are explicitly enterprise.

1. ~~[#2822] MCP-1.1 — `objectified-mcp` package + MCP SDK bootstrap **(MVP)**~~ **Done**
2. [#2823] MCP-1.2 — Transport adapters (stdio + Streamable HTTP) **(MVP)**
3. [#2824] MCP-1.3 — API-key authentication via Linked Accounts **(MVP)**
4. [#2825] MCP-1.4 — Tenant scoping + RBAC scope guard **(MVP, parallel)**
5. [#2826] MCP-1.5 — Per-key rate limits **(MVP, parallel)**
6. [#2827] MCP-1.6 — Workflow audit integration **(MVP, parallel)**
7. [#2828] MCP-1.7 — Health, readiness, version endpoints **(MVP, parallel)**
8. [#2829] MCP-1.8 — Container image + deploy descriptor **(MVP, parallel)**
9. [#2831] MCP-2.1 — Action registry + `ActionDescriptor` type **(MVP)**
10. [#2832] MCP-2.2 — `mcp.search` primitive tool **(MVP)**
11. [#2833] MCP-2.3 — `mcp.describe` primitive tool **(MVP, parallel)**
12. [#2834] MCP-2.4 — `mcp.execute` primitive tool **(MVP)**
13. [#2835] MCP-2.5 — Pagination contract **(MVP, parallel)**
14. [#2836] MCP-2.6 — Error taxonomy **(MVP, parallel)**
15. [#2837] MCP-2.7 — Request / response logging **(MVP, parallel)**
16. [#2840] MCP-3.1 — `tenant.list` + `tenant.describe` **(MVP)**
17. [#2841] MCP-3.2 — `user.list` + `user.describe` **(MVP, parallel)**
18. [#2842] MCP-3.3 — `project.list` + `project.describe` **(MVP, parallel)**
19. [#2843] MCP-3.4 — `project.list_versions` **(MVP, parallel)**
20. [#2846] MCP-4.1 — `version.describe` **(MVP, parallel)**
21. [#2847] MCP-4.2 — `version.list_branches` **(MVP, parallel)**
22. [#2848] MCP-4.3 — `version.list_tags` **(MVP, parallel)**
23. [#2849] MCP-4.4 — `version.list_change_reports` **(MVP, parallel)**
24. [#2853] MCP-5.1 — `class.list` + `class.describe` **(MVP)**
25. [#2854] MCP-5.2 — `class.list_properties` **(MVP, parallel)**
26. [#2855] MCP-5.3 — `property.list` + `property.describe` **(MVP, parallel)**
27. [#2856] MCP-5.4 — `primitive.list` + `primitive.describe` **(MVP, parallel)**
28. [#2861] MCP-5.9 — `class.export_jsonschema` **(MVP, parallel)**
29. [#2862] MCP-6.1 — `path.list` + `path.describe` **(MVP, parallel)**
30. [#2863] MCP-6.2 — `path_operation.describe` **(MVP, parallel)**
31. [#2864] MCP-6.3 — `path_operation.list_parameters` + `.list_responses` **(MVP, parallel)**
32. [#2868] MCP-6.7 — `security_scheme.list` + `server.list` **(MVP, parallel)**
33. [#2869] MCP-7.1 — `audit.search` + `audit.describe` **(MVP, parallel)**
34. [#2870] MCP-7.2 — `change_report.list` + `change_report.describe` **(MVP, parallel)**
35. [#2876] MCP-8.1 — MCP API-key issuance UI **(MVP)**
36. [#2877] MCP-8.2 — Connection wizard (`mcp.json` snippet) **(MVP)**
37. [#2878] MCP-8.3 — Action catalog browser **(MVP, parallel)**
38. [#2879] MCP-8.4 — Per-key activity log **(MVP, parallel)**
39. [#2880] MCP-8.5 — Per-tenant disable / revocation controls **(MVP, parallel)**
40. [#2881] MCP-8.6 — Documentation site **(MVP, parallel)**

— **End of MVP slice (MCP v1)** —

41. [#2830] MCP-1.9 — OAuth2 Dynamic Client Registration *(parallel)*
42. [#2838] MCP-2.8 — Streaming results for long-running execute calls *(parallel)*
43. [#2839] MCP-2.9 — Idempotency keys for cached results *(parallel)*
44. [#2844] MCP-3.5 — `project.list_collaborators` *(parallel)*
45. [#2845] MCP-3.6 — `tenant.list_quotas` *(parallel)*
46. [#2850] MCP-4.5 — `version.diff` *(parallel)*
47. [#2851] MCP-4.6 — `branch.list_revisions` *(parallel)*
48. [#2852] MCP-4.7 — `tag.describe` *(parallel)*
49. [#2857] MCP-5.5 — `class_template.list` + `class_template.describe` *(parallel)*
50. [#2858] MCP-5.6 — `property_template.list` + `property_template.describe` *(parallel)*
51. [#2859] MCP-5.7 — `group.list` + `group.describe` *(parallel)*
52. [#2860] MCP-5.8 — `class.list_dependents` *(parallel)*
53. [#2865] MCP-6.4 — `version.export_openapi` *(parallel)*
54. [#2866] MCP-6.5 — `version.export_asyncapi` *(parallel)*
55. [#2867] MCP-6.6 — `version.export_arazzo` *(parallel)*
56. [#2871] MCP-7.3 — `migration_plan.list` + `migration_plan.describe` *(parallel)*
57. [#2872] MCP-7.4 — `merge_session.list` + `merge_session.describe` *(parallel)*
58. [#2873] MCP-7.5 — `repository.list` + `repository.describe` *(parallel)*
59. [#2874] MCP-7.6 — `webhook_subscription.list` *(parallel)*
60. [#2882] MCP-8.7 — Postman / Bruno collection export *(parallel)*

— **End of post-MVP / Pro tier** —

61. [#2883] V2-MCP-9.1 — Write-back actions (gated) **(V2)**
62. [#2884] V2-MCP-9.2 — AI-assisted query planning **(V2)** *(parallel)*
63. [#2885] V2-MCP-9.3 — GraphQL-like query layer **(V2)** *(parallel)*
64. [#2886] V2-MCP-9.4 — Federated MCP across tenants **(V2)**
65. [#2887] V2-MCP-9.5 — Custom OPA policies per action **(V2)** *(parallel)*
66. [#2888] V2-MCP-9.6 — Bulk export actions **(V2)** *(parallel)*
67. [#2889] V2-MCP-9.7 — Self-hosted MCP companion **(V2)** *(parallel)*
68. [#2890] V2-MCP-9.8 — Custom action SDK **(V2)**
69. [#2875] MCP-7.7 — `data_record.search` **(V2)** *(parallel)*

---

## Revision

Update this file when:

- New issues are filed against `KenSuenobu/objectified-commercial`;
  add the row to the relevant epic summary table and the ordered
  checklist with the assigned number.
- New actions are added to the registry; add a row to the appropriate
  epic table and the ordered checklist.
- A new MCP transport lands (e.g. WebSocket); document it under MCP-1.2
  with an additive ticket.
- The MCP SDK or protocol revision changes; bump under `mcp-protocol`
  with the negotiation impact noted inline.
- Enterprise V2 items are pulled into a paid tier earlier than planned;
  remove the `v2-enterprise` label and adjust the ordered checklist.
