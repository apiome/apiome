# DEMONSTRATION — RC1 Phase 4: Stabilization & Release Gate

> **Written ahead of the recording.** This one is different from the others: it is not a feature
> demo. It is the recorded evidence that RC5 is done — the walkthrough you play at the gate
> review and keep afterwards.

| | |
|---|---|
| Epic | [RC1 Phase 4 — Stabilization & Release Gate #3607](https://github.com/apiome/apiome/issues/3607) |
| Wave | 6 — last |
| Tickets | [4.1 #3620](https://github.com/apiome/apiome/issues/3620) · [4.2 #3621](https://github.com/apiome/apiome/issues/3621) · [4.3 #3622](https://github.com/apiome/apiome/issues/3622) |
| Builds on | every other epic in this directory, plus [HIVE-EPIC-10](DEMONSTRATION_EPIC_5273.md) |
| Runtime | ~14 min, plus 30 min prep |
| Audience | whoever signs off on tagging `v1.0.0-rc.1` |
| The one beat | **Every claim in the gate checklist has evidence behind it, and the two that don't are named out loud.** |

> **RC1-4.1 starts at Wave 0, not at Wave 6.** Dogfooding runs the whole time; it is the input to
> the burn-down, not a step after it. This video is recorded at the end, but the work in it began
> on day one.

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | The golden path, start to finish | One take, no cuts, no rescue. | 4:00 |
| 2 | What the beta cohort found | Real usage, triaged, with numbers. | 2:00 |
| 3 | The bug ledger | Zero Critical, zero High — and what was deferred. | 2:30 |
| 4 | Latency under load | A budget, and a measurement against it. | 2:00 |
| 5 | Accessibility | Carried from HIVE-10.2, plus browse and the designer. | 1:30 |
| 6 | Security | The `/security-review` gate, including the four OLO follow-ups. | 2:00 |

---

## PREP — before anyone is watching (~30 min)

**DO** — Run against a **release-candidate build**, not a dev stack. A gate review recorded on
`yarn dev` proves nothing about the thing you are shipping.

**DO** — Rehearse Act 1 until it runs clean **without any rescue step**. That is the point of the
act: if the golden path needs a save, the gate answer is "not yet". Time it.

**DO** — Have these ready as artifacts, not as live queries:
- the beta cohort's issue list, labelled and triaged;
- the open-bug query by severity;
- the deferred list, each with a written reason;
- the load-test report against the documented latency budget;
- the axe results across `apiome-ui`, browse and the designer;
- the `/security-review` output.

**DO** — Resolve the four unmilestoned OLO-7.3 security follow-ups
([#4960](https://github.com/apiome/apiome/issues/4960),
[#4961](https://github.com/apiome/apiome/issues/4961),
[#4962](https://github.com/apiome/apiome/issues/4962),
[#4963](https://github.com/apiome/apiome/issues/4963)) — fixed or explicitly deferred with a
note. Act 6 names them either way; unresolved-and-unmentioned is the one outcome that is not
allowed.

**DO** — Write down, before recording, the things that are **not** ready. Act 3 is where they go.

---

## ACT 1 — The golden path, start to finish (4:00)

*One take. If it needs a rescue, stop recording — that is the finding.*

**DO** — Sign in. Create a tenant, or enter an existing one.

**DO** — Import a spec. Lint it. See the grade.

**DO** — Edit it in Studio. Comment on a field. Request a review. Approve it.

**DO** — Publish. Watch the gate pass.

**DO** — Turn the mock on. Call it.

**DO** — Generate an SDK. Download it.

**DO** — Open the public Browse page as an anonymous visitor. Get the SDK from there.

**SAY**

> That's the spine, end to end, in one take: import, lint, design, discuss, review, publish, mock,
> generate, consume.
>
> No cuts, and nothing in that run needed a workaround. That's the claim the rest of this video
> supports — and it's the claim I'd retract first if the take had needed a rescue, because a
> golden path that only works when the person driving knows where the potholes are is not a
> golden path.

---

## ACT 2 — What the beta cohort found (2:00)

**DO** — Show the cohort: how many people, over what period, doing what.

**DO** — Show the issue list they generated — labelled, triaged, and linked to the workflows they
came from.

**DO** — Pick two or three and say what happened to each: fixed, deferred, or a design change.

**SAY**

> This is the part that is not a metric. A small group used it for real work and told us what
> broke.
>
> What matters here is the *shape* of what they found. If the reports are about workflows we
> never anticipated, the product is fine and the documentation isn't. If they're about the spine
> — import, publish, mock — that's a different conversation and it happens before the tag, not
> after.

---

## ACT 3 — The bug ledger (2:30)

**DO** — Show the open-bug query by severity. Zero Critical, zero High.

**DO** — Now show the **deferred** list. Read two or three out, with the reason each was deferred.

**DO** — Say plainly what is still weak.

**SAY**

> Zero Critical and zero High at the gate. That's the bar, and it's only meaningful next to the
> list beside it.
>
> Because "no High bugs" is trivially achievable by re-labelling, and everyone in this room knows
> it. So here is what we deferred, and why, in writing — each one a decision somebody made on
> purpose rather than a thing that quietly fell off the board.
>
> And here is what I'd still call thin. [Say it. Name the two or three areas with the least
> coverage or the most recent churn.] That belongs in this video, because the point of a gate is
> to make a decision with the real picture, not a flattering one.

---

## ACT 4 — Latency under load (2:00)

**DO** — Show the **documented** latency budget for the spine endpoints. Show it as a written
target that existed before the test.

**DO** — Show the load-test report against it. Walk the endpoints that pass and any that don't.

**DO** — If something misses, say by how much and what the plan is.

**SAY**

> A budget written down first, then measured. In that order — a latency number produced without a
> target is just a number, and it will always be described as acceptable.
>
> [Walk the results honestly. If an endpoint misses, name it and say whether it blocks the tag.]

---

## ACT 5 — Accessibility (1:30)

**DO** — Reference the [HIVE-10.2 evidence](DEMONSTRATION_EPIC_5273.md) rather than repeating it.

**DO** — Show the results for the two surfaces HIVE-10 did **not** cover: the designer and paths
editors, and the browse app.

**DO** — Show anything triaged rather than fixed, with its reason.

**SAY**

> The control panel's accessibility evidence is the previous video — full axe coverage in three
> themes, keyboard traversal of every new pattern. I'm not going to re-run it here.
>
> What this act adds is the two surfaces that epic didn't touch: the editors and browse. [Walk
> the results.] Anything triaged rather than fixed is listed with a reason, same as the bug
> ledger.

---

## ACT 6 — Security (2:00)

**DO** — Show the `/security-review` output for the release branch.

**DO** — Go through the four OLO-7.3 follow-ups explicitly, one at a time:
[#4960 token encryption at rest](https://github.com/apiome/apiome/issues/4960),
[#4961 Public Suffix List for callback allowlist](https://github.com/apiome/apiome/issues/4961),
[#4962 account enumeration on legacy self-signup](https://github.com/apiome/apiome/issues/4962),
[#4963 link-route CSRF and login fail-closed](https://github.com/apiome/apiome/issues/4963).
Fixed, or deferred with a reason. Say which.

**DO** — Close on the gate checklist from [#3607](https://github.com/apiome/apiome/issues/3607),
ticked, with this video as the evidence for each line.

**SAY**

> These four were found by a security review, filed, and then sat unmilestoned — which is how
> security follow-ups usually disappear. So they get named here, individually, and the answer is
> either "fixed" or "deferred, for this reason". Not silence.
>
> That's the gate. Every line has evidence, the deferrals are written down, and the things I'd
> still call weak were said out loud rather than left for someone to find.
>
> On that basis: [state the recommendation — tag, or don't, and what would change it].

---

## RESCUE — when it goes wrong on stage

There is no rescue section for this one, and that is deliberate.

If Act 1 needs a workaround, **stop recording**. The golden path failing under rehearsal
conditions is the most valuable output this exercise can produce, and editing around it converts
a real finding into a false record. Fix it, then record again.

For Acts 2–6, a bad number is not a failure of the video. Read it out. A gate review that only
shows good numbers is not a gate review.

---

## IF ASKED

**"What's explicitly not in this release?"**
The format-expansion pack ([FMT-EPIC-5…11](https://github.com/apiome/apiome/issues/5405), 43
open), the admin console redesign
([HIVE-EPIC-9 #5272](https://github.com/apiome/apiome/issues/5272)), and the expanded SSO catalog
([OLO-EPIC-9 #4983](https://github.com/apiome/apiome/issues/4983)) — all deferred past RC5 on
purpose. See §5 of [`RC5_EPIC_ORDER_OF_EXECUTION.md`](RC5_EPIC_ORDER_OF_EXECUTION.md).

**"What about the v2 items in the Future milestone?"**
Every epic in this directory has `Future` children. They are listed per epic in the order-of-
execution document and none of them gate the tag.

**"Who is the beta cohort?"**
Named in [RC1-4.1 #3620](https://github.com/apiome/apiome/issues/3620)'s triage notes.

---

## Reference

| Surface | Where |
|---|---|
| Gate checklist | [#3607](https://github.com/apiome/apiome/issues/3607) |
| Order of execution | [RC5_EPIC_ORDER_OF_EXECUTION.md](RC5_EPIC_ORDER_OF_EXECUTION.md) |
| Ticket-level sequencing | `private-suite/docs/roadmaps/RC5_OOE.md` |
| First-RC roadmap | issue pack `roadmap-first-rc` — the `docs/ROADMAP_FIRST_RC.md` path the issue bodies cite is **not in the tree**; [#3607](https://github.com/apiome/apiome/issues/3607) is the authority |
| Release process | `private-suite/docs/RELEASE_PROCESS.md` |
