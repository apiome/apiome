---
title: "Access"
description: "REST endpoints tagged access: 17 operations."
sidebar_position: 2
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.313.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `access` · 17 operations

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

## `POST /v1/access/{tenant_slug}/members/{user_id}/two-factor/reset` {#member-reset-two-factor-v1-access-tenant-slug-members-user-id-two-factor-reset-post}

**Member Reset Two Factor**

Reset a member's two-factor, as an owner of the workspace.

Allowed only for an **owner**, only for an **active member** of this workspace, and only when
that member belongs to **no other workspace** — two-factor protects the whole account, so a
member shared with another workspace is left to the installation's super-admin. An owner
cannot reset their own two-factor here; they manage it on their Profile page.

Recorded in the authentication ledger and in this workspace's access audit, with the reason.

Args:
    tenant_slug: The workspace the caller is acting in.
    user_id: The member to reset.
    payload: The reason, and the member's email typed out as confirmation.

Returns:
    What was cleared.

Operation id: `member_reset_two_factor_v1_access__tenant_slug__members__user_id__two_factor_reset_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `user_id` | path | string | yes | Path parameter identifying the user id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for member reset two factor.

- `application/json` — [`TwoFactorResetRequest`](#schema-twofactorresetrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for member reset two factor. | `application/json` [`TwoFactorResetResult`](#schema-twofactorresetresult) |
| 403 | The caller is not an owner of this workspace (owner_required), or called with an API key (session_required). | — |
| 404 | The user is not an active member of this workspace. | — |
| 409 | The member belongs to another workspace as well (multi_tenant_member), or the caller tried to reset their own two-factor (self_reset). | — |
| 422 | Reason missing or out of range, or the confirmation does not match. | — |

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

## `GET /v1/tenants/{tenant_slug}/two-factor-policy` {#get-two-factor-policy-v1-tenants-tenant-slug-two-factor-policy-get}

**Read the two-factor policy**

Whether every member must turn on two-factor authentication, the grace period in days, when the requirement was turned on, and how many active members have two-factor (`enabled`), are still inside their grace period (`grace`) or are past it (`overdue`).

A member's deadline is the later of the requirement being turned on and the member joining, plus the grace period.

Requires `members:view`.

Operation id: `get_two_factor_policy_v1_tenants__tenant_slug__two_factor_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the two-factor policy. | `application/json` [`TwoFactorPolicy`](#schema-twofactorpolicy) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/two-factor-policy` {#put-two-factor-policy-v1-tenants-tenant-slug-two-factor-policy-put}

**Change the two-factor policy**

Set `require_two_factor` and/or `grace_days` (0–90). Omitted fields are left alone. Turning the requirement on starts every member's grace period; turning it off and on again restarts them. Members past their deadline are asked to set up two-factor before they can use the app; API keys are unaffected.

Audited as `two_factor_policy.update`. Requires `members:edit`.

Operation id: `put_two_factor_policy_v1_tenants__tenant_slug__two_factor_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change the two-factor policy.

- `application/json` — [`TwoFactorPolicyInput`](#schema-twofactorpolicyinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change the two-factor policy. | `application/json` [`TwoFactorPolicy`](#schema-twofactorpolicy) |
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

### `TwoFactorPolicy` {#schema-twofactorpolicy}

The tenant's two-factor policy.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `require_two_factor` | boolean | yes | When true, every member must turn on two-factor. |
| `grace_days` | integer | yes | Days a member without two-factor may keep working after the policy is on or they join. |
| `required_since` | string or null | no | When the policy was last turned on (ISO-8601); null while off. |
| `compliance` | `TwoFactorCompliance` | no | Active members by state; all zero while the policy is off. |

### `TwoFactorPolicyInput` {#schema-twofactorpolicyinput}

A policy change. Omitted fields are left alone.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `require_two_factor` | boolean or null | no | Require Two Factor. |
| `grace_days` | integer or null | no | Grace Days. |

### `TwoFactorResetRequest` {#schema-twofactorresetrequest}

Why the factor is being reset, and proof the caller means this user.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `reason` | string | yes | Why the two-factor is being reset (10–500 characters). Stored in the audit trail. |
| `confirm` | string | yes | The target user's email address, typed out to confirm the reset. |

### `TwoFactorResetResult` {#schema-twofactorresetresult}

What a reset cleared.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` | string | yes | The user whose two-factor was reset. |
| `email` | string or null | no | That user's email address. |
| `name` | string or null | no | That user's display name. |
| `had_two_factor` | boolean | yes | Whether the user had two-factor on before the reset. |
| `sessions_revoked` | integer | yes | How many of the user's sessions were ended. |
| `trusted_devices_revoked` | integer | yes | How many trusted-device records were removed. |
