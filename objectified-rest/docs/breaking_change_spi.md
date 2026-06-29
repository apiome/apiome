# Breaking-Change Classifier (MFI-3.3)

> **Status:** format-agnostic built-in ruleset + per-format classifier SPI — `src/app/breaking_change.py`
> **Issue:** [#3744](https://github.com/objectified-project/objectified/issues/3744) ·
> **Epic:** MFI-EPIC-3 (#3718) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The [compare-any-two diff](./diff_spi.md) (MFI-3.2) says *what* changed between two
[`CanonicalApi`](./canonical_model.md) models. This module answers the next question:
*is that change safe to ship, or will it break callers?* `classify(model_diff, base,
target)` grades every change in the diff with a [`Severity`](#severities) and returns a
`ClassificationResult` — the per-change grades, the worst overall severity, and a
per-severity tally — so a diff view can surface "breaking / dangerous / safe" next to
each rendered change.

```
 diff(base, target) ─▶ ModelDiff.changes ─▶ classifier.classify_change(each) ─▶ ClassificationResult
                                              │                                   (per-change Severity
                          dispatch by target.format:                              + worst-of overall
                          registered format pack, else builtin ruleset            + counts_by_severity)
```

## Severities

Three tiers — the common ground across the per-format ecosystems this SPI abstracts
over (GraphQL-Inspector `NON_BREAKING` / `DANGEROUS` / `BREAKING`, Buf allow / warn /
break, Confluent compatible / incompatible):

| `Severity`  | Meaning                                                                 |
|-------------|-------------------------------------------------------------------------|
| `safe`      | Additive or widening; existing callers keep working.                    |
| `dangerous` | Compatible by the letter but warrants review (a default/constraint moved, a field deprecated, a folded member set changed). |
| `breaking`  | Removes or narrows surface existing callers may depend on.              |

`ClassificationResult.overall_severity` is the worst grade across all changes (`safe`
for an empty diff); `breaking` is the convenience boolean a version-roll / publish gate
keys on.

## The built-in ruleset (`BuiltinBreakingChangeClassifier`)

`classify` uses this format-agnostic baseline whenever the artifact's format has
registered no classifier of its own. It is deliberately **conservative** (it grades
from structure alone) and **pure** (no I/O). Documentation-only edits and source
declaration order never reach it — they are already invisible to the diff, which is
taken over the scrubbed, order-normalized [fingerprint](./fingerprint_spi.md)
projection.

| Change                                                   | Severity    | `rule_id`               |
|----------------------------------------------------------|-------------|-------------------------|
| **Removed** any entity (service/operation/message/channel/type/field) | `breaking`  | `removed-entity`        |
| **Added** an optional field, or any service/operation/message/channel/type | `safe`      | `added-entity`          |
| **Added** a *mandatory* field (non-nullable, no default) | `dangerous` | `added-mandatory-field` |
| **Modified** entity                                      | worst of its moved attributes | `modified-<severity>` |

A **modification** is graded as the worst grade over the canonical attributes that
moved:

- **breaking** — a field/parameter `type` narrowed nullable → non-null or retyped; a
  route/verb move (`http_path`, `http_method`); `kind`, `status_code`, `field_number`,
  `location`, `role`, `streaming`, `payload`, `payload_schema`, `aliased`, `key_type`,
  `value_type`, channel `address`/`protocol`.
- **dangerous** — `default`, `constraints`, `content_types`, `deprecated` (false→true),
  `bindings`, `name`, `tags`, `namespace`, and the **folded member lists** the baseline
  can't introspect: an operation's `parameters`, a message's `headers`, a type's
  `enum_values` / `union_members`. (The baseline can't tell an added-optional-parameter
  from a made-required one inside such a list, so it flags the whole move for review and
  leaves the sharp call to a per-format classifier.)
- **safe** — a type widened non-null → nullable (same underlying type); `required`
  dropped; `deprecated` cleared.

### Why removal is always breaking

Direction (request vs response) is unknowable from the canonical structure alone, so
removing surface is graded `breaking` by default. A per-format classifier that knows
the direction (e.g. one wrapping GraphQL-Inspector or Buf) can downgrade the cases its
ecosystem deems safe.

## Per-format classifier SPI (`BreakingChangeClassifier`)

A format whose ecosystem defines authoritative compatibility rules registers a
classifier under its format key. The expected implementation **wraps the canonical
tool** via the [toolchain runner](./toolchain_runner.md) (EPIC-5) — Buf breaking
(`WIRE` / `WIRE_JSON`), GraphQL-Inspector, `@asyncapi/diff`, `smithy diff` evaluators,
Confluent `/compatibility`, the OData §5.2 policy — and maps that tool's verdict onto a
per-change `Severity`. This mirrors the [normalizer](./normalizer_spi.md),
[fingerprint-hasher](./fingerprint_spi.md), and [diff-labeler](./diff_spi.md)
registries.

```python
from app.breaking_change import BreakingChangeClassifier, ChangeClassification, Severity

class BufClassifier(BreakingChangeClassifier, register=True):
    format = "protobuf"
    classifier_id = "buf-breaking-wire"

    def classify_change(self, change, base, target):
        # Map a precomputed `buf breaking` verdict onto this change.
        ...
        return ChangeClassification(category=change.category, kind=change.kind,
                                    key=change.key, severity=Severity.BREAKING,
                                    rule_id="WIRE_COMPATIBILITY", rationale="...")
```

- `register=True` (or `register_breaking_change_classifier(cls)`) registers under
  `format`; re-registering the same class is a no-op, a *different* class for the same
  format raises. Look up with `get_breaking_change_classifier(format)`; list with
  `available_breaking_change_formats()`.
- The only required method is `classify_change` (grade one change), so every classifier
  can answer "what is the severity of *this* change" for the diff view. A tool-wrapping
  classifier that runs its CLI once over the whole diff overrides `classify(model_diff,
  base, target)` and memoizes the tool's per-change verdicts for `classify_change` to
  read back.
- A classifier that only **sharpens a few rules** over the structural baseline subclasses
  `BuiltinBreakingChangeClassifier` instead and overrides `classify_change`, calling
  `super()` for the baseline:

```python
class GraphQLClassifier(BuiltinBreakingChangeClassifier):
    classifier_id = "graphql-inspector"
    def classify_change(self, change, base, target):
        grade = super().classify_change(change, base, target)
        # GraphQL: adding a non-null arg is breaking, removing an output field is breaking…
        return grade
```

`classify` dispatches by **`target.format`** (the "to" side defines the resulting
artifact's format).

## Usage

```python
from app.diff import diff
from app.breaking_change import classify, classify_models

result = classify(diff(base, target), base, target)   # or: classify_models(base, target)
if result.breaking:
    ...  # block the publish / require a major version bump (MFI-3.4)
for grade in result.classifications:                  # 1:1 with diff.changes, same order
    print(grade.key, grade.severity.value, grade.rule_id, grade.rationale)
print(result.counts_by_severity)                      # {"breaking": 2, "dangerous": 1, ...}
```

Each `ChangeClassification` carries the graded change's `category` / `kind` / `key`, so
a diff view joins severities back onto the changes it renders without relying on list
position. `ClassificationResult` is plain Pydantic, so `model_dump()` /
`model_validate()` round-trips it losslessly to JSONB for persistence alongside the
version diff (MFI-3.4).

## Relationship to the other MFI-EPIC-3 pieces

- **MFI-3.1 ([fingerprint](./fingerprint_spi.md)) / MFI-3.2 ([diff](./diff_spi.md)).**
  The classifier grades the `ModelDiff` the diff produces; doc-only and ordering noise
  are already filtered out upstream.
- **MFI-5.1 ([toolchain runner](./toolchain_runner.md)).** Per-format classifiers wrap
  their canonical CLI through the runner; the SPI itself only maps the verdict onto
  `Severity`.
- **MFI-3.4 (versioning).** Uses `ClassificationResult.breaking` / `overall_severity`
  to drive the version bump and persists the grades with the diff.
```
