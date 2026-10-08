# DEMONSTRATION — COL-EPIC-2: Review & Approval

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [COL-EPIC-2 #4510](https://github.com/apiome/apiome/issues/4510) · umbrella [COL #4508](https://github.com/apiome/apiome/issues/4508) |
| Wave | 3 — after [COL-EPIC-1](DEMONSTRATION_EPIC_4509.md) |
| Tickets | [2.1 #4517](https://github.com/apiome/apiome/issues/4517) · [2.2 #4518](https://github.com/apiome/apiome/issues/4518) · [2.3 #4519](https://github.com/apiome/apiome/issues/4519) · [2.4 #4520](https://github.com/apiome/apiome/issues/4520) |
| Builds on | COL-1.1 threads ✅ (Wave 3) · CTG-1.3 classified diff ✅ · GOV-2.5 publish-gate pattern ✅ |
| Runtime | ~12 min, plus 10 min prep |
| Audience | anyone who has been asked "did someone review this before it went out?" |
| The one beat | **An approval is bound to what was approved — change the spec and the approval is gone.** |

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | Try to publish | Blocked. Policy, not opinion. | 1:30 |
| 2 | Request a review | One page, three tabs, one decision. | 2:00 |
| 3 | Request changes | A decision with a required reason. | 2:00 |
| 4 | Fix it, approve it | The gate opens. | 2:00 |
| 5 | Change the spec after approval | **The approval is invalidated.** | 2:30 |
| 6 | Force-publish | Possible, audited, and it names you. | 2:00 |

---

## PREP — before anyone is watching (~10 min)

**DO** — Start the stack. Continue in the project from the
[COL-EPIC-1 recording](DEMONSTRATION_EPIC_4509.md) — the threads you created there show up in
Act 2's Discussion tab, which is worth the continuity.

**DO** — Two browser profiles again: an **author** and a **reviewer**, both tenant members.

**DO** — Set the approval policy before you start: tenant settings → governance →
`required_approvals: 1`. Act 1 depends on the policy already being on.

**DO** — Have a draft version with a handful of real changes in it — enough that the **Changes**
tab has something to show. A one-line diff makes the review page look pointless.

**DO** — Full dry run. Reset the version and the review afterwards.

---

## ACT 1 — Try to publish (1:30)

**DO** — As the author, open the draft version and click **Publish**.

**DO** — *Pause on the refusal.* The dialog names what is missing: 0 of 1 required approvals.

**SAY**

> Publishing is blocked, and it's blocked by a tenant policy rather than by a convention someone
> is supposed to remember.
>
> This is the same gate pattern as the style-guide policies — a 422 with a specific reason, not a
> disabled button. That matters because a disabled button is a UI decision that an API call
> ignores, and the whole point is that the *contract* is gated.

---

## ACT 2 — Request a review (2:00)

**DO** — Click **Request review**. Add the reviewer. Submit.

**DO** — Switch to the reviewer profile. Open the review at `/ade/reviews/{id}`.

**DO** — Walk the three tabs deliberately:
- **Changes** — the classified diff. Point at a change marked breaking.
- **Spec** — the rendered version, read-only.
- **Discussion** — the open threads from the previous chapter.

**DO** — Point at the sticky decision bar at the bottom. It does not move as you scroll.

**SAY**

> One page. What changed, what it means, what people are already arguing about, and the decision
> — without leaving.
>
> That sounds obvious and it almost never happens. The normal version of this is a diff in one
> tool, the discussion in a second, and the approval in a third, which is how you end up with an
> approval that nobody can connect to a diff.
>
> The Changes tab is the classified diff we already generate — so the reviewer is told which
> changes are *breaking*, not just which lines moved. A reviewer who has to work that out for
> themselves will eventually stop doing it.

---

## ACT 3 — Request changes (2:00)

**DO** — As the reviewer, click **Request changes**. Try to submit without a note — it refuses.

**DO** — Write a real reason referencing the breaking change. Submit.

**DO** — Switch to the author. The version row now shows a **Changes requested** pill. So does
the project card.

**SAY**

> The note is required on "request changes" and optional on "approve", and that asymmetry is
> deliberate. "Approved" is self-explanatory. "No" without a reason is how a review process
> becomes a thing engineers route around.
>
> And the state is on the version row and the project card — not only inside the review. Someone
> scanning the versions list can see this version is not going anywhere and why.

---

## ACT 4 — Fix it and approve (2:00)

**DO** — As the author, fix the breaking change in Studio. Save.

**DO** — Re-request review.

**DO** — As the reviewer, reload. The diff reflects the fix. Click **Approve**.

**DO** — As the author, click **Publish**. It goes through.

**SAY**

> Gate satisfied, publish proceeds. Nothing exotic — this is the loop working.
>
> Note the history: request, changes requested with a reason, re-request, approve. That sequence
> is stored, immutably. It is the answer to "who signed off on this and what did they see", which
> is a question that gets asked exactly once per year and always at the worst possible time.

---

## ACT 5 — Change the spec after approval (2:30)

*The act that makes this governance rather than theatre.*

**DO** — Create a new draft. Get it approved.

**DO** — *Before publishing*, go back into Studio and make another change — remove a field.

**DO** — Return to the version. *Pause.* The approval is shown as **stale**, and the publish gate
is closed again.

**DO** — Open the review. The reviewer's decision is reset to pending, with the previous decision
preserved in the history.

**SAY**

> This is the one that matters.
>
> An approval that survives a change to the thing it approved is worse than no approval, because
> it launders an unreviewed change through a real signature. Everyone has seen this: approve on
> Monday, "just one small fix" on Tuesday, ship on Wednesday, and the approval on the record is
> for a document nobody read.
>
> So decisions are bound to the spec revision. Change the spec and the decision resets — not
> deleted, reset, with the old decision still in the history showing what it was actually for.
>
> That binding is also what the Git-native chapter needs. When a repository webhook changes the
> source, the same invalidation fires — an external change cannot carry a stale approval past the
> gate either.

---

## ACT 6 — Force-publish (2:00)

**DO** — With the gate closed, click **Publish** and choose **Force publish**. It demands a
reason. Write one.

**DO** — Publish. Open the audit log at <http://localhost:3000/ade/dashboard/audit>. Show the
event: who forced it, when, which version, and the reason.

**SAY**

> You can always ship. There is a two in the morning where the gate is wrong and the outage is
> real.
>
> But it costs you a reason and it costs you a line in the audit log with your name on it. That
> is the correct trade: a gate with no override gets disabled within a month, and a gate that
> can be silently bypassed was never a gate.
>
> So — twelve minutes ago, "did anyone review this?" was answered by scrolling Slack. Now it is a
> record that is bound to what was actually reviewed, and every exception is signed.

---

## RESCUE — when it goes wrong on stage

**Publish succeeds in Act 1**
The approval policy isn't set for this tenant, or the version was already approved.
*On stage:* set `required_approvals` in the governance settings and retry. Check this in prep.

**The Changes tab spins or is empty**
The classified diff is lazy-loaded and the diff job hasn't finished.
*On stage:* narrate over the Spec tab and come back. Don't wait on camera.

**Act 5 doesn't invalidate the approval**
The revision digest isn't wired into the decision.
*On stage:* stop and file it — Act 5 is the epic's central claim, and a demo that glosses over
its failure is worse than a shorter demo.

**Force-publish doesn't ask for a reason**
*On stage:* proceed, but say the reason is required; then file the bug. An unaudited override is
a finding, not a detail.

---

## IF ASKED

**"Can we require a specific person or role?"**
Yes — the policy takes a required reviewer role alongside the count.

**"Can I approve my own version?"**
That's a policy question and the answer is per-tenant. Note that with `required_approvals: 1` and
no role constraint, a solo team needs to be able to, or the product is unusable for them.

**"What about published versions — can they be reviewed?"**
No. Only drafts are reviewable, because a review of something already shipped is a retrospective,
not a gate.

**"Does this replace pull requests?"**
No — it composes with them. The next chapter binds a draft to a branch so the review decision and
the PR check are the same decision.

---

## Reference

| Surface | Where |
|---|---|
| Review page | `/ade/reviews/{id}` |
| Versions (status pills, publish) | <http://localhost:3000/ade/dashboard/versions> |
| Audit log | <http://localhost:3000/ade/dashboard/audit> |
| Governance policy | tenant settings → governance, beside the style-guide policies |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_COLLABORATION_REVIEW.md` §3 |
