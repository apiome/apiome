---
title: "Notifications"
description: "REST endpoints tagged notifications: 3 operations."
sidebar_position: 41
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `notifications` · 3 operations

## `GET /v1/tenants/{tenant_slug}/notifications` {#list-notifications-v1-tenants-tenant-slug-notifications-get}

**List the caller's notifications**

A page of the caller's own inbox in this tenant, newest first. Each row carries the event's `type`, the `payload` its sentence and deep link need, who caused it, and the project and version it points at.

Filters combine: `unread` (only what has not been read) and `type`.

Reading the list never marks anything read. Requires only authentication — an inbox is the caller's own, so there is no permission to grant.

Operation id: `list_notifications_v1_tenants__tenant_slug__notifications_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `unread` | query | boolean | no | Only unread notifications. |
| `type` | query | enum `"mention"`, `"review_requested"`, `"review_decision"`, `"thread_resolved"`, `"version_published"` or null | no | Only this event type. |
| `limit` | query | integer | no | Page size. |
| `offset` | query | integer | no | Notifications to skip. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the caller's notifications. | `application/json` [`NotificationListResponse`](#schema-notificationlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/notifications/read` {#mark-notifications-read-v1-tenants-tenant-slug-notifications-read-post}

**Mark the caller's notifications read**

Mark the notifications named by `ids` read, or the caller's whole inbox with `{"all": true}`. Marking is idempotent: a notification that was already read is not counted again, and an id that is not the caller's own simply matches nothing.

Answers with how many rows changed and the unread count that follows, so a client can update its badge without a second call.

Requires only authentication.

Operation id: `mark_notifications_read_v1_tenants__tenant_slug__notifications_read_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for mark the caller's notifications read.

- `application/json` — [`MarkReadRequest`](#schema-markreadrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for mark the caller's notifications read. | `application/json` [`MarkReadResponse`](#schema-markreadresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/notifications/unread-count` {#unread-notification-count-v1-tenants-tenant-slug-notifications-unread-count-get}

**Count the caller's unread notifications**

How many notifications the caller has not read in this tenant, in total and per type (every type is reported, zeroes included). This is the bell badge.

Requires only authentication.

Operation id: `unread_notification_count_v1_tenants__tenant_slug__notifications_unread_count_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for count the caller's unread notifications. | `application/json` [`UnreadCount`](#schema-unreadcount) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MarkReadRequest` {#schema-markreadrequest}

Mark some — or all — of the caller's notifications read.

Attributes:
    ids: The notifications to mark. Ignored when ``all`` is set.
    all: Mark every unread notification of the caller in this tenant.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ids` | array of string or null | no | Notification ids to mark read. |
| `all` | boolean | no | Mark the caller's whole inbox read instead. |

### `MarkReadResponse` {#schema-markreadresponse}

What a mark-read call changed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `updated` | integer | yes | How many notifications went from unread to read. |
| `unread` | [`UnreadCount`](#schema-unreadcount) | yes | The caller's unread count after the change. |

### `NotificationListResponse` {#schema-notificationlistresponse}

A page of the caller's inbox.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `notifications` | array of `NotificationRecord` | no | Notifications, newest first. |
| `count` | integer | yes | How many notifications this page holds. |
| `total` | integer | yes | How many match the filters in all. |
| `limit` | integer | yes | The page size used. |
| `offset` | integer | yes | The offset used. |

### `UnreadCount` {#schema-unreadcount}

How much of the caller's inbox is unread — the bell badge (COL-3.2).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `total` | integer | yes | Unread notifications in this tenant. |
| `by_type` | map of integer | no | Unread count per type; every type is present, zeroes included. |
