---
title: "Teams"
description: "REST endpoints tagged teams: 7 operations."
sidebar_position: 85
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.285.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `teams` · 7 operations

## `GET /v1/tenants/{tenant_slug}/teams` {#list-tenant-teams-v1-tenants-tenant-slug-teams-get}

**List teams**

Every live team of the tenant, by name, with its owner links and member count. Deleted teams are not listed.

Requires `teams:view`.

Operation id: `list_tenant_teams_v1_tenants__tenant_slug__teams_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list teams. | `application/json` [`TeamListResponse`](#schema-teamlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/teams` {#create-tenant-team-v1-tenants-tenant-slug-teams-post}

**Create a team**

Create a team. The `slug` is derived from `name` when omitted and cannot be changed afterwards — gateway tags (`owner:<slug>`) and the `x-apiome-owner` extension name teams by it. `chat_url`, `oncall_url` and `docs_url` must be absolute http(s) URLs.

Audited as `team.create`. Requires `teams:create`.

Operation id: `create_tenant_team_v1_tenants__tenant_slug__teams_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create a team.

- `application/json` — [`TeamInput`](#schema-teaminput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a team. | `application/json` [`TeamRecord`](#schema-teamrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/teams/{team_slug}` {#read-tenant-team-v1-tenants-tenant-slug-teams-team-slug-get}

**Read a team**

One live team with its members, leads first.

Requires `teams:view`.

Operation id: `read_tenant_team_v1_tenants__tenant_slug__teams__team_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `team_slug` | path | string | yes | Path parameter identifying the team slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a team. | `application/json` [`TeamRecord`](#schema-teamrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/teams/{team_slug}` {#patch-tenant-team-v1-tenants-tenant-slug-teams-team-slug-patch}

**Update a team**

Change a team's name, description or owner links. Omitted fields are left alone; `null` clears an optional field. The slug is not updatable.

Audited as `team.update` with each changed field's old and new value. Requires `teams:edit`.

Operation id: `patch_tenant_team_v1_tenants__tenant_slug__teams__team_slug__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `team_slug` | path | string | yes | Path parameter identifying the team slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update a team.

- `application/json` — [`TeamPatch`](#schema-teampatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update a team. | `application/json` [`TeamRecord`](#schema-teamrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/teams/{team_slug}` {#delete-tenant-team-v1-tenants-tenant-slug-teams-team-slug-delete}

**Delete a team**

Soft-delete a team: it disappears from reads and its slug becomes free. A team that still owns entities is refused with **409** `team-owns-entities` and the `owned_count`, unless `reassign_to` names another live team to take them over.

Audited as `team.delete`. Requires `teams:delete`.

Operation id: `delete_tenant_team_v1_tenants__tenant_slug__teams__team_slug__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `team_slug` | path | string | yes | Path parameter identifying the team slug segment. |
| `reassign_to` | query | string or null | no | Slug of the live team that takes over the deleted team's entities. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete a team. | `application/json` [`TeamDeleteResponse`](#schema-teamdeleteresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/teams/{team_slug}/activity` {#read-tenant-team-activity-v1-tenants-tenant-slug-teams-team-slug-activity-get}

**Read a team's ownership and routed findings**

What the team owns (confirmed owners only, by kind), how many entities suggest it, how many owner-finding notifications routed to it the caller has not read, and the findings routed to it in the last 30 days — one row per event, however many members it reached.

Requires `teams:view`.

Operation id: `read_tenant_team_activity_v1_tenants__tenant_slug__teams__team_slug__activity_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `team_slug` | path | string | yes | Path parameter identifying the team slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a team's ownership and routed findings. | `application/json` [`TeamActivityResponse`](#schema-teamactivityresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/teams/{team_slug}/members` {#put-tenant-team-members-v1-tenants-tenant-slug-teams-team-slug-members-put}

**Replace a team's members**

Set the team's complete membership; anyone not listed is removed, and an empty list empties the team. Each member is a `user_id` with a `role` of `lead` or `member`. Every user must be a member of the tenant — otherwise **422** `team-member-not-in-tenant` names them and nothing changes. A user who later leaves the tenant leaves every team automatically.

Audited as `team.members.replace` with who was added, removed or changed role. Requires `teams:edit`.

Operation id: `put_tenant_team_members_v1_tenants__tenant_slug__teams__team_slug__members_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `team_slug` | path | string | yes | Path parameter identifying the team slug segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace a team's members.

- `application/json` — [`TeamMembersInput`](#schema-teammembersinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace a team's members. | `application/json` [`TeamRecord`](#schema-teamrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `TeamActivityResponse` {#schema-teamactivityresponse}

A team page's ownership and routing picture (CDG-2.4).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `team_id` | string | yes | Team ID. |
| `owned` | array of `OwnedEntity` | no | Confirmed ownership, by kind then name. |
| `owned_counts` | map of integer | no | Owned entities per kind. |
| `suggested_count` | integer | yes | Entities that suggest this team as owner. |
| `open_findings` | integer | yes | The caller's unread owner-finding notifications routed to this team. |
| `events` | array of `RoutedEvent` | no | Findings routed to the team in the last 30 days, newest first. |

### `TeamDeleteResponse` {#schema-teamdeleteresponse}

What a delete did.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string | yes | The deleted team's slug (now free for reuse). |
| `owned_count` | integer | yes | How many entities the team owned when it was deleted. |
| `reassigned_to` | string or null | no | The team that took over those entities, when any moved. |

### `TeamInput` {#schema-teaminput}

A team to create.

Attributes:
    slug: The handle; derived from ``name`` when omitted. Not editable afterwards.
    name: The display name.
    description: Free text about what the team does.
    contact_email: A shared mailbox.
    chat_url: Link to the team's chat channel.
    oncall_url: Link to the team's on-call schedule.
    docs_url: Link to the team's documentation.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string or null | no | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `contact_email` | string or null | no | Contact Email. |
| `chat_url` | string or null | no | Chat URL. |
| `oncall_url` | string or null | no | Oncall URL. |
| `docs_url` | string or null | no | Docs URL. |

### `TeamListResponse` {#schema-teamlistresponse}

Every live team of the tenant.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `teams` | array of [`TeamRecord`](#schema-teamrecord) | no | The teams, by name. |
| `count` | integer | yes | How many teams were returned. |

### `TeamMembersInput` {#schema-teammembersinput}

The complete membership of a team; it replaces whatever was there.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `members` | array of `TeamMemberInput` | no | Members. |

### `TeamPatch` {#schema-teampatch}

A partial update. Omitted fields are left alone; ``null`` clears an optional field.

The slug is deliberately absent: it is the handle tags and extensions name.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `contact_email` | string or null | no | Contact Email. |
| `chat_url` | string or null | no | Chat URL. |
| `oncall_url` | string or null | no | Oncall URL. |
| `docs_url` | string or null | no | Docs URL. |

### `TeamRecord` {#schema-teamrecord}

A stored team.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `contact_email` | string or null | no | Contact Email. |
| `chat_url` | string or null | no | Chat URL. |
| `oncall_url` | string or null | no | Oncall URL. |
| `docs_url` | string or null | no | Docs URL. |
| `member_count` | integer | no | How many members the team has. |
| `created_by` | string or null | no | Created By. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |
| `members` | array of `TeamMember` or null | no | The members, leads first; present on single-team reads and member writes. |
