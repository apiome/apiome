# Round-Trip Preservation Envelope (DCW-2.1)

> private-suite#2352 — backend half of the Designer's lossless hybrid source
> workspace (DCW-EPIC-2). Depends on the DCW-0.1 capability contract and the
> DCW-0.2 resource-limits artifact, both mirrored field-for-field into
> `src/app/data/`.

## Why

A visual editor cannot become a trustworthy source of truth if save/export
drops valid OpenAPI data it has not normalized. The canonical model absorbs
what Designer can edit; everything else the source legitimately carried —
unknown-but-valid fields (including under arrays), `$ref` siblings, `x-*`
extensions whose value may be `null`, `false`, or empty — must survive the
round trip **semantically unchanged**.

The preservation envelope is that carrier: a version-scoped set of **claims**,
each an RFC 6901 JSON Pointer plus the preserved subtree, with optional
source-file/digest provenance.

## Modules

| Module | Role |
|---|---|
| `app/oas_resource_limits.py` | Typed loader for the mirrored DCW-0.2 limits artifact and DCW-0.1 capability matrix (`src/app/data/oas_resource_limits.json`, `oas_capability_matrix.json`). Pin tests fail CI on unreviewed drift. |
| `app/safe_oas_parse.py` | All-or-nothing YAML/JSON parsing under the limits: duplicate keys (YAML **and** JSON), alias expansion, nesting depth, document size, multi-document streams, circular aliases → structured, non-mutating diagnostics. |
| `app/preservation_envelope.py` | Pure engine: `extract_envelope`, `validate_envelope`, `apply_envelope`, `move_claims`, `delete_canonical_subtree`, `semantic_fingerprint`. |
| `app/preservation_routes.py` | `GET`/`PUT /v1/versions/{tenant}/{project}/{revision}/preservation`. |
| `database.py` | `get_preservation_claims` / `replace_preservation_claims` (single transaction with the audit row). |
| apiome-db `V184__preservation_envelope_2352.sql` | `version_preservation_claims`, `preservation_audit`, `purge_preservation_claims(retention_days)`. |

## Deterministic semantics

- **Ordering** — claims always apply parents-first, then numeric-aware pointer
  order (`/a/2` before `/a/10`), so two applies of one envelope are identical.
- **Array insertion** — a claim at `/arr/3` *inserts* at index 3, clamped to
  the array length; ascending application reconstructs interleaved
  source/canonical array layouts exactly.
- **Collisions** — a pointer holding a canonical value can never also be
  preserved: validation and apply both reject with
  `PRESERVATION_POINTER_COLLISION`, errors sorted by (pointer, code). Apply is
  all-or-nothing: on any error the canonical document is returned unchanged.
- **Moves** — `move_claims(envelope, from, to)` relocates a claimed subtree
  with its children; collisions leave the envelope untouched.
- **Canonical deletion** — `delete_canonical_subtree` drops claims inside the
  deleted subtree (returning them for audit/recovery) and rebases array
  indices of sibling claims after a deleted element.
- **Nested claims** — a claim inside another claim's subtree is rejected
  (`PRESERVATION_NESTED_CLAIM`); merge it into the ancestor claim instead.

## Fidelity contract

`semantic_fingerprint` hashes the canonical JSON form (sorted keys, compact
separators, SHA-256, algorithm id `sha256-oas-semantic-v1`) and always reports
the DCW-0.1 **lexical exclusions** — comments, anchors, key order, quoting,
whitespace, multi-file layout — so an equal fingerprint is never misread as a
lexical-fidelity promise.

## Storage, retention, audit

Claims live in `apiome.version_preservation_claims`, tenant- and
version-scoped, at most one live row per `(version, pointer)` (partial unique
index). Replacing an envelope soft-deletes the previous claims (retention;
`apiome.purge_preservation_claims(days)` hard-deletes soft-deleted rows past
the window) and writes an `apiome.preservation_audit` row — **all in one
transaction**, satisfying the DCW-0.2 `failure-injection-no-partial-mutation`
transaction rule: canonical rows, preservation payload, and audit commit or
roll back together.

## API behavior

- Scope misses answer **404**, never 403 — cross-tenant probes cannot confirm
  a revision exists.
- Published revisions are immutable: writes answer **409**
  (`PUBLISHED_IMMUTABLE`), rechecked inside the transaction.
- Validation failures answer **422** with the deterministic `errors` list and
  mutate nothing.
- Writes require the `versions:edit` permission; the canonical document used
  for collision checks is always generated server-side (same path as
  `/v1/schema`), never client-supplied.

## Tests

`tests/test_oas_resource_limits.py` (mirror pins),
`tests/test_safe_oas_parse.py` (parser limits),
`tests/test_preservation_envelope.py` (golden 3.1/3.2 corpus round-trips +
operations; fixtures in `tests/fixtures/preservation/`),
`tests/test_preservation_routes.py` (scoping, immutability, audit).
