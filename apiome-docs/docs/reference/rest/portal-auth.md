---
title: "Portal auth"
description: "REST endpoints tagged portal-auth: 4 operations."
sidebar_position: 71
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.629.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `portal-auth` · 4 operations

## `POST /v1/portal/{tenant_slug}/auth/exchange` {#exchange-magic-link-v1-portal-tenant-slug-auth-exchange-post}

**Exchange a sign-in link for a reader session**

Trade a magic-link token for a reader session. The token is burned: a second exchange is `410 portal-token-used`, an exchange after 15 minutes `410 portal-token-expired`, and an unknown or malformed token `400 portal-token-invalid`.

The session token is returned **once**. It is bound to this tenant and is sent back as `Authorization: Reader <token>`; it is accepted only by the `portal-auth` and `browse` routes. The request's `User-Agent` is reduced to a browser family before it is stored.

No authentication — the token is the credential.

Operation id: `exchange_magic_link_v1_portal__tenant_slug__auth_exchange_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `user-agent` | header | string or null | no | Header parameter: User Agent. |

**Request body** (required)

Request body for exchange a sign-in link for a reader session.

- `application/json` — [`TokenExchange`](#schema-tokenexchange)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for exchange a sign-in link for a reader session. | `application/json` [`ReaderSessionGrant`](#schema-readersessiongrant) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/portal/{tenant_slug}/auth/magic-link` {#request-magic-link-v1-portal-tenant-slug-auth-magic-link-post}

**Send a reader sign-in link**

Mail a one-time sign-in link for the tenant's Browse portal. The link expires in 15 minutes and works once.

An address with no account gets one (a password-less user) and an `invited` reader membership, when the installation sign-up policy allows new accounts; a second request for the same address reuses both.

**Always `202`** for a well-formed request: the response never says whether a link was sent, so it cannot be used to discover accounts. `422` for a malformed address or a `return_to` that is not a path inside Browse. Budgeted per client address and per email address (`429 portal-rate-limited` with `Retry-After`).

No authentication.

Operation id: `request_magic_link_v1_portal__tenant_slug__auth_magic_link_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |

**Request body** (required)

Request body for send a reader sign-in link.

- `application/json` — [`MagicLinkRequest`](#schema-magiclinkrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for send a reader sign-in link. | `application/json` [`MagicLinkAccepted`](#schema-magiclinkaccepted) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/portal/{tenant_slug}/auth/me` {#read-me-v1-portal-tenant-slug-auth-me-get}

**The signed-in reader**

The reader behind `Authorization: Reader <token>`: their address, the tenant the session is bound to, and when the session ends.

`401 portal-session-invalid` for a missing, expired or revoked session, a session for another tenant, or a reader whose membership was revoked.

Operation id: `read_me_v1_portal__tenant_slug__auth_me_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the signed-in reader. | `application/json` [`ReaderProfile`](#schema-readerprofile) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/portal/{tenant_slug}/auth/sign-out` {#sign-out-v1-portal-tenant-slug-auth-sign-out-post}

**Sign a reader out**

Revoke the reader session in `Authorization: Reader <token>`. The session is refused from the next request on. Idempotent: an unknown or already revoked session is also `204`.

Operation id: `sign_out_v1_portal__tenant_slug__auth_sign_out_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for sign a reader out. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MagicLinkAccepted` {#schema-magiclinkaccepted}

The answer to every well-formed magic-link request.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `accepted` | `true` | no | Always true. Whether a link was actually sent is never revealed, so the answer cannot be used to learn who has an account. |
| `expires_in_minutes` | integer | no | How long a link is valid once it arrives. |

### `MagicLinkRequest` {#schema-magiclinkrequest}

Ask for a sign-in link.

Attributes:
    email: The reader's address.
    return_to: A Browse path to land on after signing in.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `email` | string | yes | The reader's email address. |
| `return_to` | string or null | no | A path inside Browse to return to after signing in (for example `/tenant/acme`). |

### `ReaderProfile` {#schema-readerprofile}

The signed-in reader.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` | string | yes | User ID. |
| `email` | string | yes | Email. |
| `name` | string or null | no | Human-readable name. |
| `tenant_slug` | string | yes | URL-safe tenant slug used in path parameters. |
| `tenant_name` | string or null | no | Tenant Name. |
| `membership_status` | enum `"invited"`, `"active"`, `"revoked"` | yes | Membership Status. |
| `session_expires_at` | string (date-time) | yes | When the current session ends. |

### `ReaderSessionGrant` {#schema-readersessiongrant}

A new reader session.

The token is returned **once**. Browse stores it in an ``HttpOnly`` cookie and forwards it as
``Authorization: Reader <token>``; it is never shown to the reader.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `session_token` | string | yes | The opaque session token. Returned once; store it securely. |
| `expires_at` | string (date-time) | yes | Expires At timestamp (ISO 8601). |
| `return_to` | string or null | no | Where the magic link asked to land. |
| `reader` | [`ReaderProfile`](#schema-readerprofile) | yes | Reader. |

### `TokenExchange` {#schema-tokenexchange}

Exchange a magic-link token for a reader session.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `token` | string | yes | The token from the magic link. |
