# Emitter SPI (MFI-22.1, MFX-1.1)

> **Status:** SPI + reference implementations — `src/app/emitter.py`,
> `src/app/openapi_emitter.py`, `src/app/sample_emitter.py`,
> `src/app/openapi_validator.py`
> **Issues:** [#4002](https://github.com/apiome/apiome/issues/4002) (MFI-22.1),
> [#3834](https://github.com/apiome/apiome/issues/3834) (MFX-1.1) ·
> **Epic:** MFX-EPIC-1 (#3814) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_EXPORT.md`

The **Emitter SPI** is the inverse of the [ImportSource SPI](./import_source_spi.md)
(MFI-1.1) and the [Normalizer SPI](./normalizer_spi.md). Where a normalizer turns a
parsed source document *into* the paradigm-agnostic
[canonical model](./canonical_model.md) (`CanonicalApi`), an emitter turns a
`CanonicalApi` back *out* to a concrete API-description format. **Conversion**
(catalog → OpenAPI, MFI-EPIC-22) and **export** (MFX-EPIC-1) both hang on this seam.

```
 normalize (MFI-2.3)              emit (this SPI)                 validate
 parsed tree ──────────▶ CanonicalApi ──────────▶ target artifact ─────▶ valid?
              (Normalizer)          (Emitter)             (per-target validator)
```

An emitter is **pure**: given the same model it returns an equal result, performs
no I/O, and emits every collection in a deterministic order so re-conversion is
byte-stable.

## The contract

```python
class Emitter(ABC):
    key: ClassVar[str]               # stable target id, e.g. "openapi"
    format: ClassVar[str]            # registry key, e.g. "openapi-3.1"
    label: ClassVar[str]
    description: ClassVar[str]
    icon: ClassVar[str]              # Lucide icon name
    paradigm: ClassVar[ApiParadigm]
    multi_file: ClassVar[bool]       # single artifact vs bundle
    required_tools: ClassVar[Tuple[str, ...]]  # hard toolchain deps

    @classmethod
    def capability_profile(cls) -> CapabilityProfile: ...

    @classmethod
    def descriptor(cls) -> EmitterDescriptor: ...

    @abstractmethod
    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[EmitOptions] = None,
    ) -> EmitResult: ...
```

A concrete emitter must:

1. **Be deterministic and side-effect free** — same `api` → equal `EmitResult`,
   no I/O. Order every emitted collection by a stable key/name.
2. **Emit a schema-valid artifact** — the reference `OpenApiEmitter` output passes
   `openapi_validator.validate_openapi_document` (the OpenAPI 3.1 meta-schema).
3. **Record provenance** — tag every emitted value `source` (came from the model),
   `inferred` (derived from the model's structure), or `default` (a system
   fallback), so the fidelity analyzer (MFI-22.3 / MFX-EPIC-2) can show what the
   conversion added.
4. **Declare a static capability profile** — which canonical constructs the target
   can represent faithfully (see below).

### Registration & lookup

```python
class MyFormatEmitter(Emitter, register=True):   # auto-registers on definition
    key = "myformat"
    format = "myformat-1"
    label = "My Format"
    paradigm = ApiParadigm.REST
    def emit(self, api, *, opts=None): ...
```

```python
get_emitter("openapi-3.1")          # -> OpenApiEmitter class
get_emitter_instance("openapi-3.1") # -> OpenApiEmitter()
available_emit_formats()            # -> ["openapi-3.1", "sample-noop", ...]
describe_emit_targets()             # -> [EmitterTarget(descriptor, capability_profile), ...]
load_builtin_emitters()             # lazy built-in registration (idempotent)
```

Built-in emitters self-register on import via the `register=True` subclass flag;
`load_builtin_emitters()` imports them so a lookup works even if the caller never
imported the adapter module (mirrors `load_builtin_import_sources`).

## Export orchestration (MFX-1.3)

Live export paths resolve emitters through `app.export_service` rather than
importing concrete emitter classes:

```python
from app.export_service import emit_canonical

result = emit_canonical(api, "openapi")  # key or format — both resolve to openapi-3.1
document = result.document
```

`resolve_emit_format(target)` maps an emitter `key` or registry `format` to the
format key; `resolve_emitter(target)` returns an instance. Catalog conversion
(`app.conversion_job.preview_conversion`) is wired through this seam today.

## Emit result envelope

`EmitResult` carries:

| Field | Meaning |
|-------|---------|
| `files` | One or more `EmittedFile{path, content, media_type?}` entries, sorted by `path` |
| `media_type` | Primary bundle media type (e.g. `application/vnd.oai.openapi+json`) |
| `provenance` | Per-construct provenance notes (`ProvenanceRecord`), sorted by JSON Pointer |
| `losses` | Paradigm projection fidelity losses (`Loss`), sorted deterministically |

`EmitResult.document` is a backward-compatible view of the **first file's content**
when it is a structured `dict` (single-file JSON/YAML targets).

```python
EmitResult.from_document(openapi_dict, path="openapi.json", media_type="application/json")
```

## Capability / fidelity profile (MFX-1.1)

Each emitter declares a frozen `CapabilityProfile` — a static boolean matrix of
which **canonical constructs** the target supports **faithfully** (not merely
approximated or synthesized). The fidelity engine (MFX-EPIC-2) compares a source
`CanonicalApi` against this profile to predict loss *before* emit.

| Field | Meaning when `True` |
|-------|---------------------|
| `operations` | HTTP/RPC operations (services, routes, bindings) |
| `events` | Event channels, pub/sub actions, async message flows |
| `unions` | Discriminated unions / one-of type alternatives |
| `nullability` | Explicit nullable / optional member semantics |
| `constraints` | Validation facets (min/max, pattern, format, enum) |
| `field_identity` | Stable field identifiers (protobuf field numbers, Avro names) |

Example profiles:

| Target | operations | events | unions | nullability | constraints | field_identity |
|--------|------------|--------|--------|-------------|-------------|----------------|
| OpenAPI 3.1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| Sample (no-op) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

Retrieve a target's profile via `OpenApiEmitter.capability_profile()` or from
`describe_emit_targets()[].capability_profile`.

## Target descriptor (MFX-1.1)

`EmitterDescriptor` is the registry's public, serializable view of an emitter —
everything a consumer needs to render a target card or a CLI verb without importing
the emitter class itself:

| Field | Meaning |
|-------|---------|
| `key` | Stable target id (`openapi`, `sample`, …) |
| `format` | Registry format key (`openapi-3.1`, …) |
| `label` / `description` / `icon` | Card / CLI presentation |
| `paradigm` | Primary `ApiParadigm` |
| `multi_file` | Whether emit produces a bundle vs one artifact |
| `needs_toolchain` | Whether a hard-required external binary is needed |
| `available` / `unavailable_reason` | Runtime toolchain availability (MFI-5.2 pattern) |

## Per-target options (MFX-1.4)

Each emitter declares a Pydantic ``options_model`` subclass of
:class:`EmitOptions` with format-specific fields and safe defaults. The registry
exposes them on every :class:`EmitterTarget` as ``options_schema`` (JSON Schema
for UI/CLI form generation) and ``default_options`` (validated default values).

```python
OpenApiEmitter.options_schema()   # → JSON Schema dict
OpenApiEmitter.default_options()  # → OpenApiEmitOptions(...)
coerce_emit_options(OpenApiEmitter, {"include_paths": False})
describe_emit_targets()[0].options_schema
describe_emit_targets()[0].default_options
```

Export callers validate options through :func:`app.export_service.resolve_emit_options`
or by passing a raw ``dict`` to :func:`app.export_service.emit_canonical` (coerced
automatically). Invalid options raise :class:`EmitOptionsError` / :class:`ExportError`
with status 422.

| Target | Options model | Notable fields |
|--------|---------------|----------------|
| OpenAPI 3.1 | `OpenApiEmitOptions` | `include_paths`, `include_components`, `include_projection_extensions` |
| Sample (no-op) | `SampleEmitOptions` | `content` |

Defaults for every built-in target produce a schema-valid artifact (OpenAPI output
passes ``validate_openapi_document``).

## Provenance

Every emitted value gets a `ProvenanceRecord(pointer, provenance, detail)` where
`pointer` is an RFC-6901 JSON Pointer into the emitted document:

| Provenance | Meaning | Example |
|------------|---------|---------|
| `source`   | copied straight from a populated canonical field | `/info/title` from `identity`/`title` |
| `inferred` | derived from the model's structure | a `POST` binding synthesized for a gRPC method; a synthesized `operationId` |
| `default`  | system fallback with no basis in the model | the `openapi` version string; an empty response `description` |

`ProvenanceTracker.records()` returns the notes sorted by pointer, so the
provenance list is deterministic too.

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

## Reference implementations

### `OpenApiEmitter`

`OpenApiEmitter` (key `openapi`, format `openapi-3.1`, paradigm `REST`) maps:

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

### `SampleEmitter`

`SampleEmitter` (key `sample`, format `sample-noop`) is the no-op acceptance adapter:
it registers and appears in `describe_emit_targets()` with an empty capability profile
and returns a blank single-file artifact. Use it as the smallest worked example when
adding a new export target.

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
