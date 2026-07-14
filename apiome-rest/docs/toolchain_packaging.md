# Tool runtime packaging (MFI-5.2)

> **Status:** bundled tool declarations + availability probe + Dockerfile installer —
> `src/app/toolchain_packaging.py`, `Dockerfile`
> **Issue:** [#3751](https://github.com/objectified-project/objectified/issues/3751) ·
> **Epic:** MFI-EPIC-5 (#3720) · **Builds on:** MFI-5.1 (#3750, the runner)

MFI-5.1 built the *seam* for shelling out to non-Python parser/linter/diff CLIs
(`app.toolchain_runner`). MFI-5.2 is the *packaging*: it ships the real binaries, pins each
to a reproducible version, and makes a missing tool a clean **"format unavailable"** signal
instead of a crash.

## What is bundled (pinned)

`BUNDLED_TOOLS` in `src/app/toolchain_packaging.py` is the **single source of truth** for
which tools ship and at what version. The Dockerfile installs exactly these versions via
build args (`BUF_VERSION`, `TSP_VERSION`, …) — **bump both together**.

| Key | Tool | Pinned | Runtime | Installed by |
|-----|------|--------|---------|--------------|
| `buf` | Protobuf/gRPC build·lint·breaking | `1.50.0` | native | GitHub release binary |
| `tsp` | TypeSpec compiler (`@typespec/compiler`) | `0.65.0` | node | npm into tools prefix + wrapper |
| `smithy` | Smithy IDL build·validate | `1.53.0` | jvm | GitHub CLI zip (bundles its own runtime) |
| `drafter` | API Blueprint → JSON | `4.0.0` | native | built from source (pinned tag) |
| `amf` | AML Modeling Framework (RAML/OAS) | `5.7.1` | jvm | MuleSoft Nexus assembly jar + `java -jar` wrapper |
| `asyncapi` | AsyncAPI validate·convert·diff (`@asyncapi/cli`) | `2.16.0` | node | npm into tools prefix + wrapper |
| `asyncapi-parser` | AsyncAPI parse·validate·dereference → canonical JSON (`@asyncapi/parser`, MFI-8.1) | `3.6.0` | node | npm into tools prefix + Node wrapper (`toolchain/asyncapi-parse.mjs`) |
| `asyncapi-diff` | AsyncAPI diff → breaking/non-breaking/unclassified (`@asyncapi/diff`, MFI-8.4) | `0.5.0` | node | npm into tools prefix + Node wrapper (`toolchain/asyncapi-diff.mjs`) |
| `rover` | Apollo GraphQL schema CLI | `0.27.0` | native | GitHub release tarball |
| `graphql-inspector-diff` | GraphQL diff → breaking/dangerous/non-breaking (`@graphql-inspector/core`, MFI-10.5) | `6.2.0` | node | npm into tools prefix + Node wrapper (`toolchain/graphql-inspector-diff.mjs`) |
| `spectral` | OpenAPI/AsyncAPI lint (`@stoplight/spectral-cli`, CLX-2.2) | `6.16.1` | node | npm into tools prefix + wrapper |
| `vacuum` | OpenAPI lint (`daveshanley/vacuum`, CLX-2.2) | `0.29.9` | native | GitHub release tarball |
| `redocly` | OpenAPI lint/resolve (`@redocly/cli`, CLX-2.2) | `2.39.0` | node | npm into tools prefix + wrapper |

All thirteen land under `/opt/apiome-tools/bin` (on `PATH`); the JVM/Node tools are thin
wrappers so the runner invokes them by bare name exactly like the native binaries. The
`asyncapi-parser` tool is a small repo-committed Node script (`apiome-rest/toolchain/
asyncapi-parse.mjs`) that imports `@asyncapi/parser`: it reads a document on `stdin` and writes
the validated, `$ref`-dereferenced canonical JSON (plus identity + diagnostics) on `stdout`. It
is driven by the `app.asyncapi_parser` service. The `asyncapi-diff` tool is a sibling Node
script (`toolchain/asyncapi-diff.mjs`) that imports `@asyncapi/diff`: it reads
`{"old": …, "new": …}` (two dereferenced documents) on `stdin` and writes each change's
`breaking`/`non-breaking`/`unclassified` verdict on `stdout`. It is driven by the
`app.asyncapi_diff` service and its breaking-change classifier. The `graphql-inspector-diff`
tool is a third Node script (`toolchain/graphql-inspector-diff.mjs`) that imports
`@graphql-inspector/core` (+ its `graphql` peer): it reads `{"old": …, "new": …}` (two SDL
strings) on `stdin`, builds each into a `graphql-js` schema, and writes each change's
`BREAKING`/`DANGEROUS`/`NON_BREAKING` verdict on `stdout`. It is driven by the
`app.graphql_diff` service and its breaking-change classifier. Spectral, Vacuum, and Redocly
back the CLX-2.2 OpenAPI validation packs (`app.openapi_validation_pack`).
`oasdiff` backs CLX-2.3 independent OpenAPI compatibility evidence
(`app.openapi_compatibility_adapters`); `openapi-changes` is an optional HTML
renderer and is not required in the image.

## Footprint

Approximate added image size over the base `python:3.12-slim` runtime (amd64; the tools tree
plus the JRE the AMF wrapper needs — smithy ships its own runtime, so no extra JRE for it):

| Component | Approx. size |
|-----------|-------------:|
| `default-jre-headless` (for AMF) | ~140 MB |
| `smithy` CLI (self-contained runtime) | ~80 MB |
| `amf` assembly jar | ~60 MB |
| `tsp` + `asyncapi` + `@asyncapi/parser` + `@asyncapi/diff` + `@graphql-inspector/core` + spectral + redocly (node_modules) | ~180 MB |
| `buf` | ~30 MB |
| `vacuum` | ~25 MB |
| `rover` | ~30 MB |
| `drafter` | ~5 MB |
| **Total added** | **~480 MB** |

The build-time `tools` stage also pulls `cmake`/`build-essential`/`git` to compile drafter,
but that toolchain stays in the builder stage and is **not** copied into the runtime image.

If the footprint is unacceptable for a deployment, the same `BUNDLED_TOOLS` declarations work
unchanged when the tools live in a **sidecar**: point each `APIOME_<TOOL>_BIN` at the
sidecar mount, or omit a tool entirely and accept its format degrading to "unavailable".

## Optional / lazy — the "format unavailable" path

Tools are optional by construction:

* **Resolution is lazy.** `probe_tool(key)` / `probe_all()` only do a `PATH`/override lookup —
  no subprocess — so an absent tool is reported as `available: false` cheaply.
* **A missing binary never crashes the service.** At call time the runner raises
  `ToolNotAvailableError`; before calling, an adapter can `probe_tool(...)` and skip straight
  to a "format unavailable" status.
* **Overrides.** Set `APIOME_<KEY>_BIN` (e.g. `APIOME_BUF_BIN`) to an absolute path
  to use a custom/sidecar binary instead of the bundled one.

## Operator surface

`GET /v1/ops/toolchain` (platform-admin) returns each tool's pinned version and availability:

```jsonc
{
  "summary": { "total": 7, "available": 7, "unavailable": 0 },
  "tools": [
    { "key": "buf", "pinned_version": "1.50.0", "runtime": "native",
      "available": true, "resolved_path": "/opt/apiome-tools/bin/buf",
      "override_env": "APIOME_BUF_BIN", "detail": "resolved to /opt/apiome-tools/bin/buf" }
    // …
  ]
}
```

Add `?verify=true` to additionally invoke each available tool's `--version` probe and confirm
it actually runs (one subprocess per available tool, so it is slower).

## Keeping versions in sync

1. Edit the `version=` field of the relevant `BundledTool` in `toolchain_packaging.py`.
2. Edit the matching `ARG <TOOL>_VERSION` default in `Dockerfile`.
3. Update the table above.

The Python pin is authoritative for what the *runtime reports*; the Dockerfile pin is what is
*installed*. A mismatch does not break anything (the tool still resolves and runs), but the
reported `pinned_version` would then be misleading — so keep them aligned.
