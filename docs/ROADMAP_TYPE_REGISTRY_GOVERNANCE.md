# Objectified Primitives — JSON Schema 2020-12 Governance Roadmap

## 1. Source Description

> `docs/planning/mockups/governance` and `docs/planning/mockups/types` for the types roadmap
> and governance setup but only for the JSON Schema types and schemas as discussed in this
> conversation.

This roadmap extends the **Primitives** capability under **Control Panel → Governance** in
`objectified-ui`. It is scoped *strictly* to JSON Schema **types and schemas** — reusable type
definitions, namespace/`$ref` resolution, import surfaces, and property bindings. It does **not**
cover the broader Authoring platform (Scribe/Slate), documentation, or marketing — those are
tracked separately in `docs/ROADMAP_AUTHORING_PLATFORM.md`.

**Codename:** Primitives (formerly Atlas). In-app label: **Primitives** (`/ade/dashboard/primitives`).

**Design sources (built earlier this conversation):**
- App-accurate, in-application mockups: `docs/planning/mockups/governance/` (+ its `README.md`,
  which sketches routes/entities) — the Type Registry rendered inside the real Control Panel
  shell under the Governance section.
- Standalone product mockups: `docs/planning/mockups/types/` (legacy Atlas mockups — map to Primitives UI).

---

## 1a. Design change (2026-06): single database — extend `odb.primitives`

> **The type registry is NOT a separate database.** An earlier iteration provisioned a separate
> `objectified-types-db` (its own `otr` schema, `registry` CLI, dedicated REST connection). That
> is the wrong design and has been reversed. The registry lives in the **existing `objectified-db`
> database (`odb` schema) by extending the `odb.primitives` table in place**. Primitives are
> tenant-associated (a tenant has its own primitives via `tenant_id`) **and** system-wide (via
> `is_system`/`is_public`), so they must compose with the tenant's other data through ordinary
> same-database foreign keys. Epic 1 reflects this: 1.1 removes the separate DB, 1.2 extends
> `odb.primitives`, 1.3 adds same-DB import/binding links, 1.4 seeds system primitives.

## 1b. Existing Primitives Baseline (shipped)

Before implementing net-new registry mechanics, account for what is **already live**:

| Layer | Implementation | Gap vs this roadmap |
|---|---|---|
| Storage | `odb.primitives` in **objectified-db** (tenant-scoped via `tenant_id`; system-wide via `is_system`/`is_public`) | No `namespace` / `base_uri` / `$id` / `draft` / `$ref` columns on `odb.primitives` — **extend the existing table in place** (same database, `odb` schema; no separate database, no new schema, no new tables) |
| System seed | 36 ISO-aligned system primitives (`20260124-140000.sql`) | Flat schemas; no `std/v0` namespace or composite `$ref` chains (`money` → `decimal`) |
| REST | `/v1/primitives/{tenant_slug}` CRUD + `/import` from `$defs` | No namespaces, resolver, stats, or server-side draft 2020-12 gate |
| UI proxy | `/api/primitives/*` | ✅ **Done** — closed as duplicate (#3455) |
| Management UI | `/ade/dashboard/primitives` — stats, table, CRUD, import dialog | ✅ Nav done (#3466 closed); overview/import are **partial** — extend, don't rebuild |
| Designer | `PrimitiveSelector` — merges primitive schema onto property | No persisted `$ref` binding (#3475); picker lacks namespace tabs (#3474) |
| Validation | AJV in `PrimitiveEditorDialog` (client) | ✅ **Done** — REST persist strictly validated against draft 2020-12 with field-level errors (#3452) |
| Scope | `is_system` immutability, tenant rows | ✅ **Done** — reads resolve `is_system ∪ tenant` (cross-tenant isolation; all tenants see `std/*`); core→tenant and tenant→other-tenant `$ref` rejected on save/import (#3453) |

**Tickets closed as duplicates:** #3455 (UI proxy), #3466 (Governance nav). All other #3446–#3481
issues remain open with scopes adjusted to **extend** Primitives toward full JSON Schema 2020-12 support.

**What the registry must do (from the mockups & conversation):**
- Store JSON Schema **draft 2020-12** types **in the existing `objectified-db` database (`odb`
  schema), by extending the `odb.primitives` table** — *not* in a separate database. Primitives
  are the type registry: a tenant owns its own primitives (via `tenant_id`) and also sees
  system-wide primitives (via `is_system`/`is_public`), all in one table so they compose across
  the tenant's projects with ordinary same-database foreign keys.
- Address types by **relative `$ref`** rooted at each type's **import-source base URL** in the
  API server. Canonical example: `std/v0/types/date` → `"$ref": "../primitives/string"`, base
  `api.objectified.dev/types/std/v0/types/` → resolves to `std/v0/primitives/string`.
- Provide **system-wide types** (`std/v0/*`, `is_system`) visible to **all tenants**, and
  **per-tenant** private types (`tenant/<slug>/*`, owned by `tenant_id`). A tenant type may
  `$ref` a system type; a system type may not `$ref` a tenant type.
- **Import** both raw **JSON Schema** documents (single or `$defs`-bundled) *and* **Objectified
  type-definition bundles** (`.zip`/`.json`). (OpenAPI 3.1 components is a V2 extension.)
- Let the **visual editor** (Designer) bind a property to a **standard** (primitive) or
  **custom** (imported/tenant/core) type, on a per-tenant and per-system basis, storing a `$ref`.

---

## 2. MVP Definition

The MVP delivers a **working type registry loop**: an extended `odb.primitives` table seeded with
core system types; a service+API to manage namespaces and draft-2020-12 types with scope rules;
a relative-`$ref` resolver that flags unresolved references; an import surface that ingests JSON
Schemas **and** type-definition bundles; a Governance → Type Registry UI (overview, type detail,
import, resolver, namespaces, settings); and the Designer property→type binding that writes a
`$ref`.

**In scope for MVP**

| Area | MVP capability |
|---|---|
| Database | Extend `odb.primitives` in **objectified-db** (`odb` schema) with namespace / `$id` / `base_uri` / draft / source / `$ref` columns + import & property-binding links; seeded `std/v0` core system primitives. **No separate database.** |
| Service/API | Namespace CRUD; type CRUD with draft-2020-12 validation; system-core vs tenant scope enforcement; coverage stats; UI proxy + client |
| Resolution | Relative `$ref` resolution against import-source base; unresolved-reference detection; resolver API + basic dependency listing |
| Import | Pipeline + ingestion (file/paste/URL/git); JSON Schema doc parser (single + `$defs`); type-definition bundle importer; `$ref` rewrite + namespace/scope mapping; conflict/dedupe + validation report |
| Governance UI | Sidebar entry under Governance; Type Registry overview; type detail; import wizard; reference resolver; namespaces & scopes; settings |
| Designer integration | Type picker (Standard/Core/Tenant/Custom); property→type `$ref` binding storage + read; resolved-type display in Designer |
| Governance | Entitlement gating; publish/validation gate; basic audit log |

**Deferred to V2**

| Area | V2 capability |
|---|---|
| Import | OpenAPI 3.1 components importer; Avro/Protobuf (experimental); advanced conflict UX |
| Resolution | Circular-reference detection; remote `$ref` allowlist; resolution-depth policy; full graph visualization |
| Governance | Promote-tenant-type-to-core (CAB) workflow; version roots (`v1` draft) management & deprecation lifecycle; Governance-area overview landing |
| Designer | "Used by properties" dependents/impact analysis |

The MVP/V2 flag for every issue is in each epic table (**MVP** column) and summarized in §13.

---

## 3. Architecture (target state)

```mermaid
flowchart TB
  subgraph UI["objectified-ui (Control Panel → Governance)"]
    nav["DashboardSideNav → Governance → Type Registry"]
    pages["/ade/dashboard/governance/types/* (overview·detail·import·resolver·namespaces·settings)"]
    picker["Designer property editor → Type picker"]
    proxy["Next.js /api/types/* proxy"]
    nav --> pages --> proxy
    picker --> proxy
  end

  subgraph REST["objectified-rest — Type Registry service"]
    api["Namespace + Type CRUD\n(draft 2020-12 validation, scope rules)"]
    resolver["Relative $ref resolver\n(unresolved / circular)"]
    import["Import: JSON Schema + type-def bundle (+ OpenAPI 3.1 v2)"]
    bind["Property↔type binding read model"]
  end

  subgraph ODB[("objectified-db — odb schema (single database)")]
    prim[("odb.primitives (extended)\nschema JSONB · namespace · base_uri · $id · draft · source · refs JSONB")]
    cls[("odb.class_property\n(property → primitive $ref binding)")]
    imp[("import provenance (existing infra, reused)")]
  end

  proxy --> api & resolver & import & bind
  api --> prim
  resolver --> prim
  import --> prim & imp
  bind -->|$ref| cls
  cls -->|primitive_id / $ref| prim
  api -. seeds .-> seed["std/v0 core system primitives\n(is_system rows: primitives + std types)"]
```

**Conventions inherited from the codebase (verified):**
- UI: Next.js 16 App Router; nav in `DashboardSideNav.tsx` (already has a **Governance**
  section containing *Primitives*); routes under `/ade/dashboard/*`; client → `/api/*` proxy →
  `objectified-rest` with `createRestAuthHeaders()`.
- REST: FastAPI; tenant-scoped `/v1/...` with `validate_authentication()`.
- DB: PostgreSQL `odb` schema, UUID PKs, soft deletes, JSONB; migrations in
  `objectified-db/scripts/<timestamp>.sql`. The registry **extends the existing `odb.primitives`
  table in the same `objectified-db` database** — no separate database, no new schema; bindings
  reference primitives with ordinary same-database foreign keys.
- Brand: in-app the feature uses the Control Panel **indigo** accent; the standalone Atlas
  mockups use teal.

---

## 4. Relationship to Existing Issues (de-duplication)

These open issues are *adjacent* and must be cross-linked, **not duplicated**:

| Existing | Relationship |
|---|---|
| #624–#636 (`registry` "Schema Registry": centralized repo, namespacing #627, dependency tracking #630, versioning #626, search #629/#631) | The Type Registry is the concrete, draft-2020-12 **type** layer of this vision. Reuse the `registry` label; this roadmap supersedes the generic stubs for the *type* scope. Namespacing (#627) and dependency tracking (#630) are realized here for types. |
| #719–#728 (`governance`: approval workflows, naming, gates, dashboard) | The Type Registry's publish/validation gate (7.2) and audit (7.4) align; promote-to-core (7.3) is a governed workflow consistent with #722/#724. |
| #2299 Import History Data Model · #2305 User Attribution on Import · #2316 REST API for Import (`import`) | The Type Registry import (Epic 4) should **reuse** the existing import history/attribution infrastructure rather than re-implement it; this roadmap adds the type-specific source parsers + `$ref` rewrite. |
| #1130 Type Mapping Registry (mobile-sdk) | Different concern (code-gen type mapping). No overlap beyond the word "type". |

No existing issue implements a JSON Schema 2020-12 **type registry (an extended `odb.primitives`
table) with relative `$ref` resolution**, so the core of this roadmap is net-new.

---

## 5. Epic Index

| # | Epic | Theme | Primary module(s) |
|---|---|---|---|
| 1 (#3439) | Primitives Registry Schema | Extend `odb.primitives` (namespace/`$ref`/draft columns), bindings, core-type seed | objectified-db (`odb` schema) |
| 2 (#3440) | Registry Service & API | Namespace/type CRUD, scope rules, validation, proxy | objectified-rest, objectified-ui |
| 3 (#3441) | Reference Resolution Engine | Relative `$ref` resolve, unresolved/circular, graph | objectified-rest |
| 4 (#3442) | Import System | JSON Schema + type-def bundle (+ OpenAPI 3.1 v2) | objectified-rest |
| 5 (#3443) | Governance UI: Type Registry | Nav + overview/detail/import/resolver/namespaces/settings | objectified-ui |
| 6 (#3444) | Designer Property Binding | Type picker, property→`$ref` binding, resolved display | objectified-ui, objectified-rest |
| 7 (#3445) | Scopes, Governance & Publishing | Entitlements, publish gate, promote-to-core, audit | objectified-rest, objectified-ui |

**Labels.** Reuse: `epic`, `mvp`, `enhancement`, `governance`, `registry`, `rest`, `ui`,
`import`, `versions`, `schema-designer`. **New labels to create:**

| Label | Color | Description |
|---|---|---|
| `type-registry` | `#0E7490` | Objectified Primitives — JSON Schema 2020-12 types (extends `/ade/dashboard/primitives`) |
| `types-db` | `#0B5563` | Primitives registry storage — extends `odb.primitives` in `objectified-db` (single database) |
| `roadmap-type-registry` | `#BFDADC` | ROADMAP_TYPE_REGISTRY_GOVERNANCE.md ticket pack |

Issue naming: `Primitives: [<epic#.issue#>] <title>`.

---

## 6. Epic 1 — Primitives Registry Schema (extend `odb.primitives`)

The registry's data model is the **existing `odb.primitives` table, extended in place** — *not*
a separate database. A tenant owns its own primitives (`tenant_id`) and also sees system-wide
primitives (`is_system`/`is_public`), all in one table in the `objectified-db` `odb` schema, so
they compose across the tenant's projects with ordinary same-database foreign keys. This epic
adds the namespace / `$id` / `$ref` / draft-2020-12 columns, the import + property-binding links,
and the core system-primitive seed.

```mermaid
erDiagram
  tenants ||--o{ primitives : owns
  primitives ||--o{ primitives : "$ref (refs JSONB)"
  class_property }o--|| primitives : "binds via $ref"
  primitives {
    uuid id
    uuid tenant_id "owning tenant (NULL-equivalent system rows via is_system)"
    text name
    text category
    jsonb schema "JSON Schema 2020-12 document"
    text namespace "e.g. std/v0/types or tenant/acme/types"
    text base_uri "import-source base URL for relative $ref"
    text schema_id "$id"
    text draft "default 2020-12"
    text source "human|imported"
    jsonb refs "array of {relative_ref, resolved_target, status}"
    bool is_system "system-wide (visible to all tenants)"
    bool is_public
  }
  class_property {
    uuid id
    uuid primitive_id "bound primitive (same-DB FK)"
    text primitive_ref "stored $ref"
  }
```

| Issue | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|---|---|---|---|:---:|:---:|---|---|
| 1.1 #3446 | Consolidate registry into `objectified-db` (remove separate DB) | Rip out the `objectified-types-db` provisioning shipped earlier; registry lives in `odb` | `type-registry`,`types-db`,`mvp`,`roadmap-type-registry` | N | Y | M | objectified-db, objectified-rest |
| 1.2 #3447 | Extend `odb.primitives` (namespace, `$id`, `$ref`, draft 2020-12) | Migration adding namespace/`base_uri`/`schema_id`/`draft`/`source`/`refs` columns to `odb.primitives` | `type-registry`,`types-db`,`mvp`,`roadmap-type-registry` | N | Y | M | objectified-db |
| 1.3 #3448 | ~~Import provenance & property binding~~ **DONE** | `odb.primitive_imports` provenance table + `report` JSON; `class_properties.primitive_id`/`primitive_ref` binding read by the Designer | `type-registry`,`types-db`,`import`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-db |
| 1.4 #3449 | ~~Seed core system primitives (`std/v0`)~~ **DONE** | Seed primitives + std types (date, uuid, money, …) as system-wide `is_system` rows | `type-registry`,`registry`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-db, objectified-rest |

### Issue 1.1 — Consolidate registry into `objectified-db` (remove separate DB)
- **Problem.** An earlier iteration provisioned a **separate** `objectified-types-db` database
  (its own `otr` schema, a `registry` CLI command group, `registry-scripts/`, a dedicated
  `objectified-rest` connection, a docker-compose `types-migrate` service). This is the wrong
  design: primitives are tenant-associated **and** system-wide and must live with the rest of the
  tenant's data in `objectified-db` so they compose with ordinary foreign keys. A separate
  database forces cross-database references and duplicate connection/migration machinery.
- **Solution/Scope.** Reverse the separate-database work: remove the `objectified-types-db`
  provisioning and `otr` schema, the `registry` command group + `registry-scripts/` +
  `registry.ts` in `objectified-db`, the `RegistryDatabase` connection / `OBJECTIFIED_TYPES_DB*`
  config / health reporting in `objectified-rest`, and the `types-migrate` docker-compose service
  and env. The registry's storage is the existing `odb.primitives` table (extended in 1.2).
- **Acceptance Criteria.** No `objectified-types-db`, `otr` schema, `registry` command, or
  `RegistryDatabase` connection remains; the stack builds and migrates with a single database;
  `GET /health` no longer reports a separate registry database; existing `/v1/primitives` works.
- **Parallelism/Dependencies.** Foundational — precedes 1.2.
- **Technical Stack.** PostgreSQL, docker-compose, FastAPI.

### Issue 1.2 — Extend `odb.primitives` (namespace, `$id`, `$ref`, draft 2020-12)
- **Problem.** `odb.primitives` stores flat JSON Schemas with no namespace, no `$id`/base-uri,
  no draft marker, and no record of a type's relative `$ref` edges.
- **Solution/Scope.** A single `objectified-db/scripts/<timestamp>.sql` migration that **adds
  columns to the existing `odb.primitives` table** (no new tables, no new schema): `namespace`
  (e.g. `std/v0/types`, `tenant/<slug>/types`), `base_uri` (import-source base URL for relative
  `$ref` resolution), `schema_id` (`$id`), `draft` (default `2020-12`), `source` ∈ {human,
  imported}, and `refs` JSONB (array of `{relative_ref, resolved_target, status ∈
  {resolved, unresolved, circular}}`). Tenant scoping reuses the existing `tenant_id` FK to
  `odb.tenants`; system-wide reuses `is_system`/`is_public`; immutability reuses `is_system`.
  Add indices (`namespace`, `schema_id`, `source`, GIN on `refs`). Source:
  `governance/type-namespaces.html`, `types/*` entity tags.
- **Acceptance Criteria.** Migration applies to `objectified-db`; the new columns + indices exist
  on `odb.primitives`; a primitive with an internal `$ref` round-trips its `refs` JSONB; the
  existing `(tenant_id, category, name)` uniqueness and all current `/v1/primitives` behaviour
  are preserved (no data loss).
- **Parallelism/Dependencies.** Depends on 1.1; blocks Epic 2/3/4.
- **Technical Stack.** PostgreSQL, JSONB.

### Issue 1.3 — Import provenance & property binding ✅ DONE (#3448)
- **Delivered.** `odb.primitive_imports` provenance table (source_kind, options/report JSONB,
  attribution, tallies) written on every `/v1/primitives/{tenant}/import`, with read endpoints
  `GET /v1/primitives/{tenant}/imports[/{id}]`; imported primitives marked `source='imported'`.
  `odb.class_properties` extended with `primitive_id` (FK to `odb.primitives`) + `primitive_ref`,
  surfaced on the Designer read path and carried through class/version copies.
- **Problem.** Imports and property bindings need durable records — in the same database.
- **Solution/Scope.** Reuse the existing import-history/attribution infrastructure (#2299/#2305)
  to record primitive imports (source_kind ∈ {json-schema, type-def-bundle, openapi}, target
  namespace/scope, options/report JSONB, attribution); and add a **property→primitive binding**
  by extending `odb.class_property` with a same-database foreign key to `odb.primitives` plus the
  stored `$ref` (and resolved target), read by the Designer. No separate database, no cross-DB
  id references. Source: `governance/type-import.html`, `governance/property-binding.html`.
- **Acceptance Criteria.** An import persists a provenance record with its report; a property
  binding persists with a real FK to `odb.primitives` and is queryable from the Designer read path.
- **Parallelism/Dependencies.** Depends on 1.2; parallel with 1.4.
- **Technical Stack.** PostgreSQL, JSONB; ordinary same-database foreign keys.

### Issue 1.4 — Seed core system primitives (`std/v0`) ✅ DONE (#3449)
- **Delivered.** Migration `objectified-db/scripts/20260622-240000.sql` seeds the `std/v0/primitives`
  (string, number, integer, boolean, null, array, object) and `std/v0/types` (date, date-time,
  time, uuid, email, uri, decimal, currency-code, money) namespaces as system-wide
  `is_system`/`is_public` rows in `odb.primitives`, with the #3447 registry columns populated
  (`namespace`, `base_uri`, `schema_id` = `$id`, `draft` = 2020-12, `source` = human) and relative
  `$ref` chains recorded in `refs` (`date` → `../primitives/string` + `format: date`; `money` →
  `./decimal`, `./currency-code`). Verified end-to-end against Postgres: 0 unresolved refs, `money`/
  `date` match the canonical schemas, and re-running the seed is idempotent
  (`ON CONFLICT (tenant_id, category, name) DO NOTHING`). DB-free structural tests in
  `objectified-db/test/primitives-std-seed.test.ts`.
- **Problem.** Tenants need a baseline of core types available to all.
- **Solution/Scope.** Seed `std/v0/primitives` (string, number, integer, boolean, null, array,
  object) and `std/v0/types` (date, date-time, uuid, email, uri, decimal, currency-code, money,
  …) as **system-wide `is_system` primitives** in `odb.primitives`, with correct relative `$ref`s
  recorded in `refs` (e.g. `date` → `../primitives/string` + `format: date`; `money` →
  `./decimal`, `./currency-code`). Idempotent seeding migration/script. Source:
  `types/browser.html`, `types/type-detail.html` (money), `governance/type-detail.html`.
- **Acceptance Criteria.** After seed, core primitives resolve fully (0 unresolved); `money` and
  `date` match the canonical schemas; re-running the seed is idempotent.
- **Parallelism/Dependencies.** Depends on 1.2; uses 3.1 for resolution verification.
- **Technical Stack.** SQL/Python seed, JSON Schema 2020-12.

---

## 7. Epic 2 — Registry Service & API

The FastAPI service exposing namespace/type CRUD with draft-2020-12 validation and scope
enforcement, plus the `objectified-ui` proxy + typed client.

| Issue | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|---|---|---|---|:---:|:---:|---|---|
| 2.1 #3450 ✅ | Registry service skeleton + auth/scoping | **DONE** — registry health/ping (`GET /v1/primitives/health`) over the `objectified-db` connection; existing tenant/scope auth confirmed, clients unaffected | `type-registry`,`rest`,`mvp`,`roadmap-type-registry` | N | Y | M | objectified-rest |
| 2.2 #3451 ✅ | Namespace CRUD API | **DONE** — `GET/POST/PUT /v1/types/{tenant_slug}/namespaces` over `odb.type_namespaces`; tenant-admin writes, system-core read-only, type counts joined from `odb.primitives` | `type-registry`,`registry`,`rest`,`mvp`,`roadmap-type-registry` | N | Y | M | objectified-rest |
| 2.3 #3452 ✅ | Type definition CRUD + draft 2020-12 validation | **DONE** — strict JSON Schema draft 2020-12 meta-validation on primitive create/update/import (`app/schema_validation.py`), field-level 422 errors, stable derived `$id` (`schema_id`) + stamped `draft` persisted to `odb.primitives` | `type-registry`,`rest`,`mvp`,`roadmap-type-registry` | N | Y | L | objectified-rest |
| 2.4 #3453 ✅ | Scope & visibility enforcement | **DONE** — read scope `is_system ∪ tenant` on `odb.primitives` reads (cross-tenant isolation, all tenants see `std/*`); centralized `$ref`-direction rules (`app/primitives_scope.py`) reject core→tenant and tenant→other-tenant refs on create/update/import with structured 422 violations | `type-registry`,`governance`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-rest |
| 2.5 #3454 | Registry coverage/stats endpoint | Counts by scope, imported, unresolved (for dashboard KPIs) | `type-registry`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | S | objectified-rest |
| 2.6 #3455 | ~~UI proxy routes + typed client~~ | **CLOSED — duplicate** (`/api/primitives/*` shipped) | `type-registry`,`ui`,`mvp`,`roadmap-type-registry` | N | Y | S | objectified-ui |

### Issue 2.1 — Registry service skeleton + auth/scoping
- **Problem.** The registry service must read/write the **extended `odb.primitives`** table over
  the existing `objectified-db` connection — there is no separate database to wire to.
- **Solution/Scope.** Extend the existing primitives service (`/v1/primitives/{tenant_slug}/...`)
  / add registry routes that operate on the extended `odb.primitives` columns (1.2), using the
  existing `objectified-db` connection and `validate_authentication()`. Pydantic DTOs in
  `models.py`. No separate DB connection or pool.
- **Acceptance Criteria.** Authenticated, tenant-scoped requests read/write `odb.primitives`
  (tenant rows + system rows); no separate registry connection is introduced.
- **Parallelism/Dependencies.** Depends on 1.1/1.2; blocks 2.2–2.6.
- **Technical Stack.** FastAPI, asyncpg/pg, Pydantic.

### Issue 2.2 — Namespace CRUD API
- **Problem.** Namespaces (system/tenant, base URI, version root) must be managed.
- **Solution/Scope.** `GET/POST/PUT /v1/types/{tenant_slug}/namespaces` honoring scope rules
  (only platform admins create system namespaces; tenant admins create tenant namespaces).
  Source: `governance/type-namespaces.html`.
- **Acceptance Criteria.** Create/list/update namespaces; defaults + visibility persisted; system
  namespaces are read-only to non-platform-admins.
- **Parallelism/Dependencies.** Depends on 2.1; blocks 4.x, 5.6.
- **Technical Stack.** FastAPI, Pydantic.
- **Delivered.** Migration `objectified-db/scripts/20260622-250000.sql` adds `odb.type_namespaces`
  (scope/base-uri/version-root/visibility/default), seeded with the `std/v0` system-core
  namespaces; its `namespace`/`base_uri` mirror `odb.primitives`, which supplies each namespace's
  type count. REST routes `GET/POST/PUT /v1/types/{tenant_slug}/namespaces`
  (`type_namespaces_routes.py`) list system-core ∪ tenant namespaces, and create/update
  tenant-owned namespaces (tenant-admin only; path immutable; base URI / version root derived from
  the path). System-core namespaces are read-only via the API (no platform-admin role exposed →
  403). DTOs in `models.py`; DAOs `Database.list/get/create/update_type_namespace()`.

### Issue 2.3 — Type definition CRUD + draft 2020-12 validation
- **Problem.** Types must be created/edited with valid JSON Schema 2020-12.
- **Solution/Scope.** CRUD `/v1/types/{tenant_slug}/{namespace}/types`; validate `json_schema`
  against **draft 2020-12** (strict mode configurable, annotations allowed) before persist;
  compute/store `$id`. Source: `types/create-type.html`, `governance/type-detail.html`,
  `governance/type-settings.html` (dialect).
- **Acceptance Criteria.** A valid 2020-12 type persists; an invalid one is rejected with a
  structured error; `$id` is derived from namespace base + name.
- **Parallelism/Dependencies.** Depends on 2.1/2.2; blocks 5.2/5.3, 6.x.
- **Technical Stack.** FastAPI, a 2020-12 validator (e.g. `jsonschema`), JSONB.

### Issue 2.4 — Scope & visibility enforcement
- **Problem.** Core types are shared with all tenants; tenant types are private; a core type must
  never reference a tenant type.
- **Solution/Scope.** Centralize scope/visibility checks: reads resolve **system-core ∪
  current-tenant**; writes restricted by scope; reject saving a core type whose `$ref` targets a
  tenant namespace. Source: `governance/type-namespaces.html` (precedence + rule box).
- **Acceptance Criteria.** Tenant A cannot see Tenant B types; all tenants see `std/*`; a
  core→tenant `$ref` is rejected; tenant→core `$ref` is allowed.
- **Parallelism/Dependencies.** Depends on 2.2/2.3; reinforced by 3.1.
- **Technical Stack.** FastAPI authorization layer.

### Issue 2.5 — Registry coverage/stats endpoint
- **Problem.** The overview KPIs need aggregate counts.
- **Solution/Scope.** `GET /v1/types/{tenant_slug}/stats` → core type count, tenant type count,
  imported count, properties bound, unresolved `$ref` count. Source:
  `governance/type-registry.html` (KPI strip).
- **Acceptance Criteria.** Numbers match fixtures and the resolver/binding state.
- **Parallelism/Dependencies.** Depends on 2.3, 3.2, 6.2; parallel otherwise.
- **Technical Stack.** FastAPI, SQL aggregation.

### Issue 2.6 — UI proxy routes + typed client
- **Problem.** Browser calls must proxy through Next.js with JWT injection.
- **Solution/Scope.** `/api/types/*` route handlers + a typed client in `objectified-ui/lib/api/`
  using `createRestAuthHeaders()`.
- **Acceptance Criteria.** Client covers namespaces, types, stats, resolver, import; typed errors.
- **Parallelism/Dependencies.** Depends on 2.2–2.5; blocks Epic 5/6 UI.
- **Technical Stack.** Next.js route handlers, TypeScript.

---

## 8. Epic 3 — Reference Resolution Engine

The defining mechanic: resolve relative `$ref` against each type's import-source base URL, and
report unresolved/circular references.

```
base      = api.objectified.dev/types/std/v0/types/      (source: date)
$ref      = ../primitives/string
resolved  = api.objectified.dev/types/std/v0/primitives/string   ✓
```

| Issue | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|---|---|---|---|:---:|:---:|---|---|
| 3.1 #3456 ✅ | Relative `$ref` resolution against base | **DONE** — `app/primitives_resolver.py` resolves each relative `$ref` against the source `base_uri` (`./`, `../`, cross-scope `../../std/...`) to an absolute registry URI, maps it to a primitive by `schema_id` within read scope (#3453), and persists `{relative_ref, resolved_target, status}` edges to `odb.primitives.refs` on create/update/import | `type-registry`,`rest`,`mvp`,`roadmap-type-registry` | N | Y | L | objectified-rest |
| 3.2 #3457 ✅ | Unresolved-reference detection & flags | **DONE** — edges are flagged `resolved`/`unresolved` on save/import (#3456); `GET /v1/primitives/{tenant_slug}/unresolved` exposes the tenant's unresolved-edge count, affected-primitive count, and per-primitive breakdown (feeds 2.5/#3454 KPIs and the 5.5/#3470 resolver UI). DB aggregates `count_unresolved_refs` / `get_primitives_with_unresolved_refs` over `odb.primitives.refs`; creating/importing/repinning a type runs `mark_refs_resolved_to_target` so fixing the target clears dependents on re-resolve | `type-registry`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-rest |
| 3.3 #3458 | Circular-reference detection | Detect cycles (A→B→A) and flag | `type-registry`,`rest`,`roadmap-type-registry` | Y | N | M | objectified-rest |
| 3.4 #3459 ✅ | Resolver API + dependency listing | **DONE** — `POST /v1/types/{tenant_slug}/resolve` re-resolves every `$ref` edge across the tenant's primitives against the current registry (same existence test as save-time #3456), persists any status that changed for the tenant's own rows ("re-resolve updates statuses"), and returns the per-primitive dependency listing (each resolved edge enriched with its target id/name) for the 5.5/#3470 resolver UI; counts mirror 3.2/#3457 plus `reresolved_primitive_count`. Pure re-evaluation in `app/type_resolver.py` | `type-registry`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-rest |

### Issue 3.1 — Relative `$ref` resolution against base
- **Problem.** Types reference each other by relative URL rooted at their import source.
- **Solution/Scope.** Implement URL-base resolution (`base + relative → absolute`), mapping the
  absolute target to a registry `type_definition`; honor scope rules (2.4). Handle `../`, `./`,
  and cross-scope `../../std/...`. Source: `types/resolver.html`, `governance/type-resolver.html`,
  `types/type-detail.html`.
- **Acceptance Criteria.** `date`→`../primitives/string`, `money`→`./decimal`/`./currency-code`,
  `tenant/acme/.../sku`→`../../std/v0/types/string` all resolve to the correct targets.
- **Parallelism/Dependencies.** Depends on 1.2/2.3; blocks 3.2/3.4, 6.3.
- **Technical Stack.** FastAPI, URL resolution.

### Issue 3.2 — Unresolved-reference detection & flags
- **Problem.** Imports/edits can leave references that point at not-yet-present types.
- **Solution/Scope.** On save/import, mark `type_ref.status = unresolved` for targets not found;
  expose counts (feeds 2.5) and a list. Source: resolver mockups (amber unresolved rows).
- **Acceptance Criteria.** A ref to a missing type is flagged unresolved; resolving the target
  clears it on re-resolve.
- **Parallelism/Dependencies.** Depends on 3.1.
- **Technical Stack.** FastAPI, SQL.

### Issue 3.3 — Circular-reference detection — V2
- **Problem.** Cycles (e.g. `node ↔ edge`) must be detected.
- **Solution/Scope.** Graph cycle detection over `type_ref`; flag `status = circular`. Source:
  resolver mockups (red circular row).
- **Acceptance Criteria.** A 2-node and 3-node cycle are detected and flagged; acyclic graphs
  are unaffected.
- **Parallelism/Dependencies.** Depends on 3.1/3.4.
- **Technical Stack.** FastAPI, graph traversal.

### Issue 3.4 — Resolver API + dependency listing
- **Problem.** The resolver UI needs resolution results + dependency edges.
- **Solution/Scope.** `POST /v1/types/{tenant_slug}/resolve` (optionally namespace-scoped)
  returning per-ref status + the dependency edge list for the graph/table. Source:
  `governance/type-resolver.html` (table + graph).
- **Acceptance Criteria.** Returns resolved/unresolved (and circular when 3.3 lands) with edges;
  matches the resolver UI's table.
- **Parallelism/Dependencies.** Depends on 3.1/3.2; blocks 5.5.
- **Technical Stack.** FastAPI.

---

## 9. Epic 4 — Import System (Schemas + Type Definitions)

Ingest external types. The conversation explicitly requires importing **both JSON Schemas and
type definitions**; OpenAPI 3.1 is a V2 add-on. Reuse existing import history/attribution
(#2299/#2305) rather than re-building it.

```mermaid
flowchart LR
  src["Source: file / paste / URL / git"] --> kind{Source kind}
  kind -->|JSON Schema 2020-12| js["Parse doc + $defs"]
  kind -->|Type-def bundle .zip/.json| bun["Expand bundle → many types"]
  kind -->|OpenAPI 3.1 v2| oas["components/schemas"]
  js & bun & oas --> rw["$ref rewrite → relative + namespace/scope map"]
  rw --> rev["Review: conflicts / dedupe / validation report"]
  rev --> commit["Commit → type_definition (+ type_import)"]
```

| Issue | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|---|---|---|---|:---:|:---:|---|---|
| 4.1 #3460 ✅ | ~~Import pipeline core + ingestion~~ | **DONE** — `POST /v1/primitives/{tenant_slug}/import/stage` orchestrator: ingests paste/file/url/git, parses JSON/YAML, stages candidate types per kind (json-schema/type-def-bundle/openapi), records a `staged` `odb.primitive_imports` row; legacy paste `/import` retained | `type-registry`,`import`,`rest`,`mvp`,`roadmap-type-registry` | N | Y | M | objectified-rest |
| 4.2 #3461 ✅ | ~~JSON Schema 2020-12 parser~~ | **DONE** — `primitives_parser.parse_json_schema_document`: each `$defs`/`definitions` entry → a discrete type (single-root doc → one type), captures intra-doc `#/$defs` refs as `internal` `refs` edges for rewrite (#3463), per-type draft 2020-12 validation report; wired through the `/import/stage` pipeline and the legacy `/import` commit path | `type-registry`,`import`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | L | objectified-rest |
| 4.3 #3462 ✅ | ~~Type-definition bundle importer~~ | **DONE** — `primitives_bundle.parse_type_def_bundle` expands a `.json`/`.yaml` bundle's `types` (or `$defs`/`definitions`) container into discrete types, capturing inter-type `#/types`/`#/$defs` refs as `internal` `refs` edges for rewrite (#3463) with per-type draft 2020-12 validation; `expand_zip_bundle` merges a `.zip` of per-type files into a bundle document. Wired through `/import/stage` (deep candidates) and the `/import` commit path (`source_kind='type-def-bundle'` → N types commit N `odb.primitives` rows with refs intact); malformed bundle → clear 400 | `type-registry`,`import`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | L | objectified-rest |
| 4.4 #3463 | `$ref` rewrite + namespace/scope mapping | Rewrite refs relative to import source; map to namespace/scope | `type-registry`,`import`,`rest`,`mvp`,`roadmap-type-registry` | N | Y | L | objectified-rest |
| 4.5 #3464 | Import review: conflicts, dedupe, report | Conflict resolution, dedupe identical, validation report | `type-registry`,`import`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-rest |
| 4.6 #3465 | OpenAPI 3.1 components importer | Extract `components/schemas` as types | `type-registry`,`import`,`rest`,`roadmap-type-registry` | Y | N | M | objectified-rest |

### Issue 4.1 — Import pipeline core + ingestion
- **Problem.** A single orchestration path is needed for all source kinds.
- **Solution/Scope.** Pipeline that accepts source kind (JSON Schema / type-def bundle / OpenAPI)
  and method (file/paste/URL/git), records a `type_import` (1.3), and stages parsed types for
  rewrite/review. Source: `governance/type-import.html` (source-type cards + method tabs).
- **Acceptance Criteria.** Each source kind/method reaches a staged result with an import record.
- **Parallelism/Dependencies.** Depends on 1.3, 2.2; blocks 4.2–4.6.
- **Technical Stack.** FastAPI, file/zip handling, git/http fetch.

### Issue 4.2 — JSON Schema 2020-12 parser
- **Problem.** Must ingest raw JSON Schemas, including `$defs`-bundled documents.
- **Solution/Scope.** Parse a 2020-12 document; optionally treat each `$defs` entry as an
  individual type; capture intra-doc refs (`#/$defs/...`) for rewrite (4.4). Source:
  `governance/type-import.html` (detected-document panel).
- **Acceptance Criteria.** A doc with 3 `$defs` yields 3 types with their internal refs captured.
- **Parallelism/Dependencies.** Depends on 4.1; parallel with 4.3.
- **Technical Stack.** FastAPI, JSON Schema parsing.

### Issue 4.3 — Type-definition bundle importer
- **Problem.** Must ingest Objectified type-definition bundles containing many types.
- **Solution/Scope.** Expand `.zip`/`.json` bundles into multiple interlinked `type_definition`s,
  preserving inter-type refs for rewrite. Source: `governance/type-import.html` (Type Definition
  Bundle card), conversation requirement ("import them as well").
- **Acceptance Criteria.** A bundle of N types imports all N with refs intact; a malformed bundle
  reports a clear error.
- **Parallelism/Dependencies.** Depends on 4.1; parallel with 4.2.
- **Technical Stack.** FastAPI, zip/json.

### Issue 4.4 — `$ref` rewrite + namespace/scope mapping
- **Problem.** External refs (`#/$defs/Money`, absolute URLs) must become **relative** refs
  rooted at the import source, mapped into a target namespace + scope.
- **Solution/Scope.** Rewrite engine: `#/$defs/Money → ./money`, external known refs → core
  types where possible; assign target namespace + scope (system/tenant). Source:
  `governance/type-import.html` (options), `types/import-review.html` ($ref rewrite table).
- **Acceptance Criteria.** Imported refs are stored relative and resolve via Epic 3; mapping to
  core types works for recognized formats.
- **Parallelism/Dependencies.** Depends on 4.2/4.3; uses 3.1.
- **Technical Stack.** FastAPI.

### Issue 4.5 — Import review: conflicts, dedupe, report
- **Problem.** Imports collide with existing types and may duplicate.
- **Solution/Scope.** Detect New/Conflict/Identical per type; offer keep/overwrite/rename; dedupe
  identical; produce a validation report (draft 2020-12: valid/errors/warnings) and unresolved-ref
  mapping. Source: `types/import-review.html`.
- **Acceptance Criteria.** Conflicts are surfaced with resolution choices; committing applies them;
  the report matches outcomes.
- **Parallelism/Dependencies.** Depends on 4.4; feeds 5.4.
- **Technical Stack.** FastAPI.

### Issue 4.6 — OpenAPI 3.1 components importer — V2
- **Problem.** Teams want to import OpenAPI `components/schemas`.
- **Solution/Scope.** Extract `components/schemas` as types (2020-12-compatible), reusing 4.4/4.5.
  Source: `governance/type-import.html` (OpenAPI card), `types/import-review.html` (stripe.openapi).
- **Acceptance Criteria.** An OpenAPI 3.1 doc yields registry types with rewritten refs.
- **Parallelism/Dependencies.** Depends on 4.4/4.5.
- **Technical Stack.** FastAPI, OpenAPI parsing.

---

## 10. Epic 5 — Governance UI: Type Registry

The in-app surface under **Control Panel → Governance**, matching the `governance/` mockups.

| Issue | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|---|---|---|---|:---:|:---:|---|---|
| 5.1 #3466 | ~~Governance nav entry + route group~~ | **CLOSED — duplicate** (`/ade/dashboard/primitives` in nav) | `type-registry`,`ui`,`governance`,`mvp`,`roadmap-type-registry` | N | Y | S | objectified-ui |
| 5.2 #3467 | Enhance Primitives overview (registry KPIs) | Extend existing page: KPIs, namespace collections, activity | `type-registry`,`ui`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-ui |
| 5.3 #3468 | Type detail page | Schema, resolved refs, dependents, metadata | `type-registry`,`ui`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-ui |
| 5.4 #3469 | Import UI (wizard) | Source/options/review wired to Epic 4 | `type-registry`,`ui`,`import`,`mvp`,`roadmap-type-registry` | Y | Y | L | objectified-ui |
| 5.5 #3470 | Reference Resolver UI | Graph + table, base, unresolved/circular | `type-registry`,`ui`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-ui |
| 5.6 #3471 | Namespaces & Scopes UI | Manage namespaces, scope, base URI, version root | `type-registry`,`ui`,`registry`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-ui |
| 5.7 #3472 | Type Registry Settings UI | DB status, dialect, resolution & validation policy | `type-registry`,`ui`,`mvp`,`roadmap-type-registry` | Y | Y | S | objectified-ui |
| 5.8 #3473 | Governance area overview page | Governance landing positioning Type Registry + tools | `type-registry`,`ui`,`governance`,`roadmap-type-registry` | Y | N | S | objectified-ui |

### Issue 5.1 — Governance nav entry + route group
- **Problem.** No Type Registry surface exists in the app nav.
- **Solution/Scope.** Add a **Type Registry** item to the existing **Governance** section of
  `DashboardSideNav.tsx` (next to Primitives), gated by `hasTenant`; create the route group
  `/ade/dashboard/governance/types` with an auth-guarded layout + in-page tabs. Source:
  `governance/type-registry.html` (sidebar + tabs), `governance/README.md`.
- **Acceptance Criteria.** Type Registry appears under Governance and routes correctly; active
  state highlights; tabs (Overview/Import/Resolver/Namespaces/Settings) switch views.
- **Parallelism/Dependencies.** Depends on 2.6; blocks 5.2–5.8.
- **Technical Stack.** Next.js App Router, React, Tailwind, lucide.

### Issue 5.2 — Type Registry overview page
- **Problem.** Users need the registry's at-a-glance state.
- **Solution/Scope.** KPI cards (core/tenant/imported/bound/unresolved), collections table by
  scope with filters, recent activity, resolution-base explainer. Source:
  `governance/type-registry.html`.
- **Acceptance Criteria.** Reflects 2.5 stats and 2.2 collections; row click → type detail.
- **Parallelism/Dependencies.** Depends on 5.1, 2.5; parallel with 5.3–5.7.
- **Technical Stack.** Next.js, Tailwind.

### Issue 5.3 — Type detail page
- **Problem.** Users need a single type's full view.
- **Solution/Scope.** JSON Schema source, reference-resolution table, example instance,
  dependents, metadata, base chain; actions (edit, bind, export, deprecate). Source:
  `governance/type-detail.html`, `types/type-detail.html`.
- **Acceptance Criteria.** Renders a type (e.g. `money`) with resolved refs and dependents.
- **Parallelism/Dependencies.** Depends on 5.1, 2.3, 3.4; parallel.
- **Technical Stack.** Next.js, Tailwind.

### Issue 5.4 — Import UI (wizard)
- **Problem.** Users need to drive imports.
- **Solution/Scope.** Source-type cards (JSON Schema / type-def bundle / OpenAPI), method tabs,
  target namespace/scope, options (`$ref` rewrite, dedupe, etc.), and a review step wired to
  Epic 4. Source: `governance/type-import.html`, `types/import.html`, `types/import-review.html`.
- **Acceptance Criteria.** A JSON Schema and a type-def bundle import end-to-end with review and
  result; conflicts resolvable.
- **Parallelism/Dependencies.** Depends on 5.1, Epic 4; parallel.
- **Technical Stack.** Next.js, Tailwind.

### Issue 5.5 — Reference Resolver UI
- **Problem.** Users need to see/resolve references.
- **Solution/Scope.** Resolution base control, dependency graph, resolution table with
  resolved/unresolved/(circular) states, re-resolve. Source: `governance/type-resolver.html`.
- **Acceptance Criteria.** Shows resolver output (3.4); re-resolve updates statuses.
- **Parallelism/Dependencies.** Depends on 5.1, 3.4; parallel.
- **Technical Stack.** Next.js, Tailwind.

### Issue 5.6 — Namespaces & Scopes UI
- **Problem.** Users need to manage namespaces and understand scope.
- **Solution/Scope.** Namespaces table (scope, base URI, version root, visibility, default),
  scope precedence/rule cards, new-namespace; promote-to-core entry (governed, 7.3). Source:
  `governance/type-namespaces.html`.
- **Acceptance Criteria.** Reflects 2.2; create/edit namespaces; scope rules explained.
- **Parallelism/Dependencies.** Depends on 5.1, 2.2; parallel.
- **Technical Stack.** Next.js, Tailwind.

### Issue 5.7 — Type Registry Settings UI
- **Problem.** Users configure registry behavior.
- **Solution/Scope.** Registry DB status, default draft, `$ref` resolution policy (relative,
  remote allowlist, depth, circular policy), import defaults, validation/publishing governance.
  Source: `governance/type-settings.html`.
- **Acceptance Criteria.** Settings persist and affect service behavior where applicable.
- **Parallelism/Dependencies.** Depends on 5.1; relates to 7.x.
- **Technical Stack.** Next.js, FastAPI.

### Issue 5.8 — Governance area overview page — V2
- **Problem.** The Governance section deserves a landing that frames its capabilities.
- **Solution/Scope.** A Governance overview positioning Type Registry + Primitives (Live) and
  planned tools; KPI strip; Type Registry callout. Source: `governance/overview.html`.
- **Acceptance Criteria.** Reachable from Governance; links into Type Registry views.
- **Parallelism/Dependencies.** Depends on 5.1/5.2.
- **Technical Stack.** Next.js, Tailwind.

---

## 11. Epic 6 — Designer Property Binding Integration

Connects the registry to the visual editor: properties reference standard or custom types via
`$ref`, per-tenant/per-system.

```mermaid
flowchart LR
  prop["Designer · Customer.birthDate"] --> picker["Type picker\nStandard · Core · Tenant · Custom"]
  picker -->|select std/v0/types/date| ref['"$ref": "std/v0/types/date"']
  ref --> store[("class_property binding")]
  store --> resolve["resolve via Epic 3 → schema at design/runtime"]
```

| Issue | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|---|---|---|---|:---:|:---:|---|---|
| 6.1 #3474 | Type picker component | Standard/Core/Tenant/Custom tabs, search, scope chips | `type-registry`,`ui`,`schema-designer`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-ui |
| 6.2 #3475 | Property→type `$ref` binding storage | Persist & read property bindings (1.3) | `type-registry`,`ui`,`rest`,`mvp`,`roadmap-type-registry` | N | Y | M | objectified-ui, objectified-rest |
| 6.3 #3476 | Resolved-type display in Designer/Paths | Show resolved schema + validate against it | `type-registry`,`ui`,`schema-designer`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-ui |
| 6.4 #3477 | "Used by properties" dependents/impact | Reverse index: which properties use a type | `type-registry`,`rest`,`roadmap-type-registry` | Y | N | M | objectified-rest, objectified-ui |

### Issue 6.1 — Type picker component
- **Problem.** The property editor needs to pick a registry type.
- **Solution/Scope.** A picker with tabs **Standard** (primitives), **Core System Types**
  (`std/*`), **Tenant Types** (`tenant/<slug>/*`), **Custom · Imported**; search; scope chips;
  shows the resulting `$ref`. Honors visibility (core to all, tenant private). Source:
  `governance/property-binding.html`, `types/property-binding.html`.
- **Acceptance Criteria.** Selecting `std/v0/types/date` yields `$ref: std/v0/types/date`; tenant
  types only appear for their tenant.
- **Parallelism/Dependencies.** Depends on 2.6; parallel with 6.3.
- **Technical Stack.** Next.js, Tailwind, Radix.

### Issue 6.2 — Property→type `$ref` binding storage
- **Problem.** A bound property must persist its type reference.
- **Solution/Scope.** Write/read the property↔type binding (1.3), storing the `$ref` + resolved
  target on the `objectified-db` `class_property` (or the binding link). Source:
  `governance/property-binding.html` (binding preview).
- **Acceptance Criteria.** Binding persists and reloads; resolves via Epic 3.
- **Parallelism/Dependencies.** Depends on 1.3, 3.1, 6.1; blocks 6.3.
- **Technical Stack.** Next.js, FastAPI, PostgreSQL.

### Issue 6.3 — Resolved-type display in Designer/Paths
- **Problem.** The Designer must render the resolved type and validate values against it.
- **Solution/Scope.** Resolve a property's `$ref` to its effective schema and display it (type,
  format, constraints); use it for client-side validation/preview. Source: property-binding +
  type-detail mockups.
- **Acceptance Criteria.** A bound property shows its resolved type; an example value validates.
- **Parallelism/Dependencies.** Depends on 6.2, 3.1; parallel with 6.1.
- **Technical Stack.** Next.js, 2020-12 validation.

### Issue 6.4 — "Used by properties" dependents/impact — V2
- **Problem.** Type owners need to see/assess impact before changing a type.
- **Solution/Scope.** Reverse index of properties/types referencing a type; surface on type
  detail ("used by N properties"). Source: type-detail mockups (dependents/used-in).
- **Acceptance Criteria.** Type detail lists dependents accurately across tenants (scope-aware).
- **Parallelism/Dependencies.** Depends on 6.2.
- **Technical Stack.** FastAPI, SQL, Next.js.

---

## 12. Epic 7 — Scopes, Governance & Publishing

Governance controls around the registry: entitlements, publish gates, promotion, audit.

| Issue | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|---|---|---|---|:---:|:---:|---|---|
| 7.1 #3478 | Entitlement & feature gating | Gate Type Registry behind tenant entitlement | `type-registry`,`governance`,`rest`,`ui`,`mvp`,`roadmap-type-registry` | Y | Y | S | objectified-rest, objectified-ui |
| 7.2 #3479 | Type publishing & validation gate | Validate on save; block publish on errors | `type-registry`,`governance`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | M | objectified-rest |
| 7.3 #3480 | Promote tenant type → core (CAB) | Governed promotion of a vetted tenant type to `std/*` | `type-registry`,`governance`,`rest`,`ui`,`roadmap-type-registry` | Y | N | M | objectified-rest, objectified-ui |
| 7.4 #3481 | Registry audit log | Record create/update/import/publish/bind events | `type-registry`,`governance`,`rest`,`mvp`,`roadmap-type-registry` | Y | Y | S | objectified-rest |
| 7.5 #3482 | Version roots & deprecation lifecycle | Manage `v0`/`v1` roots; deprecate/sunset types | `type-registry`,`versions`,`governance`,`roadmap-type-registry` | Y | N | M | objectified-rest, objectified-ui |

### Issue 7.1 — Entitlement & feature gating
- **Solution/Scope.** Add a `type-registry` entitlement; gate nav, routes, and API. Source:
  `governance/README.md`.
- **Acceptance Criteria.** Non-entitled tenants cannot see/reach the feature; entitled can.
- **Parallelism/Dependencies.** Parallel; soft-blocks 5.1 visibility.
- **Technical Stack.** FastAPI entitlements, Next.js checks.

### Issue 7.2 — Type publishing & validation gate
- **Solution/Scope.** Validate on save (2020-12); block publish on validation errors per Settings
  policy. Source: `governance/type-settings.html` (Validation & publishing).
- **Acceptance Criteria.** Invalid types cannot be published when the gate is on.
- **Parallelism/Dependencies.** Depends on 2.3; relates to 5.7.
- **Technical Stack.** FastAPI.

### Issue 7.3 — Promote tenant type → core (CAB) — V2
- **Solution/Scope.** Governed workflow to promote a vetted tenant type into `std/*` (visible to
  all tenants), with request + platform-admin approval; aligns with governance issues #722/#724.
  Source: `governance/type-namespaces.html` (promote-to-core).
- **Acceptance Criteria.** A promotion request requires approval; on approval the type moves to a
  system namespace and becomes visible to all tenants.
- **Parallelism/Dependencies.** Depends on 2.2/2.4, 7.4.
- **Technical Stack.** FastAPI, Next.js.

### Issue 7.4 — Registry audit log
- **Solution/Scope.** Append-only audit of registry events (create/update/import/publish/bind/
  promote), with actor + timestamp; reuse existing audit infra where available.
- **Acceptance Criteria.** Each governed action writes an audit record; queryable per tenant.
- **Parallelism/Dependencies.** Parallel; consumed by 7.3.
- **Technical Stack.** FastAPI, PostgreSQL.

### Issue 7.5 — Version roots & deprecation lifecycle — V2
- **Solution/Scope.** Manage version roots (`v0` stable, `v1` draft) and type deprecation/sunset;
  aligns with `versions`/governance lifecycle (#739/#748). Source: `governance/type-namespaces.html`
  (version roots), type-detail (deprecate action).
- **Acceptance Criteria.** A type can be deprecated with a sunset date; draft roots are managed
  separately from stable.
- **Parallelism/Dependencies.** Depends on 2.2/2.3.
- **Technical Stack.** FastAPI, Next.js.

---

## 13. MVP vs V2 Summary

**MVP issues (open):** 1.1–1.4, 2.1–2.5, 3.1, 3.2, 3.4, 4.1–4.5, 5.2–5.7, 6.1–6.3, 7.1, 7.2, 7.4.

**Closed duplicates (shipped):** 2.6 (#3455 UI proxy), 5.1 (#3466 nav entry).

**V2 issues:** 3.3, 4.6, 5.8, 6.4, 7.3, 7.5.

---

## 14. Work Order (sequencing)

```mermaid
flowchart TB
  subgraph W1[Wave 1 — Foundation]
    A11[1.1 DB provision]:::m --> A12[1.2 schema]:::m --> A13[1.3 import/bind tables]:::m
    A12 --> A14[1.4 seed std/v0]:::m
  end
  subgraph W2[Wave 2 — Service + Resolver]
    B21[2.1 service]:::m --> B22[2.2 namespaces]:::m --> B23[2.3 types+validate]:::m
    B23 --> B24[2.4 scope]:::m --> B25[2.5 stats]:::m --> B26[2.6 proxy/client]:::m
    B23 --> C31[3.1 resolve]:::m --> C32[3.2 unresolved]:::m --> C34[3.4 resolver API]:::m
  end
  subgraph W3[Wave 3 — Import + UI + Binding]
    D41[4.1 pipeline]:::m --> D42[4.2 JSON Schema]:::m & D43[4.3 bundle]:::m --> D44[4.4 rewrite]:::m --> D45[4.5 review]:::m
    E51[5.1 nav]:::m --> E52[5.2 overview]:::m & E53[5.3 detail]:::m & E54[5.4 import UI]:::m & E55[5.5 resolver UI]:::m & E56[5.6 namespaces UI]:::m & E57[5.7 settings UI]:::m
    F61[6.1 picker]:::m --> F62[6.2 binding]:::m --> F63[6.3 resolved display]:::m
    G71[7.1 gating]:::m & G72[7.2 publish gate]:::m & G74[7.4 audit]:::m
  end
  subgraph W4[Wave 4 — V2]
    V[3.3 circular · 4.6 OpenAPI · 5.8 gov overview · 6.4 dependents · 7.3 promote-to-core · 7.5 version roots]:::v
  end
  W1 --> W2 --> W3 --> W4
  classDef m fill:#ddf7e0,stroke:#2f9e44;
  classDef v fill:#eee,stroke:#999,stroke-dasharray:4;
```

1. **Wave 1 — Foundation (Epic 1).** Consolidate the registry into `objectified-db` / remove the
   separate DB (1.1) → extend `odb.primitives` (1.2) → import provenance + property binding (1.3)
   + seed `std/v0` core system primitives (1.4).
2. **Wave 2 — Service + Resolver (Epics 2 & 3).** Service (2.1) → namespaces (2.2) → types +
   validation (2.3) → scope (2.4) → stats (2.5) → proxy/client (2.6); resolver
   (3.1→3.2→3.4) in parallel once 2.3 lands.
3. **Wave 3 — Import + UI + Binding (Epics 4, 5, 6, 7-core).** Import pipeline + parsers + rewrite
   + review (4.1→4.2/4.3→4.4→4.5); Governance UI (5.1 then 5.2–5.7 in parallel); Designer
   binding (6.1→6.2→6.3); gating/publish/audit (7.1/7.2/7.4). **MVP complete.**
4. **Wave 4 — V2.** Circular detection (3.3), OpenAPI import (4.6), Governance overview (5.8),
   dependents/impact (6.4), promote-to-core (7.3), version roots/deprecation (7.5).

---

## 15. Issue Count & Naming

This roadmap defines **37 issues** across **7 epics** (29 MVP open + 2 closed duplicates + 6 V2). Issues follow
`Primitives: [<epic#.issue#>] <title>`, e.g.:

- `Primitives: [1.1] Consolidate registry into objectified-db (remove separate DB)`
- `Primitives: [3.1] Relative $ref resolution against import-source base`
- `Primitives: [4.3] Type-definition bundle importer`
- `Primitives: [6.1] Type picker component (Standard/Core/Tenant/Custom)`

Each epic should also get an umbrella `epic`-labeled issue. New labels to create:
`type-registry`, `types-db`, `roadmap-type-registry` (reuse `governance`, `registry`, `rest`,
`ui`, `import`, `versions`, `schema-designer`). Cross-link related existing issues per §4.

## 16. Created GitHub Issues (status: ✅ created)

All issues and the new labels (`type-registry`, `types-db`, `roadmap-type-registry`) were
created in `objectified-project/objectified`. Each child issue is a GitHub **sub-issue** of its
epic.

**Epics:** #3439 (E1) · #3440 (E2) · #3441 (E3) · #3442 (E4) · #3443 (E5) · #3444 (E6) · #3445 (E7).

**Renamed:** All child issues #3446–#3481 use the `Primitives:` prefix (formerly `Atlas:`).

**Closed as duplicates of shipped Primitives:** #3455 (UI proxy), #3466 (nav entry).

| Epic | Child issues (issue# → roadmap id) |
|---|---|
| #3439 E1 | #3446 (1.1) · #3447 (1.2) · #3448 (1.3) · #3449 (1.4) |
| #3440 E2 | #3450 (2.1) · #3451 (2.2) · #3452 (2.3) · #3453 (2.4) · #3454 (2.5) · ~~#3455 (2.6)~~ ✅ closed |
| #3441 E3 | #3456 (3.1) · #3457 (3.2) · #3458 (3.3) · #3459 (3.4) |
| #3442 E4 | #3460 (4.1) · #3461 (4.2) · #3462 (4.3) · #3463 (4.4) · #3464 (4.5) · #3465 (4.6) |
| #3443 E5 | ~~#3466 (5.1)~~ ✅ closed · #3467 (5.2) · #3468 (5.3) · #3469 (5.4) · #3470 (5.5) · #3471 (5.6) · #3472 (5.7) · #3473 (5.8) |
| #3444 E6 | #3474 (6.1) · #3475 (6.2) · #3476 (6.3) · #3477 (6.4) |
| #3445 E7 | #3478 (7.1) · #3479 (7.2) · #3480 (7.3) · #3481 (7.4) · #3482 (7.5) |

**Totals:** 7 epics + 37 child issues = **44 GitHub issues** (29 MVP open, 2 closed duplicates, 6 V2). Related existing
issues cross-linked per §4 (#624–636, #719–728, #2299/#2305/#2316, #739/#748).

> **Next step:** validate this document, then run `/create-issues docs/ROADMAP_TYPE_REGISTRY_GOVERNANCE.md`
> to create the labels + issues and back-fill issue numbers here.
