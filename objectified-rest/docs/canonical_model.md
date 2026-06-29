# Canonical API Model (MFI-2.1)

> **Status:** Design + reference implementation — `src/app/canonical_model.py`
> **Issue:** [#3738](https://github.com/objectified-project/objectified/issues/3738) ·
> **Epic:** MFI-EPIC-2 (#3717) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The **canonical model** is one paradigm-agnostic shape that every importable API
description format normalizes into, so that versioning, fingerprinting, diff,
lint, and browse are written **once** and work uniformly across REST, RPC,
event-driven, graph, and data-schema formats.

A normalizer (MFI-2.3) turns a parsed source into a `CanonicalApi`; the
persistence tables (MFI-2.2) store that `CanonicalApi` as JSONB per artifact
version; everything downstream operates on the canonical shape rather than the
original format.

## Why a canonical model

> Every format wants the same shape of treatment — *parse → resolve → normalize
> → fingerprint → diff → lint/score → catalog/browse.* Only the parser, the
> normalizer, the lint rule-pack, and the breaking-change rules are
> format-specific. (ROADMAP_MULTI_FORMAT_IMPORT §1)

So the canonical model is the contract that lets the bulk of the pipeline be
built once. Two properties make it durable across formats we have not written
yet:

- **Stable keys** — every entity carries a `key` so diffs line up by identity,
  not position (see [Stable key grammar](#stable-key-grammar)).
- **Fidelity escape hatches** — every entity has an `extras` bag, and the
  artifact has a top-level `raw` bag, so normalization is lossy-but-never-
  destructive: whatever the canonical fields cannot hold is preserved verbatim.

## Shape

```
CanonicalApi  (schema_version, paradigm, format, protocol, identity, version, servers)
  ├─ services[]            named groups of operations
  │    └─ operations[]     kind (request_response / query / mutation / subscription /
  │         │              publish / subscribe / one_way) + streaming + verb/route
  │         ├─ parameters[]   path / query / header / cookie inputs (REST-ish)
  │         └─ messages[]     request / response / error / event payloads
  ├─ channels[]            event addresses + protocol bindings (event-driven)
  └─ types[]               record / enum / union / scalar / alias / map
       └─ fields[]         typed (TypeRef), nullable, defaulted, constrained
  + raw                    native AST for full-fidelity round-trip
```

### Entities

| Entity | Purpose | Key paradigm mapping |
|---|---|---|
| `CanonicalApi` | The artifact: one API at one version. | the document/schema/service set |
| `ApiIdentity` | Version-independent identity (`name`, `namespace`, `id`). | OAS `info.title`, protobuf package, GraphQL schema |
| `Server` | A host/endpoint (URL template + variables). | OAS `servers`, AsyncAPI `servers` |
| `Service` | A named group of operations. | OAS tag, gRPC/Smithy service, GraphQL root type |
| `Operation` | A callable/subscribable unit. | path+method, RPC method, GraphQL field, AsyncAPI op |
| `Parameter` | Non-body input (path/query/header/cookie). | OAS parameters, GraphQL args |
| `Message` | An in/out payload (+ headers, status, media type). | request body / response, RPC msg, event payload |
| `Channel` | An event address + bindings. | AsyncAPI channel, Kafka/AMQP topic |
| `Type` | A named type (record/enum/union/scalar/alias/map). | schema, message, GraphQL type, Avro record |
| `CanonicalField` | A member of a record type. | object property, protobuf field, Avro field |
| `TypeRef` | A type *use* with nullability + list nesting. | GraphQL `[T!]!`, `nullable`, repeated |
| `EnumValue` | One enum member. | enum value (with wire `value`) |
| `Constraints` | Validation facets (JSON-Schema vocabulary). | `minimum`/`pattern`/`format`/… |

### Operation kind vs. streaming

`OperationKind` captures *message-exchange semantics*; `StreamingMode` captures
the orthogonal *streaming cardinality*. Together they describe every paradigm's
operation shape without a combinatorial enum:

| Source operation | `kind` | `streaming` |
|---|---|---|
| REST `GET /pets/{id}` | `request_response` | `none` |
| gRPC unary | `request_response` | `none` |
| gRPC server-streaming | `request_response` | `server` |
| gRPC bidi-streaming | `request_response` | `bidirectional` |
| GraphQL query/mutation | `query` / `mutation` | `none` |
| GraphQL subscription | `subscription` | `server` |
| AsyncAPI send / receive | `publish` / `subscribe` | `none` |
| Fire-and-forget RPC | `one_way` | `none` |

### Type references, nullability, and lists

`TypeRef` models a type *at a use site*. A leaf sets `name`; a list wraps an
inner `item` (which may itself be a list). `nullable` applies to **that level
only**, which makes GraphQL wrapper fidelity exact:

| GraphQL | `TypeRef` |
|---|---|
| `String` | `TypeRef(name="String")` |
| `String!` | `TypeRef(name="String", nullable=False)` |
| `[String!]` | `TypeRef(item=TypeRef(name="String", nullable=False))` |
| `[String!]!` | `TypeRef(item=TypeRef(name="String", nullable=False), nullable=False)` |

## Stable key grammar

Every entity's `key` is assigned deterministically by the normalizer from the
source so two versions diff by identity. The grammar mirrors each paradigm's own
coordinate system:

| Entity | REST / OpenAPI | gRPC / Protobuf | GraphQL | Avro / data-schema |
|---|---|---|---|---|
| `Service` | tag name (`pets`) | `pkg.Service` | root type (`Query`) | — |
| `Operation` | `GET /pets/{id}` | `pkg.Service.Method` | `Query.user` (coordinate) | — |
| `Type` | schema name (`Pet`) | `pkg.Message` | type name (`User`) | `ns.RecordName` |
| `CanonicalField` | `Pet.name` | `pkg.Message.field` (+ `field_number`) | `User.email` (coordinate) | `ns.Record.field` |
| `Parameter` | `GET /pets/{id}#path.id` | — | `Query.user#arg.id` | — |
| `Message` | `GET /pets/{id}#response.200` | `pkg.Service.Method#request` | `Query.user#response` | — |
| `Channel` | — | — | — | (AsyncAPI) `user/{userId}/signedup` |

protobuf/Thrift additionally carry `CanonicalField.field_number` so a rename is a
*modify*, not an *add + remove*, in a diff.

## Persistence round-trip

The model is plain Pydantic v2, so it serializes to/from JSONB losslessly. The
persistence DAO (MFI-2.2) does the equivalent of:

```python
dumped = api.model_dump()                 # JSONB column in
reloaded = CanonicalApi.model_validate(   # dict out
    json.loads(json.dumps(dumped))
)
assert reloaded == api                    # lossless
```

`schema_version` (`CANONICAL_API_SCHEMA_VERSION`) is the envelope version. When
the canonical shape changes, bump it and register a single-step upgrader exactly
as `models.py` does for `RepositoryImportSpec`, so older JSONB rows migrate
forward on read.

## Paradigm coverage

`tests/test_canonical_model.py` builds one sample per paradigm, asserts its
load-bearing fields survive normalization, and round-trips each through JSON:

| Paradigm | Sample | Load-bearing fields asserted |
|---|---|---|
| REST | OpenAPI `GET /pets/{id}` | verb/route, path param, `200` response → `Pet` |
| RPC | gRPC `RouteChat` | `streaming=bidirectional`, protobuf field numbers |
| Event | AsyncAPI `onUserSignedUp` | `kind=publish`, `channel_ref`, kafka bindings |
| Graph | GraphQL `Query.user` | `[Post!]!` wrapper nullability, enum, nullable return |
| Data schema | Avro `Card` | field default, `["null","string"]` union, `raw` AST |

These mirror MFI-2.4's fidelity tests; gaps found by a future format are fixed by
extending the model here (and bumping `CANONICAL_API_SCHEMA_VERSION` if the shape
changes).
