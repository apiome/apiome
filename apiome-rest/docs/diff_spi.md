# Compare-Any-Two Model Diff (MFI-3.2)

> **Status:** format-agnostic implementation + per-format label SPI — `src/app/diff.py`
> **Issue:** [#3743](https://github.com/objectified-project/objectified/issues/3743) ·
> **Epic:** MFI-EPIC-3 (#3718) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Once every importable format is normalized into the one
[`CanonicalApi`](./canonical_model.md) shape (MFI-2.1) and fingerprinted uniformly
([MFI-3.1](./fingerprint_spi.md)), *"what changed between these two artifacts?"* can
be answered **once**, for every paradigm. `diff(base, target)` returns a structured
`ModelDiff` listing every service / operation / message / channel / type / field
that was **added**, **removed**, or **modified**, with the before/after projection of
each and add/remove/modify counts.

This generalizes the MCP surface diff (V2-MCP-EPIC-18.2 / 24.3,
`app.mcp_client.diff.diff_surfaces`) to the canonical model.

```
 base   ─canonical_payload─▶ flatten by category ─┐
                                                  ├─ pair by key ─▶ added / removed / modified ─▶ ModelDiff
 target ─canonical_payload─▶ flatten by category ─┘                       (+ per-format labels)
```

Everything here is **pure** (no DB, no network): it takes two in-memory models and
returns a JSON-serializable `ModelDiff`, cheap to call from a version roll
(MFI-3.4), an on-demand compare API, or the CLI.

## Two defining properties

- **Compare-any-two, not just adjacent.** The two models are compared *directly*,
  never by chaining adjacent step-diffs, so the result is exact for an arbitrarily
  distant pair (`v1 → v9`) just as it is for neighbors.
- **In lock-step with change detection.** The diff is taken over exactly the
  projection the fingerprint hashes — `app.fingerprint.canonical_payload`
  (order-normalized, with `description`/`title`/`raw` scrubbed). So documentation-only
  edits and source declaration-order differences are **invisible** to the diff, and
  two models with the same fingerprint always produce an **empty** diff. The MFI-3.2
  "identical models → empty diff" acceptance criterion holds by construction.

## What the diff reports

### Stable-key identity

Entities are paired across the two models by the stable `key` every canonical entity
carries (`GET /pets/{id}`, `Pet.id`, `user/signedup`, …). Pairing by key, not by
position, makes a rename read as remove + add while an in-place edit reads as a single
modify, and lets the diff line up two versions whose sources ordered their
paths/types differently.

### Flat, globally-keyed categories

Operations live under services, messages under operations, and fields under record
types — but their keys are globally unique within the model, so the diff **flattens**
each category and pairs it independently. The six categories (`EntityCategory`) are:

| Category    | Source collection                         | Keyed by                       |
|-------------|-------------------------------------------|--------------------------------|
| `service`   | `CanonicalApi.services`                   | service key (`pets`)           |
| `operation` | every service's `operations`              | operation key (`GET /pets/{id}`) |
| `message`   | every operation's `messages`              | message key (`…#response.200`) |
| `channel`   | `CanonicalApi.channels`                   | channel key (`user/signedup`)  |
| `type`      | `CanonicalApi.types`                      | type key (`Pet`)               |
| `field`     | every record type's `fields`              | field key (`Pet.id`)           |

Removing a whole service therefore surfaces the service **and** each of its
operations/messages as separate `removed` entries — a faithful, non-double-counted
account of everything that left.

### No parent/child double-counting

An entity counts as `modified` only when its **own** attributes change. Each
entity's `before`/`after` carries its *self-projection*: its canonical attributes
**minus** the child collection that is diffed in its own category —
`operations` (off services), `messages` (off operations), `fields` (off record
types). So a type whose only change is a new field is **not** itself "modified" (the
field is reported as an `added` field, the type is untouched).

Members that are *not* separately keyed fold into their owner's self-projection and so
register as a modification of the owner, not their own category:

- a type's `enum_values` / `union_members` / `aliased` / `key_type` / `value_type`,
- an operation's `parameters`,
- a message's `headers`,
- a channel's address `parameters` and protocol `bindings`.

### Change shape

```python
ModelDiff(
    base_fingerprint=...,        # app.fingerprint.canonical_fingerprint(base)
    target_fingerprint=...,      # app.fingerprint.canonical_fingerprint(target)
    changes=[EntityChange(...), ...],   # stable order: (category spine, key)
    counts=DiffCounts(added, removed, modified, total),
    counts_by_category={"field": DiffCounts(...), ...},  # only non-empty categories
)
```

Each `EntityChange` carries `category`, `kind` (`added` / `removed` / `modified`),
`key`, optional `label` (see below), the `before`/`after` self-projections (an
addition has only `after`; a removal only `before`), and — for a modification — a
`fields` list of `FieldChange(field, before, after)` naming each canonical attribute
that moved. `ModelDiff.identical` (≡ `is_empty()`) is `True` exactly when the
fingerprints match.

Changes are emitted in a fixed `(category, key)` order, so the same pair of models
always serializes identically.

## Per-format label enrichment (`DiffLabeler`)

The structural diff says *what kind* of entity changed and *how* (the attribute
breakdown). A format whose ecosystem has a richer vocabulary for change semantics —
GraphQL's breaking/dangerous classes, Avro's compatibility-affecting edits, protobuf
field-number reuse — registers a `DiffLabeler` to attach a concise, human-readable
`EntityChange.label`. This mirrors the [normalizer](./normalizer_spi.md) and
[fingerprint-hasher](./fingerprint_spi.md) registries.

```python
from app.diff import DiffLabeler, register_diff_labeler

class GraphQLDiffLabeler(DiffLabeler, register=True):
    format = "graphql"

    def label(self, change, base, target):
        if change.category.value == "field" and change.kind.value == "removed":
            return "field removed (breaking)"
        return None
```

- `register=True` (or `register_diff_labeler(cls)`) registers under `format`;
  re-registering the same class is a no-op, a *different* class for the same format
  raises. Look up with `get_diff_labeler(format)`; list with
  `available_diff_formats()`.
- `diff()` resolves the labeler by **`target.format`** (the "to" side defines the
  resulting artifact's format) and asks it for a label per change. Labeling is
  **purely additive** — a labeler never adds, removes, or reclassifies a change, only
  annotates it; returning `None` leaves the label unset. With no labeler registered,
  every `label` is `None`.

This is the hook MFI-3.2 leaves for *"per-format diff enrichment"*; the breaking-change
classifier (MFI-3.3) consumes the same `ModelDiff` to grade changes breaking-vs-safe.

## Usage

```python
from app.diff import diff

result = diff(base_model, target_model)
if result.identical:
    ...  # no new version (MFI-3.4)
else:
    for change in result.changes:
        print(change.category.value, change.kind.value, change.key, change.label)
    print(result.counts)            # DiffCounts(added=…, removed=…, modified=…, total=…)
```

`ModelDiff` is plain Pydantic, so `model_dump()` / `model_validate()` round-trips it
losslessly to JSONB for persistence alongside the version row (MFI-3.4).

## Relationship to the other MFI-EPIC-3 pieces

- **MFI-3.1 ([fingerprint](./fingerprint_spi.md)).** The diff reuses
  `canonical_payload` so it stays byte-for-byte aligned with change detection.
- **MFI-3.3 (breaking-change classifier).** Takes a `ModelDiff` + both models and
  returns severities; format packs grade the same structured changes.
- **MFI-3.4 (versioning).** Uses `ModelDiff.identical` to decide whether a re-import
  creates a new dated version, and persists the diff with it.
```
