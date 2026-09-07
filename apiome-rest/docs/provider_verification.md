# Provider verification vs live (CTG-4.3)

> apiome#4489 — the drift half of CTG-EPIC-4 (#4466), umbrella #4458.
> Consumes ECA-1.1 (#4729) suites, ECA-1.2 (#4730) targets, and the ECA-2.1 (#4732) runner; always
> writes ECA-1.3 (#4731) evidence. Feeds CTG-4.4 (scheduled verification, #4501) and CTG-4.5
> (deploy-gating status, #4502).

## Why

A specification can be perfectly versioned, linted, published, and still lie. The deployment drifts
from the contract — a field disappears, a type narrows, a new parameter becomes required — and
nobody finds out until a consumer breaks in production. Versioning describes what was *promised*;
until this ticket nothing checked what is actually *served*.

The pieces to execute a contract already existed. What did not:

* **Coverage had no denominator.** A run recorded the cases it executed. It never recorded the
  operations it did not reach, so "the run passed" could mean "we checked one endpoint of forty".
* **Drift had no location.** The runner validated response bodies and then kept only the first
  finding's *message*. The JSON Pointer into the body — the one thing that makes drift actionable —
  was computed and discarded.
* **Mutation was all-or-nothing.** The only gate was the target's `allow_mutating_methods` boolean.
  There was no per-run opt-in, and no way to say *which record* a `DELETE /pets/{petId}` may delete.
* **There was no report.** Evidence stores case rows; a deploy gate needs an object it can fetch and
  compare.

## Modules

| Module | Role |
|---|---|
| `app/provider_verification.py` | Pure: which cases may be sent (`plan_provider_run`), and what the results mean (`build_conformance_report`). |
| `app/provider_verification_service.py` | compile → resolve → plan → run → report → record → store. |
| `app/provider_verification_store.py` | The only place a report is written or read. |
| `app/provider_verification_routes.py` | The three endpoints below. |
| `apiome-db` **V252** | `provider_verification_report` — write-once, coverage as columns, report as JSONB. |

Reused rather than rebuilt: `app/contract_suite.py` compiles the requests (declared examples, then
`app.schema_instance_synthesis` bodies — SIM-1.3's reuse point), `app/contract_runner.py` executes
them and validates responses with `app.schema_instance_validation.validate_json_instance` (SIM-1.4's
reuse point), and `app/verification_evidence*.py` stores the run.

## Endpoints

```
POST /v1/tenants/{tenant_slug}/contracts/{version_ref}/verify-provider
GET  /v1/tenants/{tenant_slug}/provider-verifications
GET  /v1/tenants/{tenant_slug}/provider-verifications/{report_id}
```

Body of the run:

```json
{
  "target_ref": "staging",
  "options": {},
  "verification": {
    "allow_mutating": false,
    "fixtures": [],
    "max_drift_findings_per_case": 20
  },
  "idempotency_key": "ci-build-42",
  "context": { "commit": "abc123", "branch": "main" }
}
```

Permissions: running needs `versions:view` **and** `verification_evidence:create`; reading needs
`verification_evidence:view`. A conformance report *is* verification evidence — same act, same run,
same readers — so it reuses that resource rather than adding one of its own.

* **201** — new evidence and a new report were written.
* **200** — idempotent replay, or `ok: false` with a taxonomy `error` (no executable cases, auth
  unavailable, compile refusal).
* **400/404/422** — addressing or target faults.

## Safe by default

Only `GET`, `HEAD`, and `OPTIONS` are executed. A mutating case runs when **all three** of these
hold, checked in this order:

1. the ECA-1.2 target policy has `allow_mutating_methods: true`;
2. the request sets `verification.allow_mutating: true`;
3. a **fixture** names the operation.

A run can narrow what the registry permits; it can never widen it. And the opt-in alone is not
enough: *"you may write"* and *"here is the row you may write to"* are different permissions, so a
run that opts in without fixtures still sends nothing and says so
(`mutating-fixture-missing`).

### Fixtures

```json
{
  "operation_key": "DELETE /pets/{petId}",
  "case_id": null,
  "path_parameters": { "petId": "scratch-42" },
  "query_parameters": {},
  "headers": { "X-Trace-Id": "verify" },
  "body": null,
  "note": "scratch-42 is recreated by the staging seed on every deploy"
}
```

A fixture supplies the **request**. It never touches the expectation, so it cannot make a failing
case pass — it can only get the case sent. Three further rules, each protecting the case it is
applied to:

* **Credentials are refused.** A fixture whose `headers` name `Authorization`, `Cookie`, `X-Api-Key`
  or any other credential header is rejected at the request model, before the service is reached.
  Authentication is the target's secret-free reference; a fixture is persisted with the report.
* **A negative case's body is never overwritten.** For a `negative_body_mutation` or
  `negative_missing_body` case, the body *is* the case.
* **A parameter-negative's target parameter is never supplied.** A case that exists to omit
  `?status` does not get `status` back from a fixture.

A fixture that names a safe operation, an operation the suite does not contain, or a case id that
does not exist is **reported** (`fixture-not-mutating`, `fixture-unmatched`,
`fixture-case-unmatched`) — never silently dropped, because a fixture that matched nothing leaves
somebody believing an operation was verified.

## Coverage is measured honestly

```
operations_total = compiled operations + operations the compiler could not compile
coverage_percent = operations_exercised / operations_total
```

The denominator is every operation the **specification** declares, not every operation the suite
compiler could express. A coverage number that quietly excluded the uncompilable would read as
reassurance about endpoints nobody checked. `operations_uncompiled` is reported beside it, and every
operation the report does not vouch for is listed in `uncovered` with a reason code:

| Reason | Meaning |
|---|---|
| `mutating-method-blocked` | The target policy or the run forbade the method — nothing was sent. |
| `mutating-fixture-missing` | The run opted in but named no fixture for the operation. |
| `UNSUPPORTED_STREAMING`, `NO_CASES_COMPILED`, … | An ECA-1.1 compiler finding: the operation was never compilable. |

An operation whose every case was held back is `skipped`, never `passed`: nothing was checked.

## Drift

Every schema violation is located. A failed response-schema check records the headline verdict
*plus* one assertion per `InstanceFinding`, whose `subject` is the RFC 6901 JSON Pointer into the
response body, and the report reads them back as `DriftFinding`s:

```json
{
  "operation_key": "GET /pets/{petId}",
  "case_id": "get-pets-petid-example",
  "kind": "response_schema",
  "code": "response-schema-mismatch",
  "pointer": "/id",
  "expected": "integer",
  "actual": "1",
  "message": "type: '1' is not of type 'integer'"
}
```

`kind` is `status` (the deployment answered with a code the contract does not declare),
`response_schema` (the body disagrees, located), or `transport` (no answer to judge). A transport
failure makes the report `errored`, not `failed` — a run that never got an answer showed nothing,
and a gate must read those differently.

## Persistence

Every run writes ECA-1.3 evidence and a V252 report row. The row is **write-once** (the same guard
V212 puts on the evidence tables) and its foreign key is composite against
`verification_run (id, tenant_id)`, so a report can neither summarise another tenant's run nor
outlive the run it cites. Coverage and the verdict are columns, so
`provider_verification_store.latest_report(tenant, version_ref)` — the call CTG-4.5 will make —
answers *"is this version's deployment still conformant?"* without parsing a report body.

An `idempotency_key` that matches an earlier run **reads** the stored report rather than writing a
second one — V252 keeps at most one report per run, so a replay returns the original, which is the
same answer a sequential retry would have got.

If the report cannot be stored, the verification is **not** reported as failed: the check already
happened and its evidence is already immutable. The response carries `report` with `stored: null`.

## Manual golden path

1. Publish a petstore version and register a verification target (`environment: staging`,
   `base_url` pointing at the deployment; `network_class: private` needs an approval reason).
2. `POST …/contracts/project/petstore/1.0.0/verify-provider` with `{"target_ref": "staging"}`.
3. Expect `ok: true`, `report.outcome: "passed"`, `report.coverage.coverage_percent` matching the
   operations the suite compiled, and every `POST`/`PUT`/`DELETE` operation listed in `uncovered`
   with `mutating-method-blocked`.
4. `GET …/provider-verifications?version_ref=project/petstore/1.0.0` returns the summary.

Deliberate drift: point the same version at a stub that drops a required field — the report must be
`failed`, with the operation key and the JSON pointer of the missing property in `drift`.

## Out of scope

* Scheduled runs and drift alerts — CTG-4.4 (#4501)
* The aggregate deploy-gate verdict — CTG-4.5 (#4502)
* Consumer-aware breaking analysis — CTG-4.2 (#4480)
* A dashboard surface — not in this ticket's affected modules
