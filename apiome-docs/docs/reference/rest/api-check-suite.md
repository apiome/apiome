---
title: "API check suite"
description: "REST endpoints tagged api-check-suite: 10 operations."
sidebar_position: 6
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `api-check-suite` · 10 operations

## `GET /v1/tenants/{tenant_slug}/governance/check-suite-policy` {#get-tenant-check-suite-policy-v1-tenants-tenant-slug-governance-check-suite-policy-get}

**Read the tenant's API change check suite policy**

Each component — `lint`, `breaking`, `consumers`, `contract`, `sdk` — is `required` (it decides the verdict), `advisory` (evaluated and reported, never deciding) or `off` (not evaluated). Absent components take their documented defaults: lint, breaking and consumers required; contract and sdk advisory.

`requiredForPublish: true` refuses to publish a version whose current content has no passing (or skipped) evaluation under the policy in force; force-publish with a reason stays the escape, and is audited.

Requires `projects:view`.

Operation id: `get_tenant_check_suite_policy_v1_tenants__tenant_slug__governance_check_suite_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the tenant's api change check suite policy. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/governance/check-suite-policy` {#put-tenant-check-suite-policy-v1-tenants-tenant-slug-governance-check-suite-policy-put}

**Save the tenant's API change check suite policy**

Each component — `lint`, `breaking`, `consumers`, `contract`, `sdk` — is `required` (it decides the verdict), `advisory` (evaluated and reported, never deciding) or `off` (not evaluated). Absent components take their documented defaults: lint, breaking and consumers required; contract and sdk advisory.

`requiredForPublish: true` refuses to publish a version whose current content has no passing (or skipped) evaluation under the policy in force; force-publish with a reason stays the escape, and is audited.

Requires a signed-in tenant administrator. Audited as `governance.check_suite_policy.update`.

Operation id: `put_tenant_check_suite_policy_v1_tenants__tenant_slug__governance_check_suite_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save the tenant's api change check suite policy.

- `application/json` — [`CheckSuitePolicyPutRequest`](#schema-checksuitepolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save the tenant's api change check suite policy. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/governance/check-suite-policy` {#delete-tenant-check-suite-policy-v1-tenants-tenant-slug-governance-check-suite-policy-delete}

**Clear the tenant's API change check suite policy**

Drop the tenant-wide policy so the documented default governs. Project overrides are left in place. Returns the policy now in force.

Requires a signed-in tenant administrator. Audited as `governance.check_suite_policy.clear`.

Operation id: `delete_tenant_check_suite_policy_v1_tenants__tenant_slug__governance_check_suite_policy_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for clear the tenant's api change check suite policy. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/check-suite-policy` {#get-project-check-suite-policy-v1-tenants-tenant-slug-projects-project-ref-check-suite-policy-get}

**Read the API change check suite policy in force for a project**

Each component — `lint`, `breaking`, `consumers`, `contract`, `sdk` — is `required` (it decides the verdict), `advisory` (evaluated and reported, never deciding) or `off` (not evaluated). Absent components take their documented defaults: lint, breaking and consumers required; contract and sdk advisory.

`requiredForPublish: true` refuses to publish a version whose current content has no passing (or skipped) evaluation under the policy in force; force-publish with a reason stays the escape, and is audited.

Resolution is project → tenant → documented default, and `source` says which supplied it.

Requires `projects:view`.

Operation id: `get_project_check_suite_policy_v1_tenants__tenant_slug__projects__project_ref__check_suite_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the api change check suite policy in force for a project. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/projects/{project_ref}/check-suite-policy` {#put-project-check-suite-policy-v1-tenants-tenant-slug-projects-project-ref-check-suite-policy-put}

**Save a project's API change check suite policy override**

Each component — `lint`, `breaking`, `consumers`, `contract`, `sdk` — is `required` (it decides the verdict), `advisory` (evaluated and reported, never deciding) or `off` (not evaluated). Absent components take their documented defaults: lint, breaking and consumers required; contract and sdk advisory.

`requiredForPublish: true` refuses to publish a version whose current content has no passing (or skipped) evaluation under the policy in force; force-publish with a reason stays the escape, and is audited.

Requires a signed-in tenant administrator. Audited as `governance.check_suite_policy.update`.

Operation id: `put_project_check_suite_policy_v1_tenants__tenant_slug__projects__project_ref__check_suite_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save a project's api change check suite policy override.

- `application/json` — [`CheckSuitePolicyPutRequest`](#schema-checksuitepolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save a project's api change check suite policy override. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/projects/{project_ref}/check-suite-policy` {#delete-project-check-suite-policy-v1-tenants-tenant-slug-projects-project-ref-check-suite-policy-delete}

**Remove a project's API change check suite policy override**

Drop the project override so the tenant-wide policy (or the documented default) governs again. Returns the policy now in force.

Requires a signed-in tenant administrator. Audited as `governance.check_suite_policy.clear`.

Operation id: `delete_project_check_suite_policy_v1_tenants__tenant_slug__projects__project_ref__check_suite_policy_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove a project's api change check suite policy override. | `application/json` [`CheckSuitePolicyOut`](#schema-checksuitepolicyout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/check-suite/runs/{run_id}` {#read-check-suite-run-v1-tenants-tenant-slug-projects-project-ref-check-suite-runs-run-id-get}

**Read one API change check suite evaluation — the drill-down**

One evaluation: every component with the evidence it read (ids, digests, counts), a link to that evidence, and the policy it was judged under. This is what a provider check's summary points at.

Requires `projects:view`.

Operation id: `read_check_suite_run_v1_tenants__tenant_slug__projects__project_ref__check_suite_runs__run_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one api change check suite evaluation — the drill-down. | `application/json` [`CheckSuiteRunDetail`](#schema-checksuiterundetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/check-suite` {#read-check-suite-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-check-suite-get}

**Read the latest API change check suite evaluation of a version**

The newest evaluation (at `commit_sha`, when given), with `stale: true` when the draft's content or either policy has moved since — the evaluation then no longer answers for the version as it is now — and the provider check it became.

Requires `projects:view`; readable by a CI key holding `diff:read` or `lint:read`.

Operation id: `read_check_suite_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__check_suite_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `commit_sha` | query | string or null | no | Only evaluations at this commit. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the latest api change check suite evaluation of a version. | `application/json` [`CheckSuiteRunDetail`](#schema-checksuiterundetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/check-suite` {#run-check-suite-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-check-suite-post}

**Run the API change check suite for a version**

Aggregate the evidence the platform already has about this version into **one** verdict — `pending`, `pass`, `fail` or `skipped` — and, when the version is bound to a repository ref, report it on the pull request as the `apiome/api-change` check.

Five components, each a reading of existing evidence: **lint** (the stored GOV lint report), **breaking** and **consumers** (the CTG classification against the previous published revision, judged by the CTG-4.5 deploy gate's own rules and thresholds), **contract** (the newest ECA contract run of this revision, if its suite is still this draft's) and **sdk** (the SDK client-kit manifest). Only the components the suite policy marks `required` decide the verdict.

**Idempotent.** An evaluation is keyed by everything it is a function of — the draft's content digest, the commit, both policies and every component's evidence. Re-running over unchanged inputs returns that evaluation (`200`, `replayed: true`) with the same evidence ids, and the provider is not called again for a publish it already has. New inputs are a new evaluation (`201`).

`commit_sha` defaults to the commit the binding is synchronized with. A newer commit on the branch gets `skipped` (`spec-unchanged`) when it does not touch the bound specification, otherwise `pending` (`draft-not-synchronized`) until the draft catches up. A commit the binding has never been observed at is `409 check-suite-commit-unknown`.

Requires `versions:edit`.

Operation id: `run_check_suite_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__check_suite_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for run the api change check suite for a version.

- `application/json` — [`CheckSuiteRunRequest`](#schema-checksuiterunrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | These inputs were already evaluated; that evaluation. | — |
| 201 | Successful response for run the api change check suite for a version. | `application/json` [`CheckSuiteRunDetail`](#schema-checksuiterundetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/check-suite/runs` {#list-check-suite-runs-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-check-suite-runs-get}

**List a version's API change check suite evaluations**

Every evaluation of the version, newest first.

Requires `projects:view`.

Operation id: `list_check_suite_runs_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__check_suite_runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `commit_sha` | query | string or null | no | Only evaluations at this commit. |
| `limit` | query | integer | no | Page size. |
| `offset` | query | integer | no | Evaluations to skip. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a version's api change check suite evaluations. | `application/json` [`CheckSuiteRunList`](#schema-checksuiterunlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CheckSuitePolicyOut` {#schema-checksuitepolicyout}

The suite policy in force for a scope.

Attributes:
    schema_version: :data:`POLICY_SCHEMA_VERSION`.
    source: ``default`` (nothing saved), ``tenant`` or ``project``.
    policy_id: The stored row; ``None`` for the documented default.
    content_fingerprint: Digest of the body.
    policy: The body itself.
    updated_at: When the stored policy last changed.
    updated_by: Who changed it.
    degraded: True when a saved policy could not be read and the default stood in, so
        "nothing is configured" and "I could not read what is" stay distinguishable.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `source` | string | yes | `default` \| `tenant` \| `project`. |
| `policyId` | string or null | no | Policy ID. |
| `contentFingerprint` | string | no | Content Fingerprint. |
| `policy` | `CheckSuitePolicy` | no | Policy. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |
| `degraded` | boolean | no | Degraded. |

### `CheckSuitePolicyPutRequest` {#schema-checksuitepolicyputrequest}

Body for saving a suite policy — the ``gnc.check-suite-policy.v1`` document.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `components` | map of string | no | component → `required` \| `advisory` \| `off`; absent components take defaults. |
| `requiredForPublish` | boolean | no | Require a passing suite evaluation of the current content to publish. |

### `CheckSuiteRunDetail` {#schema-checksuiterundetail}

An evaluation, the provider check it became, and whether it still describes the draft.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `run` | `CheckSuiteRunRecord` | yes | Run. |
| `replayed` | boolean | no | True when these inputs had already been evaluated and that row came back. |
| `stale` | boolean | no | True when the draft's content or either policy has moved since this evaluation — it no longer answers for the version as it is now. |
| `provider` | `ProviderReport` or null | no | The provider side, when the version is bound. |
| `check` | `CheckRunDetail` or null | no | The GNC-2.2 check run the verdict became, with its publishes. |

### `CheckSuiteRunList` {#schema-checksuiterunlist}

A page of a version's evaluations.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of `CheckSuiteRunRecord` | no | Newest first. |
| `count` | integer | yes | Number of count. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `CheckSuiteRunRequest` {#schema-checksuiterunrequest}

Evaluate the suite for a version, and report the verdict when it is bound.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `commit_sha` | string or null | no | The commit to report against; defaults to the commit the binding is synchronized with. Only a bound version takes one. |
| `pr_number` | integer or null | no | The pull request the commit belongs to, when known. |
| `publish` | boolean | no | Publish the verdict to the provider as well as recording it. False records the evaluation and the check without sending it. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
