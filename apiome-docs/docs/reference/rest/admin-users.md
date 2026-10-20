---
title: "Admin users"
description: "REST endpoints tagged admin-users: 1 operation."
sidebar_position: 5
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.263.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `admin-users` · 1 operation

## `POST /v1/admin/users/{user_id}/two-factor/reset` {#admin-reset-two-factor-v1-admin-users-user-id-two-factor-reset-post}

**Admin Reset Two Factor**

Reset any user's two-factor, as the installation's super-admin.

Clears the user's authenticator and backup codes, forgets their trusted devices and ends
every one of their sessions. Their next sign-in needs the first factor only. The reset is
recorded in the authentication ledger with the reason given.

Args:
    user_id: The user to reset.
    payload: The reason, and the user's email typed out as confirmation.

Returns:
    What was cleared.

Operation id: `admin_reset_two_factor_v1_admin_users__user_id__two_factor_reset_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `user_id` | path | string | yes | Path parameter identifying the user id segment. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Request body** (required)

Request body for admin reset two factor.

- `application/json` — [`TwoFactorResetRequest`](#schema-twofactorresetrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for admin reset two factor. | `application/json` [`TwoFactorResetResult`](#schema-twofactorresetresult) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 404 | No user has that id. | — |
| 422 | Reason missing or out of range, or the confirmation does not match. | — |

## Schemas used {#schemas-used}

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
