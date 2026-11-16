# AsyncAPI Diff / Breaking-Change Classifier (MFI-8.4, XPC-4.4)

> **Status:** side-aware structural baseline + `@asyncapi/diff` overlay — `src/app/asyncapi_diff.py`,
> `src/app/asyncapi_compatibility_rules.py`, `src/app/asyncapi_payload_compatibility.py`
> **Issues:** [#3762](https://github.com/objectified-project/objectified/issues/3762) (MFI-8.4) ·
> #5748 (XPC-4.4, channel and operation compatibility) ·
> **Epics:** MFI-EPIC-8 (#3723), XPC-EPIC-4 (#5745) · **Roadmaps:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`,
> `ROADMAP_CROSS_PROTOCOL_CONTRACTS.md`

The AsyncAPI provider on the [breaking-change classifier SPI](./breaking_change_spi.md)
(MFI-3.3). It answers, for two versions of an event-driven API, *is each change safe to ship,
or will it break callers?* — by **wrapping the authoritative `@asyncapi/diff` tool** and mapping
its verdict onto the canonical [`ModelDiff`](./diff_spi.md) so every change the diff lists gets
a [`Severity`](./breaking_change_spi.md) that surfaces on the diff view.

It has two layers, mirroring how MFI-8.3 layered native rules under Spectral:

```
 classify_asyncapi(base, target, mode) ─▶ diff(base, target)                     (canonical ModelDiff)
                                          + builtin grades                         (structural baseline)
                                          + asyncapi_compatibility_rules.evaluate  (per-side rules, read by mode)
                                          + @asyncapi/diff over base.raw / target.raw (authoritative verdict)
                                          ────────────────────────────────────▶   overlay ▶ ClassificationResult
```

## Structural baseline (`AsyncApiBreakingChangeClassifier`)

`AsyncApiBreakingChangeClassifier(mode=None)` subclasses the format-agnostic
`BuiltinBreakingChangeClassifier`, so every change first gets the built-in grade (a removed
channel/operation/message is breaking, an added one safe, a narrowed type breaking, …). Its
**synchronous, pure** `classify` then sharpens that grade with the per-side rules below. It is
registered under **both** `asyncapi-2` and
`asyncapi-3` (the MFI-8.2 normalizer's format keys; the two families normalize into the same
shape and `@asyncapi/diff` ships a ruleset for each), so the sync SPI dispatch
(`app.breaking_change.classify`) resolves it for any AsyncAPI artifact — even where no Node
toolchain is present. The classifier modules self-register lazily via
`breaking_change.load_format_breaking_change_classifiers()`, mirroring the lint engine.

## Per-side rules (XPC-4.4, `app.asyncapi_compatibility_rules`)

An event contract has two sides. Every rule grades both (`SideFinding.consumer` /
`SideFinding.producer`), and the classifier reads them by its `mode`:

| Side | Upgrades first | Checked by |
|------|----------------|-----------|
| consumer | new consumers, old producers | `BACKWARD`, `FULL` |
| producer | new producers, old consumers | `FORWARD`, `FULL` |

`severity_under(finding, mode)` keeps a checked side's grade and drops an unchecked side one tier
(breaking → dangerous, dangerous → safe); `_TRANSITIVE` modes grade like the plain mode (two
versions are compared). The default mode is `BACKWARD`.

| Change | Consumers | Producers | Rule id |
|--------|-----------|-----------|---------|
| channel address / template changed | breaking | dangerous | `asyncapi.consumer.address-changed` |
| address parameter added, no default | breaking | dangerous | `asyncapi.consumer.parameter-added` |
| address parameter added with default | safe | safe | `asyncapi.both.parameter-added-with-default` |
| protocol changed (server) | breaking | breaking | `asyncapi.both.protocol-changed` |
| server / channel / operation / message binding changed | breaking | breaking | `asyncapi.both.binding-changed` |
| operation `action` flipped | breaking | breaking | `asyncapi.both.action-flipped` |
| operation `reply` removed (3.x) | breaking | dangerous | `asyncapi.consumer.reply-removed` |
| message removed from the union | breaking | safe | `asyncapi.consumer.message-removed` |
| message added to the union | safe | dangerous | `asyncapi.producer.message-added` |
| payload `schemaFormat` changed language | breaking | breaking | `asyncapi.both.schema-format-changed` |
| payload accepted both ways by its check | safe | safe | `asyncapi.both.payload-compatible` |
| payload changed | by the payload's check | | `jsonschema.*`, `avro-compatibility.*`, `protobuf.*` |
| server added / removed / changed | dangerous | dangerous | `asyncapi.both.server-changed` |
| server / operation security changed | dangerous | dangerous | `asyncapi.both.security-changed` |

Rule ids are `asyncapi.<side>.<rule>` with the side the change is worst for (`both` when equal).
Each rationale reads `[<MODE>: <what it checks>] <what changed> (consumers: …, producers: …)`.

* **Pairing.** A channel's key is its address, so an address change is a removed + an added
  channel; they are paired (both graded `address-changed`) when the v3 map `name` is kept or an
  operation in both versions moved between them. A v2 operation without an `operationId` is keyed
  `"<action> <address>"`, so a flipped action is a removed + an added operation on the same
  channel; they are paired as `action-flipped`.
* **Unions.** A message counts as removed / added only when its owning operation (the key before
  `#event.`) exists in both versions; otherwise it keeps the built-in grade.
* **Modified entities.** Moved `extras` keys are graded one by one (`extras.reply`,
  `extras.bindings`, …). Attribute moves no rule handles keep their built-in grade and count in
  the worst-of; when one is worse than every finding, the rule id is the built-in `modified-<tier>`.
* **Payloads** (`app.asyncapi_payload_compatibility.compare_payloads`). The message objects are
  read back from `CanonicalApi.raw` through the normalizer's own message path (so a v2 `.proto`
  text payload and a message-level `schemaFormat` are seen); without `raw`, the canonical
  `payload_schema` and `extras.schemaFormat` are used. `schemaFormat` is reduced to its media type
  (parameters and `+json` / `+yaml` dropped; absent = `application/vnd.aai.asyncapi`). JSON Schema
  and AsyncAPI schemas go to `jsonschema_compatibility.compare_schemas`, Avro to
  `avro_compatibility.can_read` both ways, Protobuf `.proto` text to
  `ProtobufBreakingChangeClassifier` (when `buf` compiles it). A `backward` finding is a
  consumer-side break, a `forward` one a producer-side break, Protobuf grades both sides alike.
  Unsupported formats and unreadable schemas return `None` and the built-in grade stands.
* **Unattributed.** Server findings, and payload findings on a message the diff does not list,
  go to `ClassificationResult.unattributed` and count toward `overall_severity`.

## `@asyncapi/diff` overlay (`classify_async` / `classify_asyncapi`)

The authoritative grading is the **async** `classify_async` (and the module convenience
`classify_asyncapi(base, target)`), because the tool shells out asynchronously through the
[toolchain runner](./toolchain_packaging.md) (the SPI itself is sync). It:

1. starts from the sharpened structural grades (`classify`, read by the classifier's `mode`);
2. runs `@asyncapi/diff` over the two **already-validated and dereferenced** documents MFI-8.1
   preserved on `CanonicalApi.raw` (fed to the bundled `asyncapi-diff` tool as
   `{"old": …, "new": …}` on `stdin`);
3. **overlays** the tool's verdict — `breaking` → `BREAKING`, `non-breaking` → `SAFE` — onto a
   change wherever the tool classified it **and** it joins onto a canonical entity.

A change the tool reports `unclassified`, or any change that does not join cleanly onto a diffed
entity (a deep payload edit, a server binding, document metadata), keeps the sharpened structural
grade — so the result never silently downgrades a removal the tool had no opinion on. The
baseline's `unattributed` findings are kept through the overlay.

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

`tests/test_asyncapi_compatibility.py` — the XPC-4.4 fixture pairs
(`tests/fixtures/asyncapi_compatibility/cases.json`: every rule in both majors, `reply` 3.x only,
each with its consumer / producer grades and its verdict under `BACKWARD` / `FORWARD` / `FULL`);
mode and side helpers; unhandled moves kept at their built-in grade; payload delegation (Avro,
JSON Schema, Protobuf over recorded descriptors, unsupported formats, no `raw`); and the overlay
winning where it joins while the sharpened baseline and its unattributed findings stand elsewhere.


`tests/test_asyncapi_diff.py` — the tool seam over a fake runner (wrapper contract, malformed
changes skipped, infrastructure failures → `AsyncApiDiffError`, both documents on `stdin`); the
join helper for v2 + v3 (channel address resolution, operation name / `operationId`, deep edits
not joined); the overlay (a breaking + a safe change graded correctly, `unclassified` and
non-joining changes keep the structural grade); graceful degradation (no documents / tool
unavailable); SPI registration for both families and the sync structural dispatch; determinism
and JSON round-trip; and a **gated** end-to-end class over the real bundled `@asyncapi/diff`.
