# gRPC live discovery via Server Reflection (MFI-9.3)

> **Status:** discovery service — `src/app/grpc_reflection.py`
> **Issue:** [#3766](https://github.com/objectified-project/objectified/issues/3766) ·
> **Epic:** MFI-EPIC-9 (#3724) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Many gRPC services ship **no `.proto` files** to their consumers — the schema exists only on the
running server, exposed through the [gRPC Server Reflection](https://grpc.io/docs/guides/reflection/)
protocol. MFI-9.1 turns `.proto` *source* into a `FileDescriptorSet` and MFI-9.2 maps that set onto
the canonical model; this module covers the **third** way an author hands us a gRPC API — a **live
endpoint** with no source — by crawling its reflection service and assembling the very same
[`CompiledDescriptorSet`](./proto_descriptor.md) the file path produces, so the result flows into
the MFI-9.2 [`ProtoNormalizer`](./proto_normalizer.md) **unchanged**.

```
 discover_endpoint(target)
   ├─ validate_host        SSRF guard vets the host BEFORE any channel is opened
   ├─ auth → metadata      credential vault (build_auth_headers) → lower-cased gRPC metadata
   ├─ crawl  (per version, v1 then v1alpha)
   │    ├─ ListServices            enumerate the server's services
   │    └─ FileContainingSymbol    each service → its file + transitive deps (FileDescriptorProtos)
   ├─ build_descriptor_set  dedup by name, order by name, pack a FileDescriptorSet (pure, no I/O)
   └─ read_file_descriptor_set  → CompiledDescriptorSet (the MFI-9.1 artifact) → MFI-9.2
```

## One call, three outcomes

`discover_endpoint(target, …)` always returns a `GrpcReflectionResult`. Validity is a **return
value**, not an exception:

* **success** — `ok=True`, the `reflection_version` that answered, the discovered `services`, and
  the assembled `descriptor_set_bytes` / `summary` / `target_files`. `result.compiled()` rebuilds
  the `CompiledDescriptorSet` for the normalizer (re-reading the bytes with the target/import
  split restored).
* **unavailable** — `ok=False` with a human `reason` (reflection disabled, server unreachable, or
  no services exposed). Not an exception — a server being down is an outcome, not a bug.
* **misconfigured** — the one case that **raises** `GrpcReflectionError`: an unsafe target
  (`SSRFError`) or a malformed credential (`CredentialPayloadError`). A route maps this to a 4xx.

## v1 → v1alpha fallback

The Server Reflection **wire protocol is identical** for the modern `grpc.reflection.v1` service
and the legacy `grpc.reflection.v1alpha` service — they differ only in the fully-qualified service
name, and therefore the RPC method path. `grpcio-reflection` ships generated stubs for **v1alpha
only**, so rather than depend on a stub we drive the bidi `ServerReflectionInfo` stream directly
with `channel.stream_stream(<method-path>, …)`, reusing the v1alpha message classes for both
versions and swapping only the path:

| version | method path |
| --- | --- |
| `v1` | `/grpc.reflection.v1.ServerReflection/ServerReflectionInfo` |
| `v1alpha` | `/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo` |

The crawl tries **v1 first**; when the server has not implemented it the RPC fails `UNIMPLEMENTED`,
and the whole crawl transparently retries against **v1alpha**. (A server that runs the modern
`grpcio-reflection` advertises v1alpha only, so a real crawl of it exercises this fallback.) A
*connection* failure (host down, deadline) is **terminal** — it does not trigger a version retry,
because the other version lives on the same unreachable server.

## Assembly is deterministic (stable fingerprint)

`FileContainingSymbol` returns the file declaring the symbol **plus its transitive dependencies**,
so crawling every service yields the same files many times over. `build_descriptor_set` is the
pure, network-free seam that:

* **dedups** the serialized `FileDescriptorProto`s by file name (they are identical across
  responses — first wins);
* **orders** the files by name before packing them, so the resulting `FileDescriptorSet` bytes are
  deterministic regardless of reflection response order — a stable
  [MFI-3.1 fingerprint](./proto_descriptor.md);
* computes **targets vs imports**: a file is a *target* when it declares one of the discovered
  service symbols; every other file (well-known types, shared message libraries) is a pulled-in
  *import*, mirroring how a `.proto` `import` works. The split is handed to
  `read_file_descriptor_set(..., target_files=…)` so the normalizer skips imports exactly as it
  does for the file path.

Two independent caps bound a hostile/runaway server: `_MAX_DESCRIPTOR_FILES` (count) and
`_MAX_DESCRIPTOR_BYTES` (total size).

## Network opt-in, SSRF, and auth (MFI-5.3 posture)

Live discovery is the one explicit **network opt-out** of the toolchain's no-network sandbox
default ([`toolchain_sandbox.md`](./toolchain_sandbox.md), MFI-5.3). The reflection channel does
*not* run through the toolchain runner — it is a direct gRPC connection from the service process —
so it carries the same braces the HTTP live-discovery paths do:

* **SSRF guard.** The target's host is vetted by `ssrf_guard.validate_host()` **before** the
  channel is created. A gRPC target is a bare `host:port` (not a URL), so `validate_host` is the
  companion to `validate_url`: it resolves the host and rejects any non-public address (the cloud
  metadata IP, loopback, RFC1918, …), unless `APIOME_SSRF_ALLOW_PRIVATE` is set for local
  development. `_host_of` strips a `scheme://` prefix, a `user:pass@` authority, and the port
  (including bracketed IPv6) before the check.
* **Auth from the credential vault.** Auth is attached as call **metadata** built from the shared
  `mcp_auth.build_auth_headers` model — the same `none`/`bearer`/`header`/`oauth2` mapping the MCP
  discovery and GraphQL introspection paths use. The decrypted payload only ever yields headers,
  which become gRPC metadata pairs with **lower-cased keys** (`Authorization` → `authorization`,
  as gRPC requires). The header-injection / CRLF guards in `mcp_auth` apply, so a stored secret can
  never forge extra metadata.

## Testing seam

`discover_endpoint` accepts a `transport_factory` — `(version) -> ReflectionTransport` — used
instead of building a real channel, the dependency-injection seam the unit tests use to drive the
crawl/fallback/assembly logic with no network. Production omits it. The suite also stands up a
**real in-process gRPC server** with `grpcio-reflection` enabled and crawls it through the genuine
transport, proving the actual `stream_stream` wiring, the real `v1 UNIMPLEMENTED → v1alpha`
fallback, and the end-to-end flow into the MFI-9.2 normalizer.

## What this is not

* It does **not** invoke the server's RPCs — it reads the schema only (`ListServices` /
  `FileContainingSymbol`).
* It does **not** normalize: it produces the `CompiledDescriptorSet`; the canonical mapping is
  MFI-9.2's job. The source-card / CLI surface that wires this into the import pipeline is MFI-9.6.
