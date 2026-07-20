# Managed Slate hosting and immutable versioned deployment

**APX-3.1 · private-suite#2456 · Commercial MVP**

ZIP download and bring-your-own-CDN export cannot carry a paid publishing product. Neither
can say what is currently serving production, neither can put it back, and neither leaves
evidence that outlives the person who ran it. This document describes the control plane that
replaces them.

## What this is, and what it is not

This is the **control plane**: the release record, the routing pointer, the activation
ledger, retention and audit. It is complete and enforced.

It is **not an edge network**. `deploy/` in this repository is a single Caddyfile in front of
four static container hostnames; there is no CDN, no multi-region POP, and no per-tenant
domain routing behind it. `slate_release_regions` and `slate_activations` model per-region
rollout because a partial activation is a real failure the Release Center must not report as
success — but what activation drives *today* is the database routing pointer, not a live
global edge. Wiring that pointer to a real edge is APX-3.2 / UXE-3.x.

Saying so here is deliberate. The Release Center's whole design premise is that it refuses to
report activations it cannot evidence, and a backend that implied a CDN it does not have
would undermine exactly that.

## Acceptance criteria and where each is enforced

| Criterion | Enforced by |
|---|---|
| Every build has content/source/config digests and an immutable release ID | `slate_artifacts.py` (digest computation, `CHECK` constraints on shape); `slate_releases` identity columns + `slate_release_immutability_guard` trigger |
| Preview and production routes activate atomically | `slate_deployment_store.activate()` — one conditional `UPDATE` on one row |
| Promotion never rebuilds; rollback restores a retained artifact within the SLO | `slate_releases.plan_promotion()` carries `rebuilds=False`; `find_rollback_target()` requires unreaped bytes; `measure_activation_slo()` |
| Concurrent promotion, failed activation, retention and audit paths are tested | `routing_version` optimistic concurrency; `slate_release_audit` append-only trigger; 171 tests |

## The three digests

Three digests, because they answer three different questions:

- **content** — what bytes will be served. This is the artifact's identity: two releases
  carrying the same content digest serve identical bytes, which is what lets promotion route
  to an existing artifact instead of rebuilding one.
- **source** — what inputs produced them (catalog revision, guides, changelog).
- **config** — what build configuration was applied (theme, navigation, generator options).

Collapsing them into one would make an unchanged rebuild indistinguishable from a content
change, and a rebuild after a theme tweak indistinguishable from a rewrite.

Every digest is computed over a canonical serialization. The content digest is a Merkle-style
fold over `sorted(path)` with **length-prefixed** paths — digesting a directory in filesystem
order would make identity depend on walker order, so an identical rebuild on another machine
would produce a different digest and every promotion would look like new bytes. Length
prefixing is what stops `{"ab": …, "c": …}` from folding to the same input as
`{"a": …, "bc": …}`.

Each digest is domain-separated by a tag, so hashing an equal mapping for two purposes cannot
collide: without it, an attacker controlling one input could engineer a config change that
looks like no change.

## Signing

A detached HMAC-SHA256 over the three digests **and the key id**. The key id is inside the
signed payload, not merely stored beside it, so a valid signature cannot be relabelled to
claim a different key produced it.

The signing key is `APIOME_SLATE_ARTIFACT_SIGNING_KEY`, deliberately **not** the JWT secret.
An artifact signature answers "these are the bytes the build produced"; a JWT answers "this
caller is who they claim". Sharing one key would mean a leaked session secret also lets an
attacker mint artifact signatures the activation gate accepts. Production fails closed if it
is unset.

Verification is constant-time and returns a bare `False` for every failure mode — wrong key,
tampered digest, relabelled key id, malformed signature. Distinguishing them would hand an
attacker an oracle for which part of a forgery was wrong.

Signatures are verified **at record time as well as at activation**. Storing an unverifiable
artifact and only discovering it during an incident promotion would put the discovery at the
worst possible moment.

## Atomic activation

Activation is one statement:

```sql
UPDATE apiome.slate_environments
   SET active_release_id = %s, routing_version = routing_version + 1
 WHERE id = %s AND tenant_id = %s AND routing_version = %s
```

A single-row update is atomic in PostgreSQL, so **no reader ever observes a lane between two
releases**. The `routing_version` predicate is the concurrency control: the second of two
simultaneous promotions matches zero rows, is recorded in the ledger as `conflict`, and is
raised to the caller as a 409 naming both the expected and actual version. There is
deliberately no retry loop, no `ON CONFLICT DO UPDATE` near routing, and no last-write-wins
path.

When a promotion loses the race, the **evidence still commits while the routing change does
not**. A lost promotion must be reconstructable afterwards, not merely reported at the time.

`activation_completed_at` is *not* stamped at switch time. The gap between `activated_at` and
`activation_completed_at` **is** the activation SLO; collapsing them would make every rollout
look instantaneous and leave nothing to measure.

## Promotion never rebuilds

Structural, not aspirational:

- `plan_promotion()` requires a release that already has an artifact, and refuses one that
  does not with `not-built` — a reason whose sentence says promotion never starts a build.
- `ActivationPlan.rebuilds` is a literal `False`, so the guarantee is inspectable in the API
  response and asserted in tests, rather than documented and hoped for.
- There is no code path from `slate_deployment_store` to a build, and a test asserts that
  activation issues no `INSERT INTO apiome.slate_artifacts`.
- The routed digest is copied onto the ledger row, so the ledger alone evidences that
  existing bytes were routed.

## Refusals are sentences, not codes

The refusal vocabulary matches `designer/lib/authoring/release-actions.ts` exactly. The
Release Center makes `disabledReason` the only way to disable a control, so a backend that
invented its own codes would surface as a greyed-out dead end instead of an explanation.

Every reason carries an operator-facing sentence: `not-built`, `not-promotable`,
`already-active`, `nothing-active`, `no-rollback-target`, `stale-approval`,
`approval-required`, `artifact-reaped`, `signature-invalid`, `partial-region`,
`concurrent-activation`.

Two asymmetries are deliberate:

1. **A stale approval blocks promotion but never a rollback.** Requiring fresh sign-off to
   *stop* serving a bad release would make the approval policy an outage amplifier.
2. **A reaped rollback target reports `no-rollback-target`, not `not-built`.** The operator's
   situation is "there is nothing to go back to"; saying "not built" about a release that
   demonstrably served production would be confusing and wrong.

## Approvals bind to bytes

An approval records **what** was approved via its digest, not merely that approval happened.
An approval whose digest no longer matches the release artifact is stale. Approving a build
and then promoting different bytes is a supply-chain failure, not a UI inconvenience — and a
missing approval digest counts as stale rather than as a pass.

## Partial rollout

A lane where **no region has reported** is `pending`, never `complete`. Absence of evidence is
not evidence of a clean activation. Any region still activating makes the rollout `partial`; a
failed region makes it `failed`, which outranks activating.

Promoting on top of an unfinished rollout is refused (`partial-region`): it would leave
regions serving three different releases, a state no single rollback can cleanly undo.

## Retention is the rollback window

Retention and rollback capability are the same setting. `slate_sites.retained_releases`
defines how many superseded releases keep their bytes, and an artifact that has been reaped is
no longer a rollback target. The sweep is therefore conservative:

- the active release is never reaped, whatever the count says, and routing state wins over a
  stale status column;
- only releases that once served (`superseded` / `rolled-back`) are candidates — reaping a
  release awaiting approval would destroy work in progress;
- reaping **marks** the artifact and clears `storage_uri` rather than deleting the row, so
  history keeps its digest. `ON DELETE RESTRICT` on `slate_releases.artifact_id` would refuse
  a delete anyway.

`find_rollback_target()` only returns releases whose bytes are still stored, so a rollback
cannot plan successfully and then fail at activation — the worst possible moment to discover
the bytes are gone.

## Immutability is enforced by the database

`release-model.ts` declares which fields a release may never change. That list is
re-implemented one layer lower as the `slate_release_immutability_guard` trigger, because
"immutable" enforced only in application code is a property of whichever caller happens to be
writing, not a guarantee.

`artifact_id` may be attached exactly once, when the build that produced it finishes, and
never repointed. Re-pointing an existing release at different bytes would let approved,
audited history serve something else — the supply-chain failure the whole table exists to
prevent.

`slate_release_audit` refuses `UPDATE` and `DELETE` outright. An audit log that can be edited
is not an audit log.

## Authorization

Reads require `versions:view`; recording a release requires `versions:edit`; promotion,
rollback and retention require `versions:publish`.

There is no separate `deployments` resource. Publishing documentation to a production lane
*is* a publish action on the version being published, and inventing a permission dimension the
roles matrix does not render would leave it ungrantable in the UI.

Scope misses answer **404, not 403**, so a cross-tenant probe cannot confirm that a site,
environment or release exists.

## Tables (V186)

| Table | Purpose |
|---|---|
| `slate_sites` | One hosted site per project; owns retention and SLO policy |
| `slate_artifacts` | Content-addressed, signed build output |
| `slate_environments` | production / staging / preview lanes; routing pointer + concurrency token |
| `slate_releases` | The immutable release record |
| `slate_release_regions` | Per-region activation state |
| `slate_release_approvals` | Approvals bound to a digest |
| `slate_release_checks` / `_phases` / `_logs` / `_changed_pages` | Release evidence |
| `slate_release_audit` | Append-only audit |
| `slate_domains` | Hosted domain inventory, TLS and verification state |
| `slate_activations` | Every routing attempt, including conflicts and partial rollouts |

## Tests

171 tests across four suites:

- `test_slate_artifacts.py` (29) — digest stability, sensitivity, domain separation, path
  ambiguity, signing, relabelling, tampering, manifest.
- `test_slate_releases.py` (65) — every promotion and rollback gate, approval staleness,
  region rollout, SLO measurement (including breach-while-in-progress), retention selection,
  and that every refusal reason has a sentence.
- `test_slate_activation.py` (34) — the single conditional UPDATE, tenant scoping, no
  artifact insert, the concurrent-promotion conflict path (loser never supersedes the winner,
  evidence commits, no retry), failed activation rollback, append-only audit, retention SQL.
- `test_slate_routes.py` (43) — authorization per route, 404-not-403, signature verification
  at record time, the named-refusal 409 contract, dry-run, the concurrency 409, and that a
  refused action still writes audit while a refused *dry run* does not.
