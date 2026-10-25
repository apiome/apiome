---
title: "Admin signup policy"
description: "REST endpoints tagged admin-signup-policy: 3 operations."
sidebar_position: 4
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.313.3**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `admin-signup-policy` · 3 operations

## `GET /v1/admin/signup-policy` {#get-signup-policy-v1-admin-signup-policy-get}

**Get Signup Policy**

Read the installation sign-up policy (SGN-1.4).

Reads the stored row directly rather than the cached policy, so the admin console always shows
what is actually stored.

Returns:
    The effective policy, with ``source`` telling a stored policy from the env fallback.

Operation id: `get_signup_policy_v1_admin_signup_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get signup policy. | `application/json` [`SignupPolicyView`](#schema-signuppolicyview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/admin/signup-policy` {#update-signup-policy-v1-admin-signup-policy-put}

**Update Signup Policy**

Store, change or clear the installation sign-up policy (SGN-1.4).

The change is audited and applies to the next sign-up on this instance; other instances apply
it within the policy cache lifetime. It gates creating an account only — existing users keep
signing in under every mode.

Args:
    payload: The new policy, or ``mode: null`` to clear the stored one.

Returns:
    The effective policy after the write.

Raises:
    HTTPException: ``422`` with a structured body when the mode is not one of the three modes
        (``invalid_mode``) or a domain entry is malformed (``invalid_email_domain``).

Operation id: `update_signup_policy_v1_admin_signup_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Request body** (required)

Request body for update signup policy.

- `application/json` — [`SignupPolicyUpdateRequest`](#schema-signuppolicyupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update signup policy. | `application/json` [`SignupPolicyView`](#schema-signuppolicyview) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 422 | Unknown mode, or an invalid or over-long email-domain list. | — |

## `GET /v1/admin/signup-policy/blocked-attempts` {#list-blocked-signup-attempts-v1-admin-signup-policy-blocked-attempts-get}

**List Blocked Signup Attempts**

List the sign-up attempts an abuse guard refused, newest first (SGN-1.5, #5654).

Reads the failed ``sign_up`` rows of ``apiome.auth_events`` that carry a ``detail.guard``.
Sign-up happens before any workspace exists, so this is an installation view for super-admins,
not part of a workspace's access audit.

Args:
    limit: How many attempts to return (1–200).

Returns:
    The attempts, newest first.

Operation id: `list_blocked_signup_attempts_v1_admin_signup_policy_blocked_attempts_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `limit` | query | integer | no | How many attempts to return, newest first. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list blocked signup attempts. | `application/json` [`BlockedSignupAttemptList`](#schema-blockedsignupattemptlist) |
| 401 | No super-admin session presented. | — |
| 403 | Super-admin session invalid or expired. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `BlockedSignupAttemptList` {#schema-blockedsignupattemptlist}

Payload of ``GET /v1/admin/signup-policy/blocked-attempts``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `attempts` | array of `BlockedSignupAttempt` | no | Attempts. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SignupPolicyUpdateRequest` {#schema-signuppolicyupdaterequest}

Body of ``PUT /v1/admin/signup-policy``.

The policy is replaced as a whole: send the mode and the full domain list every time.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | string or null | yes | 'open', 'invite_only' or 'closed' to store the policy; null to clear the stored policy so the installation reverts to AUTH_SIGNUP_DISABLED. |
| `allowed_email_domains` | array of string | no | Email domains allowed to sign up while the mode is 'open' (e.g. 'example.com'). At most 200; matched exactly, so list subdomains separately. Ignored when mode is null. |
| `blocked_email_domains` | array of string | no | Extra email domains refused for email sign-up (e.g. 'throwaway.example'), on top of the bundled disposable-email list. At most 1000; a listed domain also blocks its subdomains. Omitted ⇒ none. Ignored when mode is null. |

### `SignupPolicyView` {#schema-signuppolicyview}

The installation sign-up policy — the shape both GET and PUT return.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | string | yes | Effective mode: 'open', 'invite_only' or 'closed'. |
| `allowed_email_domains` | array of string | no | Email domains allowed to sign up while the mode is 'open'. Empty means any domain. |
| `blocked_email_domains` | array of string | no | Extra email domains refused for email sign-up, on top of the disposable-email list the UI bundles. Empty when none are stored. Never applied to provider sign-up. |
| `source` | string | yes | 'db' when the policy is stored in the database; 'env' when none is stored and AUTH_SIGNUP_DISABLED governs. |
| `env_mode` | string | yes | The mode the env fallback gives ('closed' when AUTH_SIGNUP_DISABLED is true, else 'open') — what applies if the stored policy is cleared. |
| `updated_at` | string (date-time) or null | no | When the stored policy was last changed; null when none is stored. |
| `updated_by` | string or null | no | Who last changed the stored policy; null when none is stored. |
