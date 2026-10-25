---
title: "Cli login"
description: "REST endpoints tagged cli-login: 6 operations."
sidebar_position: 18
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.313.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `cli-login` · 6 operations

## `POST /v1/cli/login` {#start-cli-login-v1-cli-login-post}

**Start a CLI login**

Starts `apiome login`. Returns a secret `device_code` for the CLI to poll with, a `user_code` to show the person, and the apiome-ui page where they approve it. The login expires after 10 minutes. No authentication; rate-limited per client IP.

Operation id: `start_cli_login_v1_cli_login_post`

**Request body** (optional)

Request body for start a cli login.

- `application/json` — [`CliLoginStartRequest`](#schema-cliloginstartrequest) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for start a cli login. | `application/json` [`CliLoginStarted`](#schema-cliloginstarted) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/cli/login/key` {#revoke-cli-login-key-v1-cli-login-key-delete}

**Revoke this CLI login key**

Used by `apiome logout`: revokes the API key presented in `X-API-Key`, if `apiome login` created it. Any other key is refused with 409 — revoke it from the API Keys page.

Operation id: `revoke_cli_login_key_v1_cli_login_key_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for revoke this cli login key. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/cli/login/requests/{user_code}` {#read-cli-login-v1-cli-login-requests-user-code-get}

**Read a pending CLI login**

For the apiome-ui approve page: the pending login with this user code, and the signed-in person's workspaces with whether they may approve it there (`api_keys:create`). Requires a session token; 404 when no such login is waiting.

Operation id: `read_cli_login_v1_cli_login_requests__user_code__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `user_code` | path | string | yes | Path parameter identifying the user code segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a pending cli login. | `application/json` [`CliLoginRequestView`](#schema-cliloginrequestview) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/cli/login/requests/{user_code}/approve` {#approve-cli-login-v1-cli-login-requests-user-code-approve-post}

**Approve a CLI login**

Approves the pending login for one workspace. The CLI's next poll then receives a 14-day API key for that workspace, created by you. Requires a session token and `api_keys:create` in the workspace. 404 when the login is no longer waiting.

Operation id: `approve_cli_login_v1_cli_login_requests__user_code__approve_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `user_code` | path | string | yes | Path parameter identifying the user code segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Request body** (required)

Request body for approve a cli login.

- `application/json` — [`CliLoginApproveRequest`](#schema-cliloginapproverequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for approve a cli login. | `application/json` [`CliLoginApproved`](#schema-cliloginapproved) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/cli/login/requests/{user_code}/deny` {#deny-cli-login-v1-cli-login-requests-user-code-deny-post}

**Deny a CLI login**

Refuses the pending login; the CLI stops with `access_denied`. Requires a session token. 404 when the login is no longer waiting.

Operation id: `deny_cli_login_v1_cli_login_requests__user_code__deny_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `user_code` | path | string | yes | Path parameter identifying the user code segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for deny a cli login. | `application/json` [`CliLoginApproved`](#schema-cliloginapproved) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/cli/login/token` {#collect-cli-login-key-v1-cli-login-token-post}

**Collect a CLI login key**

Polled by `apiome login` with its `device_code`. Until the login is approved this answers `400` with `detail.error` set to `authorization_pending` (keep polling), `slow_down` (polling faster than `interval`), `access_denied`, `expired_token` or `invalid_grant`. Once approved it mints a workspace API key for the approving user, valid for 14 days, and returns it **once**; the login is then used up.

Operation id: `collect_cli_login_key_v1_cli_login_token_post`

**Request body** (required)

Request body for collect a cli login key.

- `application/json` — [`CliLoginTokenRequest`](#schema-clilogintokenrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for collect a cli login key. | `application/json` [`CliLoginKeyIssued`](#schema-cliloginkeyissued) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CliLoginApproveRequest` {#schema-cliloginapproverequest}

Body of ``POST /v1/cli/login/requests/{user_code}/approve``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_slug` | string | yes | URL-safe tenant slug used in path parameters. |

### `CliLoginApproved` {#schema-cliloginapproved}

The outcome of approving or denying a login.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `user_code` | string | yes | User Code. |
| `status` | string | yes | Status. |
| `tenant_slug` | string or null | no | URL-safe tenant slug used in path parameters. |

### `CliLoginKeyIssued` {#schema-cliloginkeyissued}

The key an approved login hands to the CLI — shown once.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `api_key` | string | yes | The secret. Send it as `X-API-Key`; it is never shown again. |
| `key_id` | string | yes | Key ID. |
| `key_prefix` | string | yes | Key Prefix. |
| `key_name` | string | yes | Key Name. |
| `tenant_slug` | string | yes | URL-safe tenant slug used in path parameters. |
| `tenant_name` | string | yes | Tenant Name. |
| `expires_at` | string (date-time) | yes | Expires At timestamp (ISO 8601). |

### `CliLoginRequestView` {#schema-cliloginrequestview}

What the approve page shows about a pending login.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `user_code` | string | yes | User Code. |
| `client_name` | string or null | no | Client Name. |
| `status` | string | yes | Status. |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
| `expires_at` | string (date-time) | yes | Expires At timestamp (ISO 8601). |
| `workspaces` | array of `CliLoginWorkspace` | yes | Workspaces. |

### `CliLoginStartRequest` {#schema-cliloginstartrequest}

Body of ``POST /v1/cli/login``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `client_name` | string or null | no | How the CLI names itself on the approve page, e.g. `apiome-cli on build-box`. |

### `CliLoginStarted` {#schema-cliloginstarted}

A started login (RFC 8628 §3.2 device authorization response).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `device_code` | string | yes | Secret the CLI polls with. Never show it to the person. |
| `user_code` | string | yes | Code the person compares in the browser, e.g. `KTXR-MWDB`. |
| `verification_uri` | string | yes | The approve page in apiome-ui. |
| `verification_uri_complete` | string | yes | The approve page with the code filled in. |
| `expires_in` | integer | yes | Seconds until the login expires. |
| `interval` | integer | yes | Seconds to wait between polls. |

### `CliLoginTokenRequest` {#schema-clilogintokenrequest}

Body of ``POST /v1/cli/login/token``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `device_code` | string | yes | Device Code. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
