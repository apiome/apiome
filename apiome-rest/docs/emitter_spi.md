# Emitter SPI (MFI-22.1)

> **Status:** SPI + reference implementation — `src/app/emitter.py`,
> `src/app/openapi_emitter.py`, `src/app/openapi_validator.py`
> **Issue:** [#4002](https://github.com/objectified-project/objectified/issues/4002) ·
> **Epic:** MFI-EPIC-22 (#4000) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The **Emitter SPI** is the inverse of the [Normalizer SPI](./normalizer_spi.md).
Where a normalizer turns a parsed source document *into* the paradigm-agnostic
[canonical model](./canonical_model.md) (`CanonicalApi`), an emitter turns a
`CanonicalApi` back *out* to a concrete API-description format. **Conversion**
(catalog → OpenAPI, MFI-EPIC-22) is exactly *normalize one format → emit another*.

```
 normalize (MFI-2.3)              emit (this SPI)                 validate
 parsed tree ──────────▶ CanonicalApi ──────────▶ OpenAPI 3.1 doc ─────▶ valid?
              (Normalizer)          (Emitter)             (openapi_validator)
```

An emitter is **pure**: given the same model it returns an equal result, performs
no I/O, and emits every collection in a deterministic order so re-conversion is
byte-stable.

## The contract

```python
class Emitter(ABC):
    format: ClassVar[str]            # registry key, e.g. "openapi-3.1"
    paradigm: ClassVar[ApiParadigm]  # the paradigm it primarily targets

    @abstractmethod
    def emit(self, api: CanonicalApi) -> EmitResult: ...
```

A concrete emitter must:

1. **Be deterministic and side-effect free** — same `api` → equal `EmitResult`,
   no I/O. Order every emitted collection by a stable key/name.
2. **Emit a schema-valid document** — the reference `OpenApiEmitter` output passes
   `openapi_validator.validate_openapi_document` (the OpenAPI 3.1 meta-schema).
3. **Record provenance** — tag every emitted value `source` (came from the model),
   `inferred` (derived from the model's structure), or `default` (a system
   fallback), so the fidelity analyzer (MFI-22.3) can show what the conversion
   added.

### Registration & lookup

```python
class MyFormatEmitter(Emitter, register=True):   # auto-registers on definition
    format = "myformat-1"
    paradigm = ApiParadigm.REST
    def emit(self, api): ...
```

```python
get_emitter("openapi-3.1")     # -> OpenApiEmitter
available_emit_formats()       # -> ["openapi-3.1", ...]
```

## Provenance

Every emitted value gets a `ProvenanceRecord(pointer, provenance, detail)` where
`pointer` is an RFC-6901 JSON Pointer into the emitted document:

| Provenance | Meaning | Example |
|------------|---------|---------|
| `source`   | copied straight from a populated canonical field | `/info/title` from `identity`/`title` |
| `inferred` | derived from the model's structure | a `POST` binding synthesized for a gRPC method; a synthesized `operationId` |
| `default`  | system fallback with no basis in the model | the `openapi` version string; an empty response `description` |

`ProvenanceTracker.records()` returns the notes sorted by pointer, so the
provenance list is deterministic too. `EmitResult` pairs the emitted `document`
with its `provenance`.

## Schema emission

`SchemaEmitter` is the exact inverse of the normalizer's `SchemaCoercer`. Because
OpenAPI 3.1 schemas *are* JSON Schema (draft 2020-12), the fragments it produces
are valid at both layers:

* `type_ref(TypeRef)` — a use site (field/parameter/payload type): list →
  `{"type": "array", "items": …}`, primitive → `{"type": …}`, named type →
  `{"$ref": "#/components/schemas/…"}`. Member *optionality* (`nullable`) is
  expressed by the caller through `required` membership — matching the normalizer,
  which sets `nullable=True` for every optional member — rather than a spurious
  `"null"` type.
* `named_schema(Type)` — a component schema: `RECORD` → object + `properties` +
  `required` (the non-nullable fields), `ENUM` → typed `enum` (base type recovered
  from the member values), `UNION` → `oneOf`, `MAP` → object + `additionalProperties`,
  `ALIAS` → the aliased ref's schema, `SCALAR` → a constrained leaf.

## Reference implementation: `OpenApiEmitter`

`OpenApiEmitter` (format `openapi-3.1`, paradigm `REST`) maps:

| Canonical | OpenAPI 3.1 |
|-----------|-------------|
| `identity` / `title` / `version` / `description` | `info` (title + version required — defaulted when absent) |
| `Server` (+ variables) | `servers` |
| `Operation` (grouped by route) | `paths[path][method]` (+ `operationId`/`summary`/`tags`/`deprecated`) |
| `Parameter` | `parameters` (path params forced `required`) |
| `Message` (REQUEST) | `requestBody` (content per media type) |
| `Message` (RESPONSE/ERROR) | `responses[status]` (description required — defaulted) |
| `Type` | `components.schemas` (via `SchemaEmitter`) |

Non-REST models are mapped onto the OpenAPI vocabulary by a per-paradigm
**projection strategy** — see [Paradigm projection strategies](./projection_strategies.md)
(MFI-22.2). The emitter selects a strategy from the model's `ApiParadigm` and consults
it, per operation, for the `(method, path)` binding (or to learn the operation has no
OpenAPI representation), gathering any `x-` extensions and document-level notes.

On REST input the emitter is a **fixed point** of the reference normalizer:
`normalize(emit(normalize(doc))) == normalize(doc)`.

## Losses (MFI-22.2)

Where a provenance note annotates a value that *was* emitted, a `Loss` records a
source construct the projection could **not** carry faithfully. `EmitResult.losses`
carries them alongside the provenance:

| LossKind | Meaning | Example |
|----------|---------|---------|
| `inferred` | emitted, but only via a synthesized/derived representation | a `POST /{Service}/{Method}` synthesized for a gRPC method |
| `n/a` | no OpenAPI representation at all — surfaced here, not silently dropped | a GraphQL subscription; gRPC streaming; an event pub/sub action |

The `n/a` case is why losses are a channel separate from provenance: an `n/a`
construct produces no emitted value, so no JSON Pointer can describe it. `LossTracker`
returns the losses in a deterministic order.
