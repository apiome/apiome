# Source-to-model change review (DCW-2.3)

Backend half of the Designer's editable source workspace review/apply flow
(private-suite#2360, building on the DCW-2.1 preservation envelope,
private-suite#2352).

## Why

Valid source text may not silently mutate the canonical model. Applying an
edited OpenAPI document must be reviewable (what exactly changes?), safe
(structural review, optimistic concurrency, atomic writes), and honest
(anything the relational model cannot hold is preserved, never dropped; any
value the model would alter fails the apply instead of drifting).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/versions/{tenant}/{project}/{revision}/source-review` | Parse + classify a candidate. Never mutates. |
| POST | `/v1/versions/{tenant}/{project}/{revision}/source-apply` | Apply a reviewed candidate once, in one transaction. |

Both require the `versions:edit` permission and answer 404 (never 403) on
tenant/project scope misses. Both run the DCW-0.2 safe parser, the same OAS
3.1/3.2 meta-schema validation as export, and local `$ref` integrity checks;
failures answer 422 `SOURCE_INVALID` with structured findings.

## Review

`build_source_change_set` (`app/source_change_review.py`) diffs the candidate
against the revision's **current merged document** (server-generated
canonical + live preservation envelope) and returns:

- `changes[]` — each an `addition` / `update` / `deletion`, or
  `unsupported-preserved` when the DCW-0.1 capability matrix places the
  pointer outside the visually-editable model; grouped by `document`,
  `path`, `operation`, `component`, or `schema` with a stable group key
  (e.g. `GET /pets`, schema `Pet`).
- `blockers[]` — structural reasons the apply cannot proceed:
  - `REFERENCED_COMPONENT_DELETION` — a deleted schema still referenced;
    lists **every referencing pointer**.
  - `MODEL_OWNED_VALUE` — updates/deletions of `/openapi`, `/info/*`, or
    `/x-metadata/*`, which the server generates from project/version records
    (edit them in the metadata inspector; dialect is DCW-0.1 policy).
  - `SHARED_RESPONSE_COLLISION` / `SHARED_PARAMETER_COLLISION` — the
    relational model shares responses per (path, status) and parameters per
    (path, name, in); operations that disagree cannot both be represented.
- `baseDigest` (semantic fingerprint of the merged base) and
  `changeSetDigest` (binds this candidate to this base) — the apply must
  present both.

## Apply

`Database.apply_source_change_set` runs one transaction on one locked
version row (`FOR UPDATE`):

1. Recheck tenant/project scope (404), published immutability
   (409 `PUBLISHED_IMMUTABLE`), draft-lock ownership
   (409 `DRAFT_LOCK_CONFLICT` + holder), and `versions:edit`
   (403 `PERMISSION_DENIED`) — **inside** the transaction.
2. Recompute the current merged fingerprint from the locked rows. If the
   latest successful audit row matches the presented change-set digest and
   the revision still fingerprints to its result → **idempotent replay**
   (200, `alreadyApplied`, no mutation).
3. Stale base → 409 `STALE_BASE` with `currentDigest` and `choices:
   ["rebase-reparse", "discard"]` — conflicts are resolution choices, never
   last-write-wins.
4. Re-run blockers server-side (409 `SOURCE_APPLY_BLOCKED`).
5. Plan writes (`app/source_change_apply.py`), predict the regenerated
   canonical, re-extract the preservation envelope against it, merge, and
   prove fidelity: the merged result must equal the candidate up to
   **reported deterministic generator enrichments** (injected titles,
   default responses, schema defaults). Lost or altered values → 422
   `SOURCE_APPLY_LOSSY`, rollback.
6. Rewrite canonical rows (classes/properties, paths/operations/parameters/
   request bodies/responses, apiKey security schemes, servers), replace the
   preservation claims, and insert the `apiome.source_change_audit` row
   (V185) — all on the same cursor; commit once.

A failed apply at any step leaves the revision unchanged.

## Tests

- `tests/test_source_change_review.py` — classification, grouping, blockers,
  `$ref` integrity, digest binding.
- `tests/test_source_change_apply.py` — write planning + the fidelity loop
  (lossless round trips incl. golden fixtures and envelope-preserved
  constructs; enrichment reporting; loss/drift rejection).
- `tests/test_source_apply_transaction.py` — the in-transaction rechecks,
  optimistic concurrency, atomic commit, and idempotent replay against a
  scripted connection.
- `tests/test_source_review_routes.py` — the DCW-0.2 authorization matrix,
  conflict payloads, and no-mutation guarantees at the HTTP surface.
