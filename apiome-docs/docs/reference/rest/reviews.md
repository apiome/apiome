---
title: "Reviews"
description: "REST endpoints tagged reviews: 7 operations."
sidebar_position: 54
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `reviews` · 7 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews` {#list-reviews-v1-tenants-tenant-slug-projects-project-ref-reviews-get}

**List a project's reviews**

A page of the project's reviews, most recently active first, each with the tally of its current round.

Filters combine: `version` (revision id or version label), `state` (`in_review`, `approved`, `changes_requested`), and `open` (`true` for open reviews, `false` for withdrawn ones).

Requires `projects:view`.

Operation id: `list_reviews_v1_tenants__tenant_slug__projects__project_ref__reviews_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version` | query | string or null | no | Revision id or version label. |
| `state` | query | enum `"in_review"`, `"approved"`, `"changes_requested"` or null | no | Review state. |
| `open` | query | boolean or null | no | Open (`true`) or withdrawn (`false`) reviews only. |
| `limit` | query | integer | no | Page size. |
| `offset` | query | integer | no | Reviews to skip. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's reviews. | `application/json` [`ReviewListResponse`](#schema-reviewlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews` {#request-review-v1-tenants-tenant-slug-projects-project-ref-reviews-post}

**Request a review of a draft version**

Ask named reviewers whether a draft (unpublished) version is ready: `draft → in_review`, round 1, every reviewer `pending`.

Reviewers are tenant member user ids (at most 20, duplicates collapsed) and cannot include the requester (`400 review-self-review`). A published version cannot be reviewed (`409 review-version-published`), and a version has at most one open review (`409 review-already-open`). The round records the fingerprint of the version's current content.

Requires `versions:edit`.

Operation id: `request_review_v1_tenants__tenant_slug__projects__project_ref__reviews_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for request a review of a draft version.

- `application/json` — [`ReviewRequestCreate`](#schema-reviewrequestcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for request a review of a draft version. | `application/json` [`ReviewDetail`](#schema-reviewdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}` {#read-review-v1-tenants-tenant-slug-projects-project-ref-reviews-review-id-get}

**Read a review**

A review with its current round's reviewers, every earlier round's decisions (unchanged since they were recorded), and `spec_changed` — true when the version's content no longer matches the round being decided.

Requires `projects:view`.

Operation id: `read_review_v1_tenants__tenant_slug__projects__project_ref__reviews__review_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `review_id` | path | string | yes | Path parameter identifying the review id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a review. | `application/json` [`ReviewDetail`](#schema-reviewdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/decision` {#record-review-decision-v1-tenants-tenant-slug-projects-project-ref-reviews-review-id-decision-post}

**Record a review decision**

Record the caller's `approve` or `request_changes`, with an optional note, on the current round. Any `request_changes` moves the review to `changes_requested`; once every reviewer approved it is `approved`.

A decision is recorded once and never changes (`409 review-already-decided`); a round that is already decided takes no more (`409 review-not-in-review`); and a round whose content changed must be re-requested first (`409 review-spec-changed`).

Requires `projects:view`, and the caller must be a reviewer of the current round (`403 review-not-reviewer`).

Operation id: `record_review_decision_v1_tenants__tenant_slug__projects__project_ref__reviews__review_id__decision_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `review_id` | path | string | yes | Path parameter identifying the review id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record a review decision.

- `application/json` — [`ReviewDecisionCreate`](#schema-reviewdecisioncreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record a review decision. | `application/json` [`ReviewDetail`](#schema-reviewdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/re-request` {#re-request-review-v1-tenants-tenant-slug-projects-project-ref-reviews-review-id-re-request-post}

**Re-request a review after the spec changed**

Start the next round once the version's content has changed: every reviewer is asked again with a fresh `pending` decision, and the earlier rounds' decisions stay as history. Stale approvals never carry over to changed content.

`reviewers` replaces the reviewer list for the new round; omit it to ask the current round's reviewers again. An unchanged spec is a `409 review-spec-unchanged`.

Requires `versions:edit`.

Operation id: `re_request_review_v1_tenants__tenant_slug__projects__project_ref__reviews__review_id__re_request_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `review_id` | path | string | yes | Path parameter identifying the review id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for re-request a review after the spec changed.

- `application/json` — [`ReviewReRequest`](#schema-reviewrerequest) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for re-request a review after the spec changed. | `application/json` [`ReviewDetail`](#schema-reviewdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/withdraw` {#withdraw-review-v1-tenants-tenant-slug-projects-project-ref-reviews-review-id-withdraw-post}

**Withdraw a review**

Close an open review. Its state and decisions stay as recorded, and the version can be sent for review again.

Requires `versions:edit`, and the caller must be the member who requested the review or a tenant administrator (`403 review-forbidden`).

Operation id: `withdraw_review_v1_tenants__tenant_slug__projects__project_ref__reviews__review_id__withdraw_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `review_id` | path | string | yes | Path parameter identifying the review id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for withdraw a review. | `application/json` [`ReviewDetail`](#schema-reviewdetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/review` {#read-version-review-status-v1-tenants-tenant-slug-projects-project-ref-versions-version-ref-review-get}

**Read a version's review status**

Where a version stands in review: `draft` when it has no open review, otherwise the open review's state together with the review.

Requires `projects:view`.

Operation id: `read_version_review_status_v1_tenants__tenant_slug__projects__project_ref__versions__version_ref__review_get`

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
| 200 | Successful response for read a version's review status. | `application/json` [`VersionReviewStatus`](#schema-versionreviewstatus) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ReviewDecisionCreate` {#schema-reviewdecisioncreate}

Record a reviewer's decision.

Attributes:
    decision: ``approve`` or ``request_changes``.
    note: An optional explanation.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `decision` | enum `"approve"`, `"request_changes"` | yes | Decision. |
| `note` | string or null | no | Note. |

### `ReviewDetail` {#schema-reviewdetail}

A review with its reviewers, its decision history, and whether its content is stale.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `review` | `ReviewRecord` | yes | Review. |
| `reviewers` | array of `ReviewerDecisionRecord` | no | The current round's reviewers and their decisions. |
| `history` | array of `ReviewerDecisionRecord` | no | Every earlier round's rows, unchanged since they were recorded; oldest round first. |
| `spec_changed` | boolean or null | no | True when the version's content no longer matches the current round's `spec_fingerprint` — its decisions are stale and the review should be re-requested. Null for a withdrawn review. |

### `ReviewListResponse` {#schema-reviewlistresponse}

A page of a project's reviews.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `reviews` | array of `ReviewRecord` | no | Reviews, most recently active first. |
| `count` | integer | yes | How many reviews this page holds. |
| `total` | integer | yes | How many reviews match the filters in all. |
| `limit` | integer | yes | The page size used. |
| `offset` | integer | yes | The offset used. |

### `ReviewReRequest` {#schema-reviewrerequest}

Re-request a review after the spec changed.

Attributes:
    reviewers: The reviewers to ask in the new round; omit to ask the current round's
        reviewers again.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `reviewers` | array of string or null | no | Reviewers. |

### `ReviewRequestCreate` {#schema-reviewrequestcreate}

Request a review of a draft version.

Attributes:
    version: The version — its revision id or its version label.
    reviewers: User ids of the tenant members to ask; the requester cannot be one of them.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | string | yes | Version. |
| `reviewers` | array of string | yes | Reviewers. |

### `VersionReviewStatus` {#schema-versionreviewstatus}

Where one version stands in review.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `version_label` | string or null | no | Version Label. |
| `published` | boolean | yes | Whether the version is published; published versions cannot be reviewed. |
| `state` | enum `"draft"`, `"in_review"`, `"approved"`, `"changes_requested"` | yes | The open review's state, or `draft` when the version has no open review. |
| `review` | [`ReviewDetail`](#schema-reviewdetail) or null | no | The open review, when there is one. |
