# Protobuf Lint Pack (MFI-9.4)

> **Status:** native rule pack + `buf lint` merge — `src/app/proto_lint.py`
> **Issue:** [#3767](https://github.com/objectified-project/objectified/issues/3767) ·
> **Epic:** MFI-EPIC-9 (#3724) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Quality signals for gRPC / Protocol Buffers (RPC) APIs. Like the [GraphQL pack](./graphql_lint.md)
(MFI-10.4) and the [AsyncAPI pack](./asyncapi_lint.md) (MFI-8.3) it rides the
[lint engine](./lint_engine_spi.md) (MFI-4.1) and rolls up through the same score / grade /
`report_fingerprint` formula as every other format (MFI-4.2). It has two complementary halves that
merge into one score:

```
 lint_protobuf_result(model, buf_report) ─▶ buf_findings(buf_report)        ─┐
                                            + CommonRulePack.lint(model)      ├▶ assemble_lint_result
                                            + ProtobufRulePack.lint(model)   ─┘   (one 0–100 score)
```

The native pack runs on the always-on import-time path (MFI-4.2) with no `buf` binary; the
`buf lint` half runs through the [external-linter adapter SPI](./external_linter_adapter.md)
(CLX-2.1 / #4851) on the restricted toolchain runner (MFI-5.1–5.3) and degrades gracefully
when `buf` is absent.

## Native rules (`ProtobufRulePack`)

Pure, deterministic rules over the [canonical model](./canonical_model.md) — no I/O, no `buf` —
so they run on the always-on lint path even when the `buf` binary is absent. The pack is
registered under the **`protobuf`** format key (the one the MFI-9.2 normalizer emits). The three
rules are exactly the checks the roadmap calls out — the Protobuf-specific concerns `buf`'s
default categories do **not** cover, but which are decidable over one compiled descriptor set:

| `rule_id`                          | Group     | Severity | Checks |
|------------------------------------|-----------|----------|--------|
| `protobuf.package-version-suffix`  | naming    | warning  | The artifact's package is versioned — its last component is a `buf`-style version such as `v1` / `v1beta1` (`foo.v1`). Mirrors `buf`'s `PACKAGE_VERSION_SUFFIX` on the always-on path. |
| `protobuf.field-no-required`       | structure | warning  | No field carries the proto2 / Editions `required` label — a one-way door that can never be safely removed. |
| `protobuf.reserved-on-deletion`    | structure | info     | A gap in a message's field numbers (or an enum's value numbers) that no `reserved` range covers — the single-artifact heuristic for "always `reserved` a deleted number". |

**Why the package check when `buf` also has it?** As with GraphQL mirroring `graphql-eslint`'s
`naming-convention` natively, this keeps the always-on score meaningful without `buf`. When `buf`
runs it checks **every** file's package; the native rule covers the primary package (the model's
`identity.namespace`).

**`reserved-on-deletion` nuance.** On a single artifact a deletion cannot be observed directly,
so the rule flags the next-best signal: a number missing from the *used* range that no `reserved`
declaration covers. Only gaps strictly between the smallest and largest used number are flagged
(an intentionally high starting number is never a "gap"). Message `reserved` ranges are half-open
`[start, end)` (the descriptor's exclusive end); enum ranges are inclusive `[start, end]` — the
rule honours both. The authoritative cross-version check is MFI-9.5's `buf breaking`.

Paths mirror the common pack's coordinates so a defect carries the same path regardless of which
pack reports it: `package`, `types.{type}`, and `types.{type}.fields.{field}`.

## `buf lint` findings (`buf_findings` / `run_buf_lint`)

The authoritative ruleset is **`buf lint`** with categories **MINIMAL→STANDARD** (the `STANDARD`
superset) plus **COMMENTS**. Rather than re-implement every rule:

- **`run_buf_lint(files, …)`** materialises the `.proto` sources into a private scratch `buf`
  module (the same layout MFI-9.1 compiles, plus a `buf.yaml` that enables the `STANDARD` +
  `COMMENTS` lint categories — `BUF_LINT_MODULE_YAML`) and runs
  `buf lint <module> --error-format=json` through the MFI-5.1 toolchain runner (no-network
  sandbox). Lint violations make `buf` exit non-zero (code `100`); that is the *normal* outcome —
  its JSON findings are read off stdout and returned. An operational failure (`buf` absent, a
  timeout, a proto that does not build) raises `ProtoLintError` instead.
- **`buf_findings(report)`** maps `buf lint`'s newline-delimited JSON (`{ "path", "start_line",
  "start_column", "type", "message" }` per line) into `LintFinding`s:
  - **rule** is the buf rule type re-namespaced `protobuf.buf.<type>` (e.g.
    `PACKAGE_VERSION_SUFFIX` → `protobuf.buf.package_version_suffix`), so it groups cleanly against
    the `protobuf.*` native rules and `common.*`. A missing type becomes `protobuf.buf.unknown`.
  - **category** is `buf-lint`.
  - **severity** folds to `warning` — `buf lint` reports no per-finding severity; every item is a
    rule violation, treated as a governance/style signal in the score.
  - **path** is `{path}:{start_line}:{start_column}` (degrading to `{path}:{line}` or `{path}`,
    and to `(proto)` when the path is blank).

`buf_findings` accepts the parsed list (from `run_buf_lint`), a single finding mapping, or the raw
JSON-Lines string (parsed by `parse_buf_lint_output`, which skips blank/non-JSON lines). Anything
falsy yields no findings, so the report degrades to the native + common packs.

## Merge entry points

| Function | Use |
|----------|-----|
| `lint_protobuf_result(model, buf_report=None)` | The integration seam. Merges `buf lint` output + native + common. **`buf` is opt-in and degrades gracefully**: pass `buf_report=None` (or empty) and the native + common packs still produce a deterministic score. The MFI-9.6 import pipeline, which already holds the normalized model, calls this with a previously-obtained `run_buf_lint` report. |
| `lint_protobuf(files, …)` | Convenience that ties MFI-9.1 (`buf build` → descriptor set), `run_buf_lint`, and MFI-9.2 (normalize) end-to-end from raw `.proto` source. Raises `ProtoCompileError` when the sources do not compile, `ProtoLintError` when `buf lint` cannot run. |

## Determinism & purity

The native pack and the `buf` mapping are pure and deterministic; entities are visited in
sorted-key order and `assemble_lint_result` re-sorts by `(path, rule, id)`, so emission order never
leaks. The only I/O is the `buf` subprocess inside `run_buf_lint` / `lint_protobuf`.

## Tests

`tests/test_proto_lint.py` — every native rule fires on a defective model driven through the real
MFI-9.2 normalizer over synthetic descriptor sets (no `buf`), and a clean (versioned, no-`required`,
gap-free) model yields no `protobuf.*` findings; the pack is registered under `protobuf`; the `buf`
mapping (namespacing, `warning` fold, path building, JSON-Lines parsing, single-mapping + empty-input
degradation); `run_buf_lint` driven with an injected fake runner (clean exit, exit-100 violations,
build-failure / unavailable / timeout error mapping, lint `buf.yaml` materialisation); and the merge
pulls `buf` findings into the score and degrades gracefully without a report. A gated end-to-end test
runs the real bundled `buf` over the committed fixtures when it resolves in the environment.
