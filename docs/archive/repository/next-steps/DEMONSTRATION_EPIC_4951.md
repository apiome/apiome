# DEMONSTRATION — GNC-EPIC-3: Team Flow Completion

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [GNC-EPIC-3 #4951](https://github.com/apiome/apiome/issues/4951) · umbrella [GNC #4949](https://github.com/apiome/apiome/issues/4949) |
| Wave | 4 — the last piece of the collaboration lane |
| Ticket | [GNC-3.1 · API change check suite #4740](https://github.com/apiome/apiome/issues/4740) |
| Builds on | GNC-2.2 status adapter ✅ (Wave 4) · **CTG-4.5 gate API ✅ (Wave 1)** · CTG-2.2 action ✅ · GOV-2.5 ✅ · SGD-2.1 manifest ✅ |
| Runtime | ~8 min, plus 15 min prep |
| Audience | the platform team that owns the merge button |
| The one beat | **One required check on the pull request, and everything the platform knows is behind it.** |

> This is the payoff video for three separate lanes. It only works if
> [CTG-EPIC-4](DEMONSTRATION_EPIC_4466.md) and [GNC-EPIC-2](DEMONSTRATION_EPIC_4950.md) are both
> done — the check aggregates the gate endpoint and reports through the status adapter.

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | The wall of checks | Six API checks nobody reads. | 1:00 |
| 2 | Open a pull request | One check. Pending. | 1:30 |
| 3 | It fails, with a reason | And the reason is a link, not a log. | 2:30 |
| 4 | Fix it, re-run | Idempotent. Same input, same verdict. | 1:30 |
| 5 | Make it required | Merge is gated on the contract. | 1:30 |

---

## PREP — before anyone is watching (~15 min)

**DO** — Everything from the [GNC-EPIC-2 prep](DEMONSTRATION_EPIC_4950.md): a reachable webhook,
a linked repository, a bound draft.

**DO** — Register consumers on the project ([CTG-4.1](https://github.com/apiome/apiome/issues/4479))
so Act 3's failure has a named consumer in it. "Breaks billing-service" is a story; "breaking
change detected" is a lint warning.

**DO** — Prepare **two branches**: one with a breaking change that a registered consumer depends
on, one with the fix.

**DO** — Screenshot a pull request from a real project with five or six separate API-related
checks on it, for Act 1. Your own repo probably has one.

**DO** — Full dry run — including the re-run in Act 4, which is the beat most likely to
misbehave.

---

## ACT 1 — The wall of checks (1:00)

**DO** — Show the screenshot from prep: a PR with a column of green and yellow API checks.

**SAY**

> This is what "we have API governance in CI" usually looks like. A lint check, a diff check, a
> breaking-change check, a contract test, an SDK build, and a spectral run someone added in 2024
> that nobody can turn off.
>
> Six checks, six logs, six different formats, and a reviewer who reads none of them because the
> merge button is green and it's Friday.
>
> The problem isn't that the checks are wrong. It's that a wall of checks is not a decision.

---

## ACT 2 — Open a pull request (1:30)

**DO** — Push the breaking branch. Open a pull request.

**DO** — *Pause on the checks section.* One check: **API change check** — pending.

**SAY**

> One check.
>
> It appears as pending the moment the PR opens, which matters more than it sounds. A check that
> only shows up once it has an answer is indistinguishable from a check that isn't running, and
> reviewers learn to merge past the gap.

---

## ACT 3 — It fails, with a reason (2:30)

**DO** — Let the check resolve. **Failed.**

**DO** — Show the summary on the PR itself, before clicking anything:

> **API change check — failed**
> Breaking: `pet.tag` removed from `GET /pets/{petId}` (200)
> Consumers affected: 1 of 7 — `billing-service`
> Lint grade: B · SDK compatibility: 2 published clients affected
> Verification: last run 3h ago, conforming

**DO** — Click the drill-down link. It opens the evidence — the classified diff, the consumer
verdict, the lint report.

**SAY**

> One verdict, and underneath it everything the platform already knew, which was previously
> spread across the six checks we started with.
>
> The reviewer does not need to open anything to know what to do here: it breaks billing, and
> billing has a name and a contract. If they *want* the detail, the drill-down is the actual
> evidence record — the same one an auditor would read six months from now, not a CI log that
> expired after thirty days.
>
> And this check isn't computing anything new. It calls the gate endpoint from the assurance
> chapter and reports the answer. There is one verdict model in the platform, and this is a
> transport for it — not a second opinion that can disagree with the dashboard.

---

## ACT 4 — Fix it, re-run (1:30)

**DO** — Push the fix branch commit. The check re-runs and passes.

**DO** — Now re-run the check manually, without any new commit. Same verdict, same evidence IDs.

**SAY**

> Same input, same answer, and re-running produces the same evidence rather than a new
> almost-identical record.
>
> Idempotence sounds like housekeeping. It isn't — a check that gives a different answer on a
> re-run trains everyone to just hit re-run until it's green, and at that point the gate is
> decoration.
>
> Note also the states: pending, pass, fail, and **skipped**. Skipped is deliberate — a PR that
> doesn't touch the spec should say so, not show a hollow green tick that means nothing.

---

## ACT 5 — Make it required (1:30)

**DO** — In the repository's branch protection settings, mark **API change check** as required.

**DO** — Return to the breaking PR. The merge button is blocked.

**DO** — Show the corresponding policy on the platform side: the same check maps to the publish
gate.

**SAY**

> Now it's the merge button, not a suggestion.
>
> And the same policy maps to publishing on our side, so a change cannot get in through the other
> door either. That symmetry is the whole point of the epic: whether your team's workflow starts
> in a pull request or in the designer, it meets the same gate, backed by the same evidence.
>
> That's the collaboration lane complete. The discussion is on the design, the decision is bound
> to what was decided, the repository and the designer reconcile without either one winning
> silently, and the merge button is gated on all of it.

---

## RESCUE — when it goes wrong on stage

**The check never appears on the PR**
The status adapter isn't receiving the PR event, or the app lacks checks permission.
*On stage:* show the verdict from the gate endpoint directly and narrate the PR surface. Verify
permissions in prep.

**It fails for the wrong reason**
Lint or verification failed alongside the consumer break, muddying the story.
*On stage:* fine — narrate it as "and it's telling us about three things at once". Better than
pretending.

**Re-run produces different evidence IDs**
Idempotence failure.
*On stage:* say so plainly and file it. Act 4's claim is not one to gloss.

**Branch protection can't find the check**
The check name must have been reported at least once on that branch.
*On stage:* skip to the platform-side policy — the symmetry beat survives without the GitHub UI.

---

## IF ASKED

**"Can we still have our own checks?"**
Of course. This replaces the *API* checks, not your test suite.

**"What if the platform is down — does that block our merges?"**
The check reports a distinguishable "could not run" rather than a failure, and whether that
blocks merging is your branch-protection decision. A check that can't tell "broken" from
"unreachable" is a flaky build everyone learns to ignore.

**"Does this need the draft binding from the previous chapter?"**
For the full verdict, yes — the check needs to know which project and version the PR corresponds
to. That's what the binding establishes.

---

## Reference

| Surface | Where |
|---|---|
| Gate endpoint | `GET /v1/projects/{id}/gate` |
| Versions (binding, policy) | <http://localhost:3000/ade/dashboard/versions> |
| CLI | `apiome gate $PROJECT --fail-on block` |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_GIT_NATIVE_COLLABORATION.md` |
| Assurance chapter | [DEMONSTRATION_EPIC_4466](DEMONSTRATION_EPIC_4466.md) |
