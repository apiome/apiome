# DEMONSTRATION — GNC-EPIC-2: Git Provider Synchronization

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [GNC-EPIC-2 #4950](https://github.com/apiome/apiome/issues/4950) · umbrella [GNC #4949](https://github.com/apiome/apiome/issues/4949) |
| Wave | 4 — after the Collaboration chapters |
| Tickets | [2.1 #4737](https://github.com/apiome/apiome/issues/4737) · [2.2 #4738](https://github.com/apiome/apiome/issues/4738) · [2.3 #4739](https://github.com/apiome/apiome/issues/4739) |
| Builds on | REPO-1.x provider layer ✅ · REPO-4.3/4.7 signed webhooks + rotation ✅ · RAR import-spec capture ✅ · COL-2.1 review decisions ✅ (Wave 3) |
| Runtime | ~13 min, plus 20 min prep |
| Audience | teams whose spec lives in a repo and who refuse to give that up |
| The one beat | **The repo and the designer edit the same spec, and neither one silently wins.** |

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | The objection | "Our spec lives in Git. We're not moving it." | 1:00 |
| 2 | Bind a branch to a draft | One draft, one ref, one path. | 2:30 |
| 3 | Push to the branch | The change arrives as a *candidate*, not an overwrite. | 2:30 |
| 4 | Accept the clean part | Non-overlapping changes apply themselves. | 2:00 |
| 5 | Edit both sides, then push | A real conflict, shown three ways. | 3:00 |
| 6 | Try to overwrite an active draft | It won't. That's the guarantee. | 2:00 |

---

## PREP — before anyone is watching (~20 min)

**DO** — Start the stack, and make it reachable by a webhook. `localhost` cannot receive a GitHub
delivery. Either run a tunnel and register it, or use the provider harness that replays a signed
payload locally. **Decide this in prep and rehearse it** — an unreachable webhook kills Acts 3–6.

**DO** — Create a repository with `openapi.yaml` on a branch. Link it to the tenant at
<http://localhost:3000/ade/dashboard/linked-accounts>.

**DO** — Import that spec into a project so the binding in Act 2 has both sides.

**DO** — Prepare **three commits** on your desktop, ready to push:
1. an additive change in one part of the document (Act 3/4 — clean),
2. a change to a description on a field you will *also* edit in the designer (Act 5 — conflict),
3. anything at all (Act 6 — refused).

Writing commits on camera is dead air, and getting a conflict to occur by improvisation is
unreliable.

**DO** — Full dry run, including a webhook delivery. Reset the branch afterwards.

---

## ACT 1 — The objection (1:00)

**DO** — Show the repository and its `openapi.yaml`. Then show the same spec in the designer.

**SAY**

> Here's the objection this epic exists to answer. "Our spec is in Git. It's reviewed in pull
> requests, it's versioned with the service, and we are not moving it into your tool."
>
> Which is correct. They shouldn't.
>
> The usual answer is a one-way import — we read your repo, you get a read-only copy. That's
> fine until someone edits in the designer, and then there are two specs and a bad afternoon
> ahead.
>
> So: two writers, one document. Let's see what it takes to make that safe.

---

## ACT 2 — Bind a branch to a draft (2:30)

**DO** — Open the draft version. Click **Bind to repository**. Choose the provider, the
repository, the branch, and the path to `openapi.yaml`.

**DO** — *Pause on the authorization step.* It verifies your access to that repository before it
saves.

**DO** — Show the binding: provider, repo, ref, path, and the **source digest** — the exact
content this draft was last synchronized with.

**DO** — Try to bind a second branch to the same draft. Refused.

**SAY**

> A draft binds to exactly one ref and one path. Not a list, not a glob.
>
> That constraint is doing real work. Reconciliation between one document and one source is a
> problem with an answer; reconciliation between one document and three sources is a problem with
> a research paper.
>
> And the digest is the third point of reference. Everything that follows is a three-way
> comparison — what Git has now, what the draft has now, and what they last agreed on. Without
> that third value you can detect that two things differ but not *who changed what*, which is the
> difference between merging and guessing.

---

## ACT 3 — Push to the branch (2:30)

**DO** — Push commit 1 (the additive change).

**DO** — Switch to the version. *Pause.* A **sync candidate** has appeared. The draft has not
changed.

**DO** — Open the candidate. Show the incoming changes.

**SAY**

> The push arrived and the draft did not move.
>
> That is deliberate and it is the single most important behaviour in this epic. A webhook is an
> event from outside your control. If it can write directly into a document someone is editing,
> then a colleague's push can silently destroy work in progress — and it will happen on the day
> someone is mid-refactor.
>
> So an inbound change becomes a candidate. Explicit. Reviewable. And the delivery is signature
> validated and idempotent, so a provider retrying five times produces one candidate, not five.

---

## ACT 4 — Accept the clean part (2:00)

**DO** — In the candidate, show that all incoming changes are non-overlapping — the draft has no
competing edits.

**DO** — Apply. The draft updates. The digest advances.

**SAY**

> No overlap, so it applies — and the digest moves forward to the commit we just took.
>
> This is the common case, and it should be boring. Most pushes touch a part of the document
> nobody is editing in the designer, and demanding a manual merge for those would make the
> integration exhausting enough that people turn it off.
>
> Auto-apply only where there is genuinely nothing to decide. Everything else asks.

---

## ACT 5 — Edit both sides, then push (3:00)

*The payoff. Slow down.*

**DO** — In Studio, edit the description on a specific field. Save the draft. Do not sync.

**DO** — Push commit 2 — which changes *that same field's* description to something different.

**DO** — Open the sync candidate. *Pause on the conflict view.*

> **1 conflict · 3 changes applied**
> `Pet.status` description
> **base** (last synced, `a1b2c3d`) — "The pet's status"
> **incoming** (`e4f5g6h`, branch `main`) — "Current availability status of the pet"
> **current** (draft, edited by Ada 4 minutes ago) — "Status in the adoption workflow"
> `openapi.yaml` line 84

**DO** — Choose the draft's value. Apply. Show the other three changes went in cleanly alongside.

**SAY**

> Three values, not two. That's what the digest bought us.
>
> Two-way merge can only tell you these strings differ. Three-way tells you *both sides changed
> it since they last agreed*, which is the only definition of "conflict" that doesn't produce a
> false alarm every time one side edits and the other doesn't.
>
> And it points at a line in `openapi.yaml`, because the person resolving this needs to find it
> in the file they will eventually commit to.
>
> Also worth noticing: the three non-conflicting changes applied anyway. A conflict blocks the
> field it's about, not the whole sync.

---

## ACT 6 — Try to overwrite an active draft (2:00)

**DO** — Start editing in Studio and leave the draft dirty — an unsaved or actively-edited state.

**DO** — Push commit 3.

**DO** — Show the candidate queued and explicitly **not** applied, with the reason: the draft is
active.

**DO** — Now show the other guarantee. Take a draft that has an approval on it (from the
[review chapter](DEMONSTRATION_EPIC_4510.md)), push a change, apply it — and show the approval
invalidating.

**SAY**

> Two things can never happen here.
>
> An inbound push cannot overwrite an active draft. Someone else's commit does not get to
> discard your in-progress work, ever, under any timing.
>
> And an inbound push cannot carry a stale approval past the gate. The approval was bound to a
> spec revision in the last chapter; the sync changed the revision; the approval resets. If that
> weren't true, this integration would be a hole straight through the review process — push after
> approval, publish before anyone notices.
>
> One more thing that is *not* here, deliberately: nothing we did wrote back to the repository.
> This epic reads. Write-back is a separate piece of work, because a tool that pushes to your
> branches has to earn that in its own right.

---

## RESCUE — when it goes wrong on stage

**The webhook never arrives**
Tunnel down, secret mismatch, or the provider stopped delivering after failures.
*On stage:* use the local replay harness. Have the command ready in your shell history — this is
the most likely failure in the whole script.

**The binding refuses with an authorization error**
The linked account's grant doesn't cover that repository.
*On stage:* switch to a repository you verified in prep. Do not re-authorize on camera.

**Act 5 shows no conflict**
Your two edits didn't actually overlap, or the draft edit wasn't saved before the push.
*On stage:* this is why the commits are prepared. Redo the designer edit on the exact field
commit 2 touches, save, and re-deliver the webhook.

**The candidate auto-applies over the draft**
A real failure of the epic's central guarantee.
*On stage:* stop and file it. Act 6 is the promise; a broken promise is the demo.

---

## IF ASKED

**"GitLab? Bitbucket?"**
GitHub first, through a normalized adapter interface, and the others follow through the same
interface. The normalization is the work; the second provider is much cheaper than the first.

**"Can it write back to the branch?"**
Not in this epic — deliberately. Write-back is separate scope. Everything here is read plus
explicit reconciliation.

**"What if the file is renamed or moved?"**
The binding is to a path. A move breaks it and surfaces as a binding error rather than as a
silent no-op — which is the right failure, because a silently-stopped sync is worse than a broken
one.

**"Do repository tokens ever reach the browser?"**
No. The adapter holds them server-side; that's an explicit acceptance criterion.

---

## Reference

| Surface | Where |
|---|---|
| Linked accounts | <http://localhost:3000/ade/dashboard/linked-accounts> |
| Repositories | <http://localhost:3000/ade/dashboard/repositories> |
| Versions (binding, sync candidates) | <http://localhost:3000/ade/dashboard/versions> |
| Studio editor | <http://localhost:3000/ade/studio/editor> |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_GIT_NATIVE_COLLABORATION.md` |
