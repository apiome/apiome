---
title: "Portal feedback"
description: "REST endpoints tagged portal-feedback: 5 operations."
sidebar_position: 72
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.632.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `portal-feedback` · 5 operations

## `GET /v1/portal/{tenant_slug}/feedback/{project_slug}/{version}/threads` {#list-my-feedback-v1-portal-tenant-slug-feedback-project-slug-version-threads-get}

**List my feedback on a published version**

The signed-in reader's own feedback threads on a published, public version, most recently active first, each with every message — the reader's and the team's replies (`from_team`).

Requires a reader session for this tenant (`Authorization: Reader <token>`); otherwise `401 portal-session-invalid`. `404 feedback-version-not-found` for an unknown, unpublished or private version.

Operation id: `list_my_feedback_v1_portal__tenant_slug__feedback__project_slug___version__threads_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list my feedback on a published version. | `application/json` [`FeedbackThreadList`](#schema-feedbackthreadlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/portal/{tenant_slug}/feedback/{project_slug}/{version}/threads` {#send-feedback-v1-portal-tenant-slug-feedback-project-slug-version-threads-post}

**Send feedback on a published version**

Open a feedback thread on the whole version (`target: "version"`) or on one operation (`target: "operation"` with its `method` and `path` exactly as published). The owning team sees it in its Discussion panel tagged `consumer`.

`@name` tokens are **not** resolved — feedback never notifies a team member directly.

Requires a reader session for this tenant. `404 feedback-operation-not-found` for an operation the version does not have. Rate limited per reader (`429 comment-rate-limited`).

Operation id: `send_feedback_v1_portal__tenant_slug__feedback__project_slug___version__threads_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Request body** (required)

Request body for send feedback on a published version.

- `application/json` — [`FeedbackCreate`](#schema-feedbackcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for send feedback on a published version. | `application/json` [`FeedbackThread`](#schema-feedbackthread) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/portal/{tenant_slug}/feedback/{project_slug}/{version}/threads/{thread_id}/comments` {#reply-to-my-feedback-v1-portal-tenant-slug-feedback-project-slug-version-threads-thread-id-comments-post}

**Reply in my feedback thread**

Add a message to one of the reader's own feedback threads. A resolved thread accepts it and stays resolved. Another reader's thread is `404 feedback-thread-not-found`.

Requires a reader session for this tenant. Rate limited per reader.

Operation id: `reply_to_my_feedback_v1_portal__tenant_slug__feedback__project_slug___version__threads__thread_id__comments_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Request body** (required)

Request body for reply in my feedback thread.

- `application/json` — [`FeedbackReply`](#schema-feedbackreply)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for reply in my feedback thread. | `application/json` [`FeedbackThread`](#schema-feedbackthread) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/portal/{tenant_slug}/feedback/{project_slug}/{version}/threads/{thread_id}/reopen` {#reopen-my-feedback-v1-portal-tenant-slug-feedback-project-slug-version-threads-thread-id-reopen-post}

**Reopen my feedback thread**

Reopen one of the reader's own resolved threads. Reopening an open thread changes nothing. Requires a reader session for this tenant.

Operation id: `reopen_my_feedback_v1_portal__tenant_slug__feedback__project_slug___version__threads__thread_id__reopen_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for reopen my feedback thread. | `application/json` [`FeedbackThread`](#schema-feedbackthread) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/portal/{tenant_slug}/feedback/{project_slug}/{version}/threads/{thread_id}/resolve` {#resolve-my-feedback-v1-portal-tenant-slug-feedback-project-slug-version-threads-thread-id-resolve-post}

**Resolve my feedback thread**

Mark one of the reader's own threads resolved, as the team can from the Discussion panel. Resolving a resolved thread changes nothing. Requires a reader session for this tenant.

Operation id: `resolve_my_feedback_v1_portal__tenant_slug__feedback__project_slug___version__threads__thread_id__resolve_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for resolve my feedback thread. | `application/json` [`FeedbackThread`](#schema-feedbackthread) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `FeedbackCreate` {#schema-feedbackcreate}

Open a feedback thread.

Attributes:
    target: ``version`` for the whole API, ``operation`` for one operation.
    method: The operation's HTTP method (``operation`` only).
    path: The operation's path template (``operation`` only).
    body: The first message, as Markdown.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target` | enum `"version"`, `"operation"` | yes | Target. |
| `method` | string or null | no | Method. |
| `path` | string or null | no | Path. |
| `body` | string | yes | Body. |

### `FeedbackReply` {#schema-feedbackreply}

A message added to a feedback thread.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `body` | string | yes | Body. |

### `FeedbackThread` {#schema-feedbackthread}

A reader's feedback thread with every message in it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `target` | enum `"version"`, `"operation"` | yes | `version` — the whole API; `operation` — one operation. |
| `operation` | `FeedbackOperation` or null | no | The operation, for an `operation` target that still exists. |
| `status` | enum `"open"`, `"resolved"` | yes | `open` or `resolved` (by the team or the reader). |
| `resolved_at` | string (date-time) or null | no | Resolved At timestamp (ISO 8601). |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
| `last_activity_at` | string (date-time) | yes | Last Activity At timestamp (ISO 8601). |
| `comments` | array of `FeedbackComment` | no | Oldest first. |

### `FeedbackThreadList` {#schema-feedbackthreadlist}

The reader's own feedback threads on one version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `threads` | array of [`FeedbackThread`](#schema-feedbackthread) | no | Most recently active first. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
