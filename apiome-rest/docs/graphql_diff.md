# GraphQL Diff / Breaking-Change Classifier (MFI-10.5)

> **Status:** structural baseline + GraphQL-Inspector overlay — `src/app/graphql_diff.py`
> **Issue:** [#3774](https://github.com/objectified-project/objectified/issues/3774) ·
> **Epic:** MFI-EPIC-10 (#3725) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The GraphQL provider on the [breaking-change classifier SPI](./breaking_change_spi.md)
(MFI-3.3). It answers, for two versions of a GraphQL schema, *is each change safe to ship, or
will it break callers?* — by **wrapping the authoritative GraphQL-Inspector `diff`** and mapping
its verdict onto the canonical [`ModelDiff`](./diff_spi.md) so every change the diff lists gets a
[`Severity`](./breaking_change_spi.md) that surfaces on the diff view.

It has two layers, mirroring how MFI-8.4 layered `@asyncapi/diff` over the AsyncAPI structural
baseline:

```
 classify_graphql(base, target) ─▶ diff(base, target)                          (canonical ModelDiff)
                                   + BuiltinBreakingChangeClassifier.classify   (structural baseline)
                                   + GraphQL-Inspector over base.raw / target.raw (authoritative verdict)
                                   ─────────────────────────────────────────▶  overlay ▶ ClassificationResult
```

## Structural baseline (`GraphQlBreakingChangeClassifier`)

`GraphQlBreakingChangeClassifier` subclasses the format-agnostic
`BuiltinBreakingChangeClassifier`, so its **synchronous, pure** `classify` already grades a
GraphQL diff from structure alone (a removed type/field is breaking, an added one safe, an enum's
variant set or a field's argument list moving is dangerous). It is registered under the
`graphql` format key (the one the MFI-10.2 normalizer emits), so the sync SPI dispatch
(`app.breaking_change.classify`) resolves it for any GraphQL artifact — even where no Node
toolchain is present. The classifier module self-registers lazily via
`breaking_change.load_format_breaking_change_classifiers()`, mirroring the lint engine.

## GraphQL-Inspector overlay (`classify_async` / `classify_graphql`)

The authoritative grading is the **async** `classify_async` (and the module convenience
`classify_graphql(base, target)`), because the tool shells out asynchronously through the
[toolchain runner](./toolchain_packaging.md) (the SPI itself is sync). It:

1. starts from the structural baseline grades;
2. runs GraphQL-Inspector's `diff` over the two canonical **SDL** strings MFI-10.2 preserved on
   `CanonicalApi.raw` (fed to the bundled `graphql-inspector-diff` tool as
   `{"old": …, "new": …}` on `stdin`, where each builds into a `graphql-js` schema before
   diffing);
3. **overlays** the tool's verdict — `BREAKING` → `BREAKING`, `DANGEROUS` → `DANGEROUS`,
   `NON_BREAKING` → `SAFE` — onto a change wherever it joins onto a canonical entity this diff
   reports.

A change whose schema-coordinate path does not join cleanly onto a diffed entity (a custom
directive, deep schema-root metadata) keeps the conservative structural grade — so the result
never silently downgrades a removal the tool had no opinion on. Unlike `@asyncapi/diff`,
GraphQL-Inspector always assigns one of its three criticality levels to every change it reports
(there is no "unclassified" tier), so the mapping onto `Severity` is total.

### Joining a tool change to a canonical entity

GraphQL-Inspector reports each change at a **dot-path schema coordinate** — the same grammar
`app.normalizer.Keys` assigns canonical type/field/operation/enum-value keys under
(`Type.field`, bare `Type`, `Enum.VALUE`). The join is therefore a key lookup against the diff's
own entities, not structural decoding:

| Tool path (segments)            | Lookup order                              | Canonical entity (when it matches)                    |
|----------------------------------|--------------------------------------------|---------------------------------------------------------|
| `Type.field` / `Root.field`     | exact 2-segment key, then bare `Type`/`Root` | field or operation, else the owning type/root           |
| `Enum.VALUE` / `Union.Member`   | exact 2-segment key (rarely present), then bare `Enum`/`Union` | the *owning type* — enum values / union members are folded into the type's self-projection, not separately keyed |
| bare `Type`                      | exact 1-segment key                       | type                                                     |
| anything that matches no diffed entity | — (not joined)                      | keeps the structural grade                               |

The lookup is built fresh from `key_to_category = {c.key: c.category for c in baseline.classifications}`
— i.e. exactly the entities *this diff* reports — so a change that does not correspond to any
diffed entity is never misjoined; no enumeration of GraphQL-Inspector's full change-type catalog
is required.

## Graceful degradation

Like MFI-8.4's AsyncAPI overlay, the tool-backed path **degrades gracefully** and always returns
a deterministic `ClassificationResult`:

* no canonical SDL on `raw` (e.g. normalized with `include_raw=False`) → structural baseline;
* the `graphql-inspector-diff` tool is not installed / times out / errors → structural baseline
  (logged).

In every case the result's `classifier` is `graphql-inspector-diff` and its grades are 1:1 with,
and in the same order as, the diff's changes.

## Result shape

`classify_graphql` returns the standard MFI-3.3
[`ClassificationResult`](./breaking_change_spi.md): a per-change `ChangeClassification`
(`severity` + stable `rule_id` — `graphql-inspector-diff.<CHANGE_TYPE>` for a tool verdict, else
the structural rule id — + `rationale`), the worst `overall_severity`, the `breaking`
publish-gate boolean, and a per-severity tally. It round-trips losslessly to JSONB for
persistence alongside the version diff (MFI-3.4).

## Tests

`tests/test_graphql_diff.py` — the tool seam over a fake runner (wrapper contract, malformed
changes skipped, infrastructure failures → `GraphQlDiffError`, both SDL strings on `stdin`); the
join helper (field/operation/type exact matches, enum-value/union-member folding onto the owning
type, non-joining changes); the overlay (a removed field graded breaking, an added enum value
graded dangerous — the MFI-10.5 acceptance criterion — and a safe addition graded safe);
graceful degradation (no SDL / tool unavailable); SPI registration and the sync structural
dispatch; determinism and JSON round-trip; and a **gated** end-to-end class over the real
bundled GraphQL-Inspector.
