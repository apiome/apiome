# Planned Roadmap — MCP Server (FastMCP + Postgres)

This roadmap describes a Model Context Protocol (MCP) service that lets
external clients browse the OpenAPI specifications stored in the Apiome
platform database. The service is implemented with **FastMCP** (Python) and
uses **Postgres** as its only datastore. It can be hosted either as a local
process or via Docker.

---

## Goals

- **Read-only public browse**: anonymous callers can list, search, and
  download specs flagged public.
- **Private access via API key**: authenticated callers can additionally
  see/download specs scoped to their tenant or project.
- **OpenAPI inspection**: callers can fetch the full document (JSON or YAML)
  and enumerate operations / components without parsing the whole file.
- **Trivial deployment**: `uv run` for local development, `docker compose up`
  for containerized hosting, with **no infrastructure beyond Postgres**.

## Non-goals (MVP)

- No write actions (create/update/publish specs) — see V2.
- No webhook delivery, no rate limiting, no caching layer beyond in-process
  memoization — all candidates for V2.
- No external dependencies (no Redis, Vault, Kafka, object storage, etc.).

---

## Architecture overview

```
┌────────────┐   stdio / streamable HTTP   ┌─────────────────────────┐
│  MCP host  │ ──────────────────────────▶ │   apiome-mcp       │
│ (Claude,   │                             │   FastMCP service       │
│  IDE, …)   │ ◀────────────────────────── │   (Python, async)       │
└────────────┘                             └────────────┬────────────┘
                                                        │ psycopg async pool
                                                        ▼
                                            ┌─────────────────────────┐
                                            │       Postgres          │
                                            │  (Apiome schema +  │
                                            │   mcp_api_keys,         │
                                            │   mcp_access_audit,     │
                                            │   mcp_v_public_specs)   │
                                            └─────────────────────────┘
```

- All authentication state lives in `mcp_api_keys`.
- All MCP-scoped read models are SQL views over the existing platform
  schema; no application-side caches are introduced for MVP.
- Two transports are supported from the same binary: stdio (for local LLM
  tooling) and streamable HTTP (for networked clients).

---

## MVP scope

### Epics

| Epic | Issue | Title | Labels |
|------|-------|-------|--------|
| E1 | [#2988](../../issues/2988) | MCP-EPIC-1: Server Foundation (FastMCP + Postgres) | `epic`, `mvp`, `mcp-server`, `infrastructure` |
| E2 | [#2996](../../issues/2996) | MCP-EPIC-2: API Key Authentication (Postgres-backed) | `epic`, `mvp`, `mcp-key`, `auth`, `security` |
| E3 | [#3003](../../issues/3003) | MCP-EPIC-3: Public Read-Only Spec Discovery | `epic`, `mvp`, `mcp-action`, `openapi` |
| E4 | [#3009](../../issues/3009) | MCP-EPIC-4: Private Spec Access (API-key gated) | `epic`, `mvp`, `mcp-action`, `mcp-key`, `auth`, `openapi` |
| E5 | [#3015](../../issues/3015) | MCP-EPIC-5: OpenAPI Inspection Tools | `epic`, `mvp`, `mcp-action`, `openapi` |
| E6 | [#3022](../../issues/3022) | MCP-EPIC-6: Packaging & Hosting (Docker + Local) | `epic`, `mvp`, `infrastructure`, `mcp-server` |

### Tickets — created in dependency order

#### E1 — Server Foundation (#2988)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 1.1 | ~~[#2989](../../issues/2989)~~ | ~~Scaffold FastMCP Python project (uv, src layout, pyproject)~~ (**completed**) | — |
| 1.2 | ~~[#2990](../../issues/2990)~~ | ~~Settings/config module (pydantic-settings, env vars)~~ (**completed**) | 1.1 |
| 1.3 | ~~[#2991](../../issues/2991)~~ | ~~Postgres connection pool (psycopg async)~~ (**completed**) | 1.2 |
| 1.4 | ~~[#2992](../../issues/2992)~~ | ~~Structured JSON logging~~ (**completed**) | 1.2 |
| 1.5 | ~~[#2993](../../issues/2993)~~ | ~~stdio transport entrypoint~~ (**completed**) | 1.1–1.3 |
| 1.6 | ~~[#2994](../../issues/2994)~~ | ~~Streamable HTTP transport entrypoint~~ (**completed**) | 1.1–1.3 |
| 1.7 | ~~[#2995](../../issues/2995)~~ | ~~`ping` tool (service + DB health)~~ (**completed**) | 1.3 |

#### E2 — API Key Authentication (#2996)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 2.1 | ~~[#2997](../../issues/2997)~~ | ~~Postgres migration: `mcp_api_keys` table~~ (**completed**) | E1 |
| 2.2 | [#2998](../../issues/2998) | Key issuance CLI (`mcp keys issue`) | 2.1 |
| 2.3 | ~~[#2999](../../issues/2999)~~ | ~~API key validator dependency~~ (**completed**) | 2.1 |
| 2.4 | ~~[#3000](../../issues/3000)~~ | ~~HTTP credential extraction middleware~~ (**completed**) | 1.6, 2.3 |
| 2.5 | ~~[#3001](../../issues/3001)~~ | ~~Scope model (public, tenant, project)~~ (**completed**) | 2.1 |
| 2.6 | ~~[#3002](../../issues/3002)~~ | ~~`last_used_at` + revoke command~~ (**completed**) | 2.3 |

#### E3 — Public Read-Only Spec Discovery (#3003)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 3.1 | ~~[#3004](../../issues/3004)~~ | ~~SQL view: published+public specs~~ (**completed**) | E1 |
| 3.2 | ~~[#3005](../../issues/3005)~~ | ~~Tool `spec.list` (public, paginated)~~ (**completed**) | 3.1 |
| 3.3 | ~~[#3006](../../issues/3006)~~ | ~~Tool `spec.describe` (public)~~ (**completed**) | 3.1 |
| 3.4 | ~~[#3007](../../issues/3007)~~ | ~~Tool `spec.search` (keyword)~~ (**completed**) | 3.1 |
| 3.5 | ~~[#3008](../../issues/3008)~~ | ~~Tool `spec.list_tags`~~ (**completed**) | 3.1 |

#### E4 — Private Spec Access (#3009)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 4.1 | ~~[#3010](../../issues/3010)~~ | ~~Authorization layer: scope ∩ visibility~~ (**completed**) | 2.5, 3.1 |
| 4.2 | ~~[#3011](../../issues/3011)~~ | ~~Extend `spec.list` with private results when authorized~~ (**completed**) | 4.1, 3.2 |
| 4.3 | ~~[#3012](../../issues/3012)~~ | ~~Extend `spec.describe` with private results when authorized~~ (**completed**) | 4.1, 3.3 |
| 4.4 | ~~[#3013](../../issues/3013)~~ | ~~Audit log table + insert on private read~~ (**completed**) | 2.1 |
| 4.5 | ~~[#3014](../../issues/3014)~~ | ~~Tool `spec.list_my_specs` (key-bound)~~ (**completed**) | 4.1 |

#### E5 — OpenAPI Inspection Tools (#3015)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 5.1 | ~~[#3016](../../issues/3016)~~ | ~~Tool `spec.get_openapi` (JSON)~~ (**completed**) | 3.1, 4.1 |
| 5.2 | ~~[#3017](../../issues/3017)~~ | ~~Tool `spec.export_yaml`~~ (**completed**) | 5.1 |
| 5.3 | ~~[#3018](../../issues/3018)~~ | ~~Tool `spec.list_operations`~~ (**completed**) | 5.1 |
| 5.4 | ~~[#3019](../../issues/3019)~~ | ~~Tool `spec.describe_operation`~~ (**completed**) | 5.3 |
| 5.5 | ~~[#3020](../../issues/3020)~~ | ~~Tool `spec.list_components`~~ (**completed**) | 5.1 |
| 5.6 | ~~[#3021](../../issues/3021)~~ | ~~Tool `spec.describe_component`~~ (**completed**) | 5.5 |

#### E6 — Packaging & Hosting (#3022)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 6.1 | ~~[#3023](../../issues/3023)~~ | ~~Multi-stage Dockerfile~~ (**completed**) | 1.1, 1.6 |
| 6.2 | ~~[#3024](../../issues/3024)~~ | ~~`docker-compose.yml` (mcp + postgres)~~ (**completed**) | 6.1, 2.1 |
| 6.3 | ~~[#3025](../../issues/3025)~~ | ~~`.env.example` + config docs~~ (**completed**) | 1.2 |
| 6.4 | ~~[#3026](../../issues/3026)~~ | ~~Local quickstart docs (`uv run`)~~ (**completed**) | 1.5, 1.6 |
| 6.5 | ~~[#3027](../../issues/3027)~~ | ~~README (overview + tools reference)~~ (**completed**) | E3–E5 |
| 6.6 | ~~[#3028](../../issues/3028)~~ | ~~GitHub Actions CI (lint + tests)~~ (**completed**) | 1.1 |

### Suggested parallelism

- **Wave 1 (must-finish-first):** E1 (1.1 → 1.2 → 1.3, then 1.4/1.5/1.6/1.7
  in parallel).
- **Wave 2 (can run in parallel after E1):** E2, E3, and `6.1` / `6.6` can
  all start once E1 has a runnable scaffold.
- **Wave 3:** E4 picks up after E2 and E3 land. E5 begins after E3.1 is
  merged (private-aware variants land alongside E4.1).
- **Wave 4:** E6 documentation tickets (`6.3`–`6.5`) finalize once tools
  and config stabilize. `6.2` waits on `6.1` + `2.1`.

### MVP exit criteria

- Anonymous client can `spec.list`, `spec.describe`, `spec.search`,
  `spec.list_tags`, `spec.get_openapi`, `spec.export_yaml`,
  `spec.list_operations`, `spec.describe_operation`,
  `spec.list_components`, `spec.describe_component` against public specs.
- Authenticated client (valid API key) additionally sees private specs
  within scope and can call `spec.list_my_specs`.
- Service is deployable via `uv run` or `docker compose up` against a
  vanilla Postgres 16; no other infrastructure required.
- CI runs lint + tests on every PR.

---

## V2 scope

All V2 epics retain the **Postgres-only** constraint: any caching, rate
limiting, queueing, webhook outbox, federation registry, or AI thread
storage is implemented as Postgres tables unless a future RFC explicitly
approves otherwise.

### Epics

| V# | Issue | Title | Theme |
|----|-------|-------|-------|
| V7  | [#3029](../../issues/3029) | V2-MCP-EPIC-7: Write Actions (create/update specs via MCP) | Authoring |
| V8  | [#3030](../../issues/3030) | V2-MCP-EPIC-8: Activity Log & Audit UI | Observability |
| V9  | [#3031](../../issues/3031) | V2-MCP-EPIC-9: Webhook Notifications on Spec Changes | Integration |
| V10 | [#3032](../../issues/3032) | V2-MCP-EPIC-10: Rate Limiting & Quotas (Postgres-backed) | Hardening |
| V11 | [#3033](../../issues/3033) | V2-MCP-EPIC-11: Multi-Tenant Federation | Scale |
| V12 | [#3034](../../issues/3034) | V2-MCP-EPIC-12: Caching Layer (Postgres materialized views) | Performance |
| V13 | [#3035](../../issues/3035) | V2-MCP-EPIC-13: AI-Assisted Spec Query | AI |
| V14 | [#3036](../../issues/3036) | V2-MCP-EPIC-14: SDK / Client Libraries | DX |

### Tickets — created in dependency order

#### V7 — Write Actions (#3029)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 7.1 | [#3037](../../issues/3037) | Add `write` scopes to API keys (`write:tenant`, `write:project`) | E2 |
| 7.2 | [#3038](../../issues/3038) | Optimistic concurrency token (`row_version`) on specs | E3.1 |
| 7.3 | [#3039](../../issues/3039) | Tool `spec.create_draft` | 7.1, 7.2 |
| 7.4 | [#3040](../../issues/3040) | Tool `spec.update_metadata` | 7.1, 7.2 |
| 7.5 | [#3041](../../issues/3041) | Tool `spec.replace_document` (draft only) | 7.1–7.3 |
| 7.6 | [#3042](../../issues/3042) | Tool `spec.publish_version` | 7.5 |
| 7.7 | [#3043](../../issues/3043) | Audit row per write op | 7.3–7.6 |

#### V8 — Activity Log & Audit UI (#3030) — `apiome-ui`

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 8.1 | [#3044](../../issues/3044) | ADE route + nav entry: MCP Activity | E4.4 |
| 8.2 | [#3045](../../issues/3045) | Filter bar (key, tenant, tool, time range) | 8.1 |
| 8.3 | [#3046](../../issues/3046) | Audit results table (paginated) | 8.1, 8.2 |
| 8.4 | [#3047](../../issues/3047) | Event detail drawer | 8.3 |
| 8.5 | [#3048](../../issues/3048) | CSV export of current filter set | 8.2, 8.3 |
| 8.6 | [#3049](../../issues/3049) | Saved filters per user | 8.2 |

#### V9 — Webhook Notifications (#3031)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 9.1 | [#3050](../../issues/3050) | Postgres migration: `mcp_webhook_subscriptions` | E2 |
| 9.2 | [#3051](../../issues/3051) | Postgres migration: `mcp_webhook_outbox` | — |
| 9.3 | [#3052](../../issues/3052) | Tools `webhook.subscribe` / `unsubscribe` / `list` | 9.1 |
| 9.4 | [#3053](../../issues/3053) | Spec-change emitters → outbox insert | 9.1, 9.2, V7 |
| 9.5 | [#3054](../../issues/3054) | Delivery worker with retry + exponential backoff | 9.2 |
| 9.6 | [#3055](../../issues/3055) | HMAC payload signing | 9.3, 9.5 |
| 9.7 | [#3056](../../issues/3056) | Dead-letter view + manual replay tool | 9.5 |

#### V10 — Rate Limiting & Quotas (#3032)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 10.1 | [#3057](../../issues/3057) | Postgres migration: `mcp_rate_buckets` | E1 |
| 10.2 | [#3058](../../issues/3058) | Postgres function: atomic token decrement | 10.1 |
| 10.3 | [#3059](../../issues/3059) | Enforcement middleware → 429 + Retry-After | 10.2, E1.6 |
| 10.4 | [#3060](../../issues/3060) | Per-tenant override table | 10.1 |
| 10.5 | [#3061](../../issues/3061) | Quota dashboard SQL views | 10.3 |
| 10.6 | [#3062](../../issues/3062) | Anonymous (IP-based) limits | 10.3 |

#### V11 — Multi-Tenant Federation (#3033)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 11.1 | [#3063](../../issues/3063) | Postgres migration: `mcp_federated_tenants` | E1 |
| 11.2 | [#3064](../../issues/3064) | Async federation client with timeout/circuit-breaker | 11.1 |
| 11.3 | [#3065](../../issues/3065) | Fan-out + merge layer for `spec.list`/`spec.search` | 11.2, E3 |
| 11.4 | [#3066](../../issues/3066) | Per-tenant routing rules | 11.1 |
| 11.5 | [#3067](../../issues/3067) | Federated health heartbeat | 11.2 |
| 11.6 | [#3068](../../issues/3068) | Failure isolation tests | 11.3 |

#### V12 — Caching Layer (Postgres materialized views) (#3034)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 12.1 | [#3069](../../issues/3069) | Materialized view: `mcp_mv_public_specs` | E3.1 |
| 12.2 | [#3070](../../issues/3070) | Materialized view: `mcp_mv_spec_search` | E3.1 |
| 12.3 | [#3071](../../issues/3071) | Scheduled REFRESH job (no external scheduler) | 12.1, 12.2 |
| 12.4 | [#3072](../../issues/3072) | Per-tool freshness toggles | 12.1, 12.2 |
| 12.5 | [#3073](../../issues/3073) | Stampede prevention via advisory locks | 12.3 |
| 12.6 | [#3074](../../issues/3074) | Cache hit/miss metrics tool | 12.4 |

#### V13 — AI-Assisted Spec Query (#3035)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 13.1 | [#3075](../../issues/3075) | Tool `spec.ask` (delegates to platform AI) | E5 |
| 13.2 | [#3076](../../issues/3076) | Citation extraction & response shape | 13.1 |
| 13.3 | [#3077](../../issues/3077) | Authorization-aware context windowing | 13.1 |
| 13.4 | [#3078](../../issues/3078) | Conversation thread storage in Postgres | 13.1 |
| 13.5 | [#3079](../../issues/3079) | Token-budget guardrails | 13.1, V10 |

#### V14 — SDK / Client Libraries (#3036)

| # | Issue | Title | Depends on |
|---|-------|-------|------------|
| 14.1 | [#3080](../../issues/3080) | Python SDK: scaffold + auth | MVP exit |
| 14.2 | [#3081](../../issues/3081) | Python SDK: cover all read tools | 14.1 |
| 14.3 | [#3082](../../issues/3082) | Python SDK: tests + docs + PyPI publish | 14.2 |
| 14.4 | [#3083](../../issues/3083) | TypeScript SDK: scaffold + auth | MVP exit |
| 14.5 | [#3084](../../issues/3084) | TypeScript SDK: cover all read tools | 14.4 |
| 14.6 | [#3085](../../issues/3085) | TypeScript SDK: tests + docs + npm publish | 14.5 |
| 14.7 | [#3086](../../issues/3086) | Cross-SDK contract tests | 14.3, 14.6 |

### Suggested V2 sequencing

- **Foundation enablement first:** V7 (writes) and V10 (rate limiting) are
  prerequisites for several other epics — V9 emits change events from V7
  writes; V13 enforces budgets via V10.
- **Independent tracks:** V8 (UI), V11 (federation), V12 (caching), V14
  (SDKs) can each proceed independently of one another once MVP exits.
- **Scope guard:** before opening any V2 epic, confirm that no new
  infrastructure (Redis, Kafka, queueing service, vector DB, secret
  manager, etc.) is being introduced — Postgres is the only datastore.

---

## Issue conventions

Every issue created under this roadmap carries:

- Labels: `enhancement`, `mcp`, `roadmap-mcp`, `python`, plus area labels
  (`mcp-server`, `mcp-key`, `mcp-action`, `openapi`, `auth`, `security`,
  `database`, `infrastructure`, `documentation`) and either `mvp` or
  `v2` / `v2-enterprise`. Epics also carry `epic`.
- Body sections: **Problem statement**, **Solution / Scope**,
  **Acceptance criteria**, **Parallelism / Dependencies**, and an
  **Epic parent** marker (`Parent epic: #N` for tickets;
  self-declaration for epics).
- Titles prefixed `MCP-EPIC-N:` for MVP epics, `MCP-N.M:` for MVP
  tickets, and `V2-MCP-EPIC-N:` for V2 epics.
