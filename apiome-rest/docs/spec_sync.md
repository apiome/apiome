# Three-way spec synchronization (GNC-2.3, #4739)

A bound draft has three descriptions of the same API, and they drift apart independently:

| Side | What it is | How it is identified |
|---|---|---|
| **base** | the bound selection at the commit the binding is synchronized with | `base_commit_sha` + `base_digest` (a *fileset* digest) |
| **Git** | the same selection at the commit the branch has moved to | `git_commit_sha` + `git_digest` (a *fileset* digest) |
| **draft** | the version as this platform has it | `draft_digest` (a *document* fingerprint — a draft has no commit) |

[GNC-2.1](draft_bindings.md) made the relationship durable and turned a push into a **sync
candidate** — a row that says "this moved". It deliberately stopped there, because the next step is
the dangerous one: copying either repository side over the draft destroys whatever somebody was
editing, and invalidates whatever reviewers already decided.

What is safe is a **semantic three-way merge**. Both sides are measured against the base. Incoming
changes that touch nothing the draft touched are applied deterministically. Everything that
overlaps comes back as an explicit conflict that names where it is — in the document *and* in the
repository file — with all three values side by side.

> **A merge result is a reading, never a write.** There is no code path from this surface to the
> canonical model, to `versions`, or to a review. Computing a merge writes one row; settling a
> conflict records which side a person chose. Both leave the draft exactly where it was. That is
> what makes it safe for a webhook to raise a candidate and for anyone at all to merge it.

---

## The endpoints

| Method | Path | Permission |
|---|---|---|
| `GET` | `…/projects/{project}/versions/{version}/binding/sync` | `projects:view` |
| `POST` | `…/projects/{project}/versions/{version}/binding/sync` | `versions:edit` + a proven repository read |
| `GET` | `…/projects/{project}/sync-plans/{plan_id}` | `projects:view` |
| `POST` | `…/projects/{project}/sync-plans/{plan_id}/conflicts/{conflict_id}` | `versions:edit` |

There is no synchronization RBAC resource: a merge is an activity of a version, so it borrows the
binding surface's two checks.

```bash
# The branch moved. What would land, and what collides?
curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/versions/2.0.0/binding/sync" \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'

# Decide one collision. `git` takes the repository's value; `draft` keeps the version's.
curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/sync-plans/$PLAN/conflicts/$CONFLICT" \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"resolution":"git","note":"the rename was agreed in review"}'
```

`POST …/binding/sync` merges the binding's **oldest outstanding** candidate by default — the
earliest unmerged movement is the one a reader is looking at, and taking them in order keeps the
sequence of decisions in the order the branch actually happened. Pass `candidate_id` to pick a
different one.

---

## What a merge does

Both sides are diffed against the base with `app.source_change_review.diff_documents` — the same
engine the source-to-model review uses — so a change reads identically wherever the product shows
one, and is grouped by `scope_for_pointer` into `document` / `path` / `operation` / `component` /
`schema`.

Each incoming delta is then classified against the draft's own deltas:

| Situation | Outcome |
|---|---|
| the draft left that place alone | **applied** — counted in `auto_applied_count`, listed in `changes` |
| both sides made the same change | **agreed** — nothing to do, counted in `agreed_count` |
| both sides moved the same place differently | **conflict** — one row, left for a person |
| only the draft changed | **local** — counted in `local_count`; the merge keeps out of the way |

A conflict is reported at the **exact value** both sides moved, widening only to a subtree one side
replaced outright. If the repository edits `/paths/~1pets/get/summary` and the draft replaces the
whole operation with something of another shape, the conflict is the operation — saying "summary"
would hide what really happened. If the draft merely edited the same operation's summary, the
conflict is the summary, and the draft's other edits in that operation stay its own business.

Arrays merge by position. That is safe because any shape change on the draft's side (an insert that
shifts every later index) shows up as overlapping deltas and therefore as conflicts; and within one
merge, trailing deletions apply from the highest index down before additions apply from the lowest
up, so an earlier removal never shifts a later one.

`status` is one of:

* `clean` — the repository changed nothing since the base;
* `mergeable` — incoming changes exist and none of them overlap;
* `conflicted` — at least one overlap is outstanding;
* `resolved` — every conflict has been settled towards one side.

---

## The four rules worth knowing

### 1. Three proven reads, never a payload

A merge fetches both commits itself, through
`draft_binding_store.read_source_fileset` — the same credential-resolving read binding uses, which
resolves a **stored** token (the registered repository's linked account, or the caller's own) and
actually downloads the selection. A delivery's assertion about what a commit contains is never
believed, and a repository the tenant cannot reach is answered `403 binding-repository-forbidden`
rather than merged from a guess. No credential is ever accepted in a request body, and V266 has no
column for one.

The third document is rebuilt from the canonical model exactly as lint freshness, the compatibility
engine and review fingerprints rebuild it, so "the draft changed" means the same thing everywhere.

### 2. The base must still be the base

Before merging, the selection at `base_commit_sha` is re-read and hashed. If it no longer matches
the digest the binding recorded, somebody rewrote history underneath the merge base — and every
"which side changed this" answer computed from it would be a guess. That refuses with
`sync-base-drifted` rather than merging against something nobody agreed to.

### 3. Reruns are free, not just idempotent

`plan_fingerprint(binding, base commit, git commit, draft digest)` is computable **before** any
network call, and `UNIQUE (binding_id, plan_fingerprint)` backs it. Re-running a merge of the same
three documents returns the stored result without fetching two commits to prove it would be the
same. A redelivered webhook, a double-clicked button and a refreshed page all cost nothing.

The draft is identified by its content digest rather than by its revision id, because a revision
that has been edited is a *different document* and must not reuse an older merge. A stored result
whose `draft_digest` no longer matches comes back with `stale: true`.

### 4. Work that already exists is reported, not trampled

Every result carries a `guard`:

* `none` — an ordinary draft;
* `review_decided` — an open review's current round already holds a recorded decision;
* `version_published` — the version is no longer a draft.

A guard does **not** refuse the merge. Knowing exactly what would collide is precisely what such a
reader needs. It says, on the row, that this result may not be turned into an edit — and since
nothing in this ticket can turn one into an edit anyway, the guard is the record that the question
was asked.

---

## Conflicts

Each conflict row carries:

| Field | Meaning |
|---|---|
| `pointer` | RFC 6901 pointer of the collision; `""` is the document root and is a legal value |
| `scope`, `group_key`, `label` | the shared change vocabulary, so it reads like every other change list |
| `git_kind`, `draft_kind` | `addition` / `update` / `deletion` — what each side did to the base |
| `base_value`, `git_value`, `draft_value` | all three sides, side by side |
| `source_file`, `source_line`, `source_url` | the repository file, the 1-based line, and a link at the commit |

Line numbers come from `locate_pointer_lines`, which *composes* the incoming document rather than
loading it, so node marks survive. A mapping entry reports its **key's** line: in block YAML the
value of `summary:` starts on the next line, which is not where anybody would look. JSON is a
subset of YAML for every construct a spec document uses, so one composer serves both, and anything
that cannot be composed simply yields no line — a merge without line numbers is still a merge.

Values are bounded before storage (`MAX_VALUE_BYTES`): an oversized subtree is replaced by
`{"$truncated": true, "bytes": n}`, because a conflict row is read straight into a browser response
and one enormous value would make every other conflict unreadable. A merge that collides in more
than `MAX_CONFLICTS` places stores the first page and sets `conflicts_truncated` on the plan — a
result that quietly dropped findings would read as *less* conflicted than it is, which is the one
direction this table must never be wrong in.

**A settlement is final.** `git` or `draft`, once, with an optional note; the V266 trigger refuses
to move it afterwards, exactly as GNC-2.1's trigger does for a sync candidate. The plan's
`unresolved_count` is recomputed from the rows under its row lock rather than decremented, so two
people settling the last two conflicts at once cannot leave a plan claiming an outstanding conflict
that no longer exists. `conflict_count` is what the merge *found* and never moves.

---

## Refusals

| Code | Status | Meaning |
|---|---|---|
| `sync-not-bound` | 404 | the version has no active binding to merge against |
| `sync-plan-not-found` | 404 | no such merge result in this project |
| `sync-conflict-not-found` | 404 | no such conflict on this merge result |
| `sync-nothing-to-merge` | 409 | the ref is where the binding already is, or the named candidate is not one of its own |
| `sync-base-drifted` | 409 | the merge base was rewritten; re-check and re-bind |
| `sync-conflict-resolved` | 409 | the conflict already settled; settlements are final |
| `sync-conflict` | 409 | somebody else won the race; read it again and retry |
| `sync-invalid-document` | 422 | a side is not a readable spec document |

Repository refusals keep their `binding-repository-*` codes and statuses, so a client learns one
vocabulary for "the repository could not be read".

---

## Audit

Every merge and every settlement writes a `workflow_audit` row **inside** the transaction of the
change it records:

* `sync.planned` — with the binding, the candidate, both commits, the draft digest, the status, the
  applied count, the conflict count and the guard;
* `sync.conflict_resolved` — with the plan, the conflict, its pointer, the side chosen, and what
  the plan's status became.

Both are readable through `GET /v1/tenants/{tenant_slug}/workflow-audit?version_id=…`.

---

## What this ticket does not do

* It does not **write back to Git.** Pushing a draft to a repository is a later ticket's job.
* It does not **apply a merge to a draft.** The merged document is computed (and is asserted to be
  deterministic), but turning it into an edit of the canonical model is a separate, explicit act
  that this surface gives no storage and no endpoint to.
* It does not **settle the sync candidate.** Once a merge is dealt with, the candidate is applied or
  dismissed through GNC-2.1's existing `…/binding/candidates/{id}` endpoint, which re-reads the
  source before it advances the binding.

---

## Where the code is

| File | What |
|---|---|
| `apiome-db/scripts/V266__draft_sync_plans_gnc_2_3.sql` | `draft_sync_plans`, `draft_sync_conflicts`, two guard triggers |
| `src/app/spec_sync.py` | vocabulary, models, the merge engine, the line locator — all pure |
| `src/app/spec_sync_store.py` | the rules: proven reads, the base check, guards, storage |
| `src/app/spec_sync_routes.py` | the four endpoints |
| `src/app/database.py` | the accessors, at the end |
| `tests/test_spec_sync*.py`, `tests/fake_sync_db.py` | engine, store, routes, accessors, migration |
