# Governance › Type Registry (Atlas) — in-app integration mockups

These mockups show the JSON Schema **2020-12** type registry (codename **Atlas**) rendered
**inside the real apiome-ui application**, under **Control Panel → Governance**, so a
roadmap can be scoped against the actual app surfaces. They reuse the genuine app chrome:
the `TopHeader` top bar and the `DashboardSideNav` 280px left navigation (indigo accent).

> Standalone, brand-styled (teal/awwwards) version of the same product:
> `../types/index.html`. This `governance/` set is the **app-accurate** rendering.

## Where it lives in the app

The Control Panel left nav (`DashboardSideNav.tsx`) already has a **Governance** section
(today it contains only **Primitives**). The Type Registry slots in **right next to
Primitives**:

```
Control Panel (DashboardSideNav)
├── Overview · Identity · Workspace · Specifications
└── Governance
    ├── Primitives            (exists today)
    ├── Type Registry         ← NEW (this feature)
    └── Governance overview   ← NEW (area landing, optional)
```

Within the Type Registry page, sub-views are **in-page tabs** (not extra sidebar items),
matching how other Control Panel pages work: **Overview · Import · Reference Resolver ·
Namespaces & Scopes · Settings**. Type detail and the Designer property picker are
drill-downs reached from those views.

## Screens (8)

| File | App location | Purpose |
|---|---|---|
| `overview.html` | Control Panel › Governance | Governance area landing; positions Type Registry + Primitives (Live) and planned tools (Schema Registry, Policies/Linting, Compatibility, Approvals) |
| `type-registry.html` | Governance › Type Registry · Overview | KPIs, type collections by scope, recent activity, relative-`$ref` resolution base |
| `type-detail.html` | Governance › Type Registry › `money` | A single type (`std/v0/types/money`): JSON Schema, resolved `$ref`s, dependents, metadata, base chain |
| `type-import.html` | Governance › Type Registry · Import | Import wizard — JSON Schema **and** type-definition bundles (+ OpenAPI 3.1), namespace/scope target, `$ref` rewrite options |
| `type-resolver.html` | Governance › Type Registry · Reference Resolver | Relative `$ref` graph + table, resolution-base math, unresolved & circular detection |
| `type-namespaces.html` | Governance › Type Registry · Namespaces & Scopes | System root (all tenants) vs per-tenant namespaces, base URIs, version roots, scope precedence, promote-to-core |
| `type-settings.html` | Governance › Type Registry · Settings | Registry storage (extended `apiome.primitives`), default draft, `$ref` resolution policy, import defaults, validation/publishing governance |
| `property-binding.html` | Designer › property editor | Cross-app integration: bind a class property to a standard or custom registry type (resulting `$ref`) |

## Core concepts depicted

- **Single database** — the type registry lives in the existing `apiome-db` (`apiome` schema)
  by **extending the `apiome.primitives` table** (tenant-owned rows via `tenant_id`, system-wide
  rows via `is_system`/`is_public`). There is **no** separate `apiome-types-db`.
- **Scopes**: *System · core* (`std/v0/*`, `is_system`) is curated by the platform and visible
  to **all tenants**; *Tenant* (`tenant/<slug>/*`, owned by `tenant_id`) types are private to
  that tenant. A tenant type may `$ref` a core type; a core type may not `$ref` a tenant type.
- **Relative `$ref`** resolves against each type's **import-source base URL** in the API
  server. Canonical example: `std/v0/types/date` → `"$ref": "../primitives/string"`, base
  `api.apiome.app/types/std/v0/types/` → resolves to `std/v0/primitives/string`.
- **Import** accepts raw **JSON Schema 2020-12** documents (single or `$defs`-bundled),
  **Apiome type-definition bundles** (`.zip`/`.json`), and **OpenAPI 3.1** components.
- **Property binding**: the visual editor (Designer) picks a type from the registry —
  *Standard* (primitives), *Core System*, *Tenant*, or *Custom/Imported* — and the property
  stores a `$ref` to it.

## Roadmap hooks (for `/create-roadmap`)

Suggested implementation surfaces this mockup implies:

- **apiome-ui**
  - `DashboardSideNav.tsx`: add a **Governance** group item *Type Registry* (and optional
    *Governance overview*); gate by `hasTenant`.
  - Routes under `/ade/dashboard/governance/` — e.g. `governance` (overview),
    `governance/types` (registry + tabs via query/segment: import, resolver, namespaces,
    settings), `governance/types/[id]` (type detail).
  - Designer property editor: a **type picker** that reads the registry and writes a `$ref`.
  - `/api/types/*` proxy routes (JWT via `createRestAuthHeaders`) to the registry service.
- **apiome-rest** (or a dedicated service)
  - Type registry API: CRUD types/namespaces, **import** (schema + type-def + OpenAPI),
    **`$ref` resolver** (relative→absolute, unresolved/circular), coverage of bindings,
    promote-to-core (governed).
- **apiome-db** (existing database — extend `apiome.primitives`, no separate DB)
  - Extend `apiome.primitives` with: `namespace` (path; system `std/v0/*` or `tenant/<slug>/*`),
    `base_uri`, `schema_id` (`$id`), `draft`, `source` (human|imported), and `refs` JSONB
    (relative_ref, resolved_target, status resolved|unresolved|circular). Tenant vs system
    scope reuses `tenant_id` / `is_system`. Import provenance reuses existing import-history
    infra; a property↔primitive binding link (same-DB FK on `class_property`) is consumed by the
    Designer (`class_property` → `$ref`).
- **Suggested labels**: reuse `governance`, `registry`, `ui`, `rest`, `import`; add
  `type-registry` / `atlas`.

These are starting points — run `/create-roadmap` against this folder (and `../types/`) to
produce the epics/issues.
