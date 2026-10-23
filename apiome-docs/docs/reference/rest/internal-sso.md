---
title: "Internal sso"
description: "REST endpoints tagged internal-sso: 1 operation."
sidebar_position: 39
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.309.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `internal-sso` · 1 operation

## `GET /v1/internal/sso/providers/resolved` {#get-resolved-sso-providers-v1-internal-sso-providers-resolved-get}

**Get Resolved Sso Providers**

Every enabled provider with a verified domain, secrets decrypted, for the sign-in resolver.

A provider whose secret cannot be decrypted (rotated-away key, corrupt blob) is omitted and
logged secret-free, so one bad row cannot take sign-in down for every other provider.

Operation id: `get_resolved_sso_providers_v1_internal_sso_providers_resolved_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get resolved sso providers. | `application/json` [`ResolvedSsoProviderResponse`](#schema-resolvedssoproviderresponse) |
| 401 | No internal service token presented. | — |
| 403 | Internal service token invalid. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 503 | Internal read path disabled (no INTERNAL_SERVICE_TOKEN), or the database is unavailable. | — |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ResolvedSsoProviderResponse` {#schema-resolvedssoproviderresponse}

Payload of ``GET /v1/internal/sso/providers/resolved``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `providers` | array of `ResolvedSsoProvider` | no | Providers. |
| `fingerprint` | string | yes | Changes whenever any routable provider changes; secret-free hash. |
