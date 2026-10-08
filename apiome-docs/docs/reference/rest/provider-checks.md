---
title: "Provider checks"
description: "REST endpoints tagged provider-checks: 4 operations."
sidebar_position: 51
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `provider-checks` · 4 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/checks` {#list-checks-v1-tenants-tenant-slug-projects-project-ref-checks-get}

**List a project's provider check runs**

A page of the project's normalized check verdicts, newest first. Each is one of `pending`, `pass`, `fail` or `skipped` about one commit of one bound draft.

Filters combine: `version` (revision id or version label), `commit_sha`, and `state`.

No repository credential appears anywhere in the response.

Requires `projects:view`.

Operation id: `list_checks_v1_tenants__tenant_slug__projects__project_ref__checks_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version` | query | string or null | no | Revision id or version label. |
| `commit_sha` | query | string or null | no | Only checks about this commit. |
| `state` | query | string or null | no | Only checks in this state: pending, pass, fail, skipped. |
| `limit` | query | integer | no | Page size. |
| `offset` | query | integer | no | Check runs to skip. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's provider check runs. | `application/json` [`CheckListResponse`](#schema-checklistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/checks/{check_id}` {#read-check-v1-tenants-tenant-slug-projects-project-ref-checks-check-id-get}

**Read one check run**

One normalized verdict with every attempt to publish it to the provider: what state was sent, whether it was `dispatched`, `suppressed` or `failed`, the provider's status code, and its refusal — redacted, because a provider's error body is outside our control.

Requires `projects:view`.

Operation id: `read_check_v1_tenants__tenant_slug__projects__project_ref__checks__check_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `check_id` | path | string | yes | Path parameter identifying the check id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one check run. | `application/json` [`CheckRunDetail`](#schema-checkrundetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding/checks` {#list-version-checks-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-checks-get}

**List a version's provider check runs**

The checks recorded against this version's binding, newest first.

Requires `projects:view`.

Operation id: `list_version_checks_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_checks_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `commit_sha` | query | string or null | no | Only checks about this commit. |
| `limit` | query | integer | no | Page size. |
| `offset` | query | integer | no | Check runs to skip. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a version's provider check runs. | `application/json` [`CheckListResponse`](#schema-checklistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding/checks` {#record-check-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-checks-post}

**Record a check verdict against a version's binding**

Record one normalized verdict — `pending`, `pass`, `fail` or `skipped` — about a commit of the ref this draft is bound to, and publish it to the provider.

**Idempotent.** `(binding, commit, name)` identifies the check, so the same call twice is one verdict a reviewer reads, not two they have to reconcile. Pass `rerun: true` to say this is a fresh run of the same check, which advances its attempt counter.

`commit_sha` defaults to the commit the binding is synchronized with. `publish: false` records the verdict without sending it, which is useful while a check suite is being developed against a real repository — the attempt is still ledgered, as `suppressed`.

**Recording never fails because publishing did.** A provider that refuses the write leaves a `failed` row on the check's publish ledger and a `201` here: a verdict that was recorded and not published is evidence, and losing it would be worse than not showing it. Read the check back to see what the provider did.

The repository token is resolved server-side from the registration the binding was authorized through; a credential is never accepted in the body.

Requires `versions:edit`.

Operation id: `record_check_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_checks_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record a check verdict against a version's binding.

- `application/json` — [`CheckRunUpsert`](#schema-checkrunupsert)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for record a check verdict against a version's binding. | `application/json` [`CheckRunDetail`](#schema-checkrundetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CheckListResponse` {#schema-checklistresponse}

A page of a project's check runs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `checks` | array of `CheckRunRecord` | no | Check runs, newest first. |
| `count` | integer | yes | How many check runs this page holds. |
| `limit` | integer | yes | The page size used. |
| `offset` | integer | yes | The offset used. |
| `providers` | array of string | no | Providers a verdict can be published to through the status adapter. |

### `CheckRunDetail` {#schema-checkrundetail}

A check run with the publish attempts behind it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `check` | `CheckRunRecord` | yes | Check. |
| `deliveries` | array of `CheckDeliveryRecord` | no | Publish attempts, newest first. |

### `CheckRunUpsert` {#schema-checkrunupsert}

Record a check verdict against a version's active binding.

Idempotent by construction: ``(binding, commit, name)`` identifies the check, so the same call
twice is one verdict. A credential is never accepted in the body — the repository token is
resolved server-side from the binding's registration.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | no | The check's stable name; the same name on the same commit is the same check. |
| `state` | enum `"pending"`, `"pass"`, `"fail"`, `"skipped"` | no | `pending`, `pass`, `fail`, or `skipped`. |
| `commit_sha` | string or null | no | The commit to report against; defaults to the binding's synchronized commit. |
| `title` | string | no | One-line title. |
| `summary` | string | no | The longer explanation. |
| `details_url` | string | no | Where the check points a reviewer; a failure should be a reason, not a log. |
| `pr_number` | integer or null | no | The pull request the commit belongs to, when known. |
| `publish` | boolean | no | Publish the verdict to the provider as well as recording it. False records it only — useful while a check suite is being developed against a real repository. |
| `rerun` | boolean | no | Treat this as a fresh run of the same check: the attempt counter advances. Without it, re-recording the same verdict leaves the row exactly as it is. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
