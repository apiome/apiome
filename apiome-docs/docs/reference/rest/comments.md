---
title: "Comments"
description: "REST endpoints tagged comments: 10 operations."
sidebar_position: 13
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `comments` · 10 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads` {#list-comment-threads-v1-tenants-tenant-slug-projects-project-ref-comment-threads-get}

**List a project's comment threads**

A page of the project's threads, most recently active first, each with its opening comment and its comment count.

Filters combine: `version` (revision id or version label) lists one version's threads — on its classes, properties, paths, and operations as well as on the version itself; `status` keeps `open`, `resolved`, or `orphaned` (threads whose element was deleted, each carrying the element's last-known `anchor_label`); `anchor_type` and `anchor_id` narrow to one kind of element or one element; `mentions_me=true` keeps threads with a comment mentioning the caller.

Requires `projects:view`.

Operation id: `list_comment_threads_v1_tenants__tenant_slug__projects__project_ref__comment_threads_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version` | query | string or null | no | Revision id or version label. |
| `status` | query | enum `"open"`, `"resolved"`, `"orphaned"` or null | no | `open`, `resolved`, or `orphaned`. |
| `anchor_type` | query | enum `"class"`, `"property"`, `"path"`, `"operation"`, `"version"` or null | no | Element kind. |
| `anchor_id` | query | string or null | no | Element id. |
| `mentions_me` | query | boolean | no | Only threads with a comment mentioning the caller. |
| `limit` | query | integer | no | Page size. |
| `offset` | query | integer | no | Threads to skip. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's comment threads. | `application/json` [`CommentThreadListResponse`](#schema-commentthreadlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads` {#open-comment-thread-v1-tenants-tenant-slug-projects-project-ref-comment-threads-post}

**Open a comment thread on an element**

Open a thread on one element of a version — a `class`, `property`, `path`, `operation`, or the `version` itself — together with its first comment.

The anchor is the element's **stable id**, never a canvas position, and the element must exist in the named version. For a `version` anchor `anchor_id` may be omitted; if given it must be that version's id.

`@name` tokens in the Markdown body are resolved **server-side** against the tenant's members (full email, email local part, or display name without spaces) and stored in the comment's `mentions`. A handle matching several members resolves to nobody.

Requires `projects:view` — read access to a project grants commenting. Rate limited per user (shared with replies).

Operation id: `open_comment_thread_v1_tenants__tenant_slug__projects__project_ref__comment_threads_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for open a comment thread on an element.

- `application/json` — [`CommentThreadCreate`](#schema-commentthreadcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for open a comment thread on an element. | `application/json` [`CommentThreadDetail`](#schema-commentthreaddetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}` {#read-comment-thread-v1-tenants-tenant-slug-projects-project-ref-comment-threads-thread-id-get}

**Read a comment thread**

A thread with all of its comments, oldest first.

Requires `projects:view`.

Operation id: `read_comment_thread_v1_tenants__tenant_slug__projects__project_ref__comment_threads__thread_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a comment thread. | `application/json` [`CommentThreadDetail`](#schema-commentthreaddetail) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}` {#delete-comment-thread-v1-tenants-tenant-slug-projects-project-ref-comment-threads-thread-id-delete}

**Delete a comment thread**

Delete a thread and every comment in it.

Requires `projects:view`, and the caller must be the member who opened the thread or a tenant administrator (`403 comment-forbidden` otherwise).

Operation id: `delete_comment_thread_v1_tenants__tenant_slug__projects__project_ref__comment_threads__thread_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a comment thread. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/comments` {#reply-to-comment-thread-v1-tenants-tenant-slug-projects-project-ref-comment-threads-thread-id-comments-post}

**Reply to a comment thread**

Add a Markdown comment to a thread. `@name` mentions are resolved server-side, as when opening a thread. A resolved thread accepts replies and stays resolved.

Requires `projects:view`. Rate limited per user (shared with opening threads).

Operation id: `reply_to_comment_thread_v1_tenants__tenant_slug__projects__project_ref__comment_threads__thread_id__comments_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for reply to a comment thread.

- `application/json` — [`CommentBody`](#schema-commentbody)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for reply to a comment thread. | `application/json` [`CommentRecord`](#schema-commentrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/comments/{comment_id}` {#edit-comment-v1-tenants-tenant-slug-projects-project-ref-comment-threads-thread-id-comments-comment-id-patch}

**Edit a comment**

Replace a comment's Markdown. Mentions are re-resolved from the new text and `edited_at` is stamped.

Requires `projects:view`, and the caller must be the comment's author or a tenant administrator (`403 comment-forbidden` otherwise).

Operation id: `edit_comment_v1_tenants__tenant_slug__projects__project_ref__comment_threads__thread_id__comments__comment_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `comment_id` | path | string | yes | Path parameter identifying the comment id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for edit a comment.

- `application/json` — [`CommentBody`](#schema-commentbody)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for edit a comment. | `application/json` [`CommentRecord`](#schema-commentrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/comments/{comment_id}` {#delete-comment-v1-tenants-tenant-slug-projects-project-ref-comment-threads-thread-id-comments-comment-id-delete}

**Delete a comment**

Delete a comment. Deleting a thread's **last** comment deletes the thread as well, which the response reports as `thread_deleted: true`.

Requires `projects:view`, and the caller must be the comment's author or a tenant administrator (`403 comment-forbidden` otherwise).

Operation id: `delete_comment_v1_tenants__tenant_slug__projects__project_ref__comment_threads__thread_id__comments__comment_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `comment_id` | path | string | yes | Path parameter identifying the comment id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete a comment. | `application/json` [`CommentDeletionResponse`](#schema-commentdeletionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/relink` {#relink-comment-thread-v1-tenants-tenant-slug-projects-project-ref-comment-threads-thread-id-relink-post}

**Relink an orphaned comment thread**

Re-attach an **orphaned** thread — one whose element was deleted — to another element of the thread's own version: a `class`, `property`, `path`, `operation`, or the `version` itself (for which `anchor_id` may be omitted).

The thread keeps every comment. It returns to `resolved` if it was resolved before its element was deleted, and to `open` otherwise; `anchor_label` and `orphaned_at` are cleared.

The target must exist in the thread's version (`404 comment-anchor-not-found`). A thread that is still anchored to a live element cannot be relinked (`409 comment-thread-not-orphaned`).

Requires `projects:view` — anyone taking part in the discussion may relink it.

Operation id: `relink_comment_thread_v1_tenants__tenant_slug__projects__project_ref__comment_threads__thread_id__relink_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for relink an orphaned comment thread.

- `application/json` — [`CommentThreadRelink`](#schema-commentthreadrelink)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for relink an orphaned comment thread. | `application/json` [`CommentThreadRecord`](#schema-commentthreadrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/reopen` {#reopen-comment-thread-v1-tenants-tenant-slug-projects-project-ref-comment-threads-thread-id-reopen-post}

**Reopen a comment thread**

Reopen a resolved thread, clearing its resolution. Reopening an open thread changes nothing. An orphaned thread must be relinked first (`409 comment-thread-orphaned`).

Requires `projects:view`.

Operation id: `reopen_comment_thread_v1_tenants__tenant_slug__projects__project_ref__comment_threads__thread_id__reopen_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for reopen a comment thread. | `application/json` [`CommentThreadRecord`](#schema-commentthreadrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads/{thread_id}/resolve` {#resolve-comment-thread-v1-tenants-tenant-slug-projects-project-ref-comment-threads-thread-id-resolve-post}

**Resolve a comment thread**

Mark a thread resolved, recording who resolved it and when. Resolving a thread that is already resolved changes nothing. An orphaned thread must be relinked first (`409 comment-thread-orphaned`).

Requires `projects:view` — anyone taking part in the discussion may resolve it.

Operation id: `resolve_comment_thread_v1_tenants__tenant_slug__projects__project_ref__comment_threads__thread_id__resolve_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `thread_id` | path | string | yes | Path parameter identifying the thread id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for resolve a comment thread. | `application/json` [`CommentThreadRecord`](#schema-commentthreadrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CommentBody` {#schema-commentbody}

A comment's Markdown text, for a reply or an edit.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `body` | string | yes | Body. |

### `CommentDeletionResponse` {#schema-commentdeletionresponse}

The outcome of deleting a comment.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | Always true; a comment that is not there is a 404. |
| `thread_deleted` | boolean | yes | True when this was the thread's last comment, so the thread was deleted too. |

### `CommentRecord` {#schema-commentrecord}

One stored comment.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | The comment id. |
| `thread_id` | string | yes | The thread the comment belongs to. |
| `author_id` | string or null | no | Who wrote it; null once that user has been deleted. |
| `author_name` | string or null | no | The author's display name. |
| `body` | string | yes | The comment text, as Markdown. |
| `mentions` | array of string | no | User ids of the tenant members the body's `@name` tokens resolved to, server-side, when the comment was last written. |
| `edited_at` | string (date-time) or null | no | When the comment was last edited; null when never edited. |
| `created_at` | string (date-time) | yes | When the comment was written. |

### `CommentThreadCreate` {#schema-commentthreadcreate}

Open a thread on an element, with its first comment.

Attributes:
    version: The version the element belongs to — its revision id or its version label.
    anchor_type: The kind of element.
    anchor_id: The element's stable id. Optional for a version anchor, where it can only be
        the version's own id.
    body: The first comment, as Markdown.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | string | yes | Version. |
| `anchor_type` | enum `"class"`, `"property"`, `"path"`, `"operation"`, `"version"` | yes | Anchor Type. |
| `anchor_id` | string or null | no | Anchor ID. |
| `body` | string | yes | Body. |

### `CommentThreadDetail` {#schema-commentthreaddetail}

A thread with every comment in it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `thread` | [`CommentThreadRecord`](#schema-commentthreadrecord) | yes | Thread. |
| `comments` | array of [`CommentRecord`](#schema-commentrecord) | no | The thread's comments, oldest first. |

### `CommentThreadListResponse` {#schema-commentthreadlistresponse}

A page of a project's threads.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `threads` | array of `CommentThreadSummary` | no | Threads, most recently active first. |
| `count` | integer | yes | How many threads this page holds. |
| `total` | integer | yes | How many threads match the filters in all. |
| `limit` | integer | yes | The page size used. |
| `offset` | integer | yes | The offset used. |

### `CommentThreadRecord` {#schema-commentthreadrecord}

One stored thread, without its comments.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | The thread id. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `version_id` | string | yes | The version (revision) whose element is discussed. |
| `anchor_type` | enum `"class"`, `"property"`, `"path"`, `"operation"`, `"version"` | yes | The kind of element the thread is anchored to. |
| `anchor_id` | string | yes | The anchored element's stable id. Equals `version_id` for a version anchor. On an orphaned thread it is the id of the element that was deleted. |
| `status` | enum `"open"`, `"resolved"`, `"orphaned"` | yes | `open`, `resolved`, or `orphaned` — the anchored element was deleted; relink the thread to re-attach it. |
| `anchor_label` | string or null | no | The deleted element's last-known label (`Customer`, `Customer.email`, `/customers`, `GET /customers`), captured when it was deleted. Set exactly while `orphaned`. |
| `orphaned_at` | string (date-time) or null | no | When the anchored element was deleted. Set exactly while `orphaned`. |
| `created_by` | string or null | no | Who opened the thread. |
| `created_by_name` | string or null | no | Their display name. |
| `resolved_by` | string or null | no | Who resolved it, when resolved. |
| `resolved_at` | string (date-time) or null | no | When it was resolved. |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) | yes | Last update timestamp (ISO 8601). |
| `last_activity_at` | string (date-time) | yes | The latest reply or status change. |
| `comment_count` | integer | no | How many comments the thread holds. |

### `CommentThreadRelink` {#schema-commentthreadrelink}

Re-attach an orphaned thread to another element of its own version.

Attributes:
    anchor_type: The kind of element to attach to.
    anchor_id: That element's stable id. Optional for a version anchor, where it can only be
        the thread's own version id.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `anchor_type` | enum `"class"`, `"property"`, `"path"`, `"operation"`, `"version"` | yes | Anchor Type. |
| `anchor_id` | string or null | no | Anchor ID. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
