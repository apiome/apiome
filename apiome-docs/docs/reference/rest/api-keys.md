---
title: "API keys"
description: "REST endpoints tagged api-keys: 2 operations."
sidebar_position: 7
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `api-keys` · 2 operations

## `GET /api-keys/mcp-capability-presets` {#list-mcp-capability-presets-api-keys-mcp-capability-presets-get}

**List MCP capability presets**

Enumerate named capability profiles (Catalog only, Search + catalog, Full read) with the documented toolset enable matrix for tenant MCP policy drafts (MTG-5.1, #4785). Custom is not listed — it is a UI sentinel for non-matching drafts.

Operation id: `list_mcp_capability_presets_api_keys_mcp_capability_presets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp capability presets. | `application/json` [`McpCapabilityPresetsResponse`](#schema-mcpcapabilitypresetsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /api-keys/mcp-tools` {#list-mcp-tools-api-keys-mcp-tools-get}

**List MCP tools and toolsets**

Enumerate every registered Apiome MCP tool id (and planned capability ids such as spec.mcp / spec.catalog), with description and toolset membership for admin enable/disable UX (MTG-1.1, #4765). Same source of truth as apiome-mcp call-time fail-closed checks.

Operation id: `list_mcp_tools_api_keys_mcp_tools_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp tools and toolsets. | `application/json` [`McpToolCatalogResponse`](#schema-mcptoolcatalogresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `McpCapabilityPresetsResponse` {#schema-mcpcapabilitypresetsresponse}

Named MCP capability presets (MTG-5.1). Custom is a UI sentinel only.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `presets` | array of `McpCapabilityPresetItem` | yes | Named packs in display order; see docs/MCP_CAPABILITY_PRESETS.md. |

### `McpToolCatalogResponse` {#schema-mcptoolcatalogresponse}

Full MCP tool & capability catalog (MTG-1.1).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tools` | array of `McpToolCatalogItem` | yes | Every registered tool / capability id, in registry order. |
