# API change check suite (GNC-3.1, #4740)

A pull request that changed an API used to collect a wall of checks — a lint run, a diff, a
breaking-change gate, a contract test, an SDK build — each with its own log, and a reviewer who read
none of them. The platform already *knew* every one of those answers. The check suite turns them
into **one** verdict, in the four words [GNC-2.2](provider_checks.md) publishes to a provider:
`pending`, `pass`, `fail`, `skipped`.

- Storage: apiome-db `V267__api_check_suite_gnc_3_1.sql` (`api_check_suite_policy`,
  `api_check_suite_runs`)
- Rules (pure): `app/api_check_suite.py`
- Evidence: `app/api_check_suite_evidence.py`
- Evaluating and reading: `app/api_check_suite_store.py`
- Policy: `app/api_check_suite_policy_store.py`
- Publish gate: `app/api_check_suite_gate.py` (wired into `version_publish_prechecks`)
- Routes: `app/api_check_suite_routes.py`
- CLI: `apiome checks run|show` (apiome-cli)

```bash
# In a pull-request pipeline: evaluate, report on the PR, exit with the verdict.
apiome checks run --project pets --version 2.0.0 --commit "$GITHUB_SHA" --pr 42

# The same over HTTP.
curl -sX POST "$APIOME/v1/tenants/acme/projects/pets/versions/2.0.0/check-suite" \
     -H "X-API-Key: $APIOME_KEY" -H 'Content-Type: application/json' \
     -d "{\"commit_sha\": \"$GITHUB_SHA\", \"pr_number\": 42}"
```

---

## Five components, all existing evidence

Nothing in the suite is a new analysis. Each component reads what an earlier ticket already
produces:

| Component | Lane | Reads | Judged by |
|---|---|---|---|
| `lint` | GOV | The revision's lint report, stored-first (#5259): the stored report while it still matches the content, otherwise one lint that is persisted. | Error-severity violations **fail** it (the GOV-2.5 publish rule); otherwise the grade is judged by CTG-4.5's `evaluate_lint`. |
| `breaking` | CTG | The CTG-1.1 classification of the draft against the previous **published** revision on its line — the same baseline CTG-3.1 and CTG-3.4 use. | CTG-4.5's `evaluate_breaking`. |
| `consumers` | CTG | CTG-4.2's per-consumer verdicts for that **same** classification. One diff, two questions. | CTG-4.5's `evaluate_consumers`. |
| `contract` | ECA | The newest ECA-1.3 contract run of **this revision**, and whether its suite is still the one this draft compiles to. | Current run `passed` → pass; `failed`/`errored` → fail. |
| `sdk` | SDK | The SDK-3.3 client-kit manifest built from the draft with the project's SDK-3.4 branding. | The Go client and the server stubs still generate → pass. |

**One verdict model.** The three CTG-4.5 components are judged by the deploy gate's own pure
evaluators, against the deploy gate's own thresholds (`/gate/policy`). The pull request and the
deploy gate therefore cannot disagree about what "too breaking" means: the suite is a transport
for that verdict model, not a second opinion. A gate `warn` is a `pass` here (with `warned: true`),
`not_configured` is `skipped`, and `unknown` is `pending`.

### Why a contract run is matched by revision, and then proven current

A contract run is keyed by the digest of the suite it executed, and that digest also covers the
*reference string* the suite was compiled from — so the same revision spelled `project/pets/2.0.0`
and `project/<uuid>/<uuid>` yields two digests. The suite therefore finds runs by the resolved
`source.revision_id` every run records (V267 indexes it), and then **recompiles the run's own
reference** with default options: the run counts only if that still yields the digest it
executed. A draft edited since the run compiles to a different suite, and a green run of the old
one says nothing about the new document (`contract-evidence-stale`).

### A version nothing can be built from

A version designed in the app rather than imported has no captured source document, so there is
no canonical model — and so no contract suite and no client kit — to build from it. That is a fact
about the version, the same one the SDK kit and contract suite routes report, so `contract` and
`sdk` are `skipped` with `no-captured-source` rather than left waiting forever.

---

## The verdict is deterministic

**Policy decides what counts.** Each component is `required`, `advisory` or `off`:

| Requirement | Evaluated? | Decides the verdict? |
|---|---|---|
| `required` | yes | yes |
| `advisory` | yes | no — reported only |
| `off` | **no** — not even read | no — listed with `component-off` |

The required components reduce with GNC-2.2's own precedence: **one failure fails the suite, an
unfinished component holds it, and a set of skips is a skip** — never a hollow pass.

| Suite state | Reason | When |
|---|---|---|
| `fail` | `required-component-failed` | any required component failed |
| `pending` | `required-component-pending` | none failed, and one has no verdict yet |
| `pass` | `required-components-passed` | every required component that applied passed |
| `skipped` | `no-required-component-applied` | every required component was skipped |
| `skipped` | `no-required-components` | the policy requires nothing |
| `pending` | `draft-not-synchronized` | the commit is ahead of the draft (see below) |
| `skipped` | `spec-unchanged` | the commit does not touch the bound specification |

**Missing is not unreadable.** A *required* component whose evidence has not been produced yet (no
contract run of this draft) is `pending` — a merge gate waits for it. An *advisory* one is simply
`skipped`. Evidence that exists but could not be read is `pending` with `evidence-unavailable`
either way: a check that could not look must not turn green, and "the platform could not read
this" is not a finding about the change. One unreadable component costs only itself.

| Component default | Why |
|---|---|
| `lint`, `breaking`, `consumers` → `required` | Computed from the draft itself; always available. |
| `contract`, `sdk` → `advisory` | Need evidence somebody has to *produce* (a contract run against a deployment); a project that has never run one is not held pending forever by default. |

---

## Which commit: the suite judges the draft

The suite judges the **draft** — the version this platform publishes — and a bound draft is
synchronized with exactly one commit of its branch (`binding.commit_sha`). That is the commit a
verdict is reported against, and the default when no commit is named.

A newer commit on the branch (a [sync candidate](draft_bindings.md) the draft has not caught up
with) gets a **placeholder** evaluation, recorded with `evaluated: false`:

- `skipped` · `spec-unchanged` when the bound selection at that commit is byte-for-byte what the
  draft was synchronized with — the pull request does not touch the API. The digest comes from the
  candidate, or is read through the binding's own proven-read path when the candidate has not been
  read yet.
- otherwise `pending` · `draft-not-synchronized`, until the draft catches up
  ([three-way synchronization](spec_sync.md)).

Guessing that the draft already reflects the commit would put a verdict about one document on
another. A placeholder can never pass or fail (a V267 CHECK), and never satisfies the publish gate.
A commit the binding has never been observed at is refused (`check-suite-commit-unknown`).

---

## Re-runs are idempotent

An evaluation is keyed by everything its verdict is a function of: the draft's content digest, the
commit, the binding, the suite policy's **component requirements**, the deploy-gate thresholds, and
every component's verdict **and evidence** (report fingerprint, baseline revision, contract run id
and digest, kit digest). `UNIQUE (version_id, input_fingerprint)` makes a second evaluation of the
same inputs collide with the first:

- the response is `200` with `replayed: true` and **the same evaluation** — the same id, the same
  evidence ids, not a new almost-identical record;
- the provider is not touched when its check already says exactly that; if the last publish
  failed, the replay publishes again, which is what lets a re-run heal a provider that had a bad
  minute.

New evidence behind an unchanged verdict (a newer contract run, a newer lint report) *is* a new
evaluation — the drill-down must name the evidence that was actually read.

> **A trap this exposed in GNC-2.2.** The publish ledger was `UNIQUE (check_run_id,
> request_fingerprint)`, so a verdict's *failed* publish occupied the slot its *successful* retry
> needed: the retry reached the provider, collided in the ledger, was never recorded, and the
> provider's check-run id was never written back — so every later re-run POSTed a **new** check
> run onto the pull request. V267 re-keys the ledger per outcome (`… , outcome`), and the lookup
> reads a verdict's dispatch first. A verdict is still dispatched at most once.

---

## The drill-down

`GET …/projects/{project}/check-suite/runs/{run_id}` returns one evaluation, and every provider
check's summary names it. Each component carries:

| Field | Meaning |
|---|---|
| `state`, `reason`, `detail`, `warned` | the verdict, a stable code, one sentence |
| `evidence` | what was read: report fingerprint and error findings; baseline revision and breaking changes; consumer counts (and names); contract run id, outcome and suite digests; kit digest and generator errors |
| `link` | the API path of that evidence |
| `rule` | the policy behind it: the requirement, and the CTG-4.5 thresholds where they apply |

The evaluation also snapshots **both** policy bodies it was judged under, with their sources and
fingerprints — so a stored verdict never has to be explained by a policy row that has since moved,
which is why the policy row itself can stay mutable (the V254 argument, extended).

The provider summary is the same thing as markdown: the deciding components first, a table of all
five, the evidence, and the policies, truncated with a pointer to the drill-down if it would exceed
what a provider accepts. It is rendered from the stored row, so a replay publishes byte-identical
text and GNC-2.2's ledger recognises it.

**Consumer names.** The verdict is computed once, with the platform's view of the registry, so it
never depends on who ran the suite. A *reader* without `consumer_contracts:view` gets the same
verdict with the names redacted (the CTG-4.5 rule), in the components and in the summary. The
summary published on the pull request does name them — that is where "breaks billing-service" is
actionable — so a tenant that does not want names on pull requests switches `consumers` to `off`.

---

## Policy

```bash
# Tenant-wide, or per project (project → tenant → documented default)
curl -X PUT "$APIOME/v1/tenants/acme/governance/check-suite-policy" \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"components": {"contract": "required"}, "requiredForPublish": true}'
curl -X PUT "$APIOME/v1/tenants/acme/projects/pets/check-suite-policy" -d '{"components": {"sdk": "off"}}'
```

| Endpoint | Permission |
|---|---|
| `GET …/governance/check-suite-policy`, `GET …/projects/{project}/check-suite-policy` | `projects:view` |
| `PUT` / `DELETE` of either | a **signed-in tenant administrator** (an API key cannot) |

A body naming one component configures exactly that one; the rest take their defaults. Every
problem is reported at once (`422 check-suite-policy-invalid`). `requiredForPublish` with no
required component is refused: a gate that can only ever be skipped can never block. `DELETE`
returns the policy now in force. Changes are audited in `access_audit`
(`governance.check_suite_policy.update` / `.clear`) with the whole body.

---

## Required before publish

With `requiredForPublish: true`, `POST …/publish` refuses a version whose **current content** has
no passing evaluation **under the policy in force** — `422` with `apiCheckSuiteGate`, the same
contract as every other publish gate. The newest *evaluated* run matching the draft's content
digest, the component requirements fingerprint and the thresholds fingerprint decides:

| Evaluation | Gate |
|---|---|
| `pass` or `skipped` | satisfied |
| `fail` | blocked · `check-suite-failed` (names the failing components) |
| `pending` | blocked · `check-suite-pending` |
| none for this content/policy, though evaluated before | blocked · `check-suite-stale` |
| never evaluated | blocked · `check-suite-not-evaluated` |

`skipped` satisfies it because refusing it would be a gate no author could ever satisfy. The match
uses the **requirements** fingerprint rather than the whole policy's: `requiredForPublish` cannot
change what the suite says, so switching the gate on does not stale every evaluation already made.

The gate runs after the automated gates and before the approval gate. Force-publish
(`skipPublishChecks` + reason) remains the escape. Every publish an armed policy judged is audited
as `version.api_check_suite_gate` — `satisfied` (with the evaluation that let it through),
`forced`, or `unavailable` — and a gate fault degrades to `unavailable`, which never blocks.

This is the provider-side "required status check" made symmetric: whether a change starts in a
pull request or in the designer, it meets the same gate, backed by the same evidence. Making the
check required for **merging** is the repository's branch-protection setting, and stays the
repository owner's to make.

---

## Endpoints

| Method | Path | Permission |
|---|---|---|
| `POST` | `…/projects/{project}/versions/{version}/check-suite` | `versions:edit` |
| `GET` | `…/projects/{project}/versions/{version}/check-suite[?commit_sha=]` | `projects:view` (or a `diff:read` / `lint:read` CI key) |
| `GET` | `…/projects/{project}/versions/{version}/check-suite/runs` | `projects:view` |
| `GET` | `…/projects/{project}/check-suite/runs/{run_id}` | `projects:view` |
| `GET` `PUT` `DELETE` | `…/governance/check-suite-policy`, `…/projects/{project}/check-suite-policy` | see above |

`POST` body: `commit_sha` (optional; a bound version only), `pr_number`, `publish` (default
`true`). A credential is never accepted in a body. The latest read carries `stale: true` when the
draft or either policy has moved since the evaluation.

### Refusals

| Code | Status | Meaning |
|---|---|---|
| `check-suite-project-not-found` / `-version-not-found` | 404 | nothing in this tenant answers to the reference |
| `check-suite-not-run` | 404 | the version has not been evaluated (at that commit) |
| `check-suite-run-not-found` | 404 | no such evaluation in this project |
| `check-suite-not-bound` | 409 | a commit was named for a version with no binding |
| `check-suite-commit-unknown` | 409 | the binding has never been observed at that commit |
| `check-suite-invalid-commit` | 422 | not a hexadecimal object id |
| `check-suite-invalid-document` | 422 | the draft cannot be rebuilt into a document |
| `check-suite-policy-invalid` | 422 | the policy body is not coherent; `errors` lists every problem |

The verdict is in the body, never in the status: a failing suite is a `201`/`200` with
`run.state: "fail"`.

### Audit

Every new evaluation is a `check_suite.evaluated` row in `workflow_audit`, written in the
evaluation's own transaction; a replay writes none. Reporting it is GNC-2.2's `check.recorded` /
`check.published`.
