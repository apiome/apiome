---
title: "MCP keys"
description: "REST endpoints tagged mcp-keys: 7 operations."
sidebar_position: 34
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mcp-keys` · 7 operations

## `GET /v1/tenants/{tenant_slug}/mcp-keys` {#list-mcp-api-keys-v1-tenants-tenant-slug-mcp-keys-get}

**List MCP API keys**

List MCP API key metadata for the tenant (prefix, label, scope, capability_mode, enabled_tools, timestamps). Includes revoked keys for audit. Never returns secret or hash. Tenant administrators only (MTG-3.2, #4776).

Operation id: `list_mcp_api_keys_v1_tenants__tenant_slug__mcp_keys_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp api keys. | `application/json` [`McpApiKeyListResponse`](#schema-mcpapikeylistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/mcp-keys` {#create-mcp-api-key-v1-tenants-tenant-slug-mcp-keys-post}

**Create MCP API key**

Issue a new MCP API key. Returns plaintext ``secret`` once; subsequent reads never include it. Defaults to capability_mode=inherit. Tenant administrators only (MTG-3.2, #4776).

Operation id: `create_mcp_api_key_v1_tenants__tenant_slug__mcp_keys_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create mcp api key.

- `application/json` — [`McpApiKeyCreateRequest`](#schema-mcpapikeycreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create mcp api key. | `application/json` [`McpApiKeyCreateResponse`](#schema-mcpapikeycreateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/mcp-keys/{key_id}` {#get-mcp-api-key-v1-tenants-tenant-slug-mcp-keys-key-id-get}

**Get MCP API key**

Return one MCP API key's public metadata. Never returns secret or hash. Tenant administrators only (MTG-3.2, #4776).

Operation id: `get_mcp_api_key_v1_tenants__tenant_slug__mcp_keys__key_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `key_id` | path | string (uuid) | yes | Path parameter identifying the key id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp api key. | `application/json` [`McpApiKeyMetadata`](#schema-mcpapikeymetadata) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/mcp-keys/{key_id}` {#patch-mcp-api-key-v1-tenants-tenant-slug-mcp-keys-key-id-patch}

**Update MCP API key**

Update label, expires_at, and/or scope_json on an active (non-revoked) MCP API key. Capability grants use PUT …/capabilities (MTG-3.3). Tenant administrators only (MTG-3.2, #4776).

Operation id: `patch_mcp_api_key_v1_tenants__tenant_slug__mcp_keys__key_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `key_id` | path | string (uuid) | yes | Path parameter identifying the key id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update mcp api key.

- `application/json` — [`McpApiKeyPatchRequest`](#schema-mcpapikeypatchrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update mcp api key. | `application/json` [`McpApiKeyMetadata`](#schema-mcpapikeymetadata) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/mcp-keys/{key_id}` {#revoke-mcp-api-key-v1-tenants-tenant-slug-mcp-keys-key-id-delete}

**Revoke MCP API key**

Soft-revoke an MCP API key (sets revoked_at). Idempotent for already-revoked keys. MCP auth rejects the key immediately. Tenant administrators only (MTG-3.2, #4776).

Operation id: `revoke_mcp_api_key_v1_tenants__tenant_slug__mcp_keys__key_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `key_id` | path | string (uuid) | yes | Path parameter identifying the key id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for revoke mcp api key. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/mcp-keys/{key_id}/capabilities` {#put-mcp-api-key-capabilities-v1-tenants-tenant-slug-mcp-keys-key-id-capabilities-put}

**Update MCP API key capabilities**

Set per-key capability grants: mode inherit|explicit and optional enabled_tools. inherit clears the explicit list; explicit lists must be ⊆ the tenant ceiling (422 with offending_tool_ids otherwise). Tenant administrators only (MTG-3.3, #4777).

Operation id: `put_mcp_api_key_capabilities_v1_tenants__tenant_slug__mcp_keys__key_id__capabilities_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `key_id` | path | string (uuid) | yes | Path parameter identifying the key id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update mcp api key capabilities.

- `application/json` — [`McpKeyCapabilitiesRequest`](#schema-mcpkeycapabilitiesrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update mcp api key capabilities. | `application/json` [`McpKeyCapabilitiesResponse`](#schema-mcpkeycapabilitiesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/mcp-keys/{key_id}/capabilities/preview` {#preview-mcp-api-key-capabilities-v1-tenants-tenant-slug-mcp-keys-key-id-capabilities-preview-post}

**Preview MCP API key effective capabilities**

Dry-run effective enable-set for the given mode/enabled_tools against the tenant policy, using the same MTG-1.4 resolver as MCP tools/call. Does not persist. Ceiling violations yield 422 with offending_tool_ids. Tenant administrators only (MTG-3.3, #4777).

Operation id: `preview_mcp_api_key_capabilities_v1_tenants__tenant_slug__mcp_keys__key_id__capabilities_preview_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `key_id` | path | string (uuid) | yes | Path parameter identifying the key id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for preview mcp api key effective capabilities.

- `application/json` — [`McpKeyCapabilitiesRequest`](#schema-mcpkeycapabilitiesrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview mcp api key effective capabilities. | `application/json` [`McpKeyCapabilitiesPreviewResponse`](#schema-mcpkeycapabilitiespreviewresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `McpApiKeyCreateRequest` {#schema-mcpapikeycreaterequest}

Issue a new MCP API key.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `label` | string | yes | Human label for admin UX. |
| `expires_at` | string (date-time) or null | no | Optional absolute expiry; omit for no expiry. |
| `scope_json` | `McpKeyScopeJson` | no | Read scope: {"tenants":[...],"projects":[...]}. |

### `McpApiKeyCreateResponse` {#schema-mcpapikeycreateresponse}

Create response: metadata plus one-time plaintext ``secret``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `prefix` | string | yes | Prefix. |
| `label` | string | yes | Label. |
| `scope_json` | `McpKeyScopeJson` | yes | Scope JSON. |
| `capability_mode` | enum `"inherit"`, `"explicit"` | yes | Capability Mode. |
| `enabled_tools` | array of string | no | Explicit enable-set when capability_mode=explicit; empty under inherit. |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
| `expires_at` | string (date-time) or null | no | Expires At timestamp (ISO 8601). |
| `revoked_at` | string (date-time) or null | no | Revoked At timestamp (ISO 8601). |
| `last_used_at` | string (date-time) or null | no | Last Used At timestamp (ISO 8601). |
| `created_by` | string or null | no | Created By. |
| `secret` | string | yes | Plaintext MCP API key; shown only in this response. |

### `McpApiKeyListResponse` {#schema-mcpapikeylistresponse}

Tenant MCP API key listing.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `keys` | array of [`McpApiKeyMetadata`](#schema-mcpapikeymetadata) | yes | Keys. |

### `McpApiKeyMetadata` {#schema-mcpapikeymetadata}

Public MCP API key metadata (never includes secret or hash).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `prefix` | string | yes | Prefix. |
| `label` | string | yes | Label. |
| `scope_json` | `McpKeyScopeJson` | yes | Scope JSON. |
| `capability_mode` | enum `"inherit"`, `"explicit"` | yes | Capability Mode. |
| `enabled_tools` | array of string | no | Explicit enable-set when capability_mode=explicit; empty under inherit. |
| `created_at` | string (date-time) | yes | Creation timestamp (ISO 8601). |
| `expires_at` | string (date-time) or null | no | Expires At timestamp (ISO 8601). |
| `revoked_at` | string (date-time) or null | no | Revoked At timestamp (ISO 8601). |
| `last_used_at` | string (date-time) or null | no | Last Used At timestamp (ISO 8601). |
| `created_by` | string or null | no | Created By. |

### `McpApiKeyPatchRequest` {#schema-mcpapikeypatchrequest}

Partial update of label, expiry, and/or scope (active keys only).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `label` | string or null | no | Replace label when set. |
| `expires_at` | string (date-time) or null | no | Replace expiry when field is present; null clears expiry. |
| `scope_json` | `McpKeyScopeJson` or null | no | Replace scope_json when set. |

### `McpKeyCapabilitiesPreviewResponse` {#schema-mcpkeycapabilitiespreviewresponse}

Effective enable-set table for a key (matches MCP call gate).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tools` | array of `McpKeyEffectiveToolRow` | yes | Tools. |

### `McpKeyCapabilitiesRequest` {#schema-mcpkeycapabilitiesrequest}

Writable per-key capability grants (MTG-3.3).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | enum `"inherit"`, `"explicit"` | yes | inherit = clear enabled_tools and follow tenant defaults; explicit = enabled_tools is authoritative (must be ⊆ ceiling). |
| `enabled_tools` | array of string or null | no | Tool ids when mode=explicit. Ignored (cleared) when mode=inherit. |

### `McpKeyCapabilitiesResponse` {#schema-mcpkeycapabilitiesresponse}

Stored per-key capability grants.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | enum `"inherit"`, `"explicit"` | yes | Mode. |
| `enabled_tools` | array of string | yes | Enabled Tools. |
