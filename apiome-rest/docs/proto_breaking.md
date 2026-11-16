# Protobuf Breaking-Change Classifier (MFI-9.5)

> **Status:** structural baseline + `buf breaking` overlay — `src/app/proto_breaking.py`
> **Issue:** [#3768](https://github.com/objectified-project/objectified/issues/3768) ·
> **Epic:** MFI-EPIC-9 (#3724) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Compatibility grading for gRPC / Protocol Buffers (RPC) APIs. It is the Protobuf provider on the
[breaking-change classifier SPI](./breaking_change.md) (MFI-3.3), mirroring how MFI-10.5 wrapped
GraphQL-Inspector and MFI-8.4 wrapped `@asyncapi/diff`: it grades a canonical `ModelDiff`
*breaking-vs-safe* and, when the `.proto` sources are available, sharpens that with the format's
authoritative tool — **`buf breaking`**.

```
 classify_protobuf(base, target, against_files, target_files, strictness)
   ├─ structural baseline    ProtobufBreakingChangeClassifier.classify(...)   (per-change, 1:1, pure)
   └─ buf breaking overlay   run_buf_breaking(new, --against baseline)        (authoritative verdict)
```

Two layers, same shape as the GraphQL / AsyncAPI providers.

## Structural baseline (`ProtobufBreakingChangeClassifier`)

The classifier **subclasses** the format-agnostic `BuiltinBreakingChangeClassifier`, so its
*synchronous, pure* `classify` / `classify_change` already grade a Protobuf diff from structure
alone. It is registered under the **`protobuf`** format key (the one the MFI-9.2 normalizer emits),
so the sync SPI dispatch (`app.breaking_change.classify`) resolves it for a Protobuf artifact even
when no `buf` binary is present. The built-in ruleset is already wire-aware:

- a reused wire `field_number` and a changed field `type` → **`breaking`**;
- a removed message / field / enum value → **`breaking`**;
- an added *optional* field → **`safe`**; an added *mandatory* field → **`dangerous`**.

That baseline alone satisfies the acceptance criteria (a field-number reuse / type change is
breaking, a safe addition passes) with no external tool.

### Categories and Protobuf rules (XPC-4.3, #5747)

The classifier grades at a **category** — `ProtobufBreakingChangeClassifier(category="FILE")`
(any case; default `WIRE_JSON`; the sync dispatch uses the default). On top of the built-in
ruleset, `app.proto_breaking_rules.category_findings(base, target)` grades the Protobuf-specific
changes under **all four** categories from the canonical model alone:

| Rule slug | `WIRE` | `WIRE_JSON` | `PACKAGE` | `FILE` |
|-----------|--------|-------------|-----------|--------|
| `reserved-removed` | dangerous | dangerous | dangerous | dangerous |
| `reserved-number-reused`, `reserved-name-reused` | breaking | breaking | breaking | breaking |
| `field-deleted-unreserved` (number free) | dangerous | breaking | breaking | breaking |
| `field-deleted-unreserved` (name free) | safe | breaking | breaking | breaking |
| `field-deleted` (both reserved) | safe | safe | breaking | breaking |
| `field-renamed` (same number and type) | safe | breaking | breaking | breaking |
| `field-number-reused` (new type) | breaking | breaking | breaking | breaking |
| `json-name-changed` | safe | breaking | breaking | breaking |
| `type-moved-file` | safe | safe | safe | breaking |
| `package-changed` | breaking | breaking | breaking | breaking |
| `enum-value-number-reused` (renamed) | safe | breaking | breaking | breaking |
| `enum-value-number-changed` | breaking | breaking | breaking | breaking |
| `oneof-membership-changed` | breaking | breaking | breaking | breaking |
| `cardinality-changed`, `required-changed` | breaking | breaking | breaking | breaking |
| `presence-changed` (proto3 `optional`) | safe | safe | breaking | breaking |

Rule ids are `protobuf.<category>.<slug>`, the category being the least strict one where the rule
is at its worst. Every grade's rationale starts with the category graded at (`[WIRE_JSON] …`); a
rule's rationale adds its grade under all four. A finding joins the diff change(s) it describes
and takes the worst of its grade and the baseline grade of whatever else moved on that change; a
modified change confined to reservations / oneof declarations is `protobuf.compatible` (safe); a
finding that joins no change — a file move, which the diff does not see — goes to `unattributed`.

The rules read the normalizer's `reserved_ranges` / `reserved_names`, `label`, `proto3_optional`,
`field_presence`, `oneof` and `json_name` (recorded only when not the `protoc` default) extras, and
`CanonicalApi.extras["protobuf_files"]` (file → package, syntax and top-level types; unhashed).

The grades follow Buf except for two roadmap decisions — a removed reservation is dangerous, and an
unreserved field deletion is dangerous under `WIRE` — recorded as `known_disagreements` in the Buf
corpus (`tests/fixtures/proto_breaking_categories`; re-record with
`scripts/record_proto_breaking_fixtures.py`).

## `buf breaking` overlay (`run_buf_breaking` / `classify_async`)

The authoritative ruleset is **`buf breaking`** at a **configurable strictness**. Rather than
re-implement Protobuf's compatibility rules:

- **`run_buf_breaking(target_files, against_files, strictness=…)`** materialises the **new**
  (`target_files`) and **baseline** (`against_files`) `.proto` sources into two private scratch
  `buf` modules — the new one carrying a `buf.yaml` that enables the one breaking category for the
  strictness (`buf` reads breaking rules from the *input* module; `buf_breaking_module_yaml`), the
  baseline one carrying the plain build-only config (MFI-9.1's `BUF_MODULE_YAML`) — and runs
  `buf breaking <new> --against <baseline> --error-format=json` through the MFI-5.1 toolchain runner
  (no-network sandbox). Breaking changes make `buf` exit non-zero (code `100`); that is the *normal*
  outcome — its JSON findings are read off stdout and returned as a `ProtoBreakingResult`. An
  operational failure (`buf` absent, a timeout, a proto that does not build) raises
  `ProtoBreakingError`.
- **`breaking_changes(report)`** maps `buf breaking`'s newline-delimited JSON (`{ "path",
  "start_line", "start_column", "type", "message" }` per line) into `ProtoBreakingChange`s: the
  **rule** is the `buf` type re-namespaced `protobuf.buf-breaking.<type>` (e.g. `FIELD_SAME_TYPE` →
  `protobuf.buf-breaking.field_same_type`), and the **severity** is always `breaking` — `buf
  breaking` emits nothing for a safe change, so every finding is a break; the *strictness* is what
  controls which changes count.

### Strictness (`BufBreakingStrictness`)

`buf`'s four breaking categories form a containment hierarchy (widest-last). Default is
**`WIRE_JSON`** — the roadmap's "default for services": gRPC traffic is both binary and (via
transcoding) JSON, so both wire formats must stay compatible, while source-level recompiles are not
treated as hard breaks by default.

| Strictness  | Catches |
|-------------|---------|
| `WIRE`      | Binary wire breaks only (a field's wire type changed, a number reused incompatibly). |
| `WIRE_JSON` | `WIRE` + JSON breaks (a field / enum value renamed — JSON keys on names). **Default.** |
| `PACKAGE`   | `WIRE_JSON` + per-package source breaks (a deleted field / value / message; a moved declaration). |
| `FILE`      | Strictest: `PACKAGE` + per-file source breaks. |

### How the overlay maps to severities

`buf breaking`'s machine output is *file-scoped* (a proto file plus a line/column and a rule
`type`), not a schema-coordinate that joins onto one canonical entity — so, unlike GraphQL-Inspector
/ `@asyncapi/diff`, its verdict cannot be pinned to a single canonical key. The overlay therefore
applies `buf`'s verdict at the granularity `buf` provides:

- **`buf` reports a break** → the diff is breaking at this strictness: the structural per-change
  grades are kept (the best per-change attribution available) and each `buf` finding is added to
  `unattributed` (rule `protobuf.buf-breaking.<type>`), so the **overall** severity is `breaking`.
- **`buf` reports none** → the diff is wire/JSON-compatible at this strictness: the conservative
  structural over-approximations are **capped** down — any structural `breaking` grade becomes
  `dangerous` (compatible by the letter — e.g. a wire-compatible field deletion — but review
  warranted), while `safe` / `dangerous` grades stand.
- When `buf` and the structural rules disagree about whether the diff breaks, the rationales carry
  `overlay_disagreement`'s sentence (`disagreement: …`).

The result is a standard `ClassificationResult`, 1:1 with the diff's changes, so the severities
surface on the diff view exactly like every other format's. The fully-detailed authoritative `buf`
finding list is available separately as the `ProtoBreakingResult` from `run_buf_breaking`.

## Entry points

| Function | Use |
|----------|-----|
| `run_buf_breaking(target_files, against_files, strictness=…)` | The `buf breaking` wrapper. Returns a `ProtoBreakingResult` of the authoritative breaks. Raises `ProtoBreakingError` when `buf` cannot run. |
| `ProtobufBreakingChangeClassifier.classify_async(diff, base, target, against_files=…, target_files=…, strictness=…)` | The SPI overlay. Degrades to the structural baseline when the sources or the tool are unavailable. |
| `classify_protobuf(base, target, against_files=…, target_files=…, strictness=…)` | Convenience: diff `base` → `target` and grade it in one call (the async, tool-backed counterpart of `classify_models`). |

## Determinism & degradation

The structural baseline is pure and deterministic. The only I/O is the `buf` subprocess inside
`run_buf_breaking`. Every fall-through — no `.proto` sources supplied, or the `buf` tool
unavailable / erroring — keeps the structural baseline unchanged, so a deterministic result is
always returned.

## Tests

`tests/test_proto_breaking_categories.py` (XPC-4.3) — every Buf corpus case in every category,
without `buf` (recorded descriptor sets) and, when `buf` resolves, live; agreement with the recorded
`buf breaking` verdicts or a listed disagreement; the overlay replaying `buf`'s recorded output;
requesting a category; and the normalizer / emitter `json_name` and file record.

`tests/test_proto_breaking.py` — the classifier is registered under `protobuf` and the sync
dispatch resolves it; the structural baseline grades a field-number reuse and a type change as
breaking and a safe addition as safe (built through the real MFI-9.2 normalizer over synthetic
descriptor sets, no `buf`); the strictness `buf.yaml` names the right category (defaulting to
`WIRE_JSON`); the `buf breaking` mapping (namespacing, `breaking` severity, path/line handling,
JSON-Lines parsing, single-mapping + empty-input degradation); `run_buf_breaking` driven with an
injected fake runner (clean exit, exit-100 breaks, build-failure / unavailable / timeout error
mapping, the two scratch modules' breaking vs build-only `buf.yaml`); and the overlay forces
`breaking` when `buf` finds a break and caps to `dangerous` when `buf` finds the diff compatible. A
gated end-to-end test runs the real bundled `buf` over `.proto` sources (a `string → int32` type
change is breaking; an additive field passes) when it resolves in the environment.
