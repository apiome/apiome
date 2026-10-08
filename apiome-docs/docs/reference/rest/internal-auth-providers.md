---
title: "Internal auth providers"
description: "REST endpoints tagged internal-auth-providers: 1 operation."
sidebar_position: 28
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `internal-auth-providers` · 1 operation

## `GET /v1/internal/auth-providers/resolved` {#get-resolved-auth-providers-v1-internal-auth-providers-resolved-get}

**Get Resolved Auth Providers**

Return decrypted DB provider config for the login-time merge resolver (OLO-8.5).

Reads every stored provider row and decrypts its secret in-process. A provider whose secret
cannot be decrypted is omitted (and logged secret-free) so one broken row degrades to env rather
than breaking sign-in for every provider.

Returns:
    A ``{provider_id: ResolvedProviderConfig}`` map for providers that have a stored row and
    whose secret (if any) decrypted successfully.

Operation id: `get_resolved_auth_providers_v1_internal_auth_providers_resolved_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get resolved auth providers. | `application/json` [`ResolvedProviderConfigResponse`](#schema-resolvedproviderconfigresponse) |
| 401 | No internal service token presented. | — |
| 403 | Internal service token invalid. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 503 | Resolved read path disabled (no INTERNAL_SERVICE_TOKEN configured). | — |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ResolvedProviderConfigResponse` {#schema-resolvedproviderconfigresponse}

Payload of ``GET /v1/internal/auth-providers/resolved``: stored providers only, by id.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `providers` | map of `ResolvedProviderConfig` | no | Map of provider_id → resolved DB config; a provider with no stored row is absent. |
