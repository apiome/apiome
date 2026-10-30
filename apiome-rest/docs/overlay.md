# OpenAPI Overlay — revisions and semantics

Engine reference for `app.openapi_overlay` (IXH-7.7 #5132, GVM-4.1 #5876). The product guide is
`apiome-docs/docs/bring-in/overlays.md`.

## Declared revisions

`OVERLAY_READ_VERSIONS` is the table of revisions Apiome reads. A document's `overlay` marker
selects one by `major.minor`; the patch is ignored, as the specification asks ("The patch version
SHOULD NOT be considered by tooling"). Any other marker (`1.3.0`, `2.0.0`, `1`) is refused with
`FORMAT_VERSION_UNSUPPORTED` — the document is still recognised as an overlay, so it is a version
rejection, not a format mismatch — and a bare overlay lint reports it as
`overlay.version-unsupported`.

| Revision | Specification | Read since |
| --- | --- | --- |
| 1.0 | <https://spec.openapis.org/overlay/v1.0.0.html> | IXH-7.7 |
| 1.1 | <https://spec.openapis.org/overlay/v1.1.0.html> (released 2026-01-14) | GVM-4.1 |
| 1.2 | <https://spec.openapis.org/overlay/v1.2.0.html> (released 2026-09-22) | GVM-4.1 |

Each revision is evidenced by a corpus fileset whose overlay declares it
(`tests/test_openapi_overlay_revisions.py::test_every_declared_revision_has_a_corpus_overlay`):
`openapi/34-overlay-basic-set` and `35-overlay-chain-set` (1.0), `36-overlay-1-1-set` (1.1),
`37-overlay-1-2-set` (1.2). Their provenance is pinned in `tests/golden/overlay/<set>.json`.

**Adding a revision** is the four-file move FMT-3.8 uses for a format version: a row in
`OVERLAY_READ_VERSIONS`, its semantics in `_check_action` / `_apply_action` / `_update_match`, a
corpus fileset that declares it, and the regenerated supported-formats page.

## Action semantics, as implemented

Actions run in document order, each on the result of the previous one ("MUST be applied in
sequential order"), and overlays in a chain run in member-path order.

### 1.0

- `target` — a JSONPath query. Parsed with the custom-rule DSL's parser
  (`custom_rule_dsl.parse_jsonpath_expression`), so `[*]` behaves as in custom rules.
- `update` on an **object** — recursive merge: nested objects merge, any other value (primitives
  and arrays) replaces. The 1.0 text does not say how a nested array merges; replacing is what
  Apiome has always done.
- `update` on an **array** — the value is appended as **one** entry ("a single entry appended").
- `remove: true` — removes each selected node from its parent; `update` is then ignored.
- **Deviation:** the 1.0 text says targets "MUST be zero or more objects or arrays". Apiome still
  replaces a selected primitive with the `update` value, as it did before GVM-4.1 and as 1.1
  standardised, so overlays written that way keep importing.

### 1.1

- **`copy`** — a JSONPath selecting **exactly one** node of the document being transformed; its
  value is merged into each target like an `update`. Zero or several source nodes → `action-invalid`.
- **Precedence** — `remove: true` voids `copy` and `update`; `copy` voids `update`.
- **Primitive targets** — replaced by a primitive `update`; an object or array `update` there is
  `action-invalid`.
- **Object merge** — "A property only in the target is left unchanged … only in update is
  inserted … primitive replaces primitive, array is concatenated with array, object is recursively
  merged … Other property value combinations are incompatible and result in an error." Apiome
  checks the whole merge for incompatible pairs **before** writing, so an incompatible update
  leaves the node untouched and reports `action-invalid` naming the first conflicting pointer.
- **Array target** — an array `update` is concatenated; an object or primitive is appended.
- **Multiple matches** — "the selected nodes MUST be either all objects or all arrays or all
  primitives"; a mix is `action-invalid` and nothing is changed.

### 1.2

Everything in 1.1, plus:

- **Reusable actions** — `components.actions.<name>` holds `{description, fields}`, where `fields`
  is an action without `target` (a `target` there is reported). An `actions` entry
  `{$ref: '#/components/actions/<name>', target, description?}` expands to the component's
  `fields` plus that `target`; the reference's `description` wins. A `$ref` outside
  `#/components/actions/`, to a missing name, or before 1.2 is `action-invalid`. (`~1`/`~0` in the
  name are decoded per RFC 6901.)
- **`$self`** — the overlay's own URI. A fragment is reported (the text forbids it); `$self`
  before 1.2 is reported. It is the base for resolving a relative `extends`.
- **`update` and `copy` together** — the 1.2 text says each "has no impact" when the other is
  present, so the action is refused (`action-invalid`) rather than guessing.

### Every revision

- **Zero matches** — the specification calls this success; Apiome applies nothing and reports
  `overlay.unmatched-target`, since a target that matches nothing is almost always a mistake.
- **`extends`** — when the overlay is applied in a fileset, `extends` must name the base: as a
  path relative to the overlay's member path, or — absolute, or resolved against the overlay's
  `$self` — equal to the base's `$self`. Otherwise `overlay.extends-unresolved`. The overlay is
  applied regardless (the tool chooses the target when they disagree).
- **Limits** — at most 1000 nodes per action and 500 provenance records per import (truncation is
  declared in the report).

## The `overlay` rule pack

| Rule | Default | Needs the base |
| --- | --- | --- |
| `overlay.unmatched-target` | warning | yes |
| `overlay.action-invalid` | warning | no |
| `overlay.target-expression-invalid` | warning | no |
| `overlay.extends-unresolved` | warning | yes |
| `overlay.version-unsupported` | error | no |

The pack replaces the IXH-7.7 intake rules `intake.overlay-unmatched-target` and
`intake.overlay-action-invalid` (migration V342 re-seeds the built-in style guide). Only
`overlay.version-unsupported` defaults to `error`, so it is the only one with a CLX-4.3
transparency entry and scanner-evaluation fixture (`catalog/overlay-version-unsupported`); a style
guide can raise any of the others.

## Bare overlay lint

`lint_bare_overlay(document)` runs the version, document-level and per-action structural checks and
parses every `target`/`copy` expression. The two rules that need the base are reported
`{status: skipped, reason: no-base}` — never `passed`. `POST /v1/lint/overlay` serves it; GOV-3.5
(#4442) will call it from `apiome lint <file>`.

## The report on the canonical model

`model.extras["overlay"]` carries `applied`, `provenance`, `findings`, `provenance_truncated`,
`provenance_total`, the `base` and `ignored_members`, and — only for overlays applied as 1.1 or 1.2
— `revisions` (`label → revision`). Leaving 1.0 out keeps the fingerprint (which hashes extras) of
every overlay import made before GVM-4.1 unchanged.
