# GraphQL Lint Pack (MFI-10.4)

> **Status:** native rule pack + graphql-eslint merge — `src/app/graphql_lint.py`
> **Issue:** [#3773](https://github.com/objectified-project/objectified/issues/3773) ·
> **Epic:** MFI-EPIC-10 (#3725) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Quality signals for GraphQL (graph) APIs. Like the [AsyncAPI pack](./asyncapi_lint.md)
(MFI-8.3) it rides the [lint engine](./lint_engine_spi.md) (MFI-4.1) and rolls up through the
same score / grade / `report_fingerprint` formula as every other format (MFI-4.2). It has two
complementary halves that merge into one score:

```
 lint_graphql_result(model, eslint_report) ─▶ eslint_findings(eslint_report) ─┐
                                              + CommonRulePack.lint(model)     ├▶ assemble_lint_result
                                              + GraphqlRulePack.lint(model)    ─┘   (one 0–100 score)
```

Unlike the AsyncAPI seam, the whole GraphQL toolchain in this service is **pure Python**
(`graphql-core`; see MFI-10.1/10.2/10.3), so the native pack alone fully satisfies the
acceptance criteria *“lints SDL; findings scored”* with no Node dependency on the always-on
path.

## Native rules (`GraphqlRulePack`)

Pure, deterministic rules over the [canonical model](./canonical_model.md) — no I/O, no Node —
so they run on the always-on lint path (i.e. the import-time score, MFI-4.2) even when the
`graphql-eslint` CLI is absent. The pack is registered under the **`graphql`** format key (the
one the MFI-10.2 normalizer emits). The rules encode the SDL-checkable semantics of the three
`graphql-eslint` configs the roadmap names:

| `rule_id`                                | Group         | Severity | graphql-eslint config | Checks |
|------------------------------------------|---------------|----------|-----------------------|--------|
| `graphql.naming-type-pascal-case`        | naming        | warning  | naming-convention     | Type/interface/union/enum/scalar/input names are PascalCase |
| `graphql.naming-field-camel-case`        | naming        | warning  | naming-convention     | Object/input fields **and** root-operation fields are camelCase |
| `graphql.naming-argument-camel-case`     | naming        | warning  | naming-convention     | Operation arguments are camelCase |
| `graphql.naming-enum-value-upper-case`   | naming        | warning  | naming-convention     | Enum values are `UPPER_CASE` |
| `graphql.enum-value-missing-description` | documentation | info     | require-description    | Every enum value describes itself |
| `graphql.argument-missing-description`   | documentation | info     | require-description    | Every operation argument describes itself |
| `graphql.require-deprecation-reason`     | documentation | warning  | schema-recommended     | A `@deprecated` entity carries a (non-blank) reason |

**Why these `require-description` rules and not more?** The cross-format `CommonRulePack`
already flags missing **type / field / operation / message** descriptions for every paradigm,
so the GraphQL pack only adds the gaps it does not cover — **enum values** and **operation
arguments** — rather than duplicating findings.

**`require-deprecation-reason` nuance.** `graphql-core` fills a bare `@deprecated` with the
spec-default reason (`"No longer supported"`), so over the normalized model this native rule
fires on an *explicitly empty* `reason: ""`. The authoritative bare-`@deprecated` check is
graphql-eslint's own rule, merged via `eslint_findings` (below) once MFI-4.3 supplies it.

Paths mirror the common pack's coordinates so a defect carries the same path regardless of
which pack reports it: `types.{type}`, `types.{type}.fields.{field}`,
`types.{type}.values.{value}`, `services.{root}.operations.{op}`, and
`services.{root}.operations.{op}.arguments.{arg}`.

## graphql-eslint findings (`eslint_findings`)

The authoritative **`graphql-eslint`** configs (`schema-recommended` + `require-description` +
`naming-convention`) are a Node linter. Rather than re-implement every rule, `eslint_findings`
**wraps** the linter's verdicts: it maps `graphql-eslint`'s standard ESLint JSON output — a list
of file-result objects `{ "filePath", "messages": [{ "ruleId", "severity", "message", "line",
"column" }] }` — into `LintFinding`s:

- **rule** is the plugin rule id re-namespaced `graphql.eslint.<rule>` (e.g.
  `@graphql-eslint/naming-convention` → `graphql.eslint.naming-convention`), so it groups
  cleanly against the `graphql.*` native rules and `common.*`. A `null` rule id (an ESLint
  fatal/parse message) becomes `graphql.eslint.fatal`.
- **category** is `graphql-eslint`.
- **severity** folds ESLint's numeric levels into the scorer's three: `2` → `error`, `1` →
  `warning`, anything else → `info`.
- **path** is `{filePath}:{line}:{column}` (degrading to `{filePath}:{line}` or `{filePath}`,
  and to `(sdl)` when the file path is blank).

Running the `graphql-eslint` CLI itself is the job of the generic **external-linter adapter**
(MFI-4.3) over the polyglot [toolchain runner](../src/app/toolchain_runner.py); the moment that
adapter feeds this pack `graphql-eslint` output, it is scored alongside the native findings —
exactly as MFI-4.3 requires of an external-linter adapter (failures degrade gracefully to the
native packs).

## Merge entry points

| Function | Use |
|----------|-----|
| `lint_graphql_result(model, eslint_report=None)` | The integration seam. Merges graphql-eslint output + native + common. **graphql-eslint is opt-in and degrades gracefully**: pass `eslint_report=None` (or empty) and the native + common packs still produce a deterministic score. The MFI-10.5/10.6 import pipeline, which already holds the normalized model, calls this. |
| `lint_graphql(raw, *, source_label=None, eslint_report=None)` | Convenience that ties MFI-10.1 (parse + build schema) and MFI-10.2 (normalize) to this pack end-to-end from raw SDL. Raises `GraphQlParseError` when `raw` is not valid SDL (no schema to lint). |

## Determinism & purity

The native pack and the graphql-eslint mapping are pure and deterministic; entities are visited
in sorted-key order and `assemble_lint_result` re-sorts by `(path, rule, id)`, so emission order
never leaks. The only I/O is the schema build inside `lint_graphql`.

## Tests

`tests/test_graphql_lint.py` — every native rule fires on a defective (but valid) schema driven
through the real MFI-10.1 parser + MFI-10.2 normalizer, and a clean, fully documented/named
schema yields no `graphql.*` findings; the pack is registered under `graphql`; the graphql-eslint
mapping (namespacing, severity fold, fatal/`null` rule id, path building, single-mapping +
empty-input degradation); and the merge pulls graphql-eslint findings into the score and degrades
gracefully without a report — all pure (no DB/network/Node).
