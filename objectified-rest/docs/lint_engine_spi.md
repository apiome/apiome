# Lint Engine + Rule-Pack SPI (MFI-4.1)

> **Status:** cross-format common pack + per-format rule-pack SPI — `src/app/lint_engine.py`
> **Issue:** [#3746](https://github.com/objectified-project/objectified/issues/3746) ·
> **Epic:** MFI-EPIC-4 (#3719) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The original linter ([`schema_lint.py`](../src/app/schema_lint.py)) targets one format: it
walks a reconstructed OpenAPI/JSON-Schema document and emits deterministic `LintFinding`s with
a 0–100 score, an A–F grade, and a stable `report_fingerprint`. That shape is exactly right,
but it is hard-wired to OpenAPI. Every other importable format (gRPC/protobuf, AsyncAPI,
GraphQL, Avro, …) normalizes into the single [`CanonicalApi`](./canonical_model.md) model
(MFI-2.1), so the quality checks should be written **once** over that model and reused for
every paradigm.

`lint_engine.py` generalizes the linter into a pluggable **rule-pack engine**, mirroring the
[fingerprint-hasher](./fingerprint_spi.md) and [breaking-change-classifier](./breaking_change_spi.md)
registries beside it.

```
 lint_canonical_model(api) ─▶ CommonRulePack.lint(api)            ─┐
                              + get_rule_pack(api.format)?.lint(api) ├▶ assemble_lint_result(findings)
                              + extra_findings                     ─┘    (sort + score + grade + fingerprint)
```

The OpenAPI behavior is **unchanged**: `schema_lint.lint_openapi_spec` remains the OpenAPI
rule pack and reproduces its current findings exactly (its tests are untouched). Both linters
share `schema_lint.assemble_lint_result`, so the score / grade / fingerprint formula is
identical no matter which pack produced the findings.

## Rules and rule packs

A **rule** (`LintRule`) is a stable id + group + severity bound to a pure `check`:

| Field        | Meaning                                                                          |
|--------------|----------------------------------------------------------------------------------|
| `rule_id`    | Stable, namespaced id (`common.type-missing-description`); part of the finding id |
| `category`   | The rule's group (`documentation` / `naming` / `structure` / …)                  |
| `severity`   | `error` / `warning` / `info` — drives the score penalty                          |
| `check`      | Pure generator yielding `(path, message)` for each defect over a `CanonicalApi`  |

A **rule pack** (`RulePack`) is an ordered list of rules. The engine runs each rule, turns
every `(path, message)` into a `LintFinding` tagged with the rule's `rule_id` / `category` /
`severity`, and the finding `id` is the same stable `path|rule|message` hash the OpenAPI linter
uses — so a defect has one durable id no matter which pack reported it.

## The common pack (`CommonRulePack`)

The format-agnostic pack always runs, for every paradigm. It encodes the two cross-format
concerns the roadmap calls out over the canonical entities every format normalizes into:

| `rule_id`                            | Group         | Severity | Checks                                  |
|--------------------------------------|---------------|----------|-----------------------------------------|
| `common.api-missing-description`     | documentation | info     | The artifact carries a top-level description |
| `common.type-missing-description`    | documentation | warning  | Every named type describes itself        |
| `common.field-missing-description`   | documentation | info     | Every field describes itself             |
| `common.operation-missing-description` | documentation | warning | Every operation describes what it does   |
| `common.message-missing-description` | documentation | info     | Every message payload describes itself   |
| `common.channel-missing-description` | documentation | info     | Every event channel describes itself     |
| `common.unstable-type-name`          | naming        | warning  | Type name is author-chosen, not generator output |
| `common.unstable-field-name`         | naming        | warning  | Field name is author-chosen, not generator output |

**Unstable identifiers** are names that look machine-generated or positional rather than
author-chosen (`InlineObject1`, `InlineResponse200`, `AnonymousType3`, `body`, `schema1`,
`type_0`, `_12`, an empty name). Such names rarely survive a re-import, which wrecks the diff
alignment versioning (MFI-3.x) depends on. The heuristic is deliberately **conservative** — it
only flags the well-known generator outputs, so a normal author name (`Pet`, `userId`,
`GetPet`) is never flagged — and a format pack can sharpen it for its own generator conventions.

The common pack's `format` is empty, so it is **never registered** (it runs unconditionally)
and `register_rule_pack` rejects any pack with an empty format.

## Per-format rule-pack SPI (`RulePack`)

A format whose ecosystem has its own hygiene rules registers a pack under its format key. It
adds the specifics its ecosystem cares about *on top of* the common pack.

```python
from app.lint_engine import RulePack, LintRule

class GraphqlRulePack(RulePack, register=True):
    format = "graphql"
    pack_id = "graphql"

    def rules(self):
        return [
            LintRule(
                rule_id="graphql.enum-value-screaming-snake",
                category="naming",
                severity="warning",
                description="GraphQL enum values are conventionally SCREAMING_SNAKE_CASE.",
                check=self._check_enum_values,
            ),
        ]

    def _check_enum_values(self, api):
        for t in api.types:
            for v in t.enum_values:
                if not v.name.isupper():
                    yield (f"types.{t.key}", f"Enum value '{v.name}' is not SCREAMING_SNAKE_CASE.")
```

- `register=True` (or `register_rule_pack(cls)`) registers under `format`; re-registering the
  same class is a no-op, a *different* class for the same format raises. Look up with
  `get_rule_pack(format)`; list with `available_lint_formats()`.
- The only required method is `rules()`. A pack that needs to run its rules differently can
  override `lint(api)`; the engine re-sorts the combined findings, so a pack need not sort.

## Usage

```python
from app.lint_engine import lint_canonical_model

result = lint_canonical_model(api)            # common pack + api.format's pack, if any
print(result.score, result.grade)            # e.g. 87 "B"
for f in result.findings:                     # sorted by (path, rule, id)
    print(f.path, f.rule, f.severity, f.message)
print(result.report_fingerprint)             # stable hash for audit / API identity
```

Pre-built findings (e.g. compatibility flags from
[`breaking_change`](./breaking_change_spi.md)) merge into the report and the score via
`extra_findings`, exactly as `schema_lint.lint_openapi_spec` accepts them:

```python
result = lint_canonical_model(api, extra_findings=compatibility_findings)
```

## Determinism & purity

- **Deterministic.** The same model always yields the same findings, score, grade, and
  fingerprint. Entities are visited in sorted-key order and `assemble_lint_result` re-sorts by
  `(path, rule, id)`, so emission order never leaks into the output.
- **Pure.** No database, no network, no clock. The caller passes a fully built model, and the
  input is never mutated.

## Relationship to the other MFI-EPIC-4 pieces

- **MFI-4.2 (score/grade/fingerprint reuse) ✅.** Rolls the findings up to a stored score/grade
  per version, reusing `assemble_lint_result`'s formula. The import-source `LintReport` now
  mirrors `LintResult` (score / grade / `report_fingerprint` / tallies) via
  `LintReport.from_lint_result`; the SPI default `ImportSource.lint()` rolls up through
  `lint_canonical_model`; and `import_source_pipeline.capture_canonical_quality_score` persists
  the roll-up onto the revision's `versions.quality_*` columns (one `api_artifacts` row per
  `versions` row, so it reuses the V124 columns with no new migration) — the canonical analogue
  of the spec (`_capture_version_quality_score`) and MCP (`_capture_mcp_version_score`) capture
  seams.
- **MFI-4.3 (external-linter adapter).** Wraps Spectral / Buf lint / smithy-linters / graphql-eslint
  via the [toolchain runner](./toolchain_runner.md) and maps their output into `LintFinding`s
  that merge with the native packs. The [AsyncAPI lint pack](./asyncapi_lint.md) (MFI-8.3) is
  the first realization of this: it merges the `spectral:asyncapi` diagnostics that
  `@asyncapi/parser` already produces (MFI-8.1) into the score alongside its native rules,
  degrading gracefully to the native packs when no parse result is supplied.
- **MFI-8.3 (AsyncAPI lint pack) ✅.** The first concrete format pack — see
  [`asyncapi_lint.md`](./asyncapi_lint.md). `AsyncApiRulePack` registers native event-API rules
  (message names, missing payload schema, server protocol/security) under `asyncapi-2` /
  `asyncapi-3`, and `lint_asyncapi_result` folds in the `spectral:asyncapi` findings.
- **MFI-4.4 (REST/UI/CLI surfacing).** Exposes findings + score per version everywhere, reusing
  the `lint_routes.py` shape for canonical artifacts.
