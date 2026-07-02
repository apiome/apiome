# AsyncAPI Lint Pack (MFI-8.3)

> **Status:** native rule pack + Spectral merge — `src/app/asyncapi_lint.py`
> **Issue:** [#3761](https://github.com/objectified-project/objectified/issues/3761) ·
> **Epic:** MFI-EPIC-8 (#3723) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Quality signals for event-driven (AsyncAPI) APIs. It is the **first concrete format pack** on
the [lint engine](./lint_engine_spi.md) (MFI-4.1) and rolls up through the same
score / grade / `report_fingerprint` formula as every other format (MFI-4.2). It has two
complementary halves that merge into one score:

```
 lint_asyncapi_result(model, parse_result) ─▶ spectral_findings(parse_result.diagnostics) ─┐
                                              + CommonRulePack.lint(model)                  ├▶ assemble_lint_result
                                              + AsyncApiRulePack.lint(model)                ─┘   (one 0–100 score)
```

## Native rules (`AsyncApiRulePack`)

Pure, deterministic rules over the [canonical model](./canonical_model.md) — no I/O — so they
run on the always-on lint path even when no external linter is available. The pack is
registered under **both** `asyncapi-2` and `asyncapi-3` (the format keys the MFI-8.2
normalizer emits; the two families normalize into the same shape, so the rules are identical).

| `rule_id`                          | Group         | Severity | Checks                                            |
|------------------------------------|---------------|----------|---------------------------------------------------|
| `asyncapi.message-missing-name`    | documentation | info     | Every event message carries an author-given name  |
| `asyncapi.message-unstable-name`   | naming        | warning  | Message name is author-chosen, not generator output |
| `asyncapi.message-missing-payload` | structure     | warning  | Every event message declares a payload (named `payload` **or** inline `payload_schema`) |
| `asyncapi.server-missing-protocol` | structure     | warning  | Every server declares its transport protocol (kafka/amqp/mqtt/ws/…) |
| `asyncapi.server-missing-security` | structure     | info     | Every server declares a security requirement (kept by the normalizer in `Server.extras["security"]`) |

`message-unstable-name` reuses the shared import-stability heuristic
(`app.lint_engine.is_unstable_name`), so an auto-generated message name like `InlinePayload2`
is flagged exactly like an unstable type/field name — such names rarely survive a re-import and
wreck the diff alignment versioning (MFI-3.x) depends on. `server-missing-security` is `info`
(not every broker genuinely needs auth), the rest are `warning`/`info` per the table.

Servers have no `key` on the canonical model, so a server finding's path is
`servers.{name or url}` — its authored handle when present, else its URL.

## Spectral findings (`spectral_findings`)

The authoritative **`spectral:asyncapi`** ruleset (v2 *and* v3) is already executed by
`@asyncapi/parser` during MFI-8.1 parse — i.e. we *wrap* `extends: spectral:asyncapi` through
the bundled parser rather than shipping a second copy of Spectral. Its findings surface as
[`AsyncApiDiagnostic`](../src/app/asyncapi_parser.py) items on the parse result;
`spectral_findings` maps each into a `LintFinding`:

- **rule** is namespaced `asyncapi.spectral.<code>` (e.g. `asyncapi.spectral.asyncapi-info-contact`),
  so Spectral findings group cleanly against the `asyncapi.*` native rules and `common.*`. A
  blank code becomes `asyncapi.spectral.unknown`.
- **category** is `spectral`.
- **severity** folds Spectral's four levels into the scorer's three: `error`/`warning`/`info`
  pass through and `hint` folds to `info` (so it still gently affects the score).
- **path** is the diagnostic's path, or `(document)` when Spectral reports no path.

## Merge entry points

| Function | Sync? | Use |
|----------|-------|-----|
| `lint_asyncapi_result(model, parse_result=None)` | sync, pure | The integration seam. Merges Spectral (from an already-obtained parse result) + native + common. **Spectral is opt-in and degrades gracefully**: pass `parse_result=None` (or one with no diagnostics) and the native + common packs still produce a deterministic score. The MFI-8.5 import pipeline, which already holds the parse result and the model, calls this. |
| `lint_asyncapi(raw, *, runner=None, timeout=None)` | async | Convenience that ties MFI-8.1 (parse + Spectral) and MFI-8.2 (normalize) to this pack end-to-end from raw source. Raises `AsyncApiParseError` when the parser is unavailable/times out or the document is invalid (no document to normalize). |

## Determinism & purity

Same as the engine: the native pack and the Spectral mapping are pure and deterministic;
`assemble_lint_result` re-sorts by `(path, rule, id)`, so emission order never leaks. The only
I/O is the parser invocation inside the async `lint_asyncapi` (and the gated end-to-end tests).

## Tests

`tests/test_asyncapi_lint.py` — every native rule fires on a defective model and a clean,
fully documented model scores 100/A; the pack is registered under both families and v2/v3 lint
identically; the Spectral mapping (namespacing, severity fold, blank-code/empty-path handling);
the merge pulls Spectral findings into the score and degrades gracefully without a parse
result; an end-to-end seam suite drives `lint_asyncapi` for v2 + v3 through a fake runner that
replays the parser contract; and a **gated** suite lints the real `2.6`/`3.0`/`3.1` fixtures
through the bundled parser when it is present.
