# DEMONSTRATION — CTG-EPIC-4: Contract Verification

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [CTG-EPIC-4 #4466](https://github.com/apiome/apiome/issues/4466) · umbrella [CTG #4458](https://github.com/apiome/apiome/issues/4458) |
| Wave | 1 — completes the assurance phase |
| Tickets | [4.1 #4479](https://github.com/apiome/apiome/issues/4479) · [4.2 #4480](https://github.com/apiome/apiome/issues/4480) · [4.3 #4489](https://github.com/apiome/apiome/issues/4489) · [4.4 #4501](https://github.com/apiome/apiome/issues/4501) · [4.5 #4502](https://github.com/apiome/apiome/issues/4502) |
| Builds on | ECA runner ✅, evidence schema ✅, policy evaluator ✅, CTG-1.3 classified diff ✅, SIM-1.3/1.4 synthesis + validators ✅ |
| Runtime | ~14 min, plus 15 min prep |
| Audience | platform teams who own an API that other teams depend on |
| The one beat | **"Is this change safe to ship?" stops being a judgement call and becomes an answer with names on it.** |

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | The question nobody can answer | "Who breaks if I ship this?" — today, a guess. | 1:00 |
| 2 | Register the consumers | Import a Pact file; pick operations for the team that has none. | 2:30 |
| 3 | Make a breaking change | Breaks 1 of 7. Named. The other six are unblocked. | 3:00 |
| 4 | Verify against what's actually deployed | The spec and production disagree — and nobody knew. | 3:00 |
| 5 | Put it on a schedule | Drift finds you instead of you finding it. | 2:00 |
| 6 | One endpoint for the pipeline | `GET …/gate` → one verdict, citing its evidence. | 2:30 |

---

## PREP — before anyone is watching (~15 min)

**DO** — Start the stack. You need REST on `:8000` and the mock on `:8775` — the mock is Act 4's
"deployed" target.

```bash
yarn dev
```

**DO** — Import the petstore spec and publish it. This is the provider.

```bash
cp apiome-ui/examples/openapi/30-openapi-3.0-petstore.yaml ~/Desktop/petstore.yaml
```

**DO** — Have a **Pact file on your desktop** for Act 2. One consumer, a handful of
interactions, at least one of which touches a field you will remove in Act 3. Name the consumer
something that sounds like a real team — `billing-service` narrates better than `consumer-1`.

**DO** — Seed six more consumers ahead of time so Act 3's "1 of 7" has a denominator. Do this in
prep; registering seven consumers on camera is dead air.

**DO** — Stand up the Act 4 target. The simplest honest version: turn the hosted mock on for the
published version, then edit the *spec* so it no longer matches what the mock serves. Now the
spec and the "deployment" genuinely disagree, and the drift you show is real rather than staged.

**DO** — Set the CLI up in a second terminal.

```bash
export APIOME_BASE_URL=http://localhost:8000
export APIOME_TENANT_ID=acme-corp
export APIOME_API_KEY=sk_devseed00000000000000000000000000000000000000000000000000000000
```

**DO** — Full dry run. Act 4 is the one that surprises you; run it twice.

---

## ACT 1 — The question nobody can answer (1:00)

**DO** — Open the project's Versions list at <http://localhost:3000/ade/dashboard/versions>.
Show the existing breaking-change classification from CTG-1.3 — "3 breaking changes".

**SAY**

> We already tell you *what* changed and which changes are breaking. Every API diff tool does
> some version of this.
>
> But "three breaking changes" is not a decision. The question a platform team actually has is
> narrower and much harder: **does anyone depend on the part I broke?** Because breaking a field
> nobody reads is a Tuesday, and breaking a field billing reads is an incident.
>
> Nothing in that screen knows who your consumers are. Let's fix that.

---

## ACT 2 — Register the consumers (2:30)

**DO** — Go to the project's **Consumers** tab. Click **Add consumer** → **Import Pact file**.
Drop the Pact file from prep.

**DO** — *Pause on the result.* The import maps interactions to operations and to the specific
fields each interaction reads. Show the mapped surface — it is a list of operations and fields,
not a list of tests.

**DO** — Add a second consumer the other way: **Add consumer** → **Select operations**. Pick
three operations by hand. Name it `mobile-app`.

**SAY**

> Two routes in, because teams are in two different places.
>
> If a consumer already runs Pact, we read their contract and map it onto your operations —
> they do nothing, and they keep their existing workflow. If they don't, someone ticks the
> operations they use. Thirty seconds, and it is still better than nothing, because the
> alternative is a wiki page from 2023.
>
> What we store is the *used surface*: which operations, which fields. That's the thing a diff
> can be intersected with.

---

## ACT 3 — Make a breaking change (3:00)

*The payoff act. Do not rush it.*

**DO** — Open the spec in Studio at <http://localhost:3000/ade/studio/editor>. Remove a required
response field that the imported Pact contract reads. Save as a new draft version.

**DO** — Open the diff. The classified view shows the breaking change as before.

**DO** — Switch to the **Consumers** view of that diff. *Pause here.*

> Breaks **1 of 7 consumers**
> `billing-service` — reads `pet.tag`, removed from `GET /pets/{petId}` 200 response
> 6 consumers unaffected

**SAY**

> One of seven. And it has a name.
>
> Look at what that changes about the conversation. Before, "three breaking changes" sends a
> platform team to Slack to ask seven teams whether they care, and six of them are interrupted
> for nothing. Now you know it is billing, you know it is `pet.tag`, and you can talk to exactly
> the team that has a problem.
>
> It also changes the *decision*. Six-of-seven unaffected is a change you can schedule. Seven of
> seven is a change you can't ship at all. Same diff, completely different answer — and the diff
> alone could never tell you which one you were in.

**DO** — Show the same verdict from CI.

```bash
apiome contract check --version <version-id> --format text
```

```
breaking changes        3
consumers affected      1 of 7
  billing-service       pet.tag removed from GET /pets/{petId} (200)
unaffected              mobile-app, search-indexer, partner-api, … (6)
exit 1
```

---

## ACT 4 — Verify against what is actually deployed (3:00)

*The act that surprises people, because everyone assumes their spec is true.*

**SAY**

> Everything so far compares a spec to a spec. Here is the uncomfortable question: does your
> deployed API still match the spec you publish?

**DO** — On the version, click **Verify against target**. Enter the base URL of the running mock
(`http://localhost:8775/acme-corp/<project>/<version>`). Safe methods only — leave the mutating
toggle off.

**DO** — Run it. *Pause on the report.*

> 12 operations checked · 10 conform · **2 drift**
> `GET /pets` — response missing required property `tag` (schema conformance)
> `GET /pets/{petId}` — status 200 returned `application/json`, spec declares `application/hal+json`

**SAY**

> These requests were derived from the spec — its own examples first, then synthesized minimal
> cases for the operations that have none. We didn't write a test suite; the spec *is* the test
> suite, and this is the same request synthesis and the same validators the mock uses. One
> engine, so there is nothing to drift between them.
>
> Two operations disagree with the document you're publishing. Nobody broke a build to find
> that, because nothing in a normal pipeline ever compares the two.
>
> Safe methods by default, on purpose. Pointing this at production is only a good idea if
> "verify" cannot create a pet. Mutating verification exists, it's opt-in, and it wants fixtures.

---

## ACT 5 — Put it on a schedule (2:00)

**DO** — On the verification report, click **Schedule**. Daily. Add a webhook target and a
notification recipient.

**DO** — Show a drift alert that already fired — prepare one in prep rather than waiting on
camera for a cron.

**SAY**

> Drift is not a one-time discovery, it's a slow leak. A deployment rolls back, a feature flag
> flips, someone hotfixes a serializer — and the spec you publish quietly stops being true.
>
> On a schedule, that finds you the next morning instead of six weeks later in a consumer's
> incident review. Same runner, same evidence records, same webhook infrastructure that already
> delivers publish events — we didn't build a second notification system for this.

---

## ACT 6 — One endpoint for the pipeline (2:30)

*Close on the thing a team wires up on Monday.*

**DO** — Call the gate.

```bash
curl -s "$APIOME_BASE_URL/v1/projects/<project-id>/gate" -H "X-API-Key: $APIOME_API_KEY" | jq
```

```json
{
  "verdict": "block",
  "reasons": [
    { "check": "consumer_breaks", "status": "fail",
      "detail": "breaks 1 of 7 consumers (billing-service)", "evidence_id": "ev_01J..." },
    { "check": "lint_grade", "status": "pass", "detail": "B", "evidence_id": "ev_01J..." },
    { "check": "verification_freshness", "status": "warn",
      "detail": "last verified 26h ago against https://api.example.com", "evidence_id": "ev_01J..." }
  ]
}
```

**DO** — Show it as four lines of pipeline.

```yaml
- name: Can we promote this API?
  run: apiome gate $PROJECT --fail-on block
  env:
    APIOME_API_KEY: ${{ secrets.APIOME_API_KEY }}
    APIOME_TENANT_ID: acme-corp
```

**DO** — Stop there.

**SAY**

> One call, one verdict, and every reason cites an evidence record you can open and audit
> afterwards. Not a score, not a dashboard someone has to remember to look at — a value your
> deployment pipeline can branch on.
>
> And it aggregates rather than replaces: the lint grade comes from governance, the breaking
> classification from the diff engine, the consumer verdicts from what we just registered, the
> freshness from the scheduled verification. Four systems that already existed, one answer.
>
> So: fourteen minutes ago, "is this safe to ship" was a judgement call. Now it is a
> `block` with a named consumer, a field, and a link to the evidence.

---

## RESCUE — when it goes wrong on stage

**The Pact import maps zero interactions**
The Pact file's paths don't match the spec's paths — usually a base-path prefix.
*On stage:* switch to the manual operation picker and narrate the Pact path as the automated
version. The story survives; the import is not the beat.

**Act 3 reports "0 of 7 affected"**
The field you removed isn't in any registered contract.
*On stage:* remove a different field — one you can see in the consumer's mapped surface. Have
that field written on a sticky note before you start.

**Verification returns all-conform**
The mock is serving the same spec you're verifying — you skipped the prep step that made them
disagree.
*On stage:* you cannot stage this live. Show a prepared report instead and say so.

**Verification cannot reach the target**
SSRF guards, or the mock isn't running.
*On stage:* `curl` the base URL to prove reachability, then move to Act 6 — the gate endpoint
still has a stale verification to cite, which is itself the `warn` in the payload.

---

## IF ASKED

**"Do our consumers have to adopt anything?"**
No. Pact import reads what they already produce; the operation picker needs nothing from them at
all. That is deliberate — a contract registry that requires every consumer team to act is a
registry that stays empty.

**"Isn't this just Pact?"**
Pact verifies a provider against consumer expectations at test time, and someone has to run it.
This intersects a *classified spec diff* with the consumer surface at design time, before the
change is built — and then separately checks the deployed service against the published spec.
Pact files are an input, not a competitor.

**"What stops verification from hammering production?"**
Safe methods only unless you opt in, a request budget per run, SSRF host policy shared with the
mock, and schedules are per-tenant rate-limited.

**"Can the gate be overridden?"**
Yes, and the override is an audited event with a reason — the same force-publish pattern the
governance gates already use. A gate nobody can override gets removed from the pipeline within a
month.

---

## Reference

| Surface | Where |
|---|---|
| Versions (diff, consumers, verify) | <http://localhost:3000/ade/dashboard/versions> |
| Studio editor | <http://localhost:3000/ade/studio/editor> |
| Gate endpoint | `GET /v1/projects/{id}/gate` |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_CONTRACT_TESTING_GATES.md` §4 |
| Assurance roadmap | `private-suite/docs/roadmaps/ROADMAP_EXECUTABLE_CONTRACT_ASSURANCE.md` |
