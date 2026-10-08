---
title: "Spec sync"
description: "REST endpoints tagged spec-sync: 4 operations."
sidebar_position: 69
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `spec-sync` · 4 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/sync-plans/{plan_id}` {#read-plan-v1-tenants-tenant-slug-projects-project-ref-sync-plans-plan-id-get}

**Read one merge result**

One three-way merge with every conflict it found — outstanding ones first — each carrying the base, incoming and current values and the repository file and line it lives at.

Requires `projects:view`.

Operation id: `read_plan_v1_tenants__tenant_slug__projects__project_ref__sync_plans__plan_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `plan_id` | path | string | yes | Path parameter identifying the plan id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one merge result. | `application/json` [`SyncPlanDetail`](#schema-syncplandetail) |
| 404 | Not Found | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/sync-plans/{plan_id}/conflicts/{conflict_id}` {#resolve-conflict-v1-tenants-tenant-slug-projects-project-ref-sync-plans-plan-id-conflicts-conflict-id-post}

**Settle one conflict of a merge result**

Records which side wins at one pointer: `git` takes the repository's value, `draft` keeps the version's.

Settling **records a decision and nothing else** — it does not edit the draft, take anything from the repository, or move the binding. A settlement is final; the merge moves to `resolved` once none are outstanding.

Requires `versions:edit`.

Operation id: `resolve_conflict_v1_tenants__tenant_slug__projects__project_ref__sync_plans__plan_id__conflicts__conflict_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `plan_id` | path | string | yes | Path parameter identifying the plan id segment. |
| `conflict_id` | path | string | yes | Path parameter identifying the conflict id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for settle one conflict of a merge result.

- `application/json` — [`SyncConflictResolve`](#schema-syncconflictresolve)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for settle one conflict of a merge result. | `application/json` [`SyncPlanDetail`](#schema-syncplandetail) |
| 404 | Not Found | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |
| 409 | Conflict | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding/sync` {#read-version-sync-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-sync-get}

**Read a version's synchronization state**

The most recent three-way merge of this draft against its repository ref, with its conflicts, plus the merges before it.

No provider is contacted: this is what is already known. A result whose `stale` flag is set was computed against a draft that has since been edited.

Requires `projects:view`.

Operation id: `read_version_sync_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_sync_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a version's synchronization state. | `application/json` [`VersionSyncStatus`](#schema-versionsyncstatus) |
| 404 | Not Found | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding/sync` {#compute-plan-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-binding-sync-post}

**Merge a bound draft against its repository ref**

Reads the bound selection at the commit this draft is synchronized with (the base) and at the commit its branch moved to, rebuilds the draft's own document, and merges the three.

Incoming changes that touch nothing the draft touched are recorded as applied; every overlap becomes a conflict naming its JSON Pointer, its repository file and line, and the base, incoming and current values side by side.

**The draft is never modified.** A merge result is a reading of three documents; what to do about it is a separate decision.

Re-running a merge of the same three documents returns the result already stored rather than computing a second answer to the same question, so a redelivered webhook or a double-click costs nothing.

Requires `versions:edit`, and proves the tenant's stored credential can read the repository.

Operation id: `compute_plan_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__binding_sync_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version_ref` | path | string | yes | Path parameter identifying the version ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for merge a bound draft against its repository ref.

- `application/json` — [`SyncPlanCompute`](#schema-syncplancompute)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for merge a bound draft against its repository ref. | `application/json` [`SyncPlanDetail`](#schema-syncplandetail) |
| 403 | Forbidden | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |
| 404 | Not Found | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |
| 409 | Conflict | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |
| 422 | Unprocessable Content | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |
| 502 | Bad Gateway | `application/json` [`SyncErrorDetail`](#schema-syncerrordetail) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SyncConflictResolve` {#schema-syncconflictresolve}

Settle one conflict towards one side.

Attributes:
    resolution: ``git`` takes the repository's value, ``draft`` keeps the version's. There is
        no third option: a merge result records a decision, it does not edit a document.
    note: Why, kept with the settled row.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `resolution` | enum `"git"`, `"draft"` | yes | Resolution. |
| `note` | string or null | no | Note. |

### `SyncErrorDetail` {#schema-syncerrordetail}

The body of every refusal from this surface.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `code` | string | yes | The stable refusal code a client branches on. |
| `message` | string | yes | A human-readable explanation. |

### `SyncPlanCompute` {#schema-syncplancompute}

Compute a three-way merge of a bound draft against its repository ref.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `candidate_id` | string or null | no | The outstanding sync candidate to merge. Defaults to the binding's oldest pending candidate, which is the one a reader is looking at. |
| `refresh` | boolean | no | Re-read both commits even when a merge of the same three documents is already stored. The stored result is still what is returned when the inputs are unchanged, because the same inputs cannot produce a different merge. |

### `SyncPlanDetail` {#schema-syncplandetail}

A merge result with its conflicts.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `plan` | `SyncPlanRecord` | yes | Plan. |
| `conflicts` | array of `SyncConflictRecord` | no | Every conflict, outstanding ones first. |

### `VersionSyncStatus` {#schema-versionsyncstatus}

Where one version stands with respect to merging its repository ref.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `version_label` | string or null | no | Version Label. |
| `bound` | boolean | yes | Whether the version has an active binding to merge against. |
| `latest` | [`SyncPlanDetail`](#schema-syncplandetail) or null | no | The most recent merge result, with its conflicts. |
| `history` | array of `SyncPlanRecord` | no | Earlier merge results, newest first. |
