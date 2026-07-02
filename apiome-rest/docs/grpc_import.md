# gRPC / Protobuf Import Source (MFI-9.6)

> **Status:** `ImportSource` adapter — `src/app/grpc_import_source.py`
> **Issue:** [#3769](https://github.com/objectified-project/objectified/issues/3769) ·
> **Epic:** MFI-EPIC-9 (#3724) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The [`ImportSource`](./import_source_spi.md) adapter (MFI-1.1) that makes the gRPC / Protocol
Buffers pipeline of MFI-9.1…9.5 reachable from the **UI source card** and the **CLI `import`
command**. Like the reference [OpenAPI adapter](./import_source_spi.md), the
[AsyncAPI adapter](./asyncapi_import.md), and the [GraphQL adapter](./graphql_import.md) it is a
thin seam over machinery that already exists — it adds *no* new compilation, mapping, or scoring
logic:

```
 GrpcImportSource
   ├─ detect()    .proto syntax/edition/keyword markers → protobuf     (cheap text sniff, no buf)
   ├─ parse()     buf build (MFI-9.1) → CompiledDescriptorSet          (.proto file upload)
   ├─ discover()  Server Reflection crawl (MFI-9.3) → CompiledDescriptorSet   (live endpoint)
   ├─ normalize() registered ProtoNormalizer (MFI-9.2) → CanonicalApi (paradigm RPC)
   ├─ lint()      lint_protobuf_result (MFI-9.4) → score / grade / fingerprint (+ buf lint)
   └─ fingerprint()/diff()  canonical-model defaults (the MFI-9.5 breaking overlay layers on the diff)
```

Registering the adapter (`register=True`) is **all the UI and CLI need**. Both surfaces are
data-driven off the [import-source registry](./import_source_spi.md) (`GET /v1/import/sources`):

* **UI** — the source-card grid merges every registry descriptor, so a `grpc` card with the
  `share-2` icon, the *rpc* paradigm, and file/url/paste/**discovery** inputs appears with no UI
  change.
* **CLI** — `apiome import --list` enumerates the registry and `apiome import grpc
  <input>` dispatches a `.proto` through the generic adapter-import path (MFI-1.4) with no new
  command code.

## Two intake paths, one canonical model

The acceptance criterion is that a `.proto` upload **and** a live reflection endpoint both catalog
a version. The adapter exposes both, and they converge on the same
[`CompiledDescriptorSet`](./proto_descriptor.md) the MFI-9.2 normalizer consumes:

* **`.proto` upload → `parse()`.** The uploaded source is compiled with the bundled `buf`
  (`compile_proto_descriptor_set`, MFI-9.1). Only the compiler's bundled well-known types resolve
  from a single upload; a proto that `import`s *sibling* files surfaces `buf`'s "unresolved import"
  diagnostic as an `ImportSourceError`.
* **Live reflection endpoint → `discover()`.** The SSRF-guarded Server Reflection crawler
  (`discover_endpoint`, MFI-9.3) enumerates the running server's services (`ListServices`), pulls
  each service's file plus transitive dependencies (`FileContainingSymbol`), and assembles a
  descriptor set whose bytes match the `buf build` path exactly — so it flows into `normalize()`
  unchanged. Reflection-disabled / unreachable / no-services endpoints return a not-`ok` result
  that the adapter turns into a clean `ImportSourceError`; only an unsafe target or a malformed
  credential raises earlier.

## Detection

`detect()` recognizes Protocol Buffers **source text** (not a JSON/YAML mapping): a
`syntax = "proto3"` / `"proto2"` marker is a high-confidence match, an Editions `edition = …`
marker with a `message`/`service` is next, and a bare top-level `message`/`service`/`enum`/
`package` keyword is a weaker signal; a `.proto` filename is weaker still. Detection never shells
out to `buf` and never raises — an unrecognized input is simply not a match. Because the adapter
now claims `protobuf`, the MFI-1.5 auto-detector reports a `.proto` as **importable**
(`source_key: grpc`) rather than sniffer-only.

## Async compiler over a synchronous SPI seam

The `ImportSource` SPI's `parse()` is **synchronous**, but `compile_proto_descriptor_set`
(MFI-9.1) is a coroutine that drives the `buf` subprocess, and the import pipeline
([`run_adapter_import_job`](./import_source_spi.md)) calls `parse()` from the service's **running
event loop** (where `asyncio.run` is illegal). The adapter therefore runs the compile to
completion on a **dedicated worker thread** with its own event loop (`_compile_on_worker_loop`).
A fresh sibling `ToolchainRunner` — mirroring the shared runner's concurrency/timeout/policy
configuration — is constructed *inside* that loop, so its `asyncio.Semaphore` binds to the worker
loop rather than the (different) service loop. This is the same bridge the
[AsyncAPI adapter](./asyncapi_import.md) uses for its Node parser.

When `buf` is not resolvable in a runtime (e.g. a dev sandbox without the bundled toolchain,
MFI-5.2), `parse()` degrades to a clean `ImportSourceError` and the job fails with a user-facing
message; the `discover()`, `normalize()`, and `lint()` paths do not need `buf`.

## Normalize & lint

`normalize()` accepts the `CompiledDescriptorSet` that `parse()` / `discover()` return, a bare
`google.protobuf.FileDescriptorSet`, or its serialized bytes (the latter two keep the adapter
unit-testable without `buf`). It delegates to the registered
[`ProtoNormalizer`](./proto_normalizer.md) (MFI-9.2) under the `protobuf` format key, which honours
the target/import distinction — imports are referenced by key but not re-emitted.

`lint()` delegates to `lint_protobuf_result` (MFI-9.4), which is pure over the canonical model: the
native Protobuf rule pack plus the always-on common pack always produce a deterministic score /
grade / `report_fingerprint`, and the authoritative `buf lint` findings fold in through the
end-to-end `lint_protobuf` path when `buf` is present. `fingerprint()` / `diff()` use the
canonical-model defaults; the MFI-9.5 `buf breaking` overlay layers onto the diff view through its
own SPI.

## Tests

`tests/test_grpc_import_source.py` covers the descriptor/registration, detection, and the
`normalize` / `lint` / `discover` paths without `buf` (synthetic `FileDescriptorSet`s and a
monkeypatched compiler / reflection crawler for the bridge + error mapping), plus a gated
end-to-end test that compiles the committed `tests/fixtures/proto/grpc/echo.proto` with the real
bundled `buf`.
