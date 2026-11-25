---
title: "Presence"
description: "REST endpoints tagged presence: 7 operations."
sidebar_position: 76
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.676.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `presence` · 7 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/presence` {#get-presence-v1-tenants-tenant-slug-projects-project-ref-presence-get}

**Who is viewing a project, and what is locked**

Read the project's live viewers and element locks without announcing the caller.

Operation id: `get_presence_v1_tenants__tenant_slug__projects__project_ref__presence_get`

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
| 200 | Successful response for who is viewing a project, and what is locked. | `application/json` [`PresenceSnapshot`](#schema-presencesnapshot) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/presence/heartbeat` {#post-heartbeat-v1-tenants-tenant-slug-projects-project-ref-presence-heartbeat-post}

**Announce a tab and renew its locks**

Mark the tab present for the lease, renew the locks it holds, and read the snapshot.

``lost`` in the answer names held keys that another tab now holds — the notice a takeover
happened. Clients heartbeat at least twice per ``ttl_seconds``.

Operation id: `post_heartbeat_v1_tenants__tenant_slug__projects__project_ref__presence_heartbeat_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for announce a tab and renew its locks.

- `application/json` — [`HeartbeatRequest`](#schema-heartbeatrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for announce a tab and renew its locks. | `application/json` [`PresenceSnapshot`](#schema-presencesnapshot) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/presence/leave` {#post-leave-v1-tenants-tenant-slug-projects-project-ref-presence-leave-post}

**Leave a project (release presence and locks)**

Drop the tab's presence and every lock it holds. Safe to repeat.

Operation id: `post_leave_v1_tenants__tenant_slug__projects__project_ref__presence_leave_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for leave a project (release presence and locks).

- `application/json` — [`HeartbeatRequest`](#schema-heartbeatrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for leave a project (release presence and locks). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/projects/{project_ref}/presence/locks/{element_key}` {#put-lock-v1-tenants-tenant-slug-projects-project-ref-presence-locks-element-key-put}

**Lock an element**

Mark an element as being edited by ``session_id``. ``409 presence-lock-held`` if another live tab holds it.

Operation id: `put_lock_v1_tenants__tenant_slug__projects__project_ref__presence_locks__element_key__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `element_key` | path | string | yes | Path parameter identifying the element key segment. |
| `session_id` | query | string | yes | Required. Query parameter: session id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for lock an element. | `application/json` [`PresenceSnapshot`](#schema-presencesnapshot) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/projects/{project_ref}/presence/locks/{element_key}` {#delete-lock-v1-tenants-tenant-slug-projects-project-ref-presence-locks-element-key-delete}

**Unlock an element**

Release a lock the tab holds.

Operation id: `delete_lock_v1_tenants__tenant_slug__projects__project_ref__presence_locks__element_key__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `element_key` | path | string | yes | Path parameter identifying the element key segment. |
| `session_id` | query | string | yes | Required. Query parameter: session id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unlock an element. | `application/json` [`PresenceSnapshot`](#schema-presencesnapshot) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/presence/request-takeover/{element_key}` {#post-request-takeover-v1-tenants-tenant-slug-projects-project-ref-presence-request-takeover-element-key-post}

**Ask the holder to hand an element over**

Notify the holder (on their next heartbeat) that the caller wants the element.

Operation id: `post_request_takeover_v1_tenants__tenant_slug__projects__project_ref__presence_request_takeover__element_key__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `element_key` | path | string | yes | Path parameter identifying the element key segment. |
| `session_id` | query | string | yes | Required. Query parameter: session id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ask the holder to hand an element over. | `application/json` [`PresenceSnapshot`](#schema-presencesnapshot) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/presence/take-over/{element_key}` {#post-take-over-v1-tenants-tenant-slug-projects-project-ref-presence-take-over-element-key-post}

**Take an element over after asking**

Steal a lock once the grace period since the caller's request has passed; the previous holder sees it in ``lost``.

Operation id: `post_take_over_v1_tenants__tenant_slug__projects__project_ref__presence_take_over__element_key__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `element_key` | path | string | yes | Path parameter identifying the element key segment. |
| `session_id` | query | string | yes | Required. Query parameter: session id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for take an element over after asking. | `application/json` [`PresenceSnapshot`](#schema-presencesnapshot) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `HeartbeatRequest` {#schema-heartbeatrequest}

Renew a tab's presence and the locks it holds.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `session_id` | string | yes | Client-generated id of this tab (8-64 URL-safe chars). |
| `view` | string or null | no | Which view the tab is on. |
| `held` | array of string | no | Element keys this tab believes it holds. |

### `PresenceSnapshot` {#schema-presencesnapshot}

Everything a client needs to draw avatars and lock adornments.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `viewers` | array of `ViewerRecord` | no | Viewers. |
| `locks` | array of `LockRecord` | no | Locks. |
| `lost` | array of string | no | Element keys the caller's session claimed to hold that another session now holds — the previous holder's notice that a takeover happened. |
| `server_time` | string | yes | Server clock (ISO 8601), for client skew. |
| `ttl_seconds` | integer | yes | Heartbeat at least twice per this many seconds. |
