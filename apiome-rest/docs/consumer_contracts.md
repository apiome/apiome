# Consumer contract registry — CTG-4.1 (#4479)

"Breaking" is relative. Removing a field nobody reads breaks nobody; narrowing a type one
service depends on breaks exactly that service. The CTG-1.1 classifier grades a change against
the *whole* published surface because nothing tells it who uses what — which over-warns the
provider ("47 breaking changes") and tells the consumer nothing at all.

This registry is the missing half: a **consumer** (a named client of a project) and a
**contract** (one immutable revision of the operations and fields that consumer actually uses).

| Module | What it owns |
|---|---|
| `app.consumer_contract` | The vocabulary. Pure: models, stable refusal codes, row adapters. |
| `app.consumer_surface` | `SpecIndex` — resolves a declared surface against a stored OpenAPI document, and enumerates what *could* be declared. |
| `app.pact_contract_import` | Reads a Pact document (specification 1.x–4.x) into a surface. |
| `app.consumer_contract_store` | The only place a consumer or contract is read or written. |
| `app.consumer_contract_routes` | The HTTP surface. |
| apiome-db `V251` | `consumer` + `consumer_contract`, and the `consumer_contracts` RBAC resource. |

## The pointer contract

Every operation and field carries a JSON Pointer written **exactly the way
`app.change_taxonomy_enum` writes one**. That is the whole point: CTG-4.2 intersects a classified
change with a declared surface by comparing pointers, not by re-deriving what a change touched.

A field carries **two** pointers:

* `pointer` — operation-anchored, e.g.
  `/paths/~1pets/get/responses/200/content/application~1json/schema/properties/name`. This is the
  field's identity inside the contract.
* `schema_pointer` — where the node actually lives. Equal to `pointer` for an inline schema; a
  `/components/schemas/Pet/properties/name` pointer when the field was reached through a `$ref`.

Both are needed because the classifier reports an inline schema change under `/paths/…` and a
component change under `/components/schemas/…`, and which one it emits depends on how the author
wrote the document — not on what the consumer uses. A contract that recorded only one of the two
would miss half the changes that break it.

`V251.surface_pointers` is the flattened, GIN-indexed set of both, which is what makes the CTG-4.2
lookup an array operation:

```python
from app.consumer_contract_store import contracts_affected_by

affected = contracts_affected_by(tenant_id, project_id, [c.pointer for c in classified.changes])
```

The overlap is tested **both ways** (`starts_with(changed, declared) OR starts_with(declared,
changed)`), because a change and a declared field are not always at the same depth: a change at
`/components/schemas/Pet` touches a field at `…/Pet/properties/name`, and a change at
`…/properties/name/type` touches a field at `…/properties/name`.

## Two ingestion paths, one stored shape

**Pact import.** Each interaction's method and concrete path (`/pets/42`) resolves onto the
project's path *template* (`/pets/{petId}`), through a declared server base path if there is one.
The keys of its example request and response bodies become declared fields, resolved at the
interaction's own status code; `request.query` becomes parameter usage (v2's query string and
v3+'s query object are both read). Array levels are transparent — `{"items": [{"id": 1}]}` yields
`items` and `items.id`, never `items.0.id`.

`matchingRules`, `providerStates` and generators are deliberately **not** read: they say how a
value is compared, not which fields are used.

**The picker.** The UI submits operations and fields *the way a person picks them* — method, path
template, dotted data path — and the server resolves each. A client cannot supply its own
pointers (the request model forbids the key), so a stored surface always describes something the
specification actually contains.

## Nothing is dropped

Every interaction, and every field inside one, either lands in the surface or produces an
`UnresolvedInteraction` with a stable reason: `operation-not-found`, `method-not-declared`,
`status-not-declared`, `media-type-not-declared`, `field-not-found`, `parameter-not-declared`,
`interaction-not-http`, `interaction-malformed`. These are **stored on the revision** and returned
to the caller. An import whose interactions all name retired endpoints stores a visibly empty
surface with N unresolved entries rather than succeeding quietly.

A field that does not resolve leaves its operation in place: "you call this operation but that
field is gone" is more useful than discarding the call.

## Revisions

`record_contract` always writes revision N+1 and demotes the previous current revision **in one
transaction** — V251's partial unique index allows exactly one current revision per consumer, so
a demote that committed without its insert would leave a consumer with a history and no current
contract. Nothing here mutates a stored surface, which is what makes "what did this consumer claim
it used when we published 2.0.0" answerable after the fact.

Retiring a consumer is a soft delete: a published version's per-consumer verdict has to stay
explicable after the consumer is decommissioned, and the handle becomes free again.

## Endpoints

All under `/v1/tenants/{tenant_slug}/projects/{project_ref}`; `project_ref` is a slug or an id,
and `consumer_ref` is a handle or an id.

| Method | Path | Permission |
|---|---|---|
| `GET` | `/consumers` | `consumer_contracts:view` |
| `POST` | `/consumers` | `consumer_contracts:create` |
| `GET` | `/consumers/{consumer_ref}` | `consumer_contracts:view` |
| `PATCH` | `/consumers/{consumer_ref}` | `consumer_contracts:edit` |
| `DELETE` | `/consumers/{consumer_ref}` | `consumer_contracts:delete` |
| `PUT` | `/consumers/{consumer_ref}/contract` | `consumer_contracts:edit` |
| `GET` | `/consumers/{consumer_ref}/contract` | `consumer_contracts:view` |
| `GET` | `/consumers/{consumer_ref}/contract-revisions` | `consumer_contracts:view` |
| `GET` | `/consumer-surface` | `consumer_contracts:view` |
| `POST` | `/consumer-pact-imports` | `consumer_contracts:create` |

The catalogue and the import are **sibling paths**, not sub-paths of `consumers`, so no word is
carved out of the consumer slug space — a consumer really can be called `surface`.

`PATCH` cannot change a handle. It is the name Pact files and CI jobs use, and renaming it would
silently orphan every reference; retire the consumer and register a new one instead.

The built-in Editor grid carries view/create/edit but **not** delete: declaring what your own
service consumes is developer work, while removing a consumer removes a signal that guards other
people's changes. Tenants with custom roles must grant `consumer_contracts:*` explicitly — the
V251 reseed rewrites built-in grids only.

## Limits

* An uploaded Pact document is capped at 10 MB (`consumer-pact-too-large`), matching the CTG-1.2
  inline-spec guard.
* Field enumeration walks at most `MAX_FIELD_DEPTH` levels and `MAX_FIELDS_PER_OPERATION` fields
  per operation; an operation whose list was cut reports `truncated: true`. A field the catalogue
  omitted can still be declared by naming it explicitly.
* A body offered only as XML or as an opaque binary has no addressable fields and contributes
  none, rather than pretending otherwise.
