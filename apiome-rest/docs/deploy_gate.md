# Deploy-gating status API — CTG-4.5 (#4502)

> The convergence point of CTG-EPIC-4 (#4466), umbrella #4458. Reads what CTG-3.1 (#4475),
> CTG-4.2 (#4480), CTG-4.4 (#4501) and the GOV lint engine already store. Adds no analysis.

## Why

A CD pipeline asks one question: **can I promote this API version?** Until now the answer lived in
five places —

| Question | Where it was answered |
|---|---|
| Is the specification any good? | the GOV lint grade on the revision |
| Does this publish break the contract? | CTG-3.1's `version_changelogs` |
| Whose build does it break? | CTG-4.2's per-consumer verdicts |
| Does the deployment still match? | CTG-4.3's conformance report |
| …and how recently was that checked? | CTG-4.4's schedule freshness |

— so every team scripted its own multi-call gate, and every one of them decided the combination
rules differently. This endpoint is those rules, once, on the server.

```bash
curl -sH "X-API-Key: $APIOME_KEY" \
  "$APIOME/v1/projects/$TENANT/$PROJECT/gate" | jq -r .status
```

## The endpoint

```
GET /v1/projects/{tenant_slug}/{project_ref}/gate[?revisionId=…]
```

`project_ref` is the project's slug or its id. By default the gate judges the project's **newest
published revision** — which is what "can I promote this?" means in a pipeline that just published.
`revisionId` judges a specific published one.

**The status is always `200`.** The verdict is in the body. A `409` on a failing build would make a
network fault and a breaking change look identical to a pipeline's error handling; the CLX-4.2 lint
gate made the same choice, and the caller owns the exit code.

```json
{
  "schemaVersion": "ctg.gate.v1",
  "status": "fail",
  "summary": "1.2.0 fails the deploy gate: breaking, consumers (3 of 4 signals evaluated).",
  "projectId": "…", "projectSlug": "petstore",
  "revisionId": "…", "versionLabel": "1.2.0",
  "versionRef": "project/petstore/1.2.0",
  "evaluatedSignals": 3,
  "counts": {"pass": 1, "warn": 0, "fail": 2, "not_configured": 1, "unknown": 0},
  "signals": [
    {
      "signal": "lint", "status": "pass", "satisfied": true,
      "reason": "lint-grade-meets-thresholds",
      "detail": "Lint grade A (score 94) meets the configured thresholds.",
      "link": "/v1/versions/acme/…/lint",
      "data": {"grade": "A", "score": 94, "warnBelowGrade": "B", "failBelowGrade": "D"}
    },
    { "signal": "breaking", "status": "fail", "…": "…" },
    { "signal": "consumers", "status": "fail", "…": "…" },
    { "signal": "verification", "status": "not_configured", "…": "…" }
  ],
  "policy": { "source": "tenant", "contentFingerprint": "sha256:…", "thresholds": { "…": "…" } }
}
```

Every signal carries a stable `reason` code, a human `detail`, a `link` to the evidence, and the
`data` the judgment was made from — so a verdict is checkable without a second request.

## Partial inputs are the normal case

The four signals land at different times, in different tenants, for different projects. The gate
therefore has **five** per-signal statuses, not three:

| Status | Meaning | In the verdict? |
|---|---|---|
| `pass` / `warn` / `fail` | judged against the thresholds | yes |
| `not_configured` | nothing has produced this signal for this project | **no** |
| `unknown` | it exists but could not be read or ranked | **no**, counted apart |

`not_configured` and `unknown` are different facts and are never collapsed. "Nobody has registered a
consumer" is not the same as "I could not read the registry", and neither is the same as "no
consumer is broken".

**A gate with nothing to judge answers `pass`** — the criterion is that a missing signal must not
fail the gate, and there is no fourth verdict to give. `evaluatedSignals` is how a strict pipeline
tells that apart from a real pass:

```bash
gate=$(curl -s … /gate)
[ "$(jq -r .evaluatedSignals <<<"$gate")" -gt 0 ] || { echo "nothing configured"; exit 1; }
[ "$(jq -r .status <<<"$gate")" = fail ] && exit 1
```

## Where each signal comes from

Nothing here is recomputed. Every signal is a read.

| Signal | Read from | Note |
|---|---|---|
| `lint` | `versions.quality_grade` / `quality_score` | The report #5259 captures when a revision changes. **The gate never re-lints** — that would make the cheapest call in a pipeline the most expensive one. A revision with no stored report is `not_configured`. |
| `breaking` | `version_changelogs` (CTG-3.1) | `initial` (first publication) passes: there is no earlier contract to break. `failed` is `unknown`, not `not_configured` — "I tried and could not" is a different fact from "nobody has tried". |
| `consumers` | `consumer_impact_for_diff` (CTG-4.2) | Fed the **stored** changelog rehydrated into a classified diff. A changelog entry and a classified change carry the same fields, so the intersection runs without re-diffing two documents on a gate request. |
| `verification` | CTG-4.4 schedules, falling back to CTG-4.3 reports | See below. |

### Matching a schedule to the revision

A schedule stores the *reference string* it was defined with, so the same revision may be watched as
`project/petstore/1.2.0`, `project/<uuid>/1.2.0` or `project/petstore/latest`. All three are the same
instruction and all three match; a reference naming another project, or a different version of this
one, does not. Matching on one spelling only would report a watched deployment as never verified.

Across several matching schedules:

* **freshness** is the *most recent* clean verification — any one of them verifying clean is evidence
  the deployment matched;
* **run status** is the *worst* — averaging a failing staging check against a passing production one
  would hide the failure.

`freshness_seconds: null` means **unknown, never fresh** (CTG-4.4's rule), so a schedule that has
never completed cleanly warns rather than passing.

### The manual-run fallback

A version verified by hand is still verified. When nothing schedules the gated version, the signal
falls back to CTG-4.3's stored reports, read by the **resolved** artifact coordinates rather than the
reference string (V254 indexes them). Two reads, not one: the newest report of any outcome says what
the deployment did last, and the newest **passing** one is the freshness anchor — taking a failure's
age as freshness would report a broken deployment as recently verified.

## Thresholds

Each signal has a **warn** rung and a **fail** rung, either of which may be `null` to disable it.
That is what lets one vocabulary come out of four very different measurements without a per-signal
"action" dial, and it makes a policy legible: *warn below B, fail below D* says the whole lint policy
in five words.

| Signal | Threshold | Default | Meaning |
|---|---|---|---|
| `lint` | `warnBelowGrade` | `B` | Warn when the grade is worse than this letter. |
| | `failBelowGrade` | `D` | Fail when it is worse than this letter. |
| `breaking` | `warnAtSeverity` | `null` | Warn when the worst change is at least this severe. |
| | `failAtSeverity` | `breaking` | Fail when it is at least this severe. |
| `consumers` | `warnAboveAffected` | `0` | Warn when more consumers than this are touched. |
| | `failAboveBreaking` | `0` | Fail when more consumers than this are broken. |
| `verification` | `warnAfterSeconds` | `86400` | Warn once the last clean verification is older. |
| | `failAfterSeconds` | `604800` | Fail once it is older still. |
| | `failOnUnhealthyRun` | `true` | Fail when the most recent run failed, whatever its age. |

**The default has teeth**, unlike every other policy surface in the platform. Those default to
advisory because they hang off flows that already existed (publish, import) and a blocking default
would break people who never asked for one. Nothing hangs off this: the endpoint is only reached by a
caller who chose to ask, it always answers `200`, and it refuses nothing.

A rung that could never fire — warning below D while failing below B — is refused with a `422`
listing every problem at once, rather than accepted and silently dead.

### Configuring

```
GET|PUT|DELETE /v1/tenants/{tenant_slug}/governance/deploy-gate-policy
GET|PUT|DELETE /v1/projects/{tenant_slug}/{project_ref}/gate/policy
```

Two scopes: the tenant-wide policy, and a per-project override. Resolution is **project → tenant →
documented default**, and the response's `policy.source` says which one supplied the verdict.

```bash
curl -X PUT …/gate/policy -d '{"thresholds": {"verification": {"failAfterSeconds": 3600}}}'
```

A body naming one threshold configures exactly that one; the rest keep their documented defaults. A
`null` threshold and an *absent* one mean different things — `null` disables the rung, absent takes
the default — which is why the body is one JSONB document rather than nullable columns.

`DELETE` returns the policy that is **now** in force, so a caller sees what it fell back to without
asking again. Clearing a tenant policy does not cascade to project overrides: those were configured
deliberately.

Unlike ECA-3.1's verification policy and IXH-2.3's quality policy, gate policy rows are **mutable,
not append-only**. The gate stores no verdict — it is computed on demand and returns its policy
fingerprint inline — so there is no past judgment for a version history to explain. Attribution
lives in `access_audit` (`governance.deploy_gate_policy.update` / `.clear`), carrying the whole
threshold body so a later reader can see the exact bar that was set.

## Permissions

**No new RBAC resource.** Adding one costs four synchronised edits (the role grid, the REST
`Resource` enum, the enforcement call sites, and the UI role matrix), and a permission that would
always be granted alongside an existing one earns none of them.

| Action | Permission | Why |
|---|---|---|
| Read the gate, read a policy | `versions:view` | A gate is the status of a published version — which is also what a CI runner's API key resolves to. |
| Set a policy | `verification_targets:edit` | Moving the bar is the same class of decision as deciding where verification points, which V211 already keeps out of an Editor's hands. |
| Clear a policy | `verification_targets:delete` | Likewise. |

The **consumer signal is gated inside the response**: a caller without `consumer_contracts:view`
gets that one signal as `unknown` rather than a leaked registry — and rather than a silent `pass`,
which would read as "no consumer is broken".

### CI-scoped keys

The gate and its policy read are allowlisted for **either** CTG-2.3 CI read scope — `diff:read` or
`lint:read`. The aggregate is composed of a lint grade and a breaking classification, so a key
trusted with either input is trusted with the summary; minting a third `gate:read` scope would have
to be carried through the key-management surfaces of three packages for no extra safety. Writing a
policy is never a CI-key operation.

## Failing soft

Every signal is gathered inside its own guard. A store that is unreachable, a stored payload this
release cannot parse, or a registry that cannot be read costs **that** signal — reported `unknown`
with reason `signal-unavailable` — and nothing else. A gate that returned `500` because one of four
inputs was briefly unavailable would stop every pipeline in the tenant, which is a worse failure than
answering with three signals and saying so.

The same reasoning applies to the policy itself: an unreadable policy row falls back to the
documented default and marks the response `policy.degraded: true`, so "nothing is configured" and "I
could not read what is" stay distinguishable.

## Refusals

| Status | Code | When |
|---|---|---|
| 404 | `gate-project-not-found` | Nothing in this tenant answers to the reference. |
| 404 | `gate-revision-not-found` | The named revision is not in this project. |
| 400 | `gate-revision-not-published` | It is still a draft; a gate judges what was published. |
| 409 | `gate-no-published-revision` | The project exists but has nothing to promote. |
| 422 | `gate-policy-invalid` | The threshold body is not coherent; `errors` lists every problem. |

## Modules

| Module | Role |
|---|---|
| `app/deploy_gate.py` | Pure: vocabulary, thresholds, per-signal judgment, the verdict. |
| `app/deploy_gate_store.py` | The only place a policy is read or written. |
| `app/deploy_gate_service.py` | Reads the four signals from where each already lives. |
| `app/deploy_gate_routes.py` | The seven endpoints above. |
| `apiome-db` **V254** | `deploy_gate_policy`, plus the artifact index the report fallback needs. |
