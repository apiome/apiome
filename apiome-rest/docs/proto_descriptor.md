# `.proto` → `FileDescriptorSet` (MFI-9.1)

> **Status:** compile service — `src/app/proto_descriptor.py`
> **Issue:** [#3764](https://github.com/objectified-project/objectified/issues/3764) ·
> **Epic:** MFI-EPIC-9 (#3724) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Hand-parsing `.proto` is fragile: imports, `option` inheritance, proto2/proto3 and the new
**Editions** (2023/2024) feature-resolution rules are exactly what a real compiler gets right
and a regex does not. So the canonical artifact for everything downstream — the
canonical-model mapping (MFI-9.2), the descriptor-set fingerprint hook (MFI-3.1), `buf lint` /
`buf breaking` (MFI-9.4/9.5) — is the **compiled descriptor set**, not the source text:
> *Compile to a `FileDescriptorSet` and hash **that**, not raw `.proto`.*

This module is that compile seam. It has two layers:

```
 compile_proto_descriptor_set(files)        # the buf-orchestration layer
   ├─ materialise   write the .proto files + a buf.yaml into a scratch module
   ├─ buf build     buf build <scratch> --as-file-descriptor-set --output <scratch>/….binpb
   │                (the bundled `buf` tool, via the MFI-5.1 toolchain runner: no-network sandbox)
   └─ read back     read the binary FileDescriptorSet from disk → read_file_descriptor_set

 read_file_descriptor_set(bytes)            # the pure, compiler-free read layer
   └─ descriptor_pb2.FileDescriptorSet().ParseFromString(bytes) → per-file metadata + summary
```

## Why a file, not stdout

`buf build` emits the descriptor set as a **binary** protobuf blob. The toolchain runner
([`toolchain_runner.py`](./toolchain_runner.md)) decodes a tool's stdout as UTF-8 text, which
would corrupt binary bytes, so the build is directed to a file in the scratch directory
(`--output <path>.binpb`) and the bytes are read back from disk. Those bytes are the canonical
artifact the MFI-3.1 fingerprint hook hashes.

## The `buf build` invocation

* Input is the scratch directory, which carries a minimal **buf v2** `buf.yaml`
  (`modules: [{ path: . }]`) so `buf` treats it as one self-contained module and resolves every
  `import` against it. No remote dependencies are used — the sandbox has no network anyway, and
  the **well-known types** (`google/protobuf/*.proto`) are bundled in `buf` itself.
* `--as-file-descriptor-set` makes `buf` emit a bare `google.protobuf.FileDescriptorSet` rather
  than a Buf image, so [`descriptor_pb2`](https://protobuf.dev/reference/python/python-generated/)
  reads it directly.
* **Imports are included** (the default — we do *not* pass `--exclude-imports`), so the set is
  self-contained: a multi-file proto with `import`s compiles to a single descriptor set, the
  acceptance criterion.

The `buf` binary is pinned and bundled by the runtime image (MFI-5.2,
[`toolchain_packaging.md`](./toolchain_packaging.md), `APIOME_BUF_BIN` overrides it). When
it is absent the compile raises `ProtoCompileError` ("protobuf/gRPC import is unavailable
here") instead of crashing — the same "format unavailable" posture the other polyglot formats
use.

## Editions & syntax handling

The read layer never parses proto syntax — it reads what the compiler resolved:

| File `syntax` | `edition` field | `ProtoFileDescriptor.syntax` / `.edition` |
|---|---|---|
| omitted        | —                | `proto2` / `None`   |
| `proto3`       | —                | `proto3` / `None`   |
| `editions`     | `EDITION_2023`   | `editions` / `2023` |
| `editions`     | `EDITION_2024`   | `editions` / `2024` |

Editions 2023 and proto3 compile **end-to-end** through the bundled `buf` (covered by the
fixtures); Editions 2024 is **recognised and labelled** by the read layer (covered by a
synthetic descriptor) so the catalog handles it the moment the bundled `buf`/`protoc` gains
2024 codegen — no code change here.

## Result shape

`compile_proto_descriptor_set` / `read_file_descriptor_set` return a `CompiledDescriptorSet`:

* `descriptor_set_bytes` — the canonical binary artifact (what MFI-3.1 hashes);
* `proto` — the parsed `google.protobuf.FileDescriptorSet` message, handed to the MFI-9.2
  canonical-model mapper as-is (no re-parse);
* `files` — a `ProtoFileDescriptor` per file: `name`, `package`, `syntax`, `edition`,
  `dependencies` / `public_dependencies`, message/enum/service counts, and `is_import` (the
  caller's targets are flagged `is_import=False`; everything `buf` pulled in — well-known types,
  transitive deps — `is_import=True`);
* `summary` — a serializable `DescriptorSetSummary` roll-up (file/target counts, distinct
  syntaxes/editions/packages, total services/messages/enums).

## Errors

* `ProtoCompileError` — empty/oversized input or an unsafe path (absolute, `..`, or non-`.proto`
  — validated **before** anything is spawned); `buf` not installed; a timeout; a **compile
  failure** (syntax error / unresolved import), with `buf`'s diagnostics carried on
  `.diagnostics`; or an empty/missing descriptor output.
* `ProtoDescriptorError` — bytes that are not a parseable `FileDescriptorSet` (raised by the
  read layer; should not happen for a clean `buf` run).

A proto that does not compile is therefore an **error**, not a return value — there is no
descriptor set to inspect — which is the opposite of the AsyncAPI parser's "invalid is a result"
contract because there the parser still returns a (partial) document.

## What this ticket does **not** do

MFI-9.1 stops at the descriptor set. Mapping services/methods/messages into the canonical model
(MFI-9.2), gRPC server-reflection discovery (MFI-9.3), the `buf lint` / `buf breaking` packs
(MFI-9.4/9.5), and the UI/CLI gRPC source card (MFI-9.6) build on top of it.

## Tests

`tests/test_proto_descriptor.py`:

* **read layer** — synthetic `FileDescriptorSet`s (proto3, Editions 2023/2024, proto2,
  import-flagging, public deps, counts, summary, unparseable-bytes guard);
* **compile layer** — a fake runner stands in for `buf`: it snapshots the materialised scratch
  module (proving the protos + `buf.yaml` land at the right paths) and writes a pre-built
  descriptor to the `--output` path, so materialise → invoke → read-back → import-flagging is
  exercised without the binary; error mapping (missing tool / timeout / compile failure /
  empty output) is covered too;
* **end-to-end** (gated on `buf` resolving) — the committed fixtures under
  `tests/fixtures/proto/` (`common/types.proto`, `user/user_service.proto`,
  `editions/catalog.proto`, `broken/unresolved_import.proto`) through the real `buf`.
