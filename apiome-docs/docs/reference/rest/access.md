---
title: "Access"
description: "REST endpoints tagged access: 14 operations."
sidebar_position: 2
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `access` · 14 operations

## `GET /v1/access/{tenant_slug}/audit` {#list-audit-v1-access-tenant-slug-audit-get}

**List Audit**

List access-audit entries for the tenant, newest first, with an optional category filter.

Categories are `all`, `role`, `permission`, `member`, `admin` and `styleGuide`
(style-guide governance: create / edit / assign, GOV-1.6). An unknown value is treated
as `all`.

`since` is an optional ISO 8601 lower bound on `created_at` — what the UI's date range
sends, and what its CSV export sends back so the two agree (HIVE-5.5, #5308).

Each row carries `prev_hash` and `entry_hash`, its position in the tenant's hash chain.

Operation id: `list_audit_v1_access__tenant_slug__audit_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `filter` | query | string | no | Query parameter: filter. |
| `since` | query | string or null | no | Query parameter: since. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list audit. | `application/json` array of object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/access/{tenant_slug}/audit/export` {#export-audit-v1-access-tenant-slug-audit-export-get}

**Export Audit**

Export the tenant's access-audit ledger as CSV (SOC 2 / ISO 27001 access-review evidence).

Takes the same `filter` and `since` narrowing as the list endpoint, so the CSV holds the
rows the reader was looking at rather than a second, wider answer. Omitting both exports
the whole ledger, which is what every caller before HIVE-5.5 (#5308) got.

Operation id: `export_audit_v1_access__tenant_slug__audit_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `filter` | query | string | no | Query parameter: filter. |
| `since` | query | string or null | no | Query parameter: since. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export audit. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/access/{tenant_slug}/members` {#list-members-v1-access-tenant-slug-members-get}

**List Members**

List tenant members with their role, lifecycle status, and admin flag.

Operation id: `list_members_v1_access__tenant_slug__members_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list members. | `application/json` array of object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/access/{tenant_slug}/members` {#invite-member-v1-access-tenant-slug-members-post}

**Invite Member**

Invite an existing account into the tenant and optionally assign a role.

The invitee must already have an Apiome account (email-only invites that provision brand-new
accounts are a later SSO/SCIM ticket). The new membership is created ``active``.

Seat-gated (OLO-5.3, #4213): when the tenant's license seats
(``seats.max_users_per_tenant``) are all occupied by non-suspended members, the
request is refused with a structured 403 (code ``license-seats-exhausted``)
before any lookup or write happens — including re-invites of existing members,
which are inert at capacity anyway.

Operation id: `invite_member_v1_access__tenant_slug__members_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for invite member.

- `application/json` — [`MemberInviteRequest`](#schema-memberinviterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for invite member. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/access/{tenant_slug}/members/{user_id}` {#update-member-v1-access-tenant-slug-members-user-id-patch}

**Update Member**

Assign a member's role and/or change their lifecycle status (suspend / reinstate).

Operation id: `update_member_v1_access__tenant_slug__members__user_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `user_id` | path | string | yes | Path parameter identifying the user id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update member.

- `application/json` — [`MemberUpdateRequest`](#schema-memberupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update member. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/access/{tenant_slug}/members/{user_id}` {#offboard-member-v1-access-tenant-slug-members-user-id-delete}

**Offboard Member**

Offboard a member: remove membership, role assignment, and any tenant-admin row.

Operation id: `offboard_member_v1_access__tenant_slug__members__user_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `user_id` | path | string | yes | Path parameter identifying the user id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for offboard member. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/access/{tenant_slug}/members/{user_id}/resend-invite` {#resend-member-invite-v1-access-tenant-slug-members-user-id-resend-invite-post}

**Resend Member Invite**

Re-issue a member's outstanding invitation (HIVE-5.2, #5305).

Apiome does not mail invitations: :func:`invite_member` requires the invitee to hold an
account already, and a ``pending`` membership becomes ``active`` the next time they sign
in. Re-issuing therefore renews the invitation rather than re-sending a message — the
membership row is re-stamped so the members screen's "Invited {date}" reads freshly, and
the renewal is recorded in the access ledger as ``member.invite_resent`` so an access
review can see who kept an outstanding invitation alive.

Gated on ``members:create``, the same permission as issuing the invitation in the first
place. Consumes no seat: the pending membership already holds one, so the OLO-5.3
capacity guard is deliberately not consulted.

:raises HTTPException: 404 when the user has no membership in the tenant, 409 when their
    membership is not pending (there is no invitation outstanding to renew).

Operation id: `resend_member_invite_v1_access__tenant_slug__members__user_id__resend_invite_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `user_id` | path | string | yes | Path parameter identifying the user id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for resend member invite. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/access/{tenant_slug}/permissions/me` {#get-my-permissions-v1-access-tenant-slug-permissions-me-get}

**Get My Permissions**

Return the caller's effective ``resource:action`` permissions in this tenant.

Tenant administrators are reported as having every permission. The UI uses this to show/hide
mutating controls without hard-coding role names.

Operation id: `get_my_permissions_v1_access__tenant_slug__permissions_me_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get my permissions. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/access/{tenant_slug}/roles` {#list-roles-v1-access-tenant-slug-roles-get}

**List Roles**

List the tenant's roles (built-in first) with member counts and permission grids.

Operation id: `list_roles_v1_access__tenant_slug__roles_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list roles. | `application/json` array of object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/access/{tenant_slug}/roles` {#create-role-v1-access-tenant-slug-roles-post}

**Create Role**

Create a custom role with an initial permission grid (Owner/Admin only by default).

Operation id: `create_role_v1_access__tenant_slug__roles_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create role.

- `application/json` — [`RoleWriteRequest`](#schema-rolewriterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create role. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/access/{tenant_slug}/roles/{role_id}` {#get-role-v1-access-tenant-slug-roles-role-id-get}

**Get Role**

Fetch a single role with its permission grid.

Operation id: `get_role_v1_access__tenant_slug__roles__role_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `role_id` | path | string | yes | Role identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get role. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/access/{tenant_slug}/roles/{role_id}` {#update-role-v1-access-tenant-slug-roles-role-id-put}

**Update Role**

Update a role's name/description and replace its permission grid.

Built-in role names are immutable, but their permission grids may be tuned by an administrator.

Operation id: `update_role_v1_access__tenant_slug__roles__role_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `role_id` | path | string | yes | Role identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update role.

- `application/json` — [`RoleWriteRequest`](#schema-rolewriterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update role. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/access/{tenant_slug}/roles/{role_id}` {#delete-role-v1-access-tenant-slug-roles-role-id-delete}

**Delete Role**

Delete a custom role. Built-in roles cannot be deleted.

Operation id: `delete_role_v1_access__tenant_slug__roles__role_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `role_id` | path | string | yes | Role identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete role. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/access/{tenant_slug}/roles/{role_id}/duplicate` {#duplicate-role-v1-access-tenant-slug-roles-role-id-duplicate-post}

**Duplicate Role**

Clone a role's permission grid into a new custom role.

Operation id: `duplicate_role_v1_access__tenant_slug__roles__role_id__duplicate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `role_id` | path | string | yes | Role identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for duplicate role.

- `application/json` — [`RoleDuplicateRequest`](#schema-roleduplicaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for duplicate role. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MemberInviteRequest` {#schema-memberinviterequest}

Invite an existing account to the tenant and assign a role.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `email` | string | yes | Email. |
| `role_id` | string or null | no | Role ID. |

### `MemberUpdateRequest` {#schema-memberupdaterequest}

Change a member's role and/or lifecycle status.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `role_id` | string or null | no | Role ID. |
| `status` | string or null | no | Status. |

### `RoleDuplicateRequest` {#schema-roleduplicaterequest}

Clone an existing role under a new name.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |

### `RoleWriteRequest` {#schema-rolewriterequest}

Create/update payload for a role (name, description, full permission grid).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `permissions` | array of `PermissionCell` | no | Permissions. |
