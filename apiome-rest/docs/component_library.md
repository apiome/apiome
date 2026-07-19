# Operational component library — DCW-3.1 (private-suite#2353)

The tenant-scoped library of reusable **operational** OpenAPI components:
parameters, headers, request bodies, responses, and security bundles, plus
**schema entries that pin existing Type Registry revisions** (the Type
Registry stays authoritative for schemas — the library never becomes a second
schema registry).

## Model

| Table | Purpose |
|---|---|
| `apiome.operational_components` | Stable component identity: tenant, name, kind, owner. Live names are unique per `(tenant, kind)`. |
| `apiome.operational_component_revisions` | Semver revisions (`MAJOR.MINOR.PATCH`, unique per component) with the minimal MVP lifecycle: `draft` → `published`. Published revisions are immutable. |
| `apiome.version_component_pins` | A draft project revision pins one **published** library revision. `ON DELETE RESTRICT` backstops the in-use rule at the database level. |
| `apiome.component_library_audit` | Append-only ledger written in the same transaction as each mutation. |

### Lifecycle rules (enforced in one transaction, rechecked under lock)

- **Draft → publish** requires `types:publish`; publishing must move the
  component's published head strictly forward (no unsafe downgrades —
  `409 REVISION_DOWNGRADE` names the current head). Republishing is an
  idempotent no-op.
- **Published revisions are immutable**: payload updates and deletes answer
  `409 PUBLISHED_IMMUTABLE`.
- **In-use protection**: a component (or revision) with live pins cannot be
  deleted (`409 COMPONENT_IN_USE` / `409 REVISION_IN_USE`).
- **Pins target drafts**: pin mutations on a published project revision
  answer `409 PUBLISHED_VERSION`; only published library revisions can be
  pinned (`409 REVISION_NOT_PUBLISHED`).
- **Tenant isolation**: every statement is tenant-scoped; cross-tenant reads
  and writes answer **404** (never 403) so existence cannot be probed.

### Schema-kind components

A schema revision carries `schema_primitive_id` — the pinned
`apiome.primitives` row — and **snapshots** that entry's JSON Schema as its
canonical payload at draft/update time. Publishing freezes the snapshot, so a
later Type Registry head change never mutates a project pinned to an older
revision.

## Materialization

`app/component_library.py::materialize_pinned_components` projects a
version's live pins into the generated document's standard local
`components` sections:

| Kind | Section |
|---|---|
| parameter | `components.parameters` |
| header | `components.headers` |
| requestBody | `components.requestBodies` |
| response | `components.responses` |
| securityBundle | `components.securitySchemes` (one entry per scheme) |
| schema | `components.schemas` |

- **Deterministic**: rows are processed in a stable order (section, requested
  name, semver, revision id); the same pins always produce the same document.
- **Collision-safe**: a local component is never overwritten. A taken name
  deterministically becomes `Name_2`, `Name_3`, …; the
  `GET …/materialization` preview reports every rename before export.
- **Portable**: materialized entries are plain local components with standard
  `$ref` values — the exported document resolves without Apiome services.
- **Provenance**: each materialized object optionally carries
  `x-apiome-origin` (`library`, `revision`, `componentId`, `revisionId`).
  Re-import retains it when present; stripping it leaves a valid document.

`generate_openapi_spec` loads a version's live pins automatically (or accepts
injected `component_pin_rows`, mirroring the security-scheme/server rows), so
browse, preservation, source review, diff, and export all see the same
materialized document. With no pins the generated document is unchanged.

## Routes

Prefix `/v1/component-library/{tenant_slug}`; reads need any authenticated
tenant member, library writes need `types:create|edit|publish|delete`, pin
writes need `versions:edit`.

```
GET    /components?kind=                      list (+ head revision summary)
POST   /components                            create + initial draft revision
GET    /components/{id}                       detail with revisions
DELETE /components/{id}                       soft delete (blocked while pinned)
POST   /components/{id}/revisions             new draft revision
PUT    /components/{id}/revisions/{rid}       update draft payload
DELETE /components/{id}/revisions/{rid}       delete draft (published/pinned: 409)
POST   /components/{id}/revisions/{rid}/publish
GET    /projects/{pid}/versions/{vid}/pins    list live pins
POST   /projects/{pid}/versions/{vid}/pins    pin a published revision
DELETE /projects/{pid}/versions/{vid}/pins/{pin}
GET    /projects/{pid}/versions/{vid}/materialization?includeOrigin=
```

## Tests

- `tests/test_component_library.py` — validation, semver, digests, and the
  materializer's determinism/collision/origin rules.
- `tests/test_component_library_db.py` — scripted-connection transaction
  proofs: in-tx rechecks, single commit with audit, zero-write rollbacks,
  idempotent republish, Type Registry snapshotting.
- `tests/test_component_library_routes.py` — authorization matrix
  (403 permission denials, 404 scope misses), lifecycle conflicts, and the
  materialization preview.
