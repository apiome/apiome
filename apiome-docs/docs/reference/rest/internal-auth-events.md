---
title: "Internal auth events"
description: "REST endpoints tagged internal-auth-events: 1 operation."
sidebar_position: 37
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.320.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `internal-auth-events` · 1 operation

## `POST /v1/internal/auth-events` {#record-auth-event-v1-internal-auth-events-post}

**Record Auth Event**

Append one sign-in outcome to ``auth_events`` (best-effort; hashes the IP and User-Agent).

Operation id: `record_auth_event_v1_internal_auth_events_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Request body** (required)

Request body for record auth event.

- `application/json` — [`AuthEventCreateRequest`](#schema-autheventcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for record auth event. | `application/json` [`AuthEventAccepted`](#schema-autheventaccepted) |
| 401 | No internal service token presented. | — |
| 403 | Internal service token invalid. | — |
| 422 | The event is outside the accepted vocabulary or limits. | — |
| 503 | Disabled: no INTERNAL_SERVICE_TOKEN configured. | — |

## Schemas used {#schemas-used}

### `AuthEventAccepted` {#schema-autheventaccepted}

Payload of a recorded event.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `accepted` | boolean | no | Accepted. |

### `AuthEventCreateRequest` {#schema-autheventcreaterequest}

Body of ``POST /v1/internal/auth-events``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `event_type` | string | yes | `sign_in`, `sign_up` or `link`. |
| `outcome` | string | yes | `success` or `failure`. |
| `provider` | string or null | no | `sso:<slug>` or an OAuth provider slug. |
| `user_id` | string or null | no | The resolved user, when there is one. |
| `user_label` | string or null | no | The email the attempt carried. |
| `error_code` | string or null | no | Stable error code on failure. |
| `ip` | string or null | no | Client IP; hashed, never stored. |
| `user_agent` | string or null | no | Client User-Agent; hashed, never stored. |
| `detail` | object or null | no | Small structured context, no secrets. |
