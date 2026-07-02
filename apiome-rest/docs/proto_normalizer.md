# Protobuf → canonical model (MFI-9.2)

> **Status:** normalizer — `src/app/proto_normalizer.py`
> **Issue:** [#3765](https://github.com/objectified-project/objectified/issues/3765) ·
> **Epic:** MFI-EPIC-9 (#3724) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

MFI-9.1 compiled `.proto` source to a `google.protobuf.FileDescriptorSet` (the canonical
binary artifact, see [`proto_descriptor.md`](./proto_descriptor.md)). This ticket maps that
descriptor set into the **paradigm-agnostic canonical model**
([`canonical_model.md`](./canonical_model.md)) so versioning, fingerprinting, diff, lint and
browse work over gRPC/Protobuf exactly as they do over OpenAPI, AsyncAPI and GraphQL.

Like the GraphQL normalizer — and unlike the OpenAPI/AsyncAPI ones — it consumes a **typed
object**, not a parsed `dict`: it walks the descriptor messages the compiler emitted, so
syntax/Editions feature resolution, import resolution and field numbering are the compiler's
job, never a re-parse here. `ProtoNormalizer` self-registers under the `protobuf` format key
(the one [`format_detection`](../src/app/format_detection.py) emits), produces paradigm
`RPC`, and is **pure** (no I/O).

## Mapping

```
 FileDescriptorSet (target files only — imports skipped)
   ├─ service  ───────────────►  Service            key  pkg.Service
   │    └─ rpc method ─────────►  Operation          key  pkg.Service.Method
   │         │                      kind = REQUEST_RESPONSE
   │         │                      streaming ← (client_streaming, server_streaming)
   │         ├─ input_type ─────►  Message (REQUEST)  key  pkg.Service.Method#request
   │         └─ output_type ────►  Message (RESPONSE) key  pkg.Service.Method#response
   ├─ message  ───────────────►  Type (RECORD)       key  pkg.Message   (nested: pkg.Outer.Inner)
   │    └─ field ──────────────►  CanonicalField      key  pkg.Message.field   (+ field_number)
   └─ enum     ───────────────►  Type (ENUM)         key  pkg.Enum
        └─ value ──────────────►  EnumValue (value = wire number, declaration order kept)
```

| Protobuf construct | Canonical | Key |
|---|---|---|
| `service Foo` | `Service` | `pkg.Foo` |
| `rpc Bar(Req) returns (Resp)` | `Operation` (`REQUEST_RESPONSE`) | `pkg.Foo.Bar` |
| input / output message | request / response `Message` | `pkg.Foo.Bar#request` / `#response` |
| `message M` | `Type` (`RECORD`) | `pkg.M` |
| `M.field = N` | `CanonicalField` (`field_number = N`) | `pkg.M.field` |
| nested `message`/`enum` | `Type` (parent-prefixed) | `pkg.Outer.Inner` |
| `enum E { V = N; }` | `Type` (`ENUM`) + `EnumValue(value=N)` | `pkg.E` / `pkg.E.V` |
| `map<K,V> m = N` | `Type` (`MAP`) for the synthetic `*Entry`; field references it | `pkg.M.MEntry` |

### Streaming flags (acceptance criterion)

A method's two streaming booleans map to one canonical `StreamingMode`:

| `client_streaming` | `server_streaming` | `StreamingMode` |
|---|---|---|
| `false` | `false` | `NONE` (unary) |
| `true`  | `false` | `CLIENT` |
| `false` | `true`  | `SERVER` |
| `true`  | `true`  | `BIDIRECTIONAL` |

### Field numbers, `oneof`, `reserved` (acceptance criterion)

* **Field number** is preserved on `CanonicalField.field_number`, so a rename reads as a
  *modify*, not an *add + remove*, in a diff.
* A real **`oneof`** records its name in the member field's `extras` (`{"oneof": "<name>"}`)
  and in the owning type's `extras` (`{"oneofs": [...]}`). The *synthetic* oneof a proto3
  `optional` field generates is **excluded** — that field is flagged `proto3_optional`
  instead.
* **`reserved`** ranges/names are preserved in the type's `extras` (`reserved_ranges` as
  `[start, end]` pairs, `reserved_names`), so a reservation change flips the fingerprint.

### Types & references

* Scalar fields resolve to their protobuf primitive name (`int64`, `string`, `bool`, …) — a
  leaf `TypeRef` that, like a GraphQL built-in scalar, references no local `Type`.
* Message/enum fields resolve to the **package-qualified key** of their `type_name` (the
  leading `.` the compiler emits is stripped).
* `repeated` fields become a list `TypeRef` (`nullable=False`); a proto2 `required` field is
  non-nullable, everything else nullable (presence or zero-default).
* `map<K,V>` is special-cased: the compiler's synthetic `*Entry` message becomes a `MAP` type
  carrying `key_type`/`value_type`, and the map field references that type **directly** (not as
  a list of entries).

### Imports

Only the caller's *target* files are mapped. Files the compiler pulled in to satisfy an
`import` (well-known types like `google.protobuf.Timestamp`, transitive dependencies — flagged
`is_import` by MFI-9.1) are **skipped**, so a referenced imported type appears as a `TypeRef`
by key with no local `Type` — the same dangling-by-design reference a protobuf `import` is.
Passing a bare `FileDescriptorSet` (no import flags) maps every file.

## Fingerprint stability (acceptance criterion)

[`fingerprint.py`](../src/app/fingerprint.py) strips `description`/`title`/`raw` before hashing
but keeps `extras` and field numbers. So the semantic fingerprint:

* is **invariant** to declaration order (the normalizer ends with `normalize_ordering`) and to
  comment/doc-only edits (they never reach the descriptor set), and
* **flips** on any structural change — a streaming flag, a field number, a `oneof` grouping, a
  `reserved` range, a label/presence change — because each lives in a hashed field.

## Inputs

`ProtoNormalizer().normalize(source)` accepts, in order of preference:

1. a `CompiledDescriptorSet` (from `compile_proto_descriptor_set`) — honours the target/import
   split;
2. a bare `google.protobuf.FileDescriptorSet` — every file is a target;
3. the serialized `FileDescriptorSet` `bytes`.

Anything else raises `ValueError`.

## Tests

`tests/test_proto_normalizer.py` runs two tiers (mirroring MFI-9.1):

* **Synthetic-descriptor** tests (always run, no `buf`) hand-build descriptor sets to reach
  every path — all four streaming modes, `oneof`/proto3-`optional`, `map`, `reserved`,
  proto2 `required`/defaults, enum aliases, nested types — and assert the acceptance criteria:
  streaming flags + field numbers preserved, JSONB round-trip lossless, fingerprint stable
  across re-normalization and declaration-order shuffles yet flipping on a streaming / field-
  number / reserved change.
* **End-to-end** tests (gated on `buf` being resolvable) compile the committed fixtures with
  the real compiler and normalize the result.
