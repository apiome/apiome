# Roadmap — MCP Cataloging, Versioning, Scoring & Browse

> **Status:** ✅ **Issues filed on `objectified-project/objectified`** — umbrella **#3637**,
> epics **#3638–#3650** (V2-MCP-EPIC-15…27), and 69 issues — the original 64 **#3651–#3714**
> plus 5 UI-design issues **#3938–#3942** added in the 2026-06-27 update. Each epic/issue
> heading below is annotated with its `#number`; epics track their children as GitHub
> sub-issues, all under umbrella #3637.
>
> **Positioning (decided):** this work is **folded into the existing V2-MCP roadmap**
> as a new *External MCP Catalog* track — it does **not** start a standalone line. The
> 13 epics below continue the V2-MCP epic sequence (the existing open epics are
> `V2-MCP-EPIC-7…14`, #3029–#3036), so they are created as **`V2-MCP-EPIC-15` … `V2-MCP-EPIC-27`**
> and carry the same V2-MCP roadmap label, each linked to the V2-MCP epic umbrella.
>
> **Document-local shorthand vs. created IDs.** To keep the dense cross-references in
> this design doc readable, epics/issues use a local `MCAT-<epic>.<issue>` shorthand
> (epics 1–13). The **mapping to the IDs actually created** is in §4
> (`MCAT-EPIC-1 → V2-MCP-EPIC-15`, …, `MCAT-EPIC-13 → V2-MCP-EPIC-27`).
> **GitHub title format:** `objectified: [<V2-MCP epic>.<issue>] <title>`
> (e.g. `objectified: [15.1] MCP catalog data model & migrations` for MCAT-1.1).
>
> **Update (2026-06-27) — UI design coverage.** The REST/versioning backend (EPIC-15…19) is
> largely shipped, but the **UI work was under-specified** against the resolved design mockup
> ([`docs/planning/mockups/mcp-catalog/`](planning/mockups/mcp-catalog/)). This revision
> **enriches the six ADE-UI issues (10.1–10.6) to mockup fidelity** and adds **five proposed
> issues** that cover the screens/foundation they did not break out: **10.7** design-system
> foundation & shared primitives, **10.8** grade-led catalog grid, **10.9** Settings tab,
> **10.10** dark-theme + density polish, and **9.7** public-browse relevance ordering. These were
> **filed as #3938–#3942** and linked as sub-issues of EPIC-24 (#3647) / EPIC-23 (#3646).

---

## 0. Source description (user request, verbatim)

> MCP cataloging tool that will go out to an MCP server in a registry that will
> catalog and categorize the different MCP services that the endpoint provides.
> Put this information into a database, and store the information as a version. On
> a periodic basis, the service will go back to the MCP service and re-query it for
> the services it provides through discovery. Any changes recorded will be reported
> as a new version in the MCP service catalog, with a tagged date and time so that
> the version history can be tracked. This service will also be available through
> our own browse catalog where the browser can show MCPs provided by a specific
> site, along with the ability to search for MCPs through the browser. Tenants can
> store MCP catalog information for each endpoint (given a name for cataloging
> purposes in the UI), and the information can be stored there. MCP data can be
> stored for private usage, or published as public MCP cataloged endpoints. MCP
> services that are imported need to be able to be graded and linted, given service
> scoring, and storing this information. There also needs to be a way to query and
> test the MCP that was stored, along with the ability to pass in any authentication
> data to the MCP services if one requires it.

---

## 1. Scope clarification — what this is, and what it is NOT

This repo **already** contains a large body of MCP work, but it is the **opposite
direction** of this request:

| Existing work | Direction | This roadmap |
|---|---|---|
| `objectified-mcp`, `MCP-EPIC-*` (#2815/#2816/#2818/#2820), `V2-MCP-EPIC-*` (#3029–#3036) | **objectified _is_ an MCP server** — it exposes its own specs/discovery actions to MCP clients | objectified **_consumes / catalogs_ external** MCP servers |
| #2878 "Action catalog browser", #2820 "MCP Onboarding & Catalog" | Browse **objectified's own** MCP actions | Browse **third-party** MCP endpoints registered by tenants |

**This roadmap = an MCP _aggregator / catalog_** — a downstream consumer that
connects out to arbitrary external MCP servers (and, in v2, the official MCP
Registry), discovers their tools/resources/prompts, versions and diffs that surface
over time, scores it, and exposes it through private + public browse with a live
test harness.

The MCP Registry team explicitly positions such downstream aggregators as the
intended consumers of the official registry
([registry/about](https://modelcontextprotocol.io/registry/about)).

**How this slots into the existing V2-MCP roadmap.** Although the *direction* is the
inverse of the current V2-MCP work (which hardens objectified's own MCP server), this
"consume external MCP servers" capability is being tracked **as part of the V2-MCP
roadmap line**, not as a separate program. Concretely: the 13 epics here are created
as **`V2-MCP-EPIC-15` … `V2-MCP-EPIC-27`** (continuing the `V2-MCP-EPIC-7…14`
sequence), share the V2-MCP roadmap label, and each links to the V2-MCP epic umbrella
and the most-related existing item (see §9). A new umbrella issue —
**"V2-MCP: External MCP Catalog (consume third-party MCP servers)"** — should be opened
to group epics 15–27, mirroring how #3029–#3036 are grouped.

### What already exists that we REUSE (do not rebuild)

| Capability | Where | Reuse for |
|---|---|---|
| Versioning + git-like tags | `versions`, `version_tags` (V003/V073) | Pattern for `mcp_endpoint_versions` + date/time tags |
| Quality score / grade / fingerprint columns | `versions.quality_score/quality_grade/quality_report_fingerprint` (V124) | Same shape on MCP version scores |
| Deterministic linter (pure fn → findings + score + grade + fingerprint) | `objectified-rest/.../schema_lint.py`, `lint_routes.py` | Template for `mcp_lint.py` |
| Public/private visibility + published flag + public read view | `visibility_type` enum (V006), `mcp_v_public_specs` (V095), `browse_public_routes.py` | `mcp_v_public_endpoints`, public browse |
| Async job engine (submit → poll → commit) | `spec_import_engine.py`, `spec_import_routes.py` | Discovery-job lifecycle |
| Periodic background sweep (cadence, change-detect, enqueue) | `repository_refresh_sweep.py`, `repository_import_spec` (RAR epic) | Periodic re-discovery sweep |
| Encrypted secrets / API keys per tenant | `api_keys`, tenant-scoping patterns | Credential vault for MCP auth |
| Browse app (search, tenant pages) | `objectified-browse` | Public MCP browse/search |
| Typer CLI + HTTP client + job polling | `objectified-cli` | `objectified mcp …` commands |

### The gaps this roadmap closes

1. No outbound **MCP protocol client** (Streamable HTTP / SSE, initialize handshake, `*/list` discovery).
2. No model of an **external MCP endpoint** owned by a tenant.
3. No **capability-surface versioning / diffing** for an external server (MCP has **no** built-in capability version/etag — the catalog MUST compute its own hash).
4. No **MCP-specific** linter/scorer (the existing one lints OpenAPI/JSON-Schema, not MCP tool hygiene).
5. No **outbound auth vault** (OAuth 2.1 / bearer / headers) for connecting to protected servers.
6. No **test harness** to invoke a discovered tool.
7. No **browse** surface for third-party MCP endpoints.

### Design decisions from the mockup review

These were settled while iterating on the design mockup
([`docs/planning/mockups/mcp-catalog/`](planning/mockups/mcp-catalog/)) and are reflected
in the issues below:

1. **Ingestion is an Import source, not a "register" action.** Adding an MCP server is a
   new **"MCP Server" source card in objectified-ui's existing `ImportDialog`** (alongside
   File/URL/Clipboard/Git/SwaggerHub/Postman) → endpoint URL + transport + auth → discovery
   commits catalog v1 via the spec-import job pipeline. (EPIC-17, EPIC-24.1)
2. **Lives in the sidebar under *Specifications › MCP Servers***, adopting the
   `DashboardSideNav` look & feel. (EPIC-24.1)
3. **Catalog is grade-led and grouped by site/host** by default. (EPIC-23.1, EPIC-24.1)
4. **Lint = a dedicated tab plus a compact grade summary on the Overview tab.** (EPIC-24.2/24.4)
5. **Version history can diff any two versions on demand** (base→target selectors or tick two
   in the list), not just consecutive versions. (EPIC-18.2/18.5, EPIC-24.3)
6. **Test is always available; tools with `destructiveHint` require an explicit confirm.** (EPIC-22)
7. **Public browse ranks grade-led** when idle, switching to **relevance→grade while searching**. (EPIC-23.6, EPIC-23.7)
8. **A shared design-system foundation** (grade glyph, badges, health/recency pills, tab shell, tokens) underpins every MCP screen, CSS-class/token-driven so theming is centralized. (EPIC-24.7)
9. **The catalog is a grade-led card grid** with a **grid↔dense-list density toggle** and a **"changed since last view"** indicator. (EPIC-24.8)
10. **A dark-theme variant** covers all MCP screens, honoring objectified-ui's existing theme switch. (EPIC-24.10)

---

## 2. MVP definition

**MVP (v1) — "import → discover → version → score → browse → test, manually":**

1. A tenant **imports** an external MCP server through objectified-ui's existing Import flow (a new **"MCP Server" source**) with a **friendly catalog name**, URL, and transport; stored **private** by default. *(MCAT-1, MCAT-3, MCAT-10.1)*
2. The service connects via **Streamable HTTP**, performs the `initialize` handshake with **protocol-version negotiation**, and discovers `tools/list`, `resources/list`, `resources/templates/list`, `prompts/list` with **cursor pagination**. *(MCAT-2)*
3. The discovered surface is **normalized + fingerprinted** and stored as **version 1** (immutable snapshot, date/time tagged). *(MCAT-2, MCAT-4)*
4. **Manual re-discovery** re-queries, **diffs** against the current version, and on any change writes a **new dated version** + a **change report**. *(MCAT-4)*
5. **Lint + score** the discovered surface → 0–100 score, A–F grade, stored per version. *(MCAT-7)*
6. **Browse (private)**: reached via the sidebar's **Specifications › MCP Servers**; endpoints are grade-led and grouped by site/host. View an endpoint's tools/resources/prompts, version history, lint report, and **compare/diff any two versions** on demand. *(MCAT-9, MCAT-10)*
7. **Test harness (basic)**: invoke a discovered tool (`tools/call`) with **stored bearer/header auth**, capture result/latency/errors. *(MCAT-6 partial, MCAT-8)*
8. **CLI**: `objectified mcp register | discover | list | show | lint | test`. *(MCAT-11)*
9. **Periodic sweep (basic, single global cadence)** that re-discovers enabled endpoints and versions changes automatically. *(MCAT-5)* — included in MVP because "on a periodic basis" is a core requirement.

**v2 / later:**

- Full **OAuth 2.1** authorization flow (RFC 8707/9728 discovery, DCR, token refresh). *(MCAT-6 advanced)*
- **Public publishing** + **public browse/search** in `objectified-browse`, faceted search across tool/resource/prompt text. *(MCAT-9 advanced)*
- **Categorization / auto-categorization** of MCP services. *(MCAT-9.x)*
- **Official MCP Registry ingestion** (`registry.modelcontextprotocol.io /v0.1/servers`, `server.json`). *(MCAT-12)*
- **Webhooks / notifications** on version change; **observability**. *(MCAT-13)*
- **stdio / local** server introspection; advanced scoring; rate-limit-aware polling.

---

## 3. Label strategy

There is **no `mcp` label** in the repo today (MCP work is tracked by title prefix).
**Action:** create a `mcp-catalog` label (and reuse existing ones below). Until
created, issues use the closest existing labels.

Primary labels used across this roadmap: `mcp-catalog` *(new)*, `registry`,
`integrations`, `multi-protocol`, `linting`, `validation`, `version-control`,
`versions`, `browser`, `community`, `rest`, `ui`, `database`, `python`,
`typescript`, `auth`, `api-keys`, `security`, `automation`, `polling`, `webhook`,
`monitoring`, `analytics`, `testing`, `devex`, `epic`, `mvp`, `v2`.

---

## 4. Epics overview

The **Created-as** column is the real `V2-MCP-EPIC-*` number each epic gets when
filed (continuing the existing `V2-MCP-EPIC-7…14` sequence). The `MCAT-*` shorthand
is document-local only.

| Created as | Local | Theme | Issues | MVP weight |
|---|---|---|---|---|
| **V2-MCP-EPIC-15** | MCAT-EPIC-1 | Data Model & Persistence Foundation | 1.1–1.6 | ●●● core |
| **V2-MCP-EPIC-16** | MCAT-EPIC-2 | MCP Discovery Client & Capability Normalization | 2.1–2.6 | ●●● core |
| **V2-MCP-EPIC-17** | MCAT-EPIC-3 | Endpoint Registration & Management (REST + jobs) | 3.1–3.5 | ●●● core |
| **V2-MCP-EPIC-18** | MCAT-EPIC-4 | Versioning, Fingerprinting & Change Detection | 4.1–4.5 | ●●● core |
| **V2-MCP-EPIC-19** | MCAT-EPIC-5 | Periodic Re-Discovery Sweep | 5.1–5.4 | ●● MVP |
| **V2-MCP-EPIC-20** | MCAT-EPIC-6 | Authentication & Secret Vault (outbound) | 6.1–6.5 | ●● MVP+v2 |
| **V2-MCP-EPIC-21** | MCAT-EPIC-7 | Linting, Grading & Service Scoring | 7.1–7.5 | ●●● core |
| **V2-MCP-EPIC-22** | MCAT-EPIC-8 | Query & Test Harness | 8.1–8.4 | ●● MVP |
| **V2-MCP-EPIC-23** | MCAT-EPIC-9 | Browse Catalog, Search & Categorization | 9.1–9.7 | ●● MVP+v2 |
| **V2-MCP-EPIC-24** | MCAT-EPIC-10 | ADE UI | 10.1–10.10 | ●● MVP+v2 |
| **V2-MCP-EPIC-25** | MCAT-EPIC-11 | CLI | 11.1–11.4 | ●● MVP |
| **V2-MCP-EPIC-26** | MCAT-EPIC-12 | Official MCP Registry Integration | 12.1–12.4 | ○ v2 |
| **V2-MCP-EPIC-27** | MCAT-EPIC-13 | Notifications, Webhooks & Observability | 13.1–13.4 | ○ v2 |

**Total: 13 epics (V2-MCP-EPIC-15…27), 69 issues** — the original 64 (#3651–#3714) plus the
5 UI-design issues added in this update (#3938–#3942: 9.7 and 10.7–10.10). Issue `MCAT-E.N` is
created as `V2-MCP-(E+14).N` — e.g. MCAT-7.4 → `V2-MCP-21.4`, GitHub title
`objectified: [21.4] Scoring, grading & fingerprint persistence`.

### Issue index

| ID | Title | ID | Title |
|----|-------|----|----|
| 1.1 | MCP catalog data model & migrations | 7.1 | MCP lint rule engine (pure fn) |
| 1.2 | Capability-item normalized store | 7.2 | Tool/resource/prompt hygiene rules |
| 1.3 | Version + change-record tables | 7.3 | Annotation-consistency & error-design rules |
| 1.4 | Credential vault table (encrypted) | 7.4 | Scoring, grading & fingerprint persistence |
| 1.5 | Scores, discovery-jobs, test-log tables | 7.5 | Lint REST + re-lint endpoint |
| 1.6 | Public read views + visibility/publish | 8.1 | Tool invocation service (`tools/call`) |
| 2.1 | MCP transport client (Streamable HTTP) | 8.2 | Test-harness REST endpoints |
| 2.2 | Initialize handshake + version negotiation | 8.3 | Invocation logging & safety guards |
| 2.3 | Discovery list methods + pagination | 8.4 | CLI/UI test integration |
| 2.4 | Capability-surface normalization | 9.1 | Private browse: endpoints & detail |
| 2.5 | Legacy HTTP+SSE fallback transport | 9.2 | Capability search index & query |
| 2.6 | Discovery error taxonomy & resilience | 9.3 | Categorization model & manual tags |
| 3.1 | Endpoint CRUD REST | 9.4 | Auto-categorization heuristics |
| 3.2 | Manual discovery trigger + async job | 9.5 | Public publish workflow + guards |
| 3.3 | Endpoint Pydantic models & validation | 9.6 | objectified-browse public MCP pages |
| 3.4 | Discovery job status/polling API | 10.1 | ADE nav + endpoint list + import source |
| 3.5 | Endpoint lifecycle (enable/disable/delete) | 10.2 | Endpoint detail: Overview + Capabilities tabs |
| 4.1 | Canonical surface fingerprint | 10.3 | Versions tab: history & compare/diff viewer |
| 4.2 | Surface diff engine | 10.4 | Lint & Score tab + Overview grade summary |
| 4.3 | Version creation on change | 10.5 | Test/query panel (auth-aware) |
| 4.4 | Date/time version tagging | 10.6 | Credential management UI |
| 4.5 | Change-report & compare API | 11.1 | CLI: register/list/show |
| 5.1 | Sweep scheduler & cadence config | 11.2 | CLI: discover + poll |
| 5.2 | Per-endpoint poll/diff/version step | 11.3 | CLI: lint + score |
| 5.3 | Failure handling, backoff & status | 11.4 | CLI: test/invoke |
| 5.4 | Sweep observability & metrics | 12.1 | Registry client (`/v0.1/servers`) |
| 6.1 | Auth-type model + none/bearer/header | 12.2 | server.json → endpoint import |
| 6.2 | Encryption-at-rest for credentials | 12.3 | Registry sync & namespacing |
| 6.3 | OAuth 2.1 discovery (RFC 9728/8414) | 12.4 | Federated search incl. registry |
| 6.4 | OAuth 2.1 auth-code+PKCE + refresh | 13.1 | Change-notification events |
| 6.5 | Credential REST + redaction | 13.2 | Webhook subscriptions on change |
| | | 13.3 | Health/uptime monitoring |
| | | 13.4 | Catalog analytics dashboard |

#### UI design coverage additions (this update — ✅ filed)

These close the gap between the filed issues and the resolved design mockup
([`docs/planning/mockups/mcp-catalog/`](planning/mockups/mcp-catalog/)). They extend existing
epics (no new epic) and were filed as GitHub issues **#3938–#3942**, each linked as a sub-issue
of its epic.

All UI-design coverage additions (**#3938–#3942**) are now complete — see the per-ticket
sections below (each marked ✅ **DONE**).

---

## 5. Architecture overview

```mermaid
flowchart TB
  subgraph ext[External world]
    MCP1[(External MCP Server A\nStreamable HTTP)]
    MCP2[(External MCP Server B\nOAuth-protected)]
    REG[(Official MCP Registry\nregistry.modelcontextprotocol.io)]
  end

  subgraph rest[objectified-rest · Python/FastAPI]
    CLIENT[MCP Discovery Client\ninit · tools/list · resources/list · prompts/list]
    DISC[Discovery Job Engine]
    DIFF[Fingerprint + Diff Engine]
    LINT[MCP Lint/Score Engine]
    SWEEP[Periodic Re-Discovery Sweep]
    VAULT[Credential Vault\nbearer/header/OAuth2.1]
    TEST[Test Harness · tools/call]
    REGCLI[Registry Client v2]
    API[MCP Catalog REST routers]
  end

  subgraph db[objectified-db · Postgres odb schema]
    EP[(mcp_endpoints)]
    VER[(mcp_endpoint_versions)]
    CAP[(mcp_capability_items)]
    CHG[(mcp_version_changes)]
    SCORE[(mcp_version_scores)]
    CRED[(mcp_endpoint_credentials)]
    JOB[(mcp_discovery_jobs)]
    TLOG[(mcp_test_invocations)]
    PUBV[[mcp_v_public_endpoints view]]
  end

  subgraph ui[Frontends · Next.js]
    ADE[objectified-ui · ADE\nimport source · detail · compare/diff · lint · test]
    BROWSE[objectified-browse\npublic catalog + search]
  end

  CLI[objectified-cli\nmcp register/discover/lint/test]

  MCP1 & MCP2 --> CLIENT
  REG --> REGCLI --> DISC
  CLIENT --> DISC --> DIFF --> VER
  DIFF --> CHG
  DISC --> CAP
  VER --> LINT --> SCORE
  SWEEP --> CLIENT
  VAULT --> CLIENT
  VAULT --> TEST --> TLOG
  TEST --> MCP1
  API --> EP & VER & CAP & CHG & SCORE & CRED & JOB & TLOG
  ADE --> API
  CLI --> API
  PUBV --> BROWSE
  EP --> PUBV
```

---

# Epics & issues

> Each issue below uses the GitHub title format
> `objectified: [<epic>.<issue>] <title>`. Complexity ∈ {S, M, L, XL}.

---

## MCAT-EPIC-1 — Data Model & Persistence Foundation  ·  _created as **V2-MCP-EPIC-15**_  ·  **#3638**

Establishes every table, enum, index, and read view the feature needs. Pure
`objectified-db` Flyway migrations starting at **V126**, following existing
conventions (UUID PKs, `tenant_id` scoping, soft delete via `deleted_at`,
`created_at/updated_at`, JSONB metadata, composite indexes).

```mermaid
erDiagram
  mcp_endpoints ||--o{ mcp_endpoint_versions : has
  mcp_endpoints ||--o| mcp_endpoint_credentials : "auth"
  mcp_endpoints ||--o{ mcp_discovery_jobs : runs
  mcp_endpoint_versions ||--o{ mcp_capability_items : contains
  mcp_endpoint_versions ||--o{ mcp_version_changes : "diff vs prev"
  mcp_endpoint_versions ||--o| mcp_version_scores : graded
  mcp_endpoints ||--o{ mcp_test_invocations : logs
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 1.2 | Capability-item normalized store | `mcp_capability_items` (tool/resource/template/prompt rows + JSONB schemas) | mcp-catalog,database,mvp | N | Y | M | objectified-db |
| 1.3 | Version + change-record tables | `mcp_endpoint_versions`, `mcp_version_changes` (immutable snapshots + diffs) | mcp-catalog,database,version-control,mvp | N | Y | M | objectified-db |
| 1.4 | Credential vault table (encrypted) | `mcp_endpoint_credentials` (auth_type enum, encrypted payload, OAuth fields) | mcp-catalog,database,security,mvp | Y | Y | M | objectified-db |
| 1.5 | Scores, discovery-jobs, test-log tables | `mcp_version_scores`, `mcp_discovery_jobs`, `mcp_test_invocations` | mcp-catalog,database,mvp | Y | Y | M | objectified-db |
| 1.6 | Public read views + visibility/publish | `mcp_v_public_endpoints` view + publish columns/indexes | mcp-catalog,database,browser | Y | N | S | objectified-db |

### MCAT-1.1 — MCP catalog data model & migrations  ·  **#3651**  ·  ✅ Done (V126)
- **Problem.** There is no table representing an external MCP endpoint a tenant wants to catalog.
- **Solution / Scope.** Create `odb.mcp_endpoints` (migration **V126**). Columns: `id UUID PK`, `tenant_id`, `creator_id`, `name` (friendly UI label), `slug`, `endpoint_url TEXT`, `transport VARCHAR` (`streamable_http`|`sse`|`stdio`), `description`, `category`, `visibility visibility_type DEFAULT 'private'` (reuse enum from V006), `published BOOLEAN DEFAULT false`, `enabled BOOLEAN DEFAULT true`, `discovery_cadence_seconds INT NULL`, `last_discovered_at`, `last_discovery_status VARCHAR`, `current_version_id UUID NULL` (FK added after 1.3), `metadata JSONB`, soft-delete + audit columns. `UNIQUE(tenant_id, slug)`. Indexes on `(tenant_id)`, `(tenant_id, slug)`, `(published, visibility)`, `(enabled, last_discovered_at)`. Transport values per [MCP transports spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
- **Acceptance Criteria.** Migration applies cleanly on a fresh DB and over V125; rollback notes documented; `flyway`/CI migration check passes; column comments present (matches house style).
- **Dependencies / Parallelism.** Root of the feature — blocks most REST/UI work. Not parallel with 1.3/1.6 (FK ordering) but 1.4/1.5 can follow independently.
- **Technical Stack.** PostgreSQL, Flyway SQL (`objectified-db/scripts`).

```
mcp_endpoints
└─ id, tenant_id, creator_id, name, slug, endpoint_url, transport,
   visibility, published, enabled, discovery_cadence_seconds,
   current_version_id?, last_discovered_at, last_discovery_status, metadata
```

### MCAT-1.2 — Capability-item normalized store  ·  **#3652**  ·  ✅ Done (V127)
- **Problem.** Discovered tools/resources/prompts must be queryable (search, diff, render) — not just blobs.
- **Solution / Scope.** Create `odb.mcp_capability_items` (V127): `id`, `version_id FK`, `item_type VARCHAR` (`tool`|`resource`|`resource_template`|`prompt`), `name`, `title`, `description TEXT`, `input_schema JSONB`, `output_schema JSONB`, `annotations JSONB`, `uri/uri_template` (resources), `raw JSONB` (verbatim entry for fidelity), `ordinal INT`. Indexes on `(version_id, item_type)`, `(name)`, and a `to_tsvector` GIN index on `coalesce(name||' '||description)` for search (MCAT-9.2). Field set per [tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)/[resources](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)/[prompts](https://modelcontextprotocol.io/specification/2025-06-18/server/prompts).
- **Acceptance Criteria.** Stores all four item types; nullable fields tolerate 2025-03-26 servers (no `title`/`outputSchema`); FTS index present.
- **Dependencies / Parallelism.** Needs `version_id` from 1.3. V127 lands before 1.3's table (V128), so — as with V126's `current_version_id` — `version_id` is a plain `NOT NULL UUID` here and the FK to `mcp_endpoint_versions(id)` is added in **V128** (FK ordering). Parallel with 1.4/1.5.
- **Technical Stack.** PostgreSQL JSONB + GIN/tsvector.

### MCAT-1.3 — Version + change-record tables  ·  **#3653**  ·  ✅ Done (V128)
- **Problem.** Each meaningful discovery result must be stored as an immutable, tagged version with a recorded diff.
- **Solution / Scope.** `odb.mcp_endpoint_versions` (V128): `id`, `endpoint_id FK`, `version_seq INT` (monotonic per endpoint), `protocol_version`, `server_name`, `server_title`, `server_version`, `instructions TEXT`, `capabilities JSONB`, `surface_fingerprint TEXT`, `discovered_at TIMESTAMPTZ`, `created_at`, `UNIQUE(endpoint_id, version_seq)`. `odb.mcp_version_changes`: `id`, `version_id FK`, `change_type` (`added`|`removed`|`modified`), `item_type`, `item_name`, `detail JSONB` (before/after). Add FK `mcp_endpoints.current_version_id → mcp_endpoint_versions.id`.
- **Acceptance Criteria.** A version is immutable once written; `version_seq` strictly increases; change rows link to the version that introduced them.
- **Dependencies / Parallelism.** After 1.1. Blocks 1.2/1.5/4.x.
- **Technical Stack.** PostgreSQL.

### MCAT-1.4 — Credential vault table (encrypted)  ·  **#3654**  ·  ✅ Done (V129)
- **Problem.** Connecting to protected MCP servers requires storing secrets safely.
- **Solution / Scope.** `odb.mcp_endpoint_credentials` (V129): `id`, `endpoint_id FK UNIQUE`, `auth_type VARCHAR` (`none`|`bearer`|`header`|`oauth2`|`env`), `encrypted_payload BYTEA`, `key_version INT`, `oauth_metadata JSONB` (token/authorize/registration endpoints, scopes, resource indicator), `last_refreshed_at`, audit columns. No plaintext secret columns. Encryption handled in app layer (MCAT-6.2). Auth model per [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization).
- **Acceptance Criteria.** Schema stores ciphertext only; supports all five auth types; one credential row per endpoint.
- **Dependencies / Parallelism.** After 1.1. Parallel with 1.2/1.3/1.5.
- **Technical Stack.** PostgreSQL `BYTEA`.

### MCAT-1.5 — Scores, discovery-jobs, test-log tables  ·  **#3655**  ·  ✅ Done (V130)
- **Problem.** Need persistence for scores, async discovery jobs, and test invocations.
- **Solution / Scope.** (V130) `mcp_version_scores`: `version_id FK`, `score SMALLINT`, `grade TEXT`, `report JSONB`, `report_fingerprint TEXT`, `scored_at` (mirrors `versions.quality_*` from V124). `mcp_discovery_jobs`: `id`, `endpoint_id`, `tenant_id`, `state` (`queued|running|completed|failed`), `trigger` (`manual|sweep|registry`), `started_at`, `finished_at`, `error TEXT`, `result JSONB`. `mcp_test_invocations`: `id`, `endpoint_id`, `version_id`, `item_type`, `item_name`, `arguments JSONB`, `response JSONB`, `is_error BOOLEAN`, `latency_ms INT`, `invoked_by`, `created_at`.
- **Acceptance Criteria.** All three tables created with appropriate indexes (`(endpoint_id, created_at)`, `(state)`); FK cascades on endpoint delete.
- **Dependencies / Parallelism.** After 1.3. Parallel with 1.4.
- **Technical Stack.** PostgreSQL.

### MCAT-1.6 — Public read views + visibility/publish  ·  **#3656**  ·  ✅ View shipped (objectified-db 0.16.0, V134)
- **Problem.** Public browse needs a filtered, safe read model (no secrets, only published/public).
- **Solution / Scope.** (V134) Create `odb.mcp_v_public_endpoints` view filtering `enabled = true AND published = true AND visibility = 'public' AND deleted_at IS NULL`, exposing endpoint + current version + score/grade and a userinfo-stripped `host` (mirrors `mcp_v_public_specs` from V095). Reuses the existing `idx_mcp_endpoints_published_visibility` (V126) index; never selects the raw `endpoint_url` or any credentials. Delivered alongside the 9.6/9.7 browse work.
- **Acceptance Criteria.** View returns only published/public endpoints; excludes credential columns; query plan uses indexes.
- **Dependencies / Parallelism.** After 1.1/1.3/1.5. Parallel with most REST work.
- **Technical Stack.** PostgreSQL view.

---

## MCAT-EPIC-2 — MCP Discovery Client & Capability Normalization  ·  _created as **V2-MCP-EPIC-16**_  ·  **#3639**

The outbound MCP protocol client. This is the technical heart of the feature.

```mermaid
sequenceDiagram
  participant C as Discovery Client (rest)
  participant S as External MCP Server
  C->>S: POST initialize {protocolVersion, capabilities, clientInfo}
  S-->>C: {protocolVersion, capabilities, serverInfo, instructions}
  C->>S: notifications/initialized
  loop until nextCursor empty
    C->>S: tools/list {cursor}
    S-->>C: {tools[], nextCursor?}
  end
  C->>S: resources/list · resources/templates/list · prompts/list (paged)
  C->>C: normalize → canonical surface → fingerprint
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 2.2 | Initialize handshake + version negotiation | `initialize` + `notifications/initialized`, negotiate 2025-06-18/03-26 | mcp-catalog,multi-protocol,python,mvp | N | Y | M | objectified-rest |
| 2.3 | Discovery list methods + pagination | tools/resources/templates/prompts list with cursor paging | mcp-catalog,python,mvp | N | Y | M | objectified-rest |
| 2.4 | Capability-surface normalization | Canonical, version-tolerant in-memory surface model | mcp-catalog,python,mvp | Y | Y | M | objectified-rest |
| 2.5 | Legacy HTTP+SSE fallback transport | 2024-11-05 two-endpoint SSE for back-compat | mcp-catalog,multi-protocol,python,v2 | Y | N | M | objectified-rest |
| 2.6 | Discovery error taxonomy & resilience | Timeouts, JSON-RPC errors, version mismatch, partial results | mcp-catalog,python,mvp | Y | Y | M | objectified-rest |

### MCAT-2.1 — MCP transport client (Streamable HTTP)  ·  **#3657**  ·  ✅ Done (objectified-rest 1.6.1)
- **Problem.** No client exists to speak MCP over the network.
- **Solution / Scope.** Implement `mcp_client/transport_http.py`: JSON-RPC 2.0 over **Streamable HTTP** to a single `…/mcp` endpoint. POST with `Accept: application/json, text/event-stream`; handle 200 JSON vs `text/event-stream` SSE responses and `202` accepts; capture/echo **`Mcp-Session-Id`**; send **`MCP-Protocol-Version`** on post-init requests; `DELETE` to end session; honor `Origin`/HTTPS. Uses `httpx` (already a dep). Spec: [transports 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
- **Acceptance Criteria.** Can complete a request/response and an SSE-streamed response against a local reference MCP server; session header round-trips; 400/404/405 handled per spec; unit tests with mocked httpx + an integration test against a stub server.
- **Dependencies / Parallelism.** Foundation of the epic — blocks 2.2/2.3.
- **Technical Stack.** Python, `httpx`, SSE parsing.

### MCAT-2.2 — Initialize handshake + version negotiation  ·  **#3658**  ·  ✅ Done (objectified-rest 1.6.2)
- **Problem.** Discovery is gated by the `initialize` handshake and capability negotiation.
- **Solution / Scope.** Send `initialize` with our `protocolVersion`, `capabilities`, `clientInfo`; parse `serverInfo`, `capabilities`, `instructions`; send `notifications/initialized`; implement version negotiation (echo, fallback, disconnect on unsupported) handling `-32602`. Record negotiated version for downstream field-set branching. Spec: [lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle).
- **Acceptance Criteria.** Negotiates against both 2025-06-18 and 2025-03-26 servers; persists `protocol_version`, `server_name/title/version`, `instructions`, `capabilities`; refuses unsupported versions gracefully.
- **Dependencies / Parallelism.** After 2.1. Blocks 2.3.
- **Technical Stack.** Python.

### MCAT-2.3 — Discovery list methods + pagination  ·  **#3659**  ·  ✅ Done (objectified-rest 1.6.3)
- **Problem.** Must enumerate the full capability surface, not just the first page.
- **Solution / Scope.** Implement `tools/list`, `resources/list`, `resources/templates/list` (result key `resourceTemplates`), `prompts/list`, each looping on opaque `cursor`/`nextCursor` until exhausted, **only** for capabilities the server declared. Spec: [pagination](https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/pagination).
- **Acceptance Criteria.** Pages through multi-page lists; skips undeclared capabilities; returns complete item sets; cursor-loop guarded against non-terminating servers.
- **Dependencies / Parallelism.** After 2.2. Blocks 2.4.
- **Technical Stack.** Python.

### MCAT-2.4 — Capability-surface normalization  ·  **#3660**  ·  ✅ Done (objectified-rest 1.6.4)
- **Problem.** Field sets differ across protocol versions; downstream diff/lint/store need a stable shape.
- **Solution / Scope.** Define a canonical `DiscoverySurface` dataclass (serverInfo, capabilities, instructions, tools[], resources[], resourceTemplates[], prompts[]) with version-tolerant parsing (absent `title`/`outputSchema` on 2025-03-26 → null), deterministic ordering, and a clean mapping to `mcp_capability_items`. Preserve `raw` per item.
- **Acceptance Criteria.** Same logical server yields a byte-stable normalized surface regardless of map ordering; round-trips to/from DB rows.
- **Dependencies / Parallelism.** After 2.3. Parallel with 2.5/2.6. Blocks 4.1.
- **Technical Stack.** Python, Pydantic/dataclasses.

### MCAT-2.5 — Legacy HTTP+SSE fallback transport  ·  **#3661**
- **Problem.** Some servers still use the deprecated 2024-11-05 HTTP+SSE transport.
- **Solution / Scope.** Implement two-endpoint SSE transport (server sends `endpoint` event with POST URL). Used only when Streamable HTTP fails or `transport='sse'`. Spec: [2024-11-05 transports](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports).
- **Acceptance Criteria.** Connects to a legacy SSE stub; auto-falls back from Streamable HTTP on protocol signature.
- **Dependencies / Parallelism.** After 2.1. **v2.** Parallel with 2.4/2.6.
- **Technical Stack.** Python, SSE.

### MCAT-2.6 — Discovery error taxonomy & resilience  ·  **#3662**  ·  ✅ Done (objectified-rest 1.6.5)
- **Problem.** Remote discovery fails in many ways; results must be trustworthy and diagnosable.
- **Solution / Scope.** Define typed errors (connect timeout, TLS, auth-required `401` + `WWW-Authenticate`, JSON-RPC error, version mismatch, partial-page failure). Enforce per-call timeouts, total budget, SSRF guard (block private IP ranges per [security best practices](https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices)). Surface structured failures to the job record.
- **Acceptance Criteria.** Each failure mode maps to a stable error code stored on `mcp_discovery_jobs.error`; SSRF to private ranges blocked; partial discovery never silently recorded as complete.
- **Dependencies / Parallelism.** After 2.1. Parallel with 2.4/2.5.
- **Technical Stack.** Python.

---

## MCAT-EPIC-3 — Endpoint Registration & Management (REST + jobs)  ·  _created as **V2-MCP-EPIC-17**_  ·  **#3640**

Tenant-facing CRUD + the async discovery job lifecycle (mirrors `spec_import` engine).

> **UX decision (design review):** an MCP endpoint is **registered through objectified-ui's
> existing Import flow as a new "MCP Server" import source** — *not* a bespoke "register"
> wizard. Registering = selecting the MCP source, entering endpoint URL + transport + auth,
> and running discovery, which commits catalog version 1 via the spec-import job pipeline.
> The CRUD endpoints here back that source. The catalog is surfaced in the sidebar under
> **Specifications › MCP Servers** (see EPIC-10). See
> [`docs/planning/mockups/mcp-catalog/`](planning/mockups/mcp-catalog/) for the design.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 3.1 | Endpoint CRUD REST | create/list/get/patch endpoints, tenant-scoped | mcp-catalog,rest,mvp | N | Y | M | objectified-rest |
| 3.2 | Manual discovery trigger + async job | `POST …/discover` → job, runs client → persists version | mcp-catalog,rest,automation,mvp | N | Y | L | objectified-rest |
| 3.3 | Endpoint Pydantic models & validation | request/response models, URL/transport validation | mcp-catalog,rest,validation,mvp | Y | Y | S | objectified-rest |
| 3.4 | Discovery job status/polling API | `GET …/jobs/{id}` status snapshots | mcp-catalog,rest,mvp | Y | Y | S | objectified-rest |
| 3.5 | Endpoint lifecycle (enable/disable/delete) | soft delete, enable/disable, cascade cleanup | mcp-catalog,rest | Y | Y | S | objectified-rest |

### MCAT-3.1 — Endpoint CRUD REST  ·  **#3663**  ·  ✅ Done (objectified-rest 1.6.6)
- **Problem.** Tenants need to register/manage MCP endpoints with a friendly catalog name.
- **Solution / Scope.** New `mcp_catalog_routes.py` with `mcp_endpoints_router`: `POST /mcp/endpoints`, `GET /mcp/endpoints`, `GET /mcp/endpoints/{id}`, `PATCH /mcp/endpoints/{id}`. Tenant-scoped via existing auth (API key/Bearer). DB access in `database.py`. Register router in `main.py`.
- **Acceptance Criteria.** Full CRUD with tenant isolation; slug auto-derived/unique per tenant; 404 on cross-tenant access; OpenAPI docs generated.
- **Dependencies / Parallelism.** After 1.1, 3.3. Blocks UI/CLI.
- **Technical Stack.** FastAPI, psycopg3.

### MCAT-3.2 — Manual discovery trigger + async job  ·  **#3664**  ·  ✅ Done (objectified-rest 1.7.0)
- **Problem.** Registering an endpoint must be followed by an actual discovery run.
- **Solution / Scope.** `POST /mcp/endpoints/{id}/discover` creates a `mcp_discovery_jobs` row (`trigger='manual'`), runs the Epic-2 client (loading credentials via Epic-6), normalizes (2.4), fingerprints/diffs (Epic-4), and persists a version when changed (or v1 on first run). Mirror the submit→poll pattern of `spec_import_engine.py`.
- **Acceptance Criteria.** First discover creates version 1; job transitions queued→running→completed/failed; result references `version_id`; concurrent discover on same endpoint is de-duplicated.
- **Dependencies / Parallelism.** After 2.x, 4.x, 6.1. Core MVP path.
- **Technical Stack.** FastAPI async, job engine.

### MCAT-3.3 — Endpoint Pydantic models & validation  ·  **#3665**  ·  ✅ Done (objectified-rest 1.7.1)
- **Problem.** Inputs (URL, transport, cadence) need strict validation.
- **Solution / Scope.** Pydantic v2 models in `models.py`: `McpEndpointCreate/Update/Out`, transport enum, URL must be https (or localhost in dev), cadence bounds. Redacts credentials in `Out`.
- **Acceptance Criteria.** Invalid URL/transport rejected with 422; models reused by 3.1/3.2.
- **Dependencies / Parallelism.** Parallel with 3.1 (slight ordering). 
- **Technical Stack.** Pydantic.

### MCAT-3.4 — Discovery job status/polling API  ·  **#3666**  ·  ✅ Done (objectified-rest 1.8.0)
- **Problem.** UI/CLI must follow a discovery job to completion.
- **Solution / Scope.** `GET /mcp/endpoints/{id}/jobs` and `…/jobs/{job_id}` returning state, timings, error, result. Same status contract used by CLI poller (Epic-11) and UI.
- **Acceptance Criteria.** Returns terminal state with `version_id` or structured error; tenant-scoped.
- **Dependencies / Parallelism.** After 1.5, 3.2. Parallel with 3.5.
- **Technical Stack.** FastAPI.

### MCAT-3.5 — Endpoint lifecycle (enable/disable/delete)  ·  **#3667**  ·  ✅ Done (objectified-rest 1.8.1)
- **Problem.** Endpoints must be pausable (excluded from sweep) and removable.
- **Solution / Scope.** Enable/disable already shipped in 3.1 via the `enabled` PATCH field (skipped by the Epic-5 sweep through the `enabled, last_discovered_at` partial index). This adds `DELETE …/endpoints/{id}`: soft delete the endpoint (`deleted_at`, `enabled=false`, `current_version_id` cleared) so it leaves browse and the sweep while its slug stays reserved, and hard-purge its children in one tenant-scoped transaction — credentials (security purge), discovery jobs, and version snapshots (cascade-reaping capability items/changes/scores via `mcp_endpoint_versions`'s `ON DELETE CASCADE`). New `soft_delete_mcp_endpoint` DB method and `McpEndpointDeleteResponse` model.
- **Acceptance Criteria.** Disabled endpoints skipped by sweep; deleted endpoints disappear from browse and purge credentials.
- **Dependencies / Parallelism.** After 3.1. Parallel with 3.4.
- **Technical Stack.** FastAPI, SQL cascades.

---

## MCAT-EPIC-4 — Versioning, Fingerprinting & Change Detection  ·  _created as **V2-MCP-EPIC-18**_  ·  **#3641**

MCP has **no built-in capability version/etag** — the catalog computes its own.

```mermaid
flowchart LR
  N[Normalized surface] --> F[Canonical JSON\n+ SHA-256 fingerprint]
  F -->|== current| SKIP[No new version\nupdate last_discovered_at]
  F -->|!= current| D[Diff vs current version]
  D --> V[Insert mcp_endpoint_versions\nversion_seq+1, discovered_at]
  D --> C[Insert mcp_version_changes]
  V --> T[Auto date/time tag]
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 4.1 | Canonical surface fingerprint | Stable SHA-256 over normalized surface | mcp-catalog,python,version-control,mvp | N | Y | M | objectified-rest |
| 4.2 | Surface diff engine | added/removed/modified between **any two** version surfaces | mcp-catalog,python,version-control,mvp | N | Y | M | objectified-rest |
| 4.3 | Version creation on change | persist new version + change rows only when fingerprint differs | mcp-catalog,rest,versions,mvp | N | Y | M | objectified-rest |
| 4.4 | Date/time version tagging | auto-tag each version with discovery timestamp label | mcp-catalog,versions,mvp | Y | Y | S | objectified-rest,objectified-db |
| 4.5 | Change-report & compare API | version history + diff vs previous **+ compare any two versions** | mcp-catalog,rest,version-control | Y | Y | S | objectified-rest |

### MCAT-4.1 — Canonical surface fingerprint  ·  **#3668**  ·  ✅ Done (objectified-rest 1.8.2)
- **Problem.** Need a deterministic signal for "did the server's offering change?"
- **Solution / Scope.** Serialize the normalized surface to canonical JSON (sorted keys, stable item ordering, excluding volatile fields), SHA-256 → `surface_fingerprint`. Choose which fields are semantically meaningful (tool name/description/inputSchema/outputSchema/annotations; resource uri/mimeType; prompt args; serverInfo.version; instructions; protocolVersion). Research note: no official etag exists — diffing is our responsibility ([schema.ts](https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2025-06-18/schema.ts)).
- **Acceptance Criteria.** Identical offerings → identical fingerprint across runs/hosts; a single tool-description change flips it; documented field list.
- **Dependencies / Parallelism.** After 2.4. Blocks 4.2/4.3.
- **Technical Stack.** Python, `hashlib`.

### MCAT-4.2 — Surface diff engine  ·  **#3669**  ·  ✅ Done (objectified-rest 1.8.3)
- **Problem.** A new version must report *what* changed — and (per mockup review) users must be able to diff **any two versions on demand**, not only consecutive ones.
- **Solution / Scope.** A pure `diff_surfaces(base, target)` that compares **two arbitrary normalized surfaces** and returns structured changes: tools/resources/prompts added/removed, and per-item field-level `modified` (description, schema, annotations, server metadata) with before/after detail and counts. Used in two ways: (a) `previous → new` to persist `mcp_version_changes` at version-creation time (4.3), and (b) on-demand `vX → vY` for the compare API (4.5). Diffing arbitrary versions directly (not chaining adjacent steps) keeps it exact; deterministic, stable item keys.
- **Acceptance Criteria.** Correctly classifies add/remove/modify on fixtures for both adjacent and non-adjacent pairs; identical surfaces → empty diff + "fingerprint unchanged"; modified entries include before/after; stable ordering.
- **Dependencies / Parallelism.** After 4.1. Blocks 4.3/4.5.
- **Technical Stack.** Python.

### MCAT-4.3 — Version creation on change  ·  **#3670**  ·  ✅ Done (objectified-rest 1.8.4)
- **Problem.** Only changes should create versions (avoid version spam).
- **Solution / Scope.** In the discovery pipeline: if `fingerprint == current` → update `last_discovered_at` only; else insert a new `mcp_endpoint_versions` (`version_seq+1`, `discovered_at`), persist capability items + change rows, and set `mcp_endpoints.current_version_id`. Transactional.
- **Acceptance Criteria.** Re-discovering an unchanged server creates no version; a changed server creates exactly one new version with diffs; `current_version_id` advances.
- **Dependencies / Parallelism.** After 4.2, 1.3. Used by 3.2 and Epic-5.
- **Technical Stack.** FastAPI, SQL transaction.

### MCAT-4.4 — Date/time version tagging  ·  **#3671**  ·  ✅ Done (objectified-db 0.13.0, objectified-rest 1.8.5)
- **Problem.** Version history must be navigable by tagged date/time (explicit user requirement).
- **Solution / Scope.** Auto-create a human-readable tag per version (e.g. `2026-06-26T14:03Z`) — either a column on the version or reuse a `version_tags`-style table for MCP. Expose in history listings.
- **Acceptance Criteria.** Every version is addressable by its date/time tag; tags are unique per endpoint and immutable.
- **Dependencies / Parallelism.** After 4.3. Parallel with 4.5.
- **Technical Stack.** PostgreSQL, FastAPI.

### MCAT-4.5 — Change-report & compare API  ·  **#3672**  ·  ✅ Done (objectified-rest 1.8.6)
- **Problem.** UI/CLI need to render version history, per-version change records, **and an on-demand diff between any two chosen versions** (mockup's compare bar).
- **Solution / Scope.** `GET /mcp/endpoints/{id}/versions` (list with seq, date tag, score, change counts), `GET …/versions/{vid}` (full surface), `GET …/versions/{vid}/changes` (stored diff vs previous), and `GET …/versions/compare?base={vid}&target={vid}` → on-demand structured diff (added/removed/modified + counts + `fingerprintChanged`) computed via 4.2. Normalizes order (older→newer) and handles `base == target`. Pydantic models.
- **Acceptance Criteria.** History returns newest-first; compare endpoint returns a structured diff for any base/target pair (adjacent or not); same version → empty diff; tenant-scoped.
- **Dependencies / Parallelism.** After 4.2/4.3. Parallel with 4.4.
- **Technical Stack.** FastAPI.

---

## MCAT-EPIC-5 — Periodic Re-Discovery Sweep  ·  _created as **V2-MCP-EPIC-19**_  ·  **#3642**

Reuses the `repository_refresh_sweep.py` pattern: a cadence-driven background loop
that re-discovers enabled endpoints, diffs, and versions changes automatically.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 5.1 | Sweep scheduler & cadence config | due-selection loop + per-endpoint cadence | mcp-catalog,polling,automation,mvp | N | Y | M | objectified-rest |
| 5.2 | Per-endpoint poll/diff/version step | run discovery→diff→version for due endpoints | mcp-catalog,polling,automation,mvp | N | Y | M | objectified-rest |
| 5.3 | Failure handling, backoff & status | retries, exponential backoff, disable on chronic failure | mcp-catalog,polling,monitoring,mvp | Y | Y | M | objectified-rest |
| 5.4 | Sweep observability & metrics | per-run counters, last-status, surfaced via API | mcp-catalog,monitoring,analytics | Y | N | S | objectified-rest |

### MCAT-5.1 — Sweep scheduler & cadence config  ·  **#3673**  ·  ✅ Done (objectified-rest 1.9.0, V132)
- **Problem.** Endpoints must be re-queried "on a periodic basis."
- **Solution / Scope.** A background async loop (mirror `repository_refresh_sweep.py`) selecting endpoints where `enabled AND (last_discovered_at + cadence) <= now()`. Global default cadence + per-endpoint override (`discovery_cadence_seconds`). Registry-recommended aggregator cadence is ~hourly ([registry/about](https://modelcontextprotocol.io/registry/about)).
- **Acceptance Criteria.** Due endpoints selected fairly; disabled/deleted skipped; cadence override respected; loop is idempotent and singleton-safe.
- **Dependencies / Parallelism.** After 3.2/4.3. Blocks 5.2.
- **Technical Stack.** Python asyncio.
- **Implementation.** Due-selection DAO `Database.list_due_mcp_endpoints` (enabled + live filter, `COALESCE(discovery_cadence_seconds, default)` cadence, oldest-first ordering). Sweep `app/mcp_discovery_sweep.py` (`process_mcp_discovery_sweep`) dispatches each due endpoint through the shared `trigger_discovery` pipeline tagged `trigger='sweep'`; the existing per-endpoint enqueue dedup (advisory lock + active-state check) provides idempotency/singleton-safety. Background loop `_mcp_discovery_sweep` wired in `app/main.py`. Config: `OBJECTIFIED_MCP_DISCOVERY_ENABLED` (kill switch), `OBJECTIFIED_MCP_DISCOVERY_DEFAULT_CADENCE` (~hourly), `OBJECTIFIED_MCP_DISCOVERY_MIN_INTERVAL` (tick floor). Migration **V132** corrects the `discovery_cadence_seconds` column comment: null now means "use the global default cadence" (the `enabled` column is the on/off switch). Per-endpoint poll→diff→version concurrency bounding + timeouts are MCAT-5.2.

### MCAT-5.2 — Per-endpoint poll/diff/version step  ·  **#3674**  ·  ✅ Done (objectified-rest 1.10.0)
- **Problem.** The sweep must reuse the same discovery→diff→version pipeline as manual runs.
- **Solution / Scope.** For each due endpoint, create a `mcp_discovery_jobs` row (`trigger='sweep'`) and execute the shared pipeline; concurrency cap; per-endpoint timeout.
- **Acceptance Criteria.** Sweep produces new versions on change, none on no-change; jobs labeled `sweep`; bounded concurrency.
- **Dependencies / Parallelism.** After 5.1. Blocks 5.3.
- **Technical Stack.** Python.
- **Implementation.** The discovery engine's enqueue and run halves are split: `enqueue_discovery_job` creates (or coalesces onto) a `trigger='sweep'` job *without* starting it, and `run_discovery_job` drives one job to terminal state bounded by a per-endpoint wall-clock timeout (an overrun is recorded as a `budget_exceeded` failure so a slow endpoint can't hold a slot). `trigger_discovery` (manual route) is unchanged — it enqueues then schedules the run in the background. The sweep `process_mcp_discovery_sweep` now enqueues every due endpoint up front (dedup-aware) and drives the freshly-created jobs through the shared discovery→diff→version pipeline under an `asyncio.Semaphore` concurrency cap, awaiting them so the cap is real and the next tick can't pile on. Version-on-change / no-version-on-no-change comes for free from reusing the MCAT-3.2/4.x engine. New config: `OBJECTIFIED_MCP_DISCOVERY_MAX_CONCURRENCY` (default 4), `OBJECTIFIED_MCP_DISCOVERY_ENDPOINT_TIMEOUT` (default 150s, above the client's ~120s network budget).

### MCAT-5.3 — Failure handling, backoff & status  ·  **#3675**  ·  ✅ Done (objectified-rest 1.11.0, objectified-db 0.15.0, V133)
- **Problem.** Flaky/dead endpoints must not wedge the sweep or spam failures.
- **Solution / Scope.** Exponential backoff on repeated failures; `last_discovery_status`; auto-disable (or quarantine) after N consecutive failures with an emitted event; respect rate limits.
- **Acceptance Criteria.** Failing endpoint backs off and eventually quarantines; healthy endpoints unaffected; status visible via API.
- **Dependencies / Parallelism.** After 5.2. Parallel with 5.4.
- **Technical Stack.** Python.
- **Implementation.** Migration **V133** adds per-endpoint failure state to `mcp_endpoints`: `consecutive_failures`, `next_discovery_after` (backoff anchor), `quarantined_at`, `quarantine_reason` (+ a partial due-selection index excluding quarantined rows). The sweep's due-selection `Database.list_due_mcp_endpoints` now skips quarantined endpoints and any inside their backoff window, so healthy endpoints are unaffected. On failure, `Database.record_mcp_discovery_failure` increments the counter, stamps `last_discovery_status` with the *specific* error code (e.g. `connect_error`, `rate_limited`), writes an exponential backoff anchor (`app/mcp_discovery_backoff.py` — `base * 2**(n-1)` clamped to a ceiling), and quarantines once the count crosses the threshold, emitting a one-shot WARNING quarantine event; a successful/unchanged discovery resets all of it so a recovered endpoint rejoins the sweep automatically. Rate limits are respected: HTTP 429 is surfaced as a dedicated `McpRateLimitedError`/`rate_limited` error carrying the parsed `Retry-After`, which is honoured as a backoff floor (even above the ceiling). Status is exposed via `McpEndpointOut` (`consecutive_failures`, `quarantined`, `quarantined_at`, `quarantine_reason`, `next_discovery_after`). New config: `OBJECTIFIED_MCP_DISCOVERY_QUARANTINE_THRESHOLD` (default 5), `OBJECTIFIED_MCP_DISCOVERY_BACKOFF_BASE` (default 60s), `OBJECTIFIED_MCP_DISCOVERY_BACKOFF_MAX` (default 6h).

### MCAT-5.4 — Sweep observability & metrics  ·  **#3676**
- **Problem.** Operators need visibility into sweep health.
- **Solution / Scope.** Per-run counters (checked/changed/failed), durations, last-run timestamp; surfaced via an admin/status endpoint (and feeds 13.4).
- **Acceptance Criteria.** Metrics queryable; counts reconcile with job rows.
- **Dependencies / Parallelism.** After 5.2. **v2.**
- **Technical Stack.** Python, FastAPI.

---

## MCAT-EPIC-6 — Authentication & Secret Vault (outbound)  ·  _created as **V2-MCP-EPIC-20**_  ·  **#3643**

Stores and applies the auth needed to connect to protected MCP servers.

```mermaid
flowchart TB
  subgraph store[mcp_endpoint_credentials]
    direction LR
    none --- bearer --- header --- oauth2 --- env
  end
  cred[(encrypted_payload BYTEA)] --> dec[App-layer decrypt]
  dec --> apply[Inject into MCP client\nAuthorization/headers]
  oauth2 --> flow[OAuth2.1 auth-code + PKCE\nRFC 8707 resource · refresh]
  flow --> cred
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 6.1 | Auth-type model + none/bearer/header | apply static auth to outbound client | mcp-catalog,auth,security,mvp | N | Y | M | objectified-rest |
| 6.2 | Encryption-at-rest for credentials | envelope encryption of stored secrets | mcp-catalog,security,mvp | N | Y | M | objectified-rest |
| 6.3 | OAuth 2.1 discovery (RFC 9728/8414) | parse `WWW-Authenticate`, fetch AS metadata | mcp-catalog,auth,security,v2 | Y | N | M | objectified-rest |
| 6.4 | OAuth 2.1 auth-code+PKCE + refresh | full token acquisition + refresh + DCR | mcp-catalog,auth,security,v2 | N | N | L | objectified-rest |
| 6.5 | Credential REST + redaction | set/clear creds, never echo secrets | mcp-catalog,rest,security,mvp | Y | Y | S | objectified-rest |

### MCAT-6.1 — Auth-type model + none/bearer/header  ·  **#3677**  ·  ✅ Done (objectified-rest 1.12.0)
- **Problem.** Many servers need a bearer token or custom header; this is the MVP auth path.
- **Solution / Scope.** Apply `none`/`bearer`/`header` credentials to the Epic-2 client (`Authorization: Bearer …` or arbitrary headers); never put tokens in URLs (per spec). `env` type supported for future stdio.
- **Acceptance Criteria.** Discovery/test succeed against a bearer-protected stub; tokens only ever sent in headers.
- **Dependencies / Parallelism.** After 1.4, 2.1. Blocks 3.2 protected path.
- **Technical Stack.** Python.
- **Implementation.** New `app/mcp_auth.py` holds the pure auth-type model: `build_auth_headers(auth_type, payload)` maps a **decrypted** credential onto request headers — `none`→`{}`, `bearer`→`Authorization: Bearer <token>`, `header`→one arbitrary `<name>: <value>`, `oauth2`→presents an already-obtained `access_token` as a bearer (full flow is 6.3/6.4), `env`→no HTTP headers (its `vars` bundle is surfaced via `env_vars_for_payload` for a future stdio transport). The model returns headers only — never a URL — and validates header names against the RFC 9110 token grammar while rejecting CR/LF/control characters in values, so a stored secret can't inject headers or split a request; secrets are never logged. `app/mcp_credentials.py` routes the stored row through the model behind a single `decrypt_credential_payload` seam: `none` is the anonymous fast path, and every sealed type degrades to an unauthenticated run until the MCAT-6.2 (#3678) decrypting key is wired into that one function. An end-to-end test drives the full `initialize`→`*/list` discovery against a bearer-protected loopback stub, asserting success and that the token appears only in headers, never in any request path.

### MCAT-6.2 — Encryption-at-rest for credentials  ·  **#3678**  ·  ✅ Done (objectified-rest 1.13.0)
- **Problem.** Secrets must never be stored in plaintext.
- **Solution / Scope.** Envelope encryption (app-managed key, e.g. AES-GCM via a KMS/master key from env) for `encrypted_payload`; key-version column for rotation; decrypt only in-memory at connect time.
- **Acceptance Criteria.** DB contains only ciphertext; rotation supported; decrypt path covered by tests; secrets absent from logs.
- **Dependencies / Parallelism.** After 1.4. Blocks 6.1 real storage.
- **Technical Stack.** Python `cryptography`.
- **Implementation.** New `app/mcp_credential_crypto.py` seals secrets with **AES-256-GCM envelope encryption**: a per-secret random data-encryption key (DEK) encrypts the JSON payload, and a long-lived master key from the environment wraps that DEK — only the wrapped DEK and the ciphertext are persisted (`seal_credential_payload` → `(encrypted_payload, key_version)`), so the DB holds ciphertext only. `unseal_credential_payload` decrypts in-memory at connect time and is fail-safe: a tampered/foreign/wrong-version blob or a missing key yields `None`, so discovery degrades to an unauthenticated run rather than crashing. **Rotation** rides the `key_version` column — `OBJECTIFIED_MCP_CREDENTIAL_ENCRYPTION_KEYS` is a JSON version→key map and `OBJECTIFIED_MCP_CREDENTIAL_ACTIVE_KEY_VERSION` selects the active key, so older rows stay decryptable while new secrets seal under the active version; `reseal_credential_payload` migrates a row onto it, and the key-version is bound into the GCM AAD so a row can't be silently re-pointed at another key. The MCAT-6.1 `decrypt_credential_payload` seam in `app/mcp_credentials.py` now delegates here, and `validate_credential_encryption_keys` fails fast at startup on a misconfigured key map. Secrets never appear in logs or error messages; covered by `tests/test_mcp_credential_crypto.py` (round-trip, ciphertext-only, rotation, fail-safe/fail-closed paths, secret-absent-from-logs) plus an end-to-end seal→decrypt→header test in `tests/test_mcp_credentials.py`.

### MCAT-6.3 — OAuth 2.1 discovery (RFC 9728/8414)  ·  **#3679**
- **Problem.** Protected remote servers advertise an authorization server to use.
- **Solution / Scope.** On `401` parse `WWW-Authenticate` → fetch `/.well-known/oauth-protected-resource` (RFC 9728) → AS metadata `/.well-known/oauth-authorization-server` (RFC 8414); persist endpoints + scopes + resource indicator. Spec: [authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization).
- **Acceptance Criteria.** Resolves AS metadata for a compliant server; stored in `oauth_metadata`.
- **Dependencies / Parallelism.** After 2.6. **v2.** Parallel with 6.1/6.2.
- **Technical Stack.** Python, `httpx`.

### MCAT-6.4 — OAuth 2.1 auth-code + PKCE + refresh  ·  **#3680**
- **Problem.** Full token acquisition for OAuth-protected servers.
- **Solution / Scope.** Authorization-code + **PKCE** (required), RFC 8707 `resource` param, optional Dynamic Client Registration (RFC 7591); store access/refresh tokens; auto-refresh; audience validation. UI-assisted consent redirect (ties to 10.6).
- **Acceptance Criteria.** Obtains and refreshes tokens against a reference AS; tokens scoped to the resource; expiry handled transparently during sweep/test.
- **Dependencies / Parallelism.** After 6.3. **v2.** Largest auth item.
- **Technical Stack.** Python OAuth, PKCE.

### MCAT-6.5 — Credential REST + redaction  ·  **#3681**  ·  ✅ Done (objectified-rest 1.14.0)
- **Problem.** Tenants set/update/clear credentials safely.
- **Solution / Scope.** `PUT /mcp/endpoints/{id}/credentials`, `DELETE …/credentials`; responses **redact** secrets (return masked indicators only). Reuses 6.2 encryption.
- **Acceptance Criteria.** Secrets never returned; setting then GET shows masked status; clearing removes the row.
- **Dependencies / Parallelism.** After 6.1/6.2. Parallel with 6.3.
- **Technical Stack.** FastAPI.
- **Implementation.** Three tenant-scoped routes under `/v1/mcp/{tenant_slug}/endpoints/{id}/credentials` in `app/mcp_catalog_routes.py`: `PUT` sets/replaces a credential, `GET` returns its redacted status, `DELETE` clears it (idempotent). Every route re-validates the endpoint against the caller's token tenant (`_require_tenant_endpoint`), so a cross-tenant id reads as `404`. **Secrets travel inbound only**: the plaintext `payload` on `PUT` is validated against its `auth_type` by a new `validate_credential_payload` in `app/mcp_auth.py` (reuses the MCAT-6.1 header model, so a missing field, wrong type, or CR/LF header-injection attempt is rejected `422` at the boundary), then sealed by the MCAT-6.2 `seal_credential_payload` and upserted as ciphertext via the new `db.upsert_mcp_endpoint_credentials` (one row per endpoint, bumps `last_refreshed_at`). No response can leak a secret: every read projects through `mcp_credential_status_from_row`, whose `McpCredentialStatusOut` carries only `auth_type`, a `configured` flag, a fixed `masked_secret` placeholder, `key_version`, non-secret `oauth_metadata` and timestamps — there is no field for the ciphertext or the decrypted secret. `auth_type` on `PUT` must be a secret-bearing scheme (`bearer`/`header`/`oauth2`/`env`); the anonymous `none` state is reached by `DELETE` (new `db.delete_mcp_endpoint_credentials`, returns whether a row was dropped). A `PUT` while credential encryption is unconfigured fails closed with `503` rather than storing an unprotected secret. Covered by `tests/test_mcp_credentials_routes.py` (seal-and-redact round-trip asserting the secret never appears in the response, set→GET masked status, idempotent clear, cross-tenant `404`, payload/injection `422`, unconfigured `503`, and the redaction/validation units).

---

## MCAT-EPIC-7 — Linting, Grading & Service Scoring  ·  _created as **V2-MCP-EPIC-21**_  ·  **#3644**

An MCP-specific linter, modeled on the existing deterministic `schema_lint.py`
(pure fn → findings + 0–100 score + A–F grade + fingerprint), persisted per version.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 7.1 | MCP lint rule engine (pure fn) | deterministic linter over a discovery surface | mcp-catalog,linting,python,mvp | N | Y | M | objectified-rest |
| 7.2 | Tool/resource/prompt hygiene rules | descriptions, inputSchema validity, titles, mimeType | mcp-catalog,linting,mvp | Y | Y | M | objectified-rest |
| 7.3 | Annotation-consistency & error-design rules | contradictory hints, isError vs JSON-RPC, security posture | mcp-catalog,linting,security,mvp | Y | Y | M | objectified-rest |
| 7.4 | Scoring, grading & fingerprint persistence | 0–100 + A–F + report, stored per version | mcp-catalog,linting,analytics,mvp | N | Y | S | objectified-rest,objectified-db |
| 7.5 | Lint REST + re-lint endpoint | fetch/compute lint for a version | mcp-catalog,rest,linting,mvp | Y | Y | S | objectified-rest |

### MCAT-7.1 — MCP lint rule engine (pure fn)  ·  **#3682**  ·  ✅ Done (objectified-rest 1.15.0)
- **Problem.** Imported MCP services must be graded/linted; the existing linter targets OpenAPI/JSON-Schema, not MCP.
- **Solution / Scope.** New `mcp_lint.py`: pure function taking a normalized surface → ordered `LintFinding[]` with stable IDs (hash of `path|rule|message`), severity, and rule group. Mirrors `schema_lint.py` structure for consistency.
- **Acceptance Criteria.** No DB/network in the function; deterministic findings + stable IDs; unit-tested on fixtures.
- **Dependencies / Parallelism.** After 2.4. Blocks 7.2/7.3/7.4.
- **Technical Stack.** Python.

### MCAT-7.2 — Tool/resource/prompt hygiene rules  ·  **#3683**  ·  ✅ Done (objectified-rest 1.16.0)
- **Problem.** Need concrete quality signals from the surface.
- **Solution / Scope.** New `mcp_lint_hygiene.py` rule pack auto-registered by the engine. Rules: tool missing/empty `description` (warning); `inputSchema` absent / non-object / not `type:object` / structurally invalid (error); missing `title` on any kind (info); tools without `outputSchema` (info); resources missing `mimeType` (warning) / invalid `uri` (error); resource templates with malformed `uriTemplate` (error) / missing `mimeType` (warning); prompt args lacking `description` (warning) / `required` (info). Two new rule groups: `schema` (MUST/error) and `quality` (SHOULD/advisory). Per [tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)/[resources](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)/[prompts](https://modelcontextprotocol.io/specification/2025-06-18/server/prompts) (separate normative MUST fails from best-practice soft signals).
- **Acceptance Criteria.** Each rule fires on a crafted bad surface and stays silent on a clean one; MUST vs SHOULD severities distinguished.
- **Dependencies / Parallelism.** After 7.1. Parallel with 7.3.
- **Technical Stack.** Python, `jsonschema`.

### MCAT-7.3 — Annotation-consistency & error-design rules  ·  **#3684**  ·  ✅ Done (objectified-rest 1.17.0)
- **Problem.** The highest-signal MCP-specific checks are annotation consistency and error design.
- **Solution / Scope.** Rules: contradictory annotations (`readOnlyHint:true` with `destructiveHint:true`/`idempotentHint:false`); missing server `instructions` (info); over-broad scopes / token-passthrough indicators in auth metadata; SSRF-risky resource URIs. Per [security best practices](https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices) and Anthropic [writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents).
- **Acceptance Criteria.** Detects contradictory annotation sets; flags security-posture gaps; documented rationale per rule.
- **Dependencies / Parallelism.** After 7.1. Parallel with 7.2.
- **Technical Stack.** Python.

### MCAT-7.4 — Scoring, grading & fingerprint persistence  ·  **#3685**  ·  ✅ Done (objectified-rest 1.18.0)
- **Problem.** Findings must roll up to a stored score/grade per version.
- **Solution / Scope.** Weighted 0–100 score (MUST fails weighted heavier than SHOULD), A–F bands (reuse V124 thresholds A≥90…F<60), stable report fingerprint; persist to `mcp_version_scores`; capture automatically at version creation (best-effort, like `_capture_version_quality_score()`).
- **Acceptance Criteria.** Score deterministic for a fixed surface; grade bands match house standard; auto-captured on new version.
- **Dependencies / Parallelism.** After 7.2/7.3, 1.5. Blocks 7.5.
- **Technical Stack.** Python, PostgreSQL.

### MCAT-7.5 — Lint REST + re-lint endpoint  ·  **#3686**  ·  ✅ Done (objectified-rest 1.19.0)
- **Problem.** UI/CLI need to fetch and recompute lint.
- **Solution / Scope.** `GET /mcp/endpoints/{id}/versions/{vid}/lint` (stored or computed) and `POST …/lint` to recompute. Mirrors `lint_routes.py`.
- **Acceptance Criteria.** Returns findings + score + grade + fingerprint; recompute updates stored score; tenant-scoped.
- **Dependencies / Parallelism.** After 7.4. Parallel with 7.2/7.3 wrap-up.
- **Technical Stack.** FastAPI.

---

## MCAT-EPIC-8 — Query & Test Harness  ·  _created as **V2-MCP-EPIC-22**_  ·  **#3645**

Invoke a stored MCP tool with stored auth and capture the result.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 8.1 | Tool invocation service (`tools/call`) | call a discovered tool via the client | mcp-catalog,testing,python,mvp | N | Y | M | objectified-rest |
| 8.2 | Test-harness REST endpoints | `POST …/test` with arguments + auth | mcp-catalog,rest,testing,mvp | N | Y | M | objectified-rest |
| 8.3 | Invocation logging & safety guards | log to `mcp_test_invocations`, guard destructive calls | mcp-catalog,testing,security,mvp | Y | Y | S | objectified-rest |
| 8.4 | CLI/UI test integration | wire test into CLI + ADE panel | mcp-catalog,devex,ui | Y | N | S | objectified-cli,objectified-ui |

### MCAT-8.1 — Tool invocation service (`tools/call`)  ·  **#3687**  ·  ✅ Done (objectified-rest 1.20.0)
- **Problem.** Users need to query/test a cataloged MCP, passing arguments.
- **Solution / Scope.** Service calling `tools/call` (and optionally `resources/read`, `prompts/get`) through the Epic-2 client with Epic-6 auth; capture result content, `isError`, latency. Distinguish MCP execution errors (`isError:true` in result) from JSON-RPC protocol errors per [tools spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).
- **Acceptance Criteria.** Calls a stub tool and returns content + latency; `isError` results surfaced distinctly from transport errors.
- **Dependencies / Parallelism.** After 2.x, 6.1. Blocks 8.2.
- **Technical Stack.** Python.

### MCAT-8.2 — Test-harness REST endpoints  ·  **#3688**  ·  ✅ Done (objectified-rest 1.21.0)
- **Problem.** Expose invocation to UI/CLI.
- **Solution / Scope.** `POST /mcp/endpoints/{id}/test` `{item_type, item_name, arguments, auth_override?}`; validates arguments against the stored `inputSchema`; returns response + latency + error.
- **Acceptance Criteria.** Argument validation against schema; per-call timeout; tenant-scoped; optional ephemeral auth override (not persisted).
- **Dependencies / Parallelism.** After 8.1. Blocks 8.3/8.4.
- **Technical Stack.** FastAPI, `jsonschema`.

### MCAT-8.3 — Invocation logging & safety guards  ·  **#3689**  ·  ✅ Done (objectified-rest 1.22.0)
- **Problem.** Test calls hit live external systems and may be destructive.
- **Solution / Scope.** Log every invocation to `mcp_test_invocations`; warn/confirm when tool annotations indicate `destructiveHint`/`openWorldHint`; rate-limit per endpoint; never log secret args/headers.
- **Acceptance Criteria.** Invocations recorded with redaction; destructive tools require an explicit confirm flag; rate limit enforced.
- **Dependencies / Parallelism.** After 8.2. Parallel with 8.4.
- **Technical Stack.** FastAPI.

### MCAT-8.4 — CLI/UI test integration  ·  **#3690**
- **Problem.** Surface the harness to humans.
- **Solution / Scope.** CLI `objectified mcp test` (Epic-11) and ADE test panel (Epic-10.5) call 8.2.
- **Acceptance Criteria.** End-to-end test from CLI and UI returns a tool result.
- **Dependencies / Parallelism.** After 8.2. **v2 polish.** Parallel with 8.3.
- **Technical Stack.** Typer, React.

---

## MCAT-EPIC-9 — Browse Catalog, Search & Categorization  ·  _created as **V2-MCP-EPIC-23**_  ·  **#3646**

Private browse (MVP) and public browse/search (v2), plus categorization.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 9.1 | Private browse: endpoints & detail | list a tenant's MCPs + view capabilities | mcp-catalog,browser,rest,mvp | N | Y | M | objectified-rest,objectified-ui |
| 9.2 | Capability search index & query | search tools/resources/prompts by text | mcp-catalog,browser,rest,mvp | N | Y | M | objectified-rest,objectified-db |
| 9.3 | Categorization model & manual tags | categories + tenant-assigned tags per endpoint | mcp-catalog,community,database | Y | N | S | objectified-rest,objectified-db |
| 9.4 | Auto-categorization heuristics | infer category from tool semantics | mcp-catalog,ai-llm,analytics | Y | N | M | objectified-rest |
| 9.5 | Public publish workflow + guards | publish endpoint public; gate on score/secret checks | mcp-catalog,governance,security | N | N | M | objectified-rest |
| 9.6 | objectified-browse public MCP pages | public browse-by-site + search UI | mcp-catalog,browser,community,v2 | N | N | L | objectified-browse |
| 9.7 | Public browse: relevance→grade search ordering | grade-led when idle, relevance→grade while searching | mcp-catalog,browser,community,v2 | Y | N | S | objectified-browse |

### MCAT-9.1 — Private browse: endpoints & detail  ·  **#3691**  ·  ✅ Done (objectified-rest 1.23.0 / objectified-ui 0.16.0)
- **Problem.** Tenants must browse their cataloged MCPs and inspect what each provides.
- **Solution / Scope.** REST list/detail (reusing 3.1/4.5) consumed by an ADE browse view (Epic-10) showing endpoints grouped by site/host, with capability counts, score, last-discovered.
- **Acceptance Criteria.** Browse lists endpoints by host; detail shows tools/resources/prompts + version/score.
- **Dependencies / Parallelism.** After 3.1/4.5. Blocks 9.2.
- **Technical Stack.** FastAPI, React.

### MCAT-9.2 — Capability search index & query  ·  **#3692**  ·  ✅ Done (objectified-rest 1.24.0)
- **Problem.** "Ability to search for MCPs through the browser."
- **Solution / Scope.** `GET /mcp/search?q=…&scope=tool|resource|prompt|endpoint` using the `tsvector` GIN index from 1.2 (and a public variant via 1.6). Rank by relevance + score; filter by host/category/grade.
- **Acceptance Criteria.** Free-text query returns matching tools/endpoints; filters compose; respects visibility (private vs public scope).
- **Dependencies / Parallelism.** After 9.1, 1.2/1.6. Blocks 9.6.
- **Technical Stack.** PostgreSQL FTS, FastAPI.

### MCAT-9.3 — Categorization model & manual tags  ·  **#3693**
- **Problem.** "Catalog and categorize the different MCP services."
- **Solution / Scope.** Category enum/lookup + free tags table per endpoint; CRUD; surfaced as browse facets.
- **Acceptance Criteria.** Endpoints can be categorized/tagged; facets filter browse/search.
- **Dependencies / Parallelism.** After 1.1. Parallel with 9.4. **v2.**
- **Technical Stack.** PostgreSQL, FastAPI.

### MCAT-9.4 — Auto-categorization heuristics  ·  **#3694**
- **Problem.** Manual categorization doesn't scale.
- **Solution / Scope.** Heuristic/LLM-assisted suggestion of a category from tool names/descriptions (suggest-only, human-confirmed). Optional LLM uses latest Claude models.
- **Acceptance Criteria.** Suggests a plausible category for fixture servers; never auto-applies without confirmation.
- **Dependencies / Parallelism.** After 9.3. **v2.** Parallel with 9.3.
- **Technical Stack.** Python, optional LLM.

### MCAT-9.5 — Public publish workflow + guards  ·  **#3695**
- **Problem.** Endpoints may be published public — but must not leak secrets or low-quality entries.
- **Solution / Scope.** `POST /mcp/endpoints/{id}/publish` sets `published=true, visibility='public'` after guards: no credentials exposed in public view, minimum lint grade (configurable), endpoint reachable. Unpublish supported. Mirrors version publish gates.
- **Acceptance Criteria.** Publish blocked when guards fail with clear reasons; public view never includes credentials; unpublish reverts.
- **Dependencies / Parallelism.** After 1.6, 7.4. Blocks 9.6 data.
- **Technical Stack.** FastAPI.

### MCAT-9.6 — objectified-browse public MCP pages  ·  **#3696**  ·  ✅ Done (objectified-browse 0.3.0)
- **Problem.** "Available through our own browse catalog… show MCPs provided by a specific site… search."
- **Solution / Scope.** New pages in `objectified-browse`: public MCP index (`/mcp`, host-grouped, grade-led), endpoint detail (`/mcp/[tenantSlug]/[endpointSlug]`, tools/resources/templates/prompts + score), and capability search (`/mcp/search`). No auth. Server components read the `mcp_v_public_endpoints` view (V134) directly via `lib/db/helper.ts`; search reuses the V127 FTS GIN index. New "MCP Catalog" navbar entry.
- **Acceptance Criteria.** Public users browse published MCPs by site and search; private endpoints never appear (view-enforced); SSR + indexable.
- **Dependencies / Parallelism.** After 9.2/9.5 (9.5 publish workflow remains its own ticket #3695; the view reads existing flags). **v2.** Largest UI item.
- **Technical Stack.** Next.js (objectified-browse).

### MCAT-9.7 — Public browse: relevance→grade search ordering  ·  **#3942**  ·  ✅ Done (objectified-browse 0.3.0)
- **Problem.** The mockup resolves public browse to **grade-led** ranking, but flags an open question: while a user is **actively searching**, strict grade-led ordering buries the most relevant hits. The mockup's public search default shows `Sort: Top graded ▾`.
- **Solution / Scope.** On the objectified-browse public MCP pages (9.6), order results **grade-led when the query is empty** (idle browse) and switch to **relevance→grade** while a search term is present (FTS rank primary, service grade as tiebreaker), with the sort control reflecting the active mode and allowing an explicit override. Implemented as a single pure helper `lib/mcpSort.ts` (`resolveDefaultSortMode` + `mcpSortOrderSql`) driving both the SQL `ORDER BY` and the `/mcp/search` sort `<select>`; mode is carried in the URL so SSR and the control agree. Public scope only; reuses `mcp_v_public_endpoints`.
- **Acceptance Criteria.** Idle browse is grade-led; an active query ranks by relevance with grade as tiebreaker; the sort control shows/permits the mode; private endpoints never appear.
- **Dependencies / Parallelism.** After 9.2, 9.6. **v2.** Parallel with the rest of EPIC-9 v2.
- **Technical Stack.** Next.js (objectified-browse), PostgreSQL FTS.

---

## MCAT-EPIC-10 — ADE UI (objectified-ui)  ·  _created as **V2-MCP-EPIC-24**_  ·  **#3647**

> **Mockup fidelity (this update).** The resolved design in
> [`docs/planning/mockups/mcp-catalog/`](planning/mockups/mcp-catalog/) is the binding visual
> reference for every issue in this epic. It defines the sidebar placement, a **grade-led
> catalog grid**, the MCP **import source** flow, and a **7-tab endpoint detail**
> (Overview · Capabilities · Versions · Lint & Score · Test · Credentials · Settings). The six
> original issues (10.1–10.6) are **enriched below to that fidelity**, and four new issues
> (**10.7–10.10**) fill the screens the original set did not break out: the shared design-system
> foundation, the grade-led catalog grid, the Settings tab, and the dark-theme/density polish.
> 10.7–10.10 are **proposed (not yet filed)**; 10.1–10.6 are already created (#3697–#3702).

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 10.1 | ADE nav + endpoint list + import source | sidebar entry under Specifications, list route shell, MCP import source card in `ImportDialog` | mcp-catalog,ui,mvp | N | Y | M | objectified-ui |
| 10.2 | Endpoint detail: Overview + Capabilities tabs | identity header + meta strip + instructions + at-a-glance counts (Overview); grouped tools/resources/prompts with schemas/annotations (Capabilities) | mcp-catalog,ui,mvp | N | Y | M | objectified-ui |
| 10.3 | Versions tab: history & compare/diff viewer | date-tagged timeline + compare bar to diff any two (base→target) | mcp-catalog,ui,version-control | N | Y | M | objectified-ui |
| 10.4 | Lint & Score tab + Overview grade summary | grade gauge + category bars + MUST/SHOULD findings; compact summary on Overview | mcp-catalog,ui,linting | Y | Y | S | objectified-ui |
| 10.5 | Test tab (auth-aware) | tool picker + schema-driven arg form + result/latency/isError; destructive confirm | mcp-catalog,ui,testing | Y | N | M | objectified-ui |
| 10.6 | Credentials tab | set bearer/header/OAuth, masked display, encryption note | mcp-catalog,ui,auth,security | Y | N | M | objectified-ui |
| 10.7 | Design-system foundation & shared MCP UI primitives | grade glyph, transport/visibility/auth/annotation badges, health & recency pills, tab shell, tokens | mcp-catalog,ui,design-system,mvp | N | Y | M | objectified-ui |
| 10.8 | Catalog grade-led card grid (filter/group/sort + density) | grade-led cards, badges, counts, health; group-by-host, sort-by-grade, filter; grid↔dense-list density toggle; "changed since last view" | mcp-catalog,ui,browser,mvp | N | Y | M | objectified-ui |
| 10.9 | Endpoint detail: Settings tab | name/URL/transport/cadence/visibility edit; disable & delete with confirms | mcp-catalog,ui | Y | Y | S | objectified-ui |
| 10.10 | Dark-theme variant + density polish | dark-theme tokens across all MCP screens; honor app theme; density preference persistence | mcp-catalog,ui,design-system | Y | N | S | objectified-ui |

### MCAT-10.1 — ADE nav (Specifications › MCP Servers) + endpoint list + import source  ·  **#3697**  ·  ✅ Done (objectified-ui 0.17.0)
- **Problem.** Tenants need a UI to add/manage MCP servers, consistent with how specs are imported today.
- **Solution / Scope.** Add a **"MCP Servers" item under the existing "Specifications" group** in `DashboardSideNav` (Lucide `network` icon, like Projects/Repositories/Published). Build the **catalog route + page shell** (header, "+ Register MCP endpoint" entry, the search/sort/group toolbar, and the responsive container) — the **card-grid presentation itself is 10.8**, which renders into this shell. Adding a server is a **new "MCP Server" source card in the existing `ImportDialog`** (alongside File/URL/Clipboard/Git/SwaggerHub/Postman): selecting it reveals endpoint URL + transport + auth inputs, then runs the discovery/import job through the standard numbered stepper with live status, committing catalog **v1** via the spec-import job pipeline. **Reuse, do not fork, `ImportDialog`/`DashboardSideNav`.** Design mockup: the *Sidebar* + *Catalog* + *Import dialog (MCP source)* screens in [`docs/planning/mockups/mcp-catalog/`](planning/mockups/mcp-catalog/).
- **Acceptance Criteria.** "MCP Servers" appears under Specifications and routes to the catalog page shell; Import → MCP Server source → numbered stepper runs the discovery job with live status → endpoint appears with v1; uses the shared primitives from 10.7.
- **Dependencies / Parallelism.** After 3.x and 10.7. Blocks 10.2, 10.8.
- **Technical Stack.** Next.js, TanStack Query.

### MCAT-10.2 — Endpoint detail: Overview + Capabilities tabs  ·  **#3698**  ·  ✅ Done (objectified-ui 0.18.0)
- **Problem.** Need to see what an MCP provides, with a scannable summary first and the full surface on demand (the mockup splits this into two tabs).
- **Solution / Scope.** Build the **endpoint-detail shell** (identity header with name/host/grade glyph/health, the meta strip, and the tab strip from 10.7) and its first two tabs:
  - **Overview tab** — server `instructions`, a meta strip (transport, visibility, auth type, cadence, last-discovered), and an **at-a-glance counts** block (tools/resources/templates/prompts, current version tag, plus the **compact grade summary** rendered by 10.4). Header controls: re-discover, enable/disable, publish.
  - **Capabilities tab** — grouped **tools / resources / resource_templates / prompts** with title/description, `inputSchema`/`outputSchema`, annotations (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint` badges from 10.7), resource `uri`/`mimeType`; a "Filter capabilities" box; inline lint hints on offending items. Empty/"no description" states per mockup.
- **Acceptance Criteria.** Detail shell renders the identity header + 7-tab strip; Overview shows instructions, meta strip, at-a-glance counts, and the compact grade summary; Capabilities renders all four item types with schemas + annotation badges and filters; actions wired to REST.
- **Dependencies / Parallelism.** After 10.1, 10.7, 4.5. Blocks 10.3, 10.9.
- **Technical Stack.** Next.js.

### MCAT-10.3 — Versions tab: history & compare/diff viewer  ·  **#3699**  ·  ✅ Done (objectified-ui 0.19.0)
- **Problem.** Users must track version history by date/time **and run a diff between any two versions** to see exactly what changed (per mockup).
- **Solution / Scope.** The detail **Versions tab**: a version timeline (date tags, seq, score, change counts, a `current` marker) plus a **compare bar**: pick a **base** and **target** version (selectors), *or* tick two versions in the timeline, then render the diff from the compare API (4.5). Diff panel header reads `vX → vY` with change counts (`+added · −removed · ~modified · fingerprint changed`) and color-coded rows (added=green, removed=red, modified=blue) showing the item path + before/after. Enforces older→newer (auto-swap) and shows an "identical surface" state when nothing changed. Backed by the four read routes from **4.5** (`…/versions`, `…/versions/{vid}`, `…/versions/{vid}/changes`, `…/versions/compare`). See the mockup's *Versions* tab (`Diff · v4 → v5`).
- **Acceptance Criteria.** Timeline newest-first with date tags; selecting any two versions (adjacent or not) renders the correct diff; same-version selection shows the identical-surface state; counts match the API.
- **Dependencies / Parallelism.** After 10.2, 4.5. Parallel with 10.4.
- **Technical Stack.** Next.js.

### MCAT-10.4 — Lint & Score tab + Overview grade summary  ·  **#3700**  ·  ✅ Done (objectified-ui 0.20.0)
- **Problem.** Show grading/linting results, and surface the headline grade where users land first.
- **Solution / Scope.** A **dedicated "Lint & Score" tab** — a **grade gauge** (A–F + 0–100), **category bars**, and findings grouped/split **MUST vs SHOULD** with links to the offending capability item, from 7.5 — **plus the compact grade summary surfaced on the Overview tab** (grade, score, MUST/SHOULD counts) consumed by 10.2, per the mockup decision. Reuses the grade glyph + finding-severity styling from 10.7.
- **Acceptance Criteria.** Lint tab renders the gauge, category bars, and MUST/SHOULD findings linking to offending items; Overview shows the compact grade summary; both use shared primitives.
- **Dependencies / Parallelism.** After 7.5, 10.2, 10.7. Parallel with 10.3.
- **Technical Stack.** Next.js.

### MCAT-10.5 — Test tab (auth-aware)  ·  **#3701**
- **Problem.** Let users invoke a tool from the UI.
- **Solution / Scope.** The detail **Test tab**: tool picker + argument form generated from `inputSchema`; result/error/latency/`isError` viewer (mockup shows `142 ms · isError: false`); destructive-tool confirm for tools carrying `destructiveHint`. Auth-aware (uses stored credentials via 8.2). Calls 8.2.
- **Acceptance Criteria.** Form invokes a tool and renders result/latency/isError; destructive confirm enforced; missing-credential state surfaced.
- **Dependencies / Parallelism.** After 8.2, 10.2. **v2.** Parallel with 10.6.
- **Technical Stack.** Next.js, JSON-Schema form.

### MCAT-10.6 — Credentials tab  ·  **#3702**
- **Problem.** Configure outbound auth safely.
- **Solution / Scope.** The detail **Credentials tab**: forms for bearer/header (and the OAuth 2.1 connect flow in v2); **masked** secret display (`••••••••`), an encryption-at-rest note, and clear-credential. Never echoes stored secrets. Calls 6.5/6.4.
- **Acceptance Criteria.** Set/clear creds; secrets shown masked; encryption note present; OAuth connect handshake (v2) completes.
- **Dependencies / Parallelism.** After 6.5. **v2 for OAuth.** Parallel with 10.5.
- **Technical Stack.** Next.js.

### MCAT-10.7 — Design-system foundation & shared MCP UI primitives  ·  **#3938**  ·  ✅ Done (objectified-ui 0.21.0)
- **Problem.** Every MCP screen in the mockup reuses the same visual atoms — the A–F **grade glyph** (the lead signal everywhere, e.g. `B · 82`), **badges** (transport `streamable_http`/`http+sse (legacy)`, visibility `private`/`public`, auth `bearer`/`header`/`OAuth 2.1`, capability annotations `readOnly`/`destructive`/`idempotent`/`openWorld`), **health/recency pills** (`healthy`/`degraded`/`unreachable`, `Last discovered …`), the **finding-severity** styling (MUST vs SHOULD), and the **detail tab strip**. Building these ad-hoc per screen would drift from the mockup and from objectified-ui. They must exist **before** the screens that consume them.
- **Solution / Scope.** A small, documented component library + tokens under objectified-ui, mirroring the mockup's `:root` (brand indigo `#6366f1`, slate neutrals, Aptos/Segoe type, 8/12px radii) and objectified-ui conventions: `<GradeGlyph>`, `<McpBadge variant=…>`, `<HealthPill>`/`<RecencyPill>`, `<FindingSeverity>`, the `<DetailTabs>` shell, and shared empty/loading/error states. **CSS classes only — no hard-coded colors/spacing in consumers** (tokens drive theming, which 10.10 extends to dark). Includes Storybook/wiki entries and unit/visual tests. Reuse objectified-ui primitives where they already exist; do not fork.
- **Acceptance Criteria.** All listed primitives exist, are token-driven (no literals in consumers), documented with examples, and render every variant the mockup shows; 10.1/10.2/10.4/10.8 consume them rather than re-implementing.
- **Dependencies / Parallelism.** After 3.x (so REST shapes are known); foundational — **blocks 10.1, 10.2, 10.4, 10.8** and feeds 10.10. Can start in parallel with late EPIC-3/4 REST work.
- **Technical Stack.** Next.js, CSS modules/tokens, Storybook.

### MCAT-10.8 — Catalog grade-led card grid (filter / group / sort + density)  ·  **#3939**  ·  ✅ **DONE**
- **Problem.** The catalog landing (Specifications › MCP Servers) is, in the mockup, a **grade-led card grid grouped by site/host** — not a plain table. The original 10.1 only builds the route/shell; the rich grid presentation, grouping, and the open density/"changed since" questions need their own issue.
- **Solution / Scope.** Render the catalog inside 10.1's shell: **grade-led cards** (grade glyph lead, name/host, transport + visibility + auth **badges**, capability counts, **health** rollup like `11 healthy · 1 failing`, recency), **grouped by site/host** by default with per-group headers; a **Sort** control (default `Grade ▾`) and filters (host, grade, transport, visibility, auth, category); the catalog search box. Adds the resolved-open-question polish: a **grid ↔ dense-list density toggle** and a **"changed since last view"** indicator on cards whose surface versioned since the user last looked. All atoms from 10.7. Backed by private browse (9.1) + search/filter (9.2).
- **Acceptance Criteria.** Catalog renders grade-led cards grouped by host; sort defaults to grade; filters compose; density toggle switches grid↔dense-list and persists the preference (see 10.10); "changed since last view" appears only on newly-versioned endpoints; empty/loading/error states present.
- **Dependencies / Parallelism.** After 10.1, 10.7, 9.1/9.2. Parallel with 10.2/10.3.
- **Technical Stack.** Next.js, TanStack Query.

### MCAT-10.9 — Endpoint detail: Settings tab  ·  **#3940**  ·  ✅ **DONE**
- **Problem.** The mockup's detail view has a **Settings tab** (edit identity/connection, manage lifecycle) that the original 10.x set never broke out, leaving the enable/disable/delete UI (REST shipped in 3.5) and cadence/visibility editing unowned.
- **Solution / Scope.** The detail **Settings tab**: edit **name, endpoint URL, transport, discovery cadence, visibility**; **disable/enable**; and **delete** with an explicit confirm that names the cascade (versions, jobs, credentials are purged per 3.5). Inline validation mirrors the import-source inputs (URL/transport rules). Wires to the endpoint CRUD/lifecycle REST (3.1/3.5). Uses 10.7 primitives; destructive actions use the shared confirm pattern.
- **Acceptance Criteria.** Editable fields persist via PATCH; visibility/cadence changes reflected; disable hides the endpoint from sweeps; delete requires a typed/explicit confirm and shows the teardown summary; no hard-coded styles.
- **Dependencies / Parallelism.** After 10.2 (detail shell), 3.5. Parallel with 10.3/10.4/10.5/10.6.
- **Technical Stack.** Next.js.

### MCAT-10.10 — Dark-theme variant + density polish  ·  **#3941**  ·  ✅ **DONE**
- **Problem.** objectified-ui ships multiple themes; the mockup is light-only and flags a **dark-theme variant** and a **density** preference as open polish items. Without a token pass the MCP screens would break under the app's dark theme.
- **Solution / Scope.** Extend the 10.7 tokens with a **dark-theme variant** covering every MCP screen (catalog grid, all detail tabs, import source, diff colors that stay legible on dark), wired to honor the app's existing theme switch (no bespoke toggle unless objectified-ui lacks one). Persist the catalog **density** preference (grid↔dense-list from 10.8) across sessions. Pure token/CSS work — no behavioral change. Verifies contrast/legibility (esp. grade glyph and diff add/remove/modify colors).
- **Acceptance Criteria.** Switching the app to dark renders all MCP screens correctly (no literal-color leaks); diff/grade colors remain legible; density preference persists; light theme unchanged.
- **Dependencies / Parallelism.** After 10.7 and the screens it themes (10.1/10.2/10.8 at least). **v2/polish.** Parallel with test/credentials work.
- **Technical Stack.** Next.js, CSS tokens.

---

## MCAT-EPIC-11 — CLI (objectified-cli)  ·  _created as **V2-MCP-EPIC-25**_  ·  **#3648**

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 11.1 | CLI: register/list/show | manage endpoints from CLI | mcp-catalog,devex,python,mvp | N | Y | M | objectified-cli |
| 11.2 | CLI: discover + poll | trigger discovery, poll job to completion | mcp-catalog,devex,python,mvp | N | Y | S | objectified-cli |
| 11.3 | CLI: lint + score | print lint findings/score for a version | mcp-catalog,devex,linting | Y | Y | S | objectified-cli |
| 11.4 | CLI: test/invoke | call a tool with args + auth | mcp-catalog,devex,testing | Y | N | S | objectified-cli |

### MCAT-11.1 — CLI: register/list/show  ·  **#3703**
- **Problem.** Power users/automation need CLI parity.
- **Solution / Scope.** New `mcp` Typer command group: `mcp register --name --url --transport [--bearer/--header]`, `mcp list`, `mcp show <id>`. Reuses CLI HTTP client/auth/config patterns.
- **Acceptance Criteria.** Register/list/show work against REST; human + `--json` output.
- **Dependencies / Parallelism.** After 3.1. Blocks 11.2.
- **Technical Stack.** Python, Typer.

### MCAT-11.2 — CLI: discover + poll  ·  **#3704**
- **Problem.** Trigger and follow a discovery run.
- **Solution / Scope.** `mcp discover <id>` posts a job and polls status (reuse import poll loop + `--import-timeout`-style option) printing the resulting version/score.
- **Acceptance Criteria.** Polls to terminal state; prints new version + change summary; configurable timeout.
- **Dependencies / Parallelism.** After 11.1, 3.4. Parallel with 11.3.
- **Technical Stack.** Python, Typer.

### MCAT-11.3 — CLI: lint + score  ·  **#3705**
- **Problem.** Inspect grading from CLI.
- **Solution / Scope.** `mcp lint <id> [--version]` prints findings + score/grade (mirrors existing `lint` command).
- **Acceptance Criteria.** Prints findings/score; `--json` mode.
- **Dependencies / Parallelism.** After 7.5. Parallel with 11.2/11.4.
- **Technical Stack.** Python, Typer.

### MCAT-11.4 — CLI: test/invoke  ·  **#3706**
- **Problem.** Invoke a cataloged tool from CLI.
- **Solution / Scope.** `mcp test <id> --tool <name> --arg k=v …` calling 8.2; prints result/latency/error; `--confirm` for destructive tools.
- **Acceptance Criteria.** Invokes a tool and prints result; destructive confirm enforced.
- **Dependencies / Parallelism.** After 8.2. **v2.** Parallel with 11.3.
- **Technical Stack.** Python, Typer.

---

## MCAT-EPIC-12 — Official MCP Registry Integration (v2)  ·  _created as **V2-MCP-EPIC-26**_  ·  **#3649**

Consume the official registry as an upstream source of endpoints.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 12.1 | Registry client (`/v0.1/servers`) | paginate official registry server list | mcp-catalog,registry,integrations,v2 | N | N | M | objectified-rest |
| 12.2 | server.json → endpoint import | map registry entries to `mcp_endpoints` | mcp-catalog,registry,import,v2 | N | N | M | objectified-rest |
| 12.3 | Registry sync & namespacing | periodic sync, reverse-DNS namespacing, status | mcp-catalog,registry,polling,v2 | Y | N | M | objectified-rest |
| 12.4 | Federated search incl. registry | blend registry results into browse/search | mcp-catalog,registry,browser,v2 | Y | N | M | objectified-rest,objectified-browse |

### MCAT-12.1 — Registry client (`/v0.1/servers`)  ·  **#3707**
- **Problem.** The official registry is the canonical upstream of MCP servers.
- **Solution / Scope.** Client for `GET /v0.1/servers` (cursor paging, `search`, `updated_since`, `version=latest`) and `/v0.1/servers/{name}/versions/{version}`. Pin to `/v0.1/`; treat schema as moving (preview). Source: [official registry API](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md).
- **Acceptance Criteria.** Paginates the live/staging registry; tolerates schema drift; respects `nextCursor`.
- **Dependencies / Parallelism.** **v2.** Blocks 12.2.
- **Technical Stack.** Python, `httpx`.

### MCAT-12.2 — server.json → endpoint import  ·  **#3708**
- **Problem.** Registry entries (`server.json`) must become catalog endpoints.
- **Solution / Scope.** Map `server.json` (`name`, `description`, `version`, `remotes[]` (`streamable-http`/`sse` + url + headers), `websiteUrl`, `_meta` status) → `mcp_endpoints` (+ optional live discovery to enrich). Handle camelCase draft schema. Source: [server.schema.json](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/draft/server.schema.json).
- **Acceptance Criteria.** Imports a registry server as a (system/registry-owned) endpoint with `remotes` mapped to transport+url.
- **Dependencies / Parallelism.** After 12.1. Blocks 12.3.
- **Technical Stack.** Python.

### MCAT-12.3 — Registry sync & namespacing  ·  **#3709**
- **Problem.** Keep registry-sourced entries fresh and uniquely named.
- **Solution / Scope.** Periodic sync (~hourly), reverse-DNS namespace (`io.github.*`, `com.example.*`), honor registry `_meta` status (active/deprecated/deleted). Reuses Epic-5 sweep infra.
- **Acceptance Criteria.** Sync updates/marks entries by status; no duplicate names; cadence configurable.
- **Dependencies / Parallelism.** After 12.2, Epic-5. **v2.** Parallel with 12.4.
- **Technical Stack.** Python.

### MCAT-12.4 — Federated search incl. registry  ·  **#3710**
- **Problem.** Browse/search should optionally span registry-sourced entries.
- **Solution / Scope.** Blend registry entries into search results with provenance badges; dedupe against tenant-owned endpoints.
- **Acceptance Criteria.** Search returns local + registry results, labeled; dedup correct.
- **Dependencies / Parallelism.** After 12.2, 9.2. **v2.** Parallel with 12.3.
- **Technical Stack.** Python, Next.js.

---

## MCAT-EPIC-13 — Notifications, Webhooks & Observability (v2)  ·  _created as **V2-MCP-EPIC-27**_  ·  **#3650**

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 13.1 | Change-notification events | emit event when a new version is created | mcp-catalog,automation,v2 | N | N | S | objectified-rest |
| 13.2 | Webhook subscriptions on change | deliver change events to tenant webhooks | mcp-catalog,webhook,integrations,v2 | N | N | M | objectified-rest |
| 13.3 | Health/uptime monitoring | track reachability/latency per endpoint | mcp-catalog,monitoring,v2 | Y | N | M | objectified-rest |
| 13.4 | Catalog analytics dashboard | sweep/score/usage analytics | mcp-catalog,analytics,monitoring,v2 | Y | N | M | objectified-ui |

### MCAT-13.1 — Change-notification events  ·  **#3711**
- **Problem.** Downstream consumers want to know when an MCP changed.
- **Solution / Scope.** Emit an internal event on new version creation (payload: endpoint, version seq, change summary). Foundation for 13.2.
- **Acceptance Criteria.** Event emitted exactly once per new version with change summary.
- **Dependencies / Parallelism.** After 4.3. **v2.** Blocks 13.2.
- **Technical Stack.** Python.

### MCAT-13.2 — Webhook subscriptions on change  ·  **#3712**
- **Problem.** Notify external systems of catalog changes.
- **Solution / Scope.** Tenant webhook subscriptions for MCP change events, reusing the existing webhook-dispatch queue (`push_webhook_*`). Signed deliveries + retries.
- **Acceptance Criteria.** Subscribed webhook receives a signed change payload with retry on failure.
- **Dependencies / Parallelism.** After 13.1. **v2.** Parallel with 13.3.
- **Technical Stack.** Python, existing webhook infra.

### MCAT-13.3 — Health/uptime monitoring  ·  **#3713**
- **Problem.** Catalog quality includes endpoint reachability over time.
- **Solution / Scope.** Lightweight periodic reachability/latency probe (lighter than full discovery); store uptime/latency history; surface a health badge.
- **Acceptance Criteria.** Health/latency recorded per endpoint; badge reflects recent status.
- **Dependencies / Parallelism.** After Epic-5. **v2.** Parallel with 13.2.
- **Technical Stack.** Python.

### MCAT-13.4 — Catalog analytics dashboard  ·  **#3714**
- **Problem.** Operators/tenants want catalog-wide insight.
- **Solution / Scope.** Dashboard: endpoints by category/grade, change frequency, sweep health (5.4), top searched. 
- **Acceptance Criteria.** Dashboard renders counts/trends from real data.
- **Dependencies / Parallelism.** After 5.4, 9.x. **v2.** Parallel with 13.3.
- **Technical Stack.** Next.js.

---

## 6. Work order (dependency-driven sequence)

```mermaid
flowchart LR
  E1[E1 Data Model] --> E2[E2 Discovery Client]
  E1 --> E6[E6 Auth Vault]
  E2 --> E4[E4 Versioning/Diff]
  E2 --> E7[E7 Lint/Score]
  E6 --> E3[E3 Endpoint REST + Jobs]
  E4 --> E3
  E3 --> E5[E5 Periodic Sweep]
  E3 --> E8[E8 Test Harness]
  E7 --> E8
  E3 --> E9[E9 Browse/Search]
  E9 --> E10[E10 ADE UI]
  E3 --> E11[E11 CLI]
  E9 --> E12[E12 Registry v2]
  E4 --> E13[E13 Notifications v2]
```

**Recommended build order:**

1. **Foundation (parallelizable):** MCAT-1.1→1.6 (DB) ‖ begin MCAT-2.1/2.2 (transport+handshake). DB 1.1/1.3 first (FK ordering).
2. **Discovery core:** 2.3 → 2.4 → 2.6; 6.1/6.2 (bearer/header + encryption) in parallel.
3. **Versioning:** 4.1 → 4.2 → 4.3 → 4.4/4.5.
4. **Endpoint surface:** 3.3 → 3.1 → 3.2 (ties client+diff+auth together) → 3.4/3.5.
5. **Scoring:** 7.1 → 7.2/7.3 → 7.4 → 7.5 (can overlap step 3–4).
6. **Periodic sweep:** 5.1 → 5.2 → 5.3 (after 3.2/4.3).
7. **Test harness:** 8.1 → 8.2 → 8.3.
8. **Browse (private) + CLI:** 9.1 → 9.2; 11.1 → 11.2 → 11.3 in parallel.
9. **ADE UI MVP:** 10.1 → 10.2 → 10.3 → 10.4.
10. **MVP ships here.** Then v2: full OAuth (6.3/6.4, 10.6), public publish + public browse (9.3–9.6), test polish (8.4/10.5/11.4), registry (Epic-12), notifications/observability (Epic-13, 5.4).

---

## 7. Cross-cutting risks & decisions

1. **Version-aware parsing is mandatory.** Field sets differ by `protocolVersion` (`title`/`outputSchema` absent in 2025-03-26; auth + `MCP-Protocol-Version` header differ). Branch on the negotiated version. ([lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle))
2. **No native capability versioning** — our SHA-256 surface fingerprint (4.1) is the source of truth for change detection; pick the meaningful-field list carefully to avoid false positives/negatives.
3. **Registry is preview + draft schema (camelCase, dated 2025-12-11)** — pin `/v0.1/`, treat schema as moving; position as a downstream aggregator. ([registry/about](https://modelcontextprotocol.io/registry/about))
4. **Security:** SSRF guards on outbound discovery/test (block private IP ranges), encryption-at-rest for credentials, redaction in logs/responses, destructive-tool confirmation, never expose credentials in public views. ([security best practices](https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices))
5. **Naming collision:** keep `mcp_*` catalog tables/routes clearly separated from the existing objectified-as-MCP-server code to avoid confusion; create the `mcp-catalog` label.
6. **Scheduler:** the repo has no external job queue — reuse the in-process async sweep pattern from `repository_refresh_sweep.py`; ensure singleton execution.

---

## 8. Sources

- MCP lifecycle / initialize / negotiation — https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- MCP transports (Streamable HTTP / stdio / legacy SSE) — https://modelcontextprotocol.io/specification/2025-06-18/basic/transports · /2024-11-05/basic/transports
- Tools / Resources / Prompts — https://modelcontextprotocol.io/specification/2025-06-18/server/tools · /server/resources · /server/prompts
- Pagination — https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/pagination
- Authorization (OAuth 2.1, RFC 8707/9728/8414/7591) — https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- Security best practices — https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices
- Canonical schema — https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2025-06-18/schema.ts
- MCP Registry (about / API / server.json) — https://modelcontextprotocol.io/registry/about · https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md · https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/draft/server.schema.json
- Anthropic — writing tools for agents / code execution with MCP — https://www.anthropic.com/engineering/writing-tools-for-agents · https://www.anthropic.com/engineering/code-execution-with-mcp
- Existing patterns reused (in-repo): `versions`/`version_tags` (V003/V073), `versions.quality_*` (V124), `visibility_type` (V006), `mcp_v_public_specs` (V095), `schema_lint.py`/`lint_routes.py`, `spec_import_engine.py`, `repository_refresh_sweep.py`, `browse_public_routes.py`, `objectified-browse`, `objectified-cli`.

---

## 9. Related existing issues to reconcile before creating tickets

These overlap conceptually (mostly objectified-as-MCP-server or generic catalog) and
should be cross-referenced/linked, **not** duplicated:

- #2820 (closed) MCP Onboarding & Catalog · #2878 (closed) Action catalog browser — *objectified's own* MCP actions.
- #2815/#2816/#2818 (closed) MCP discovery-action epics — *exposing* objectified via MCP.
- #3029–#3036 (open) V2-MCP-EPIC-* — write actions, audit, webhooks, federation, caching, SDKs for *objectified's* MCP server.
- #3489 (open) Schema Registry & Discovery · #3496 (open) Community & Schema Browser — generic schema browse (UI patterns to reuse for Epic-9/10).
- #1048/#1049/#1341 (open) Service Catalog / API Discovery — generic catalog concepts.
- #1737/#1720/#2769/#2265 (open) Validation/Quality-scoring epics — reuse scoring conventions for Epic-7.
- #3485/#626/#2129 (open) Git-like version control / history — reuse versioning UX for Epic-4/10.

**Recommendation (per the fold-in decision):** create these epics as
`V2-MCP-EPIC-15…27` under the **existing V2-MCP roadmap label** (the same one carried
by #3029–#3036) plus a `mcp-catalog` label for the external-catalog track, grouped
beneath a new umbrella issue *"V2-MCP: External MCP Catalog (consume third-party MCP
servers)."* Link each new epic to the related existing issue above so reviewers can
confirm it **extends** the V2-MCP line rather than duplicating the
objectified-as-MCP-server work. Do **not** open a parallel standalone roadmap.
