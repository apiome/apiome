---
title: "Merge requests"
description: "REST endpoints tagged merge-requests: 9 operations."
sidebar_position: 61
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.604.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `merge-requests` · 9 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/draft-branches` {#list-draft-branches-v1-tenants-tenant-slug-projects-project-ref-draft-branches-get}

**List draft branches**

List the project's draft branches, each with the version line it was drafted off.

Operation id: `list_draft_branches_v1_tenants__tenant_slug__projects__project_ref__draft_branches_get`

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
| 200 | Successful response for list draft branches. | `application/json` [`DraftBranchListResponse`](#schema-draftbranchlistresponse) |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/draft-branches` {#create-draft-branch-v1-tenants-tenant-slug-projects-project-ref-draft-branches-post}

**Create a draft branch off a version line**

Create a named draft branch off a version line (a branch; the default branch when omitted).

The line's tip is copied — classes and paths — into a new draft revision that becomes the
branch's tip, so edits on the branch never touch the line. ``version_label`` names that
revision; it defaults to the next patch version of the project.

Operation id: `create_draft_branch_v1_tenants__tenant_slug__projects__project_ref__draft_branches_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create a draft branch off a version line.

- `application/json` — [`DraftBranchCreate`](#schema-draftbranchcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a draft branch off a version line. | `application/json` [`DraftBranchRecord`](#schema-draftbranchrecord) |
| 403 | Missing permission, or the action needs an attributable user. | — |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 409 | The request conflicts with the current state (see the `code`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/merge-requests` {#list-merge-requests-v1-tenants-tenant-slug-projects-project-ref-merge-requests-get}

**List merge requests**

List the project's merge requests, most recently active first.

Operation id: `list_merge_requests_v1_tenants__tenant_slug__projects__project_ref__merge_requests_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `state` | query | enum `"open"`, `"merged"`, `"closed"` or null | no | Only requests in this state. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list merge requests. | `application/json` [`MergeRequestListResponse`](#schema-mergerequestlistresponse) |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/merge-requests` {#open-merge-request-v1-tenants-tenant-slug-projects-project-ref-merge-requests-post}

**Open a merge request**

Open a merge request from a draft branch into a line (the line it was drafted off by default).

The branch tip's review is requested from ``reviewers`` (COL-2.1), or the tip's open review is
attached when it already has one.

Operation id: `open_merge_request_v1_tenants__tenant_slug__projects__project_ref__merge_requests_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for open a merge request.

- `application/json` — [`MergeRequestCreate`](#schema-mergerequestcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for open a merge request. | `application/json` [`MergeRequestDetail`](#schema-mergerequestdetail) |
| 403 | Missing permission, or the action needs an attributable user. | — |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 409 | The request conflicts with the current state (see the `code`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/merge-requests/{merge_request_id}` {#read-merge-request-v1-tenants-tenant-slug-projects-project-ref-merge-requests-merge-request-id-get}

**Read a merge request**

Read a merge request: its branches' tips, merge base, review, merge session, and readiness.

Operation id: `read_merge_request_v1_tenants__tenant_slug__projects__project_ref__merge_requests__merge_request_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `merge_request_id` | path | string | yes | Path parameter identifying the merge request id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a merge request. | `application/json` [`MergeRequestDetail`](#schema-mergerequestdetail) |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/merge-requests/{merge_request_id}/check` {#check-merge-request-v1-tenants-tenant-slug-projects-project-ref-merge-requests-merge-request-id-check-post}

**Check a merge request for conflicts**

Run a merge session (the existing merge preview, persisted) for the current tips.

The session's conflicts come back on ``conflicts``; a session with conflicts is left in
``resolving`` until the branch is updated and checked again.

Operation id: `check_merge_request_v1_tenants__tenant_slug__projects__project_ref__merge_requests__merge_request_id__check_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `merge_request_id` | path | string | yes | Path parameter identifying the merge request id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for check a merge request for conflicts.

- `application/json` — [`MergeRequestMerge`](#schema-mergerequestmerge) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for check a merge request for conflicts. | `application/json` [`MergeRequestDetail`](#schema-mergerequestdetail) |
| 403 | Missing permission, or the action needs an attributable user. | — |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 409 | The request conflicts with the current state (see the `code`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/merge-requests/{merge_request_id}/close` {#close-merge-request-v1-tenants-tenant-slug-projects-project-ref-merge-requests-merge-request-id-close-post}

**Close a merge request without merging**

Close the merge request. The branch and its revisions stay; its review is withdrawn when allowed.

Operation id: `close_merge_request_v1_tenants__tenant_slug__projects__project_ref__merge_requests__merge_request_id__close_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `merge_request_id` | path | string | yes | Path parameter identifying the merge request id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for close a merge request without merging. | `application/json` [`MergeRequestDetail`](#schema-mergerequestdetail) |
| 403 | Missing permission, or the action needs an attributable user. | — |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 409 | The request conflicts with the current state (see the `code`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/merge-requests/{merge_request_id}/merge` {#merge-merge-request-v1-tenants-tenant-slug-projects-project-ref-merge-requests-merge-request-id-merge-post}

**Merge a merge request**

Merge the branch into the line through a merge session and the existing merge path.

Needs the review approved and current (and the approval policy satisfied, when one applies).
Conflicts refuse with ``mr-conflicts``; the merge path's own refusals (``STALE_HEAD``,
``PUBLISHED_IMMUTABLE``, ``MERGE_BLOCKED_BY_COMPAT_GATE``) pass through unchanged.

Operation id: `merge_merge_request_v1_tenants__tenant_slug__projects__project_ref__merge_requests__merge_request_id__merge_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `merge_request_id` | path | string | yes | Path parameter identifying the merge request id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for merge a merge request.

- `application/json` — [`MergeRequestMerge`](#schema-mergerequestmerge) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for merge a merge request. | `application/json` [`MergeRequestDetail`](#schema-mergerequestdetail) |
| 403 | Missing permission, or the action needs an attributable user. | — |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 409 | The request conflicts with the current state (see the `code`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/merge-requests/{merge_request_id}/review` {#request-merge-request-review-v1-tenants-tenant-slug-projects-project-ref-merge-requests-merge-request-id-review-post}

**Request a review of the branch's current tip**

Attach a review of the branch's current tip, withdrawing the review of an older tip.

Use it after the branch moved on (``review-outdated``) or its review was withdrawn. A review
whose round went stale on the *same* tip is re-requested on the review page instead.

Operation id: `request_merge_request_review_v1_tenants__tenant_slug__projects__project_ref__merge_requests__merge_request_id__review_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `merge_request_id` | path | string | yes | Path parameter identifying the merge request id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for request a review of the branch's current tip.

- `application/json` — [`MergeRequestReviewRequest`](#schema-mergerequestreviewrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for request a review of the branch's current tip. | `application/json` [`MergeRequestDetail`](#schema-mergerequestdetail) |
| 403 | Missing permission, or the action needs an attributable user. | — |
| 404 | Unknown project, branch, or merge request (`mr-*-not-found`). | — |
| 409 | The request conflicts with the current state (see the `code`). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `DraftBranchCreate` {#schema-draftbranchcreate}

Create a draft branch off a version line.

Attributes:
    name: The new branch's name (letters, digits, ``. _ - /``; starts with a letter).
    base_branch: The version line to draft off — a branch name or id. Omit for the project's
        default branch.
    version_label: The draft revision's version label. Omit to take the next patch version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `base_branch` | string or null | no | Base Branch. |
| `version_label` | string or null | no | Version Label. |

### `DraftBranchListResponse` {#schema-draftbranchlistresponse}

A project's draft branches.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `branches` | array of [`DraftBranchRecord`](#schema-draftbranchrecord) | no | Newest first. |

### `DraftBranchRecord` {#schema-draftbranchrecord}

A draft branch, with the line it was drafted off.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | The branch id. |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `name` | string | yes | Human-readable name. |
| `tip_revision_id` | string | yes | The branch's tip — the draft revision edits land on. |
| `tip_version_label` | string or null | no | The tip's version label. |
| `base_branch_id` | string or null | no | The version line (branch) it was drafted off; null once that branch is gone. |
| `base_branch_name` | string or null | no | That line's name. |
| `branched_from_revision_id` | string or null | no | The line's tip when the draft was created. |
| `created_by` | string or null | no | Created By. |
| `created_at` | string (date-time) or null | no | Creation timestamp (ISO 8601). |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MergeRequestCreate` {#schema-mergerequestcreate}

Open a merge request from a draft branch, asking reviewers to review its tip.

Attributes:
    source_branch: The draft branch — name or id.
    target_branch: The line to merge into — name or id. Omit for the line the draft was
        drafted off.
    title: A one-line summary.
    description: Optional detail.
    reviewers: User ids of the tenant members to ask; the requester cannot be one of them.
        Required unless the branch tip already has an open review, which is then attached.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `source_branch` | string | yes | Source Branch. |
| `target_branch` | string or null | no | Target Branch. |
| `title` | string | yes | Title. |
| `description` | string or null | no | Free-text description. |
| `reviewers` | array of string or null | no | Reviewers. |

### `MergeRequestDetail` {#schema-mergerequestdetail}

A merge request with its branches, review, merge session, and readiness.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `merge_request` | `MergeRequestRecord` | yes | Merge Request. |
| `source_tip_revision_id` | string or null | no | The branch's current tip. |
| `source_tip_version_label` | string or null | no | Source Tip Version Label. |
| `target_tip_revision_id` | string or null | no | The line's current tip. |
| `target_tip_version_label` | string or null | no | Target Tip Version Label. |
| `merge_base_revision_id` | string or null | no | The common ancestor the Changes tab compares the branch tip with. |
| `merge_base_version_label` | string or null | no | Merge Base Version Label. |
| `review` | `ReviewDetail` or null | no | The attached review, when there is one. |
| `review_outdated` | boolean | no | True when the review judged an older tip than the branch's current one. |
| `merge_session` | object or null | no | The latest merge session (`status`, tips, merge base). |
| `conflicts` | array of `MergeConflict` | no | That session's conflicts, when its tips are still current. |
| `readiness` | `MergeReadiness` | yes | Readiness. |

### `MergeRequestListResponse` {#schema-mergerequestlistresponse}

A page of a project's merge requests.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `merge_requests` | array of `MergeRequestRecord` | no | Merge requests, most recently active first. |
| `count` | integer | yes | How many merge requests this page holds. |
| `total` | integer | yes | How many merge requests match the filter in all. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `MergeRequestMerge` {#schema-mergerequestmerge}

Merge an approved merge request.

Attributes:
    override_published_immutability: Tenant administrators only — merge into a line whose tip
        is published and immutable (forwarded to the merge path, which audits it).
    override_reason: The audit text for that override.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `override_published_immutability` | boolean | no | Override Published Immutability. |
| `override_reason` | string or null | no | Override Reason. |

### `MergeRequestReviewRequest` {#schema-mergerequestreviewrequest}

Request a review of the source branch's current tip.

Used when the branch moved on after the review was requested (``review-outdated``) or the
review was withdrawn. Any open review of an older tip is withdrawn first.

Attributes:
    reviewers: The reviewers to ask; omit to ask the previous review's reviewers again.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `reviewers` | array of string or null | no | Reviewers. |
