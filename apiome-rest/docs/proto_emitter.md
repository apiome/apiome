# Canonical model → Protobuf (proto3) — MFX-12.1

> **Status:** emitter — `src/app/proto_emitter.py`
> **Issue:** [#3879](https://github.com/apiome/apiome/issues/3879) ·
> **Epic:** MFX-EPIC-12 (#3825) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_EXPORT.md`

The **Protobuf emitter** is the inverse of the [Protobuf normalizer](./proto_normalizer.md)
(MFI-9.2) and an implementation of the [Emitter SPI](./emitter_spi.md). Where the normalizer maps
a compiled `FileDescriptorSet` *into* the paradigm-agnostic
[canonical model](./canonical_model.md), this emitter walks a `CanonicalApi` back *out* to
**proto3** `.proto` source text.

```
 normalize (MFI-9.2)              emit (this module)              validate
 FileDescriptorSet ─────▶ CanonicalApi ─────▶ .proto source ─────▶ buf build
              (ProtoNormalizer)      (ProtoEmitter)        (proto_descriptor.py)
```

It self-registers under the **`proto3`** format key (target key `protobuf`), so
`app.emitter.get_emitter("proto3")` resolves it and it appears in the export target registry
(`/v1/export/{tenant}/targets`).

## Mapping (the inverse of `proto_normalizer.py`)

| Canonical | proto3 |
|---|---|
| `identity.namespace` | `package` |
| `Service` | `service` block |
| `Operation` (+ `StreamingMode`) | `rpc M (…) returns (…)` with `stream` on request/response |
| `Operation.extras["idempotency_level"]` | `option idempotency_level = …;` |
| `RECORD` `Type` | `message` (nesting reconstructed from the dotted key) |
| `ENUM` `Type` | `enum` (value numbers preserved, a zero value floated first) |
| `MAP` `Type` referenced by a field | `map<key, value>` (the `*Entry` message is **not** re-emitted) |
| `CanonicalField.field_number` | the field's `= N` |
| list `TypeRef` (`item` set) | `repeated` |
| field `extras["proto3_optional"]` | `optional` |
| field/type `extras["oneof"]` / `["oneofs"]` | `oneof <name> { … }` |
| type `extras["reserved_ranges"]` / `["reserved_names"]` | `reserved …;` |
| a scalar `TypeRef.name` (`int64`, `string`, …) | the proto scalar keyword |
| a named `TypeRef.name` | the fully-qualified reference `.pkg.Type` |
| a well-known type reference (`google.protobuf.Timestamp`, …) | the matching `import "…";` |

**Streaming** is the acceptance criterion and is exact: `NONE`→unary, `CLIENT`→`stream` request,
`SERVER`→`stream` response, `BIDIRECTIONAL`→`stream` on both — the inverse of the normalizer's
`(client_streaming, server_streaming)` pairing.

**Nesting.** The canonical type list is flat, keyed by package-qualified coordinates
(`pkg.Outer.Inner`); the emitter regroups them into nested `message`/`enum` declarations so a
type's fully-qualified name round-trips to the same key.

**References** are emitted fully-qualified with a leading dot (`.pkg.Type`) so resolution is
unambiguous regardless of nesting; the normalizer strips the dot, so the reference round-trips to
the same key.

## Fidelity — what proto3 cannot carry

Protobuf is an RPC/type vocabulary with no validation facets, no first-class union, and no pub/sub.
Rather than drop such a construct silently, the emitter records an `EmitResult.losses` entry (the
material the gRPC fidelity pack (MFX-12.3 `ProtoFidelityRulePack`) turns into `APPROX`/`DROP`/`SYNTH` verdicts):

| Loss `subject` | When |
|---|---|
| `field-constraints` | a field carried `Constraints` (min/max/pattern/…), which proto3 has no syntax for |
| `proto3-default` | a proto2 `default` value (proto3 has no field defaults) |
| `synthesized-field-number` | a field arrived without a number; the next free one was assigned (reuses a persisted assignment on re-export when available) |

## Stable field numbers (MFX-12.2)

When exporting through `/v1/export/.../document` (or `emit_canonical` with
`ExportPersistenceContext`), synthesized protobuf field numbers are stored in
`export_field_identities` keyed by `(project, target, field_key)` and loaded on
the next export. Pass `ProtoEmitOptions.persisted_field_numbers` for dry-run /
unit tests without the database.
| `synthesized-enum-number` / `synthesized-enum-zero` | an enum lacked wire numbers, or lacked the proto3-required zero value |
| `union-as-oneof` | a `UNION` type, approximated as a message wrapping a `oneof` |
| `event-operation` / `synthesized-request` / `synthesized-response` | a non-RPC (pub/sub/one-way) operation reframed as a unary `rpc`, using `google.protobuf.Empty` where a message was missing |

## Properties

* **Pure & deterministic.** `emit()` performs no I/O and emits every collection in the model's
  (already order-normalized) order, so re-emitting the same model yields byte-identical text.
* **Provenance-tracked.** Each construct is tagged `SOURCE`, `INFERRED` (a synthesized field
  number, a union-as-oneof), or `DEFAULT` (the `syntax` line).

## Multi-file packaging (MFX-12.4)

Types are grouped by their protobuf ``package`` (derived from each type's canonical key) and
emitted as **one ``.proto`` file per package** with deterministic module-relative paths
(``acme.user`` → ``acme/user.proto``). Cross-package type references add the sibling file's
``import`` path; well-known types still import from ``google/protobuf/…``. A single-package source
yields one file; the emitter's ``multi_file`` descriptor flag is ``True`` so export delivery
(MFX-4.2) can zip multi-package bundles.

Every emitted file in the bundle is validated together via ``buf build`` — both
:func:`compile_emitted_descriptor_set` and :func:`app.export_validation.validate_emitted_artifact`
pass the full ``EmitResult.files`` list to :func:`app.proto_descriptor.compile_proto_descriptor_set`.

## Optional `FileDescriptorSet` + validation

`emit()` returns text only. The convenience coroutine
`compile_emitted_descriptor_set(api, *, opts=None)` pairs it with
`app.proto_descriptor.compile_proto_descriptor_set` to compile **every** emitted ``.proto`` with the
bundled **`buf`** and return the `CompiledDescriptorSet` — proving the bundle compiles (the
acceptance criterion) and yielding the optional binary `FileDescriptorSet`. A protobuf source is an
exact **fixed point** of `normalize ∘ emit`: `tests/test_proto_emitter.py` verifies emit → `buf
build` → re-import with streaming modes and field numbers preserved (including cross-package
imports), gated on `buf` being resolvable in the runtime.
