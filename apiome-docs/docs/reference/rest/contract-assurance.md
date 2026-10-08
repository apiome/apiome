---
title: "Contract assurance"
description: "REST endpoints tagged contract-assurance: 23 operations."
sidebar_position: 16
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `contract-assurance` · 23 operations

## `POST /v1/tenants/{tenant_slug}/contracts/{version_ref}/run` {#run-contract-suite-for-version-v1-tenants-tenant-slug-contracts-version-ref-run-post}

**Execute a contract suite against a verification target**

Compile the version's deterministic contract suite (ECA-1.1), resolve the named verification target (ECA-1.2), execute every case under the target's policy (timeouts, concurrency, transport-only retries, mutating-method gate), validate status codes and response schemas, and **always** persist the result as immutable verification evidence (ECA-1.3).

**Retries never mask a contract failure.** A status or schema mismatch ends the case immediately; only transport failures (connect/timeout/network) honour `policy.retry_attempts`.

**A suite carries no credentials.** Auth comes from the target's secret-free reference (`env` or `stored`); evidence snapshots the target identity only.

A version that cannot yield executable cases answers **200** with `ok: false` and a stable taxonomy `error`. Addressing faults are HTTP errors (400/404/422). Target resolution faults are 400/404. Evidence submission faults are 400.

Operation id: `run_contract_suite_for_version_v1_tenants__tenant_slug__contracts__version_ref__run_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for execute a contract suite against a verification target.

- `application/json` — [`ContractRunRequest`](#schema-contractrunrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for execute a contract suite against a verification target. | `application/json` [`ContractRunResponse`](#schema-contractrunresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/contracts/{version_ref}/suite` {#compile-contract-suite-for-version-v1-tenants-tenant-slug-contracts-version-ref-suite-post}

**Compile a deterministic contract suite from a version**

Compile a published version into an executable contract suite (ECA-1.1): one case per declared example, per schema-valid generated body, and per required negative case, with the operation, the source, and the expected outcome on every one of them.

**Addressing** is the schema-reference grammar without a type segment — ``project/{project_slug}/{version}`` for a Project revision or ``catalog/{item}/{version}`` for a Catalog revision — so a suite is compiled from the same coordinate a payload is validated against.

**Compilation is deterministic.** The same version and the same options produce a byte-identical manifest and therefore the same ``digest``, which is what lets a CI gate assert that a deployment was verified against a specific contract.

**Declared examples come first.** A request body the author wrote is compiled ahead of anything generated, and is the only kind of case marked ``synthetic: false``. An example that does not satisfy its own schema is reported and left out rather than compiled into a test a correct implementation would fail.

**Nothing is skipped silently.** A streaming operation, a non-HTTP paradigm, an XML-only body, a structured parameter, an undeclared status code — each appears in ``findings`` with a stable code, so partial coverage can never read as full coverage.

**A suite carries no target and no credentials.** Paths are relative and security requirements are reported for the runner to satisfy; targets are configured separately.

Nothing is persisted. A version that yields no suite is **not** an HTTP error: the response is a 200 with ``ok: false`` and a stable intake-taxonomy ``error`` code plus remediation. Only addressing faults are HTTP errors — 400 for a malformed or type-qualified reference, 404 for one that names nothing visible, 422 for one that resolves to material no canonical model can be rebuilt from.

Operation id: `compile_contract_suite_for_version_v1_tenants__tenant_slug__contracts__version_ref__suite_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for compile a deterministic contract suite from a version.

- `application/json` — [`ContractSuiteCompileRequest`](#schema-contractsuitecompilerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for compile a deterministic contract suite from a version. | `application/json` [`ContractSuiteResponse`](#schema-contractsuiteresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/contracts/{version_ref}/verify-provider` {#verify-provider-for-version-v1-tenants-tenant-slug-contracts-version-ref-verify-provider-post}

**Verify a live deployment against a published contract**

Compile the version's deterministic contract suite (ECA-1.1), resolve the named verification target (ECA-1.2), execute the cases this run is allowed to send, validate every response against the contract's own schema, and return a **conformance report**: per-operation verdicts, each schema violation located by its JSON Pointer into the response body, and coverage measured against every operation in the specification.

**Safe by default.** Only `GET`/`HEAD`/`OPTIONS` are executed unless the request both sets `verification.allow_mutating` **and** supplies a fixture naming the operation — opting in is a permission, not a payload. Neither can widen the verification target's own `allow_mutating_methods` policy, and a fixture may not carry credentials.

**Coverage is honest.** The denominator is every operation the specification declares, including those the suite compiler could not compile; what was not exercised is named with its reason rather than left out.

The run is always recorded as immutable ECA-1.3 evidence and the report is persisted beside it. A version that cannot yield executable cases answers **200** with `ok: false` and a stable taxonomy `error`. Addressing faults are HTTP errors (400/404/422); target resolution faults are 400/404; evidence faults are 400.

Operation id: `verify_provider_for_version_v1_tenants__tenant_slug__contracts__version_ref__verify_provider_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for verify a live deployment against a published contract.

- `application/json` — [`ProviderVerificationRequest`](#schema-providerverificationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for verify a live deployment against a published contract. | `application/json` [`ProviderVerificationResponse`](#schema-providerverificationresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/provider-verifications` {#list-provider-verifications-v1-tenants-tenant-slug-provider-verifications-get}

**List provider verification reports**

A tenant's conformance reports, newest first, without their per-operation detail. Every field is a stored column, so a deploy gate can ask *did the newest report for this version pass, and how much did it cover?* without opening a report body.

Filter by `version_ref` for one version's history, `target_id` for one deployment, or `outcome` for what is currently drifting.

Operation id: `list_provider_verifications_v1_tenants__tenant_slug__provider_verifications_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_ref` | query | string or null | no | Restrict to one version reference. |
| `target_id` | query | string or null | no | Restrict to one verification target. |
| `outcome` | query | string or null | no | Restrict to one verdict: `passed`, `failed`, or `errored`. |
| `limit` | query | integer | no | Maximum reports to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list provider verification reports. | `application/json` array of [`ConformanceReportSummary`](#schema-conformancereportsummary) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/provider-verifications/{report_id}` {#read-provider-verification-v1-tenants-tenant-slug-provider-verifications-report-id-get}

**Read one provider verification report**

The full conformance report: per-operation verdicts, every drift located by its JSON Pointer into the response body, the operations the run does not vouch for and why, and the id of the immutable evidence run the report was read from.

Operation id: `read_provider_verification_v1_tenants__tenant_slug__provider_verifications__report_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `report_id` | path | string | yes | Path parameter identifying the report id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one provider verification report. | `application/json` [`ConformanceReportRecord`](#schema-conformancereportrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-runs` {#list-verification-runs-v1-tenants-tenant-slug-verification-runs-get}

**List verification runs**

Recorded runs, newest first, without per-case detail.

The filters are the questions a gate asks: the newest evidence for *this* compiled suite (`suite_digest`), everything that ran against *this* target (`target_id`), or only the failures (`outcome`).

Requires `verification_evidence:view`.

Operation id: `list_verification_runs_v1_tenants__tenant_slug__verification_runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `target_id` | query | string or null | no | Restrict to one target. |
| `suite_digest` | query | string or null | no | Restrict to one compiled suite digest (`sha256:<hex>`). |
| `outcome` | query | string or null | no | Restrict to one verdict: passed, failed, errored, cancelled. |
| `limit` | query | integer | no | Maximum runs to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list verification runs. | `application/json` [`VerificationRunListResponse`](#schema-verificationrunlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/verification-runs` {#create-verification-run-v1-tenants-tenant-slug-verification-runs-post}

**Record verification evidence for a finished run**

Record one finished contract run as **immutable** evidence: the executed suite digest, the target identity, timing, per-case outcomes, per-assertion detail, and references to redacted artifacts.

**The verdict is derived, not accepted.** Case counts and the run outcome are computed from the submitted case records; a declared `outcome` that disagrees is refused. Only `cancelled` — which no set of records can imply — is taken on the runner's word.

**A failure must say why.** A case recorded as `failed` or `errored` needs a `failure_code`, and a failed assertion needs a `code`; an outcome with no stated reason cannot be compared across runs or gated on.

**Artifacts are linked, never embedded.** An artifact reference carries a URI, a size, and a content hash — a `data:` URI is refused, as is one embedding `user:pass@` credentials — and every free-text field is scrubbed for credentials before storage.

**Recording is idempotent.** Repeating the request with the same `idempotency_key` returns the originally stored run with `200` rather than creating a duplicate.

Requires `verification_evidence:create`.

Operation id: `create_verification_run_v1_tenants__tenant_slug__verification_runs_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record verification evidence for a finished run.

- `application/json` — [`VerificationRunInput`](#schema-verificationruninput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for record verification evidence for a finished run. | `application/json` [`VerificationRunRecord`](#schema-verificationrunrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-runs/{run_id}` {#read-verification-run-v1-tenants-tenant-slug-verification-runs-run-id-get}

**Read one verification run**

One run in full: every case record, its assertions, and the references to its redacted artifacts.

The target identity is the **snapshot taken at run time**, not a live read of the target — a target that has since been renamed, repointed, or retired cannot rewrite what this run says it did.

Requires `verification_evidence:view`.

Operation id: `read_verification_run_v1_tenants__tenant_slug__verification_runs__run_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one verification run. | `application/json` [`VerificationRunRecord`](#schema-verificationrunrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-runs/{run_id}/export` {#export-verification-run-v1-tenants-tenant-slug-verification-runs-run-id-export-get}

**Export one verification run as JSON or JUnit**

Export the stored evidence.

* `json` — the whole record (`application/json`), keys sorted so two exports of the same run are byte-identical and can be diffed without a semantic differ.
* `junit` — JUnit XML (`application/xml`), which GitHub Actions, GitLab, Jenkins, and Buildkite render natively. One `<testcase>` per stored case in stored order; a contract violation becomes `<failure>` and an unexecutable case becomes `<error>`, because that is the distinction contract verification needs. The suite digest and target identity travel as `<properties>`.

Neither exporter recomputes a verdict: the counters come from the stored counts, so an export can never disagree with the run it exports.

Requires `verification_evidence:view`.

Operation id: `export_verification_run_v1_tenants__tenant_slug__verification_runs__run_id__export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `format` | query | string | no | Export format: json, junit. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The exported evidence. | `application/json` any; `application/xml` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-runs/{run_id}/mock-attestation` {#read-verification-run-mock-attestation-v1-tenants-tenant-slug-verification-runs-run-id-mock-attestation-get}

**Read a run's mock attestation as a signed in-toto statement**

Render the run's release-proof mock attestation (PMR-3.2) as an **in-toto Statement v1** inside a **DSSE envelope**, so a release pipeline can prove offline which mock backed a verification.

The statement's subject is the mock bundle itself, digested with a plain `sha256` over the bundle's `manifestDigest` value — so a holder of the bundle file ties it to this statement without any Apiome-specific knowledge. The predicate carries the bundle coordinates, the runtime version and image, the conformance corpus identity and result, every fixture-pack digest, and the verification run it belongs to. Identities and verdicts only: never spec text, fixture bodies, or credentials.

**A missing or failed verification is still attested.** A run whose mock says `missing` or `failed` returns a statement saying exactly that, signed — silence is never the answer. `404` is returned only when the run recorded no mock at all.

The envelope is HMAC-SHA256 signed with the shared attestation secret and names the same key id as a lint gate attestation, so a verifier that already holds that secret needs no new configuration. Without a configured secret the envelope is well-formed but its `signatures` list is empty.

Requires `verification_evidence:view`.

Operation id: `read_verification_run_mock_attestation_v1_tenants__tenant_slug__verification_runs__run_id__mock_attestation_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a run's mock attestation as a signed in-toto statement. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-schedules` {#list-verification-schedules-v1-tenants-tenant-slug-verification-schedules-get}

**List scheduled verifications**

Every live verification schedule in the tenant, newest first, each carrying its **freshness**: `last_success_at` and `freshness_seconds` — the seconds since this deployment last verified clean.

`freshness_seconds` is `null` when the schedule has never verified clean. A gate must read that as *unknown*, never as *fresh*.

Filter by `version_ref` to ask "is this version's deployment being watched, and how recently?", by `target_id` for one deployment, or by `enabled` to find what is paused.

Requires `verification_targets:view`.

Operation id: `list_verification_schedules_v1_tenants__tenant_slug__verification_schedules_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_ref` | query | string or null | no | Restrict to one version reference. |
| `target_id` | query | string or null | no | Restrict to one verification target. |
| `enabled` | query | boolean or null | no | Restrict to enabled (`true`) or paused (`false`) schedules. |
| `limit` | query | integer | no | Maximum schedules to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list scheduled verifications. | `application/json` array of [`VerificationScheduleRecord`](#schema-verificationschedulerecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/verification-schedules` {#create-verification-schedule-v1-tenants-tenant-slug-verification-schedules-post}

**Schedule recurring verification of a deployment**

Define a standing instruction: verify one published version against one registered deployment on a cadence, and notify when it drifts.

**Each tick is a CTG-4.3 run, unchanged.** The same suite is compiled, the same requests are sent, the same mutation rules apply (safe methods only unless the target policy, the schedule's `verification.allow_mutating`, *and* a fixture naming the operation all agree), and the same immutable evidence and conformance report are written. A scheduled check that behaved differently from a manual one would be worthless as a gate input.

**Cadence** is a number of seconds or one of `5m`, `15m`, `30m`, `hourly`, `6h`, `12h`, `daily`, `weekly`. The floor is five minutes: anything shorter against a live deployment is load, not monitoring.

**Alerting is quiet by design.** A pass→fail transition notifies exactly once; a repeat of the same failure is silent; a failure whose set of violations *changed* notifies again, because new drift hiding behind old drift is how a second regression is missed. Recovery notifies unless `alert_on_recovery` is false.

One live schedule per handle, and one per (version, deployment) pair — a second schedule for the same pair would double the traffic and double every alert.

Requires `verification_targets:create`.

Operation id: `create_verification_schedule_v1_tenants__tenant_slug__verification_schedules_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for schedule recurring verification of a deployment.

- `application/json` — [`VerificationScheduleInput`](#schema-verificationscheduleinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for schedule recurring verification of a deployment. | `application/json` [`VerificationScheduleRecord`](#schema-verificationschedulerecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-schedules/{schedule_ref}` {#read-verification-schedule-v1-tenants-tenant-slug-verification-schedules-schedule-ref-get}

**Read one scheduled verification**

Read a schedule by its handle or its id, with its current freshness and alert state.

`alert_state` is `alerting` while drift is outstanding — that is the state which makes a repeated failure quiet, and it clears when the deployment verifies clean again.

Requires `verification_targets:view`.

Operation id: `read_verification_schedule_v1_tenants__tenant_slug__verification_schedules__schedule_ref__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schedule_ref` | path | string | yes | Path parameter identifying the schedule ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one scheduled verification. | `application/json` [`VerificationScheduleRecord`](#schema-verificationschedulerecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/verification-schedules/{schedule_ref}` {#update-verification-schedule-v1-tenants-tenant-slug-verification-schedules-schedule-ref-patch}

**Retune or pause a scheduled verification**

Change the cadence, the name, the run options, or whether the schedule ticks. A paused schedule (`enabled: false`) keeps its history and its freshness anchor.

**The scheduling state is not settable here.** `last_success_at`, `alert_state`, and the failure counters are the sweep's record of what actually happened; a monitor whose freshness could be edited would not be a monitor.

**Cadence** accepts seconds or one of `5m`, `15m`, `30m`, `hourly`, `6h`, `12h`, `daily`, `weekly`.

Requires `verification_targets:edit`.

Operation id: `update_verification_schedule_v1_tenants__tenant_slug__verification_schedules__schedule_ref__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schedule_ref` | path | string | yes | Path parameter identifying the schedule ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for retune or pause a scheduled verification.

- `application/json` — [`VerificationSchedulePatch`](#schema-verificationschedulepatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for retune or pause a scheduled verification. | `application/json` [`VerificationScheduleRecord`](#schema-verificationschedulerecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/verification-schedules/{schedule_ref}` {#remove-verification-schedule-v1-tenants-tenant-slug-verification-schedules-schedule-ref-delete}

**Retire a scheduled verification**

Stop the schedule ticking. The retirement is a **soft delete**: the run history stays, because "when did this version last verify clean?" outlives the instruction that answered it.

To stop checks temporarily, PATCH `enabled: false` instead — a paused schedule can be resumed, a retired one cannot.

Requires `verification_targets:delete`.

Operation id: `remove_verification_schedule_v1_tenants__tenant_slug__verification_schedules__schedule_ref__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schedule_ref` | path | string | yes | Path parameter identifying the schedule ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for retire a scheduled verification. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-schedules/{schedule_ref}/runs` {#list-verification-schedule-runs-v1-tenants-tenant-slug-verification-schedules-schedule-ref-runs-get}

**Read a schedule's verification history**

The write-once history of what each tick found, newest first: the verdict, the coverage it measured, how much drift it saw, and — for every tick, not only the noisy ones — whether it notified and why. "Why was I not paged?" is answerable from the history rather than from a worker's log.

`status` is `passed`, `failed` (the deployment contradicted the contract), or `errored` (no verdict to trust — the deployment never answered, or the run could not be executed at all; the latter carries an `error_code`).

`drift_fingerprint` is the digest of the violation set: two failing ticks with the same fingerprint found the same thing, which is exactly when the second one stays silent.

Requires `verification_evidence:view` — a verification history is evidence.

Operation id: `list_verification_schedule_runs_v1_tenants__tenant_slug__verification_schedules__schedule_ref__runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schedule_ref` | path | string | yes | Path parameter identifying the schedule ref segment. |
| `status` | query | string or null | no | Restrict to `passed`, `failed`, or `errored`. |
| `limit` | query | integer | no | Maximum ticks to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a schedule's verification history. | `application/json` array of [`VerificationScheduleRunRecord`](#schema-verificationschedulerunrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-targets` {#list-verification-targets-v1-tenants-tenant-slug-verification-targets-get}

**List the tenant's verification targets**

Every live verification target defined in the tenant, newest first.

A target is **secret-free by construction**: it carries a credential *reference* (an environment-variable name, or an id in the encrypted credential vault), never a credential, so this response needs no redacted variant.

Requires `verification_targets:view` — the same permission a run needs to resolve one.

Operation id: `list_verification_targets_v1_tenants__tenant_slug__verification_targets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the tenant's verification targets. | `application/json` [`VerificationTargetListResponse`](#schema-verificationtargetlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/verification-targets` {#create-verification-target-v1-tenants-tenant-slug-verification-targets-post}

**Define a verification target**

Define where a compiled contract suite may be executed.

**The URL is vetted before anything is stored.** http/https only, no `user:pass@` authority, and — for the default `public` network class — every address the host resolves to must be globally routable. A target that must reach an internal address declares `network_class: private`, which requires an `approval_reason`; the authenticated caller is recorded as its approver.

**The credential is a reference, never a value.** `auth.kind: env` stores an environment-variable NAME the runner reads from its own environment; `auth.kind: stored` stores the id of a row in the encrypted credential vault. Both shapes are validated here and constrained again in the database, so a pasted token is rejected rather than stored.

Requires `verification_targets:create`.

Operation id: `create_verification_target_v1_tenants__tenant_slug__verification_targets_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for define a verification target.

- `application/json` — [`VerificationTargetInput`](#schema-verificationtargetinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for define a verification target. | `application/json` [`VerificationTargetRecord`](#schema-verificationtargetrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-targets-audit` {#read-verification-target-audit-v1-tenants-tenant-slug-verification-targets-audit-get}

**Read the verification-target audit ledger**

The append-only record of every target definition change and every target *selection*, including denials, newest first.

Entries carry the actor and whether they were an interactive user or a CI runner (`actor_kind: api_key`). The `detail` block holds non-secret context only — an update records which field names changed, never their values, and a resolve records the credential reference *kind* but never the reference itself.

Requires `verification_targets:view`.

Operation id: `read_verification_target_audit_v1_tenants__tenant_slug__verification_targets_audit_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `target_id` | query | string or null | no | Restrict the ledger to one target's history. |
| `limit` | query | integer | no | Maximum entries to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the verification-target audit ledger. | `application/json` [`TargetAuditResponse`](#schema-targetauditresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/verification-targets/{target_ref}` {#get-verification-target-v1-tenants-tenant-slug-verification-targets-target-ref-get}

**Read one verification target**

Read a target by its slug or its id. Accepting both is what lets CI name a stable handle (`staging`) while an evidence record names an immutable id.

Requires `verification_targets:view`.

Operation id: `get_verification_target_v1_tenants__tenant_slug__verification_targets__target_ref__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `target_ref` | path | string | yes | Path parameter identifying the target ref segment. |
| `include_deleted` | query | boolean | no | Resolve retired targets too. Evidence records name a target id, and that reference has to keep resolving after the target is retired. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one verification target. | `application/json` [`VerificationTargetRecord`](#schema-verificationtargetrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/verification-targets/{target_ref}` {#update-verification-target-v1-tenants-tenant-slug-verification-targets-target-ref-patch}

**Update a verification target**

Apply a partial update. Omitted fields are left alone; `auth` and `policy` are replaced wholesale when present, because a half-applied credential reference is exactly the state that puts a value in the wrong column.

The result is validated as a whole: supplying `network_class: private` and its `approval_reason` together is one coherent change, and moving a target back to `public` re-runs the address check its URL previously skipped.

Requires `verification_targets:edit`.

Operation id: `update_verification_target_v1_tenants__tenant_slug__verification_targets__target_ref__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `target_ref` | path | string | yes | Path parameter identifying the target ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update a verification target.

- `application/json` — [`VerificationTargetPatch`](#schema-verificationtargetpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update a verification target. | `application/json` [`VerificationTargetRecord`](#schema-verificationtargetrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/verification-targets/{target_ref}` {#delete-verification-target-v1-tenants-tenant-slug-verification-targets-target-ref-delete}

**Retire a verification target**

Soft-delete a target. The definition stays readable by id (`?include_deleted=true`) so an evidence record that names it keeps resolving, and the slug is freed for reuse.

Requires `verification_targets:delete`.

Operation id: `delete_verification_target_v1_tenants__tenant_slug__verification_targets__target_ref__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `target_ref` | path | string | yes | Path parameter identifying the target ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for retire a verification target. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/verification-targets/{target_ref}/resolve` {#resolve-verification-target-v1-tenants-tenant-slug-verification-targets-target-ref-resolve-post}

**Resolve a verification target for a run**

Select a target for a verification run — **the audited moment a definition becomes traffic**.

Everything a read tolerates is refused here: a retired target, a disabled one, and a URL that no longer satisfies its network class. That last check is re-run at resolve time on purpose: DNS moves, so a hostname that resolved publicly when the target was defined can point at an internal address today while the definition looks unchanged.

Success **and** refusal are written to the audit ledger, with the acting user or CI runner, so "which target did this run use" and "what was turned away" are answered from the same place.

The response carries the target identity, the base URL, the policy the runner must honour, and the credential *reference* — never a credential.

Requires `verification_targets:view`.

Operation id: `resolve_verification_target_v1_tenants__tenant_slug__verification_targets__target_ref__resolve_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `target_ref` | path | string | yes | Path parameter identifying the target ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for resolve a verification target for a run.

- `application/json` — [`ResolveTargetRequest`](#schema-resolvetargetrequest) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for resolve a verification target for a run. | `application/json` [`ResolvedTarget`](#schema-resolvedtarget) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ConformanceReportRecord` {#schema-conformancereportrecord}

A report with its detail — per-operation verdicts, drift, and uncovered operations.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Report id. |
| `tenant_id` | string | yes | Tenant that owns it. |
| `run_id` | string | yes | The ECA-1.3 evidence run this report summarises. |
| `version_ref` | string | yes | Version reference that was verified. |
| `artifact_kind` | string or null | no | `project` or `catalog`. |
| `artifact_id` | string or null | no | Artifact id. |
| `artifact_slug` | string or null | no | Artifact slug. |
| `version_label` | string or null | no | Resolved version label. |
| `suite_digest` | string | yes | Digest of the executed suite. |
| `target_id` | string or null | no | Target, when it still exists. |
| `target_slug` | string | yes | Target handle at run time. |
| `target_environment` | string | yes | Environment class at run time. |
| `target_network_class` | string | no | `public` or `private`. |
| `target_base_url` | string | yes | Base URL at run time. |
| `outcome` | string | yes | `passed`, `failed`, or `errored`. |
| `operations_total` | integer | yes | Operations in the specification, compiled or not. |
| `operations_exercised` | integer | yes | Operations that received a request. |
| `operations_passed` | integer | yes | Exercised operations with no drift. |
| `operations_failed` | integer | yes | Exercised operations that drifted. |
| `operations_errored` | integer | yes | Exercised operations that never answered. |
| `operations_skipped` | integer | yes | Compiled operations nothing was sent for. |
| `operations_uncompiled` | integer | yes | Operations the compiler could not compile. |
| `coverage_percent` | number | yes | Exercised over total, as a percentage. |
| `cases_total` | integer | yes | Cases accounted for. |
| `cases_passed` | integer | yes | Cases that passed. |
| `cases_failed` | integer | yes | Cases that drifted. |
| `cases_errored` | integer | yes | Cases that never answered. |
| `cases_skipped` | integer | yes | Cases deliberately not sent. |
| `drift_count` | integer | yes | Disagreements observed. |
| `mutating_allowed` | boolean | yes | Whether the run opted in to mutating methods. |
| `fixture_count` | integer | yes | Fixtures the caller supplied. |
| `created_at` | string (date-time) or null | no | When it was written. |
| `created_by` | string or null | no | User who ran it. |
| `actor_label` | string or null | no | Actor label at the time. |
| `actor_kind` | string | no | `user`, `api_key`, or `system`. |
| `report` | `ConformanceReport` | yes | The stored conformance report. |

### `ConformanceReportSummary` {#schema-conformancereportsummary}

A report without its detail — what a list read returns.

Every field here is a stored column rather than a JSON lookup, which is what lets CTG-4.4 and
CTG-4.5 ask "did the newest report for this version pass, and how much did it cover?" without
opening a single report body.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Report id. |
| `tenant_id` | string | yes | Tenant that owns it. |
| `run_id` | string | yes | The ECA-1.3 evidence run this report summarises. |
| `version_ref` | string | yes | Version reference that was verified. |
| `artifact_kind` | string or null | no | `project` or `catalog`. |
| `artifact_id` | string or null | no | Artifact id. |
| `artifact_slug` | string or null | no | Artifact slug. |
| `version_label` | string or null | no | Resolved version label. |
| `suite_digest` | string | yes | Digest of the executed suite. |
| `target_id` | string or null | no | Target, when it still exists. |
| `target_slug` | string | yes | Target handle at run time. |
| `target_environment` | string | yes | Environment class at run time. |
| `target_network_class` | string | no | `public` or `private`. |
| `target_base_url` | string | yes | Base URL at run time. |
| `outcome` | string | yes | `passed`, `failed`, or `errored`. |
| `operations_total` | integer | yes | Operations in the specification, compiled or not. |
| `operations_exercised` | integer | yes | Operations that received a request. |
| `operations_passed` | integer | yes | Exercised operations with no drift. |
| `operations_failed` | integer | yes | Exercised operations that drifted. |
| `operations_errored` | integer | yes | Exercised operations that never answered. |
| `operations_skipped` | integer | yes | Compiled operations nothing was sent for. |
| `operations_uncompiled` | integer | yes | Operations the compiler could not compile. |
| `coverage_percent` | number | yes | Exercised over total, as a percentage. |
| `cases_total` | integer | yes | Cases accounted for. |
| `cases_passed` | integer | yes | Cases that passed. |
| `cases_failed` | integer | yes | Cases that drifted. |
| `cases_errored` | integer | yes | Cases that never answered. |
| `cases_skipped` | integer | yes | Cases deliberately not sent. |
| `drift_count` | integer | yes | Disagreements observed. |
| `mutating_allowed` | boolean | yes | Whether the run opted in to mutating methods. |
| `fixture_count` | integer | yes | Fixtures the caller supplied. |
| `created_at` | string (date-time) or null | no | When it was written. |
| `created_by` | string or null | no | User who ran it. |
| `actor_label` | string or null | no | Actor label at the time. |
| `actor_kind` | string | no | `user`, `api_key`, or `system`. |

### `ContractRunRequest` {#schema-contractrunrequest}

What to execute against which target.

Compiler options are optional and default to the same defaults as suite compilation, so a
digest recorded in evidence matches ``POST …/suite`` with the same options.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target_ref` | string | yes | Verification target slug or id (ECA-1.2). |
| `options` | `ContractSuiteOptions` | no | Compiler options; hashed into the suite digest recorded on the run. |
| `idempotency_key` | string or null | no | Evidence upload retry key; forwarded to the verification-runs store. |
| `context` | object | no | Non-secret CI context (commit, branch, workflow URL). |

### `ContractRunResponse` {#schema-contractrunresponse}

The outcome of one contract run attempt.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Whether the suite executed and evidence was recorded. |
| `version_ref` | string | yes | The version reference exactly as requested. |
| `suite_digest` | string or null | no | Digest of the suite that was executed, when compiled. |
| `run` | [`VerificationRunRecord`](#schema-verificationrunrecord) or null | no | Immutable evidence record when `ok` is true. |
| `created` | boolean or null | no | True when evidence was newly written; False on idempotent replay. |
| `error` | `SpecImportJobError` or null | no | Populated when `ok` is false: stable taxonomy code plus remediation. |

### `ContractSuiteCompileRequest` {#schema-contractsuitecompilerequest}

What to compile for the version named in the URL.

The options are wrapped rather than inlined so the request can grow a sibling field without
changing the meaning of an existing body. An empty body compiles everything under the
default options.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `options` | `ContractSuiteOptions` | no | Compiler options. They are echoed on the manifest and hashed into its digest, so the same version compiled with the same options always yields the same suite. |

### `ContractSuiteResponse` {#schema-contractsuiteresponse}

The compiled suite for one version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Whether a suite could be compiled at all. |
| `version_ref` | string | yes | The reference exactly as it was requested. |
| `manifest` | `ContractSuiteManifest` or null | no | The compiled suite. Present whenever `ok` is true — including when it contains no cases, which is a real answer about a version that declares no operations. |
| `error` | `SpecImportJobError` or null | no | Populated when `ok` is false: stable taxonomy code plus remediation. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ProviderVerificationRequest` {#schema-providerverificationrequest}

What to verify, against which deployment, and how much of it may be touched.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target_ref` | string | yes | Verification target slug or id (ECA-1.2) naming the deployment to check. |
| `options` | `ContractSuiteOptions` | no | Suite compiler options; hashed into the suite digest the report and the evidence both record, so two reports with the same digest checked the same requests. |
| `verification` | `ProviderVerificationOptions` | no | What this run may send. Safe methods only by default; mutating operations require both `allow_mutating` and a fixture naming the operation. |
| `idempotency_key` | string or null | no | Evidence retry key; forwarded to the verification-runs store. |
| `context` | object | no | Non-secret CI context (commit, branch, workflow URL). Never credentials. |

### `ProviderVerificationResponse` {#schema-providerverificationresponse}

The outcome of one provider verification attempt.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Whether the suite executed and a report was produced. |
| `version_ref` | string | yes | The version reference exactly as requested. |
| `suite_digest` | string or null | no | Digest of the suite that was executed, when compiled. |
| `report` | `ConformanceReport` or null | no | The conformance report when `ok` is true. |
| `stored` | [`ConformanceReportRecord`](#schema-conformancereportrecord) or null | no | The persisted report, when it was written. Null — with `report` still populated — when persistence was not possible, so a caller is never handed a report id that does not exist. |
| `run` | [`VerificationRunRecord`](#schema-verificationrunrecord) or null | no | The immutable ECA-1.3 evidence behind the report. |
| `created` | boolean or null | no | True when evidence was newly written; False on idempotent replay. |
| `error` | `SpecImportJobError` or null | no | Populated when `ok` is false: stable taxonomy code plus remediation. |

### `ResolveTargetRequest` {#schema-resolvetargetrequest}

What a runner says when it selects a target.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `suite_digest` | string or null | no | The ECA-1.1 suite digest this run will execute. Recorded on the audit entry so a target selection can be tied to the exact contract it was selected for. |

### `ResolvedTarget` {#schema-resolvedtarget}

A target selected for a run: identity, endpoint, policy, and a credential *reference*.

This is the object an ECA-2.1 runner executes against and the one ECA-1.3 records the identity
of. It is deliberately the same secret-free shape as the stored record plus the resolution's
own facts — because "what the run used" and "what is configured" should never be two different
truths.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target_id` | string | yes | The resolved target's id — the run's target identity. |
| `slug` | string | yes | The handle that was resolved. |
| `name` | string | yes | Display name at resolution time. |
| `environment` | string | yes | Environment class. |
| `network_class` | string | yes | `public` or `private`. |
| `base_url` | string | yes | Normalized base URL to join relative paths onto. |
| `policy` | `VerificationPolicy` | yes | The policy the runner must honour. |
| `auth` | `TargetAuthReference` | yes | Where the runner obtains the credential. No credential material is returned by this API — an `env` reference is read from the runner's own environment, and a `stored` one is unsealed only at request time by the runner service. |
| `resolved_at` | string (date-time) | yes | When the target was resolved. |

### `TargetAuditResponse` {#schema-targetauditresponse}

The audit ledger read.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `entries` | array of `TargetAuditEntry` | no | Ledger entries, newest first. |
| `count` | integer | yes | How many entries were returned. |

### `VerificationRunInput` {#schema-verificationruninput}

A complete run, as a runner submits it once execution has finished.

Evidence is recorded in **one** shot rather than opened, appended to, and closed: that is what
makes immutability enforceable rather than aspirational (V212 rejects every UPDATE), and it
means a half-written run can never be mistaken for a finished one.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target_ref` | string | yes | The verification target this run executed against — its slug or its id. Recorded as an identity snapshot, so a later rename or retirement cannot rewrite the evidence. |
| `suite_digest` | string | yes | The ECA-1.1 manifest digest that was executed (`sha256:<hex>`). |
| `suite_schema_version` | integer or null | no | Manifest envelope version of the executed suite. |
| `suite_compiler_version` | integer or null | no | Compiler rules version of the executed suite. |
| `suite_case_count` | integer or null | no | How many cases the manifest declared. Recorded so a run that executed fewer is visibly partial rather than silently so. |
| `runner_name` | string | yes | Which runner produced the evidence. |
| `runner_version` | string or null | no | Runner version, so a behaviour change is attributable. |
| `started_at` | string (date-time) | yes | When the run began. |
| `finished_at` | string (date-time) | yes | When the run ended. |
| `outcome` | string or null | no | Optional declared verdict. It is *checked* against the outcome derived from the operation records and refused when it disagrees; only `cancelled` — which no record can imply — is taken on the runner's word. |
| `source` | object | no | Provenance of the compiled suite (artifact kind, reference, revision, version label), as the manifest reports it. |
| `context` | object | no | Non-secret CI context (commit, branch, workflow URL). Never credentials. |
| `idempotency_key` | string or null | no | Retry key. A runner that uploads evidence and loses the response can repeat the request with the same key and get the original run back instead of a duplicate. |
| `operations` | array of `OperationResultInput` | no | One record per executed case. |
| `artifacts` | array of `ArtifactReferenceInput` | no | Run-level artifact references (the runner log, a summary report). |
| `mock` | `MockAttestationInput` or null | no | Release-proof mock attestation (PMR-3.2): the immutable bundle digest the run was served from, the runtime version, the conformance corpus and result, and every fixture-pack digest. Attach it verbatim from `apiome-mock attest`. A run against a `mock` environment that omits it is recorded as an *explicitly* missing mock verification rather than as silence. |

### `VerificationRunListResponse` {#schema-verificationrunlistresponse}

A page of run summaries.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of `VerificationRunSummary` | no | Matching runs, newest first. |
| `count` | integer | yes | How many runs were returned. |

### `VerificationRunRecord` {#schema-verificationrunrecord}

A run with its full detail — what a read of one run, and both exporters, work from.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Run id — what a gate decision cites as its evidence. |
| `tenant_id` | string | yes | Tenant that owns the evidence. |
| `suite_digest` | string | yes | The executed ECA-1.1 manifest digest. |
| `suite_schema_version` | integer or null | no | Manifest envelope version. |
| `suite_compiler_version` | integer or null | no | Compiler rules version. |
| `suite_case_count` | integer or null | no | Cases the manifest declared. |
| `target_id` | string or null | no | Target used, when it still exists. |
| `target_slug` | string | yes | Target handle at run time. |
| `target_environment` | string | yes | Environment class at run time. |
| `target_network_class` | string | yes | `public` or `private`, at run time. |
| `target_base_url` | string | yes | Base URL at run time. |
| `runner_name` | string | yes | Which runner produced the evidence. |
| `runner_version` | string or null | no | Runner version. |
| `recorded_by` | string or null | no | User who recorded the evidence. |
| `actor_label` | string or null | no | Actor email/name at the time. |
| `actor_kind` | string | no | `user`, `api_key`, or `system`. |
| `started_at` | string (date-time) or null | no | When the run began. |
| `finished_at` | string (date-time) or null | no | When the run ended. |
| `duration_ms` | integer | no | Wall-clock duration in milliseconds. |
| `outcome` | string | yes | `passed`, `failed`, `errored`, or `cancelled`. |
| `counts` | map of integer | no | `total`, `passed`, `failed`, `errored`, `skipped` — always summing to total. |
| `source` | object | no | Provenance of the compiled suite. |
| `context` | object | no | Non-secret CI context. |
| `idempotency_key` | string or null | no | Caller-supplied retry key. |
| `created_at` | string (date-time) or null | no | When the evidence was recorded (server clock). |
| `operations` | array of `OperationRecord` | no | Case records, in stored order. |
| `artifacts` | array of `ArtifactRecord` | no | Run-level artifact references. |
| `mock` | `MockAttestationRecord` or null | no | The run's mock attestation (PMR-3.2). Present whenever the run named a mock — carrying `status: missing` with a reason when nothing was attested — and `null` for a run that had nothing to do with a mock. |

### `VerificationScheduleInput` {#schema-verificationscheduleinput}

A complete schedule definition, as a caller supplies it on create.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string | yes | Stable handle CI and the UI address the schedule by. |
| `name` | string | yes | Human-readable display name. |
| `description` | string or null | no | Operator note: what this schedule is watching, and why. |
| `version_ref` | string | yes | `project/{slug}/{version}` or `catalog/{item}/{version}` to verify. |
| `target_ref` | string | yes | Verification target slug or id (ECA-1.2) naming the deployment to check. |
| `cadence` | any | no | How often to run: a number of seconds, or one of `5m`, `15m`, `30m`, `hourly`, `6h`, `12h`, `daily`, `weekly`. |
| `enabled` | boolean | no | Whether the schedule ticks. A paused schedule keeps its history. |
| `alert_on_recovery` | boolean | no | Notify when a drifting deployment verifies clean again. |
| `options` | `ContractSuiteOptions` | no | ECA-1.1 compiler options, hashed into the suite digest each run records. |
| `verification` | `ProviderVerificationOptions` | no | What each run may send. Safe methods only by default; mutating operations require both `allow_mutating` and a fixture naming the operation, and a fixture carrying a credential header is refused before it is stored. |

### `VerificationSchedulePatch` {#schema-verificationschedulepatch}

A partial update. Every field is optional; only what is set is changed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `cadence` | any or null | no | New cadence (seconds or preset). |
| `enabled` | boolean or null | no | Pause or resume the schedule. |
| `alert_on_recovery` | boolean or null | no | Alert On Recovery. |
| `options` | `ContractSuiteOptions` or null | no | Options. |
| `verification` | `ProviderVerificationOptions` or null | no | Verification. |

### `VerificationScheduleRecord` {#schema-verificationschedulerecord}

A stored schedule, as every reader sees it.

There is no redacted variant: a schedule holds a *reference* to a target, and the target holds
a *reference* to a credential, so nothing here can be a secret.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Schedule id. |
| `tenant_id` | string | yes | Tenant that owns it. |
| `slug` | string | yes | Stable handle. |
| `name` | string | yes | Display name. |
| `description` | string or null | no | Operator note. |
| `version_ref` | string | yes | Version reference verified on each tick. |
| `target_id` | string | yes | The verification target's id. |
| `target_slug` | string | yes | The target's handle at definition time. |
| `cadence_seconds` | integer | yes | Interval between ticks, in seconds. |
| `enabled` | boolean | yes | Whether the schedule ticks. |
| `alert_on_recovery` | boolean | yes | Whether recovery notifies. |
| `options` | `ContractSuiteOptions` | no | Compiler options each run uses. |
| `verification` | `ProviderVerificationOptions` | no | Run options each tick uses. |
| `last_run_at` | string (date-time) or null | no | When the schedule last ticked, whatever the outcome. |
| `last_status` | string or null | no | `passed`, `failed`, or `errored`; null before the first tick. |
| `last_success_at` | string (date-time) or null | no | When it last verified clean — the freshness anchor. |
| `last_report_id` | string or null | no | The newest conformance report this schedule produced. |
| `consecutive_failures` | integer | no | Unhealthy ticks since the last clean one. |
| `run_count` | integer | no | Ticks recorded for this schedule. |
| `alert_state` | string | no | `ok`, or `alerting` while drift is outstanding. |
| `alert_fingerprint` | string or null | no | Digest of the violation set last alerted on. |
| `last_alert_at` | string (date-time) or null | no | When an alert was last sent. |
| `freshness_seconds` | integer or null | no | Seconds since the last clean verification, computed at read time. Null when this schedule has never verified clean — which a gate must read as 'unknown', never as 'fresh'. |
| `created_at` | string (date-time) or null | no | When it was defined. |
| `updated_at` | string (date-time) or null | no | When it last changed. |
| `created_by` | string or null | no | User who defined it. |
| `updated_by` | string or null | no | User who last changed it. |

### `VerificationScheduleRunRecord` {#schema-verificationschedulerunrecord}

One recorded tick — the write-once history row, as a reader sees it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Run-history row id. |
| `tenant_id` | string | yes | Tenant that owns it. |
| `schedule_id` | string | yes | The schedule that ticked. |
| `report_id` | string or null | no | The conformance report, when one was produced and stored. |
| `run_id` | string or null | no | The ECA-1.3 evidence run behind the report. |
| `status` | string | yes | `passed`, `failed`, or `errored`. |
| `error_code` | string or null | no | Set only when the run could not be executed at all (the version stopped compiling, the target was withdrawn). A deployment that answered wrongly is `failed` with no error code; one that never answered is `errored` with none either. |
| `error_message` | string or null | no | Remediation text, when refused. |
| `operations_total` | integer | no | Operations the specification declares. |
| `operations_exercised` | integer | no | Operations that received a request. |
| `operations_failed` | integer | no | Exercised operations that drifted. |
| `coverage_percent` | number | no | Exercised over total, as a percent. |
| `drift_count` | integer | no | Located disagreements observed. |
| `drift_fingerprint` | string or null | no | Digest of the violation set; null for a clean tick. |
| `alerted` | boolean | no | Whether this tick notified. |
| `alert_reason` | string or null | no | `transition`, `new-violations`, or `recovered`. |
| `alert_deliveries` | integer | no | Webhook deliveries enqueued for this tick's alert. |
| `started_at` | string (date-time) or null | no | When the tick began. |
| `finished_at` | string (date-time) or null | no | When it ended. |
| `duration_ms` | integer | no | Wall-clock duration in milliseconds. |
| `created_at` | string (date-time) or null | no | When it was recorded. |

### `VerificationTargetInput` {#schema-verificationtargetinput}

A complete target definition, as a caller supplies it on create.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string | yes | Stable handle used from the CLI and CI (`--target staging`). |
| `name` | string | yes | Human-readable display name. |
| `description` | string or null | no | Optional note about what this target is. |
| `environment` | string | no | `mock`, `development`, `test`, `staging`, or `production`. |
| `base_url` | string | yes | Base URL the suite's relative paths are joined onto. |
| `network_class` | string | no | `public` (must resolve to a globally routable address) or `private` (an internal target, which requires `approval_reason`). |
| `approval_reason` | string or null | no | Why a private-network target is justified. Required when `network_class` is `private`; the approver is the authenticated caller. |
| `auth` | `TargetAuthReference` | no | The credential reference — never a credential. |
| `policy` | `VerificationPolicy` | no | Execution and failure policy. |
| `enabled` | boolean | no | A disabled target stays defined but cannot be resolved. |

### `VerificationTargetListResponse` {#schema-verificationtargetlistresponse}

Every live target defined in the tenant.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `targets` | array of [`VerificationTargetRecord`](#schema-verificationtargetrecord) | no | The tenant's live targets, newest first. |
| `count` | integer | yes | How many targets were returned. |

### `VerificationTargetPatch` {#schema-verificationtargetpatch}

A partial update. Every field is optional; omitted fields are left as they are.

``auth`` and ``policy`` are replaced wholesale when present, because a half-applied credential
reference (a new ``ref`` against an old ``kind``) is exactly the kind of state that stores a
secret in the wrong column.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `environment` | string or null | no | Environment. |
| `base_url` | string or null | no | Base URL. |
| `network_class` | string or null | no | Network Class. |
| `approval_reason` | string or null | no | Approval Reason. |
| `auth` | `TargetAuthReference` or null | no | Auth. |
| `policy` | `VerificationPolicy` or null | no | Policy. |
| `enabled` | boolean or null | no | Whether the resource is active. |

### `VerificationTargetRecord` {#schema-verificationtargetrecord}

A stored target, as every reader sees it.

There is no redacted variant of this model because there is nothing to redact: the schema
cannot hold credential material, so the full record is always safe to return.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Target id — the identity an evidence row records. |
| `tenant_id` | string | yes | Tenant that owns the target. |
| `slug` | string | yes | Stable handle used from the CLI and CI. |
| `name` | string | yes | Human-readable display name. |
| `description` | string or null | no | Operator note. |
| `environment` | string | yes | Environment class. |
| `base_url` | string | yes | Base URL, normalized (no trailing slash). |
| `network_class` | string | yes | `public` or `private`. |
| `approved_by` | string or null | no | User who approved a private-network target. |
| `approved_at` | string (date-time) or null | no | When the private-network exception was approved. |
| `approval_reason` | string or null | no | Why a private-network target is justified. |
| `auth` | `TargetAuthReference` | yes | The credential reference — never a credential. |
| `policy` | `VerificationPolicy` | yes | Execution and failure policy. |
| `enabled` | boolean | yes | Whether the target may be resolved for a run. |
| `created_by` | string or null | no | User who created the target. |
| `updated_by` | string or null | no | User who last modified it. |
| `created_at` | string (date-time) or null | no | When it was defined. |
| `updated_at` | string (date-time) or null | no | When it last changed. |
| `deleted_at` | string (date-time) or null | no | Soft-delete timestamp; a retired target is still resolvable by id for the evidence rows that name it. |
