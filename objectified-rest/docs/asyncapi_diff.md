# AsyncAPI Diff / Breaking-Change Classifier (MFI-8.4)

> **Status:** structural baseline + `@asyncapi/diff` overlay — `src/app/asyncapi_diff.py`
> **Issue:** [#3762](https://github.com/objectified-project/objectified/issues/3762) ·
> **Epic:** MFI-EPIC-8 (#3723) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The AsyncAPI provider on the [breaking-change classifier SPI](./breaking_change_spi.md)
(MFI-3.3). It answers, for two versions of an event-driven API, *is each change safe to ship,
or will it break callers?* — by **wrapping the authoritative `@asyncapi/diff` tool** and mapping
its verdict onto the canonical [`ModelDiff`](./diff_spi.md) so every change the diff lists gets
a [`Severity`](./breaking_change_spi.md) that surfaces on the diff view.

It has two layers, mirroring how MFI-8.3 layered native rules under Spectral:

```
 classify_asyncapi(base, target) ─▶ diff(base, target)                          (canonical ModelDiff)
                                    + BuiltinBreakingChangeClassifier.classify   (structural baseline)
                                    + @asyncapi/diff over base.raw / target.raw   (authoritative verdict)
                                    ─────────────────────────────────────────▶  overlay ▶ ClassificationResult
```

## Structural baseline (`AsyncApiBreakingChangeClassifier`)

`AsyncApiBreakingChangeClassifier` subclasses the format-agnostic
`BuiltinBreakingChangeClassifier`, so its **synchronous, pure** `classify` already grades an
AsyncAPI diff from structure alone (a removed channel/operation/message is breaking, an added
one safe, a narrowed type breaking, …). It is registered under **both** `asyncapi-2` and
`asyncapi-3` (the MFI-8.2 normalizer's format keys; the two families normalize into the same
shape and `@asyncapi/diff` ships a ruleset for each), so the sync SPI dispatch
(`app.breaking_change.classify`) resolves it for any AsyncAPI artifact — even where no Node
toolchain is present. The classifier modules self-register lazily via
`breaking_change.load_format_breaking_change_classifiers()`, mirroring the lint engine.

## `@asyncapi/diff` overlay (`classify_async` / `classify_asyncapi`)

The authoritative grading is the **async** `classify_async` (and the module convenience
`classify_asyncapi(base, target)`), because the tool shells out asynchronously through the
[toolchain runner](./toolchain_packaging.md) (the SPI itself is sync). It:

1. starts from the structural baseline grades;
2. runs `@asyncapi/diff` over the two **already-validated and dereferenced** documents MFI-8.1
   preserved on `CanonicalApi.raw` (fed to the bundled `asyncapi-diff` tool as
   `{"old": …, "new": …}` on `stdin`);
3. **overlays** the tool's verdict — `breaking` → `BREAKING`, `non-breaking` → `SAFE` — onto a
   change wherever the tool classified it **and** it joins onto a canonical entity.

A change the tool reports `unclassified`, or any change that does not join cleanly onto a diffed
entity (a deep payload edit, a server binding, document metadata), keeps the conservative
structural grade — so the result never silently downgrades a removal the tool had no opinion on.

### Joining a tool change to a canonical entity

`@asyncapi/diff` reports each change at an RFC-6901 JSON Pointer (the Node wrapper decodes it
into plain, unescaped segments). These coordinates join onto a canonical `(category, key)`:

| Tool pointer (decoded)                          | Canonical entity | Key                                                   |
|-------------------------------------------------|------------------|-------------------------------------------------------|
| `channels` / `<mapName>`                        | channel          | the channel **address** (v3 `address`; v2 map key)    |
| `operations` / `<opName>`                       | operation (v3)   | the operation **name**                                |
| `channels` / `<addr>` / `publish`\|`subscribe`  | operation (v2)   | `operationId`, else `"{action} {address}"`            |
| anything deeper (`…/messages/…`, `/info/…`)     | — (not joined)   | keeps the structural grade                            |

This matches the key grammar `app.normalizer.Keys` assigns, so the tool verdict lands on the
same change the diff renders.

## Graceful degradation

Like MFI-8.3's opt-in Spectral half, the tool-backed path **degrades gracefully** and always
returns a deterministic `ClassificationResult`:

* no source documents on `raw` (e.g. normalized with `include_raw=False`) → structural baseline;
* the `asyncapi-diff` tool is not installed / times out / errors → structural baseline (logged).

In every case the result's `classifier` is `asyncapi-diff` and its grades are 1:1 with, and in
the same order as, the diff's changes.

## Result shape

`classify_asyncapi` returns the standard MFI-3.3
[`ClassificationResult`](./breaking_change_spi.md): a per-change `ChangeClassification`
(`severity` + stable `rule_id` — `asyncapi-diff.breaking` / `asyncapi-diff.non-breaking` for a
tool verdict, else the structural rule id — + `rationale`), the worst `overall_severity`, the
`breaking` publish-gate boolean, and a per-severity tally. It round-trips losslessly to JSONB
for persistence alongside the version diff (MFI-3.4).

## Tests

`tests/test_asyncapi_diff.py` — the tool seam over a fake runner (wrapper contract, malformed
changes skipped, infrastructure failures → `AsyncApiDiffError`, both documents on `stdin`); the
join helper for v2 + v3 (channel address resolution, operation name / `operationId`, deep edits
not joined); the overlay (a breaking + a safe change graded correctly, `unclassified` and
non-joining changes keep the structural grade); graceful degradation (no documents / tool
unavailable); SPI registration for both families and the sync structural dispatch; determinism
and JSON round-trip; and a **gated** end-to-end class over the real bundled `@asyncapi/diff`.
