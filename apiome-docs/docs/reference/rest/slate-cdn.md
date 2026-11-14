---
title: "Slate cdn"
description: "REST endpoints tagged slate-cdn: 4 operations."
sidebar_position: 90
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.554.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `slate-cdn` · 4 operations

## `GET /v1/slate/environments/{environment_id}/cdn` {#get-cdn-config-v1-slate-environments-environment-id-cdn-get}

**Get Cdn Config**

Return a lane's CDN provider (never its credential) and the last purge sent to it.

Operation id: `get_cdn_config_v1_slate_environments__environment_id__cdn_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get cdn config. | `application/json` [`CdnConfigResponse`](#schema-cdnconfigresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/cdn` {#save-cdn-config-v1-slate-environments-environment-id-cdn-post}

**Save Cdn Config**

Attach or update a lane's CDN provider, sealing the credential before it is stored.

Refusals: 422 ``cdn-config-invalid`` (every bad field listed in ``errors``), 422
``cdn-credential-required``, 409 ``cdn-vault-not-configured`` when this deployment has no
key to seal credentials with — a credential is never stored in plaintext as a fallback.

Operation id: `save_cdn_config_v1_slate_environments__environment_id__cdn_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save cdn config.

- `application/json` — [`SaveCdnProviderRequest`](#schema-savecdnproviderrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save cdn config. | `application/json` [`CdnConfigResponse`](#schema-cdnconfigresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/cdn` {#detach-cdn-v1-slate-environments-environment-id-cdn-delete}

**Detach Cdn**

Detach a lane's CDN provider and delete its stored credential.

Operation id: `detach_cdn_v1_slate_environments__environment_id__cdn_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for detach cdn. | `application/json` [`CdnDetachResponse`](#schema-cdndetachresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/cdn/dispatches` {#get-cdn-dispatches-v1-slate-environments-environment-id-cdn-dispatches-get}

**Get Cdn Dispatches**

Return the purges sent to a lane's CDN, most recent first.

Operation id: `get_cdn_dispatches_v1_slate_environments__environment_id__cdn_dispatches_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get cdn dispatches. | `application/json` [`CdnDispatchHistoryResponse`](#schema-cdndispatchhistoryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CdnConfigResponse` {#schema-cdnconfigresponse}

A lane's CDN configuration.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | Environment ID. |
| `configured` | boolean | yes | A provider is attached. |
| `vaultConfigured` | boolean | yes | This deployment can seal credentials. False means saving is refused. |
| `edgeAttached` | boolean | yes | Purges on this lane are dispatched to the CDN. |
| `provider` | `CdnProviderBody` or null | no | Provider. |
| `lastDispatch` | `CdnDispatchBody` or null | no | Last Dispatch. |

### `CdnDetachResponse` {#schema-cdndetachresponse}

The outcome of detaching a provider.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | Environment ID. |
| `detached` | boolean | yes | Detached. |

### `CdnDispatchHistoryResponse` {#schema-cdndispatchhistoryresponse}

A lane's CDN purge log.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | Environment ID. |
| `dispatches` | array of `CdnDispatchBody` | yes | Dispatches. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SaveCdnProviderRequest` {#schema-savecdnproviderrequest}

Attach or update a lane's CDN provider.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | string | yes | cloudflare, fastly or custom. |
| `target` | string | yes | Cloudflare zone id, Fastly service id, or the custom https purge URL. |
| `authHeaderName` | string or null | no | Header a custom endpoint reads its credential from. |
| `credential` | string or null | no | Write-only. API token (Cloudflare), API key (Fastly) or header value (custom). Blank keeps the stored credential when the provider is unchanged. |
| `purgeOnDeploy` | boolean | no | Purge the CDN when a release is promoted or rolled back. |
