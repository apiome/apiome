---
title: "MCP policy"
description: "REST endpoints tagged mcp-policy: 3 operations."
sidebar_position: 36
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mcp-policy` · 3 operations

## `GET /v1/tenants/{tenant_slug}/mcp-policy` {#get-tenant-mcp-policy-v1-tenants-tenant-slug-mcp-policy-get}

**Get tenant MCP policy**

Return the tenant's MCP tool governance policy (ceiling, default enable-set, anonymous flags). Tenant members may read; an unseeded tenant synthesizes default_mode=all with an empty tools list (MTG-3.1, #4775).

Operation id: `get_tenant_mcp_policy_v1_tenants__tenant_slug__mcp_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant mcp policy. | `application/json` [`TenantMcpPolicyResponse`](#schema-tenantmcppolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/mcp-policy` {#put-tenant-mcp-policy-v1-tenants-tenant-slug-mcp-policy-put}

**Replace tenant MCP policy**

Replace the tenant MCP policy (default_mode, anonymous kill switch, and full per-tool flag list). Tenant administrators with a signed-in session only; API keys cannot mutate governance. Unknown tool ids and default_enabled without in_ceiling yield 422 (MTG-3.1, #4775; MTG-3.4, #4778). Non-noop writes append a policy change audit row (MTG-5.2, #4786).

Operation id: `put_tenant_mcp_policy_v1_tenants__tenant_slug__mcp_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace tenant mcp policy.

- `application/json` — [`TenantMcpPolicyPutRequest`](#schema-tenantmcppolicyputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace tenant mcp policy. | `application/json` [`TenantMcpPolicyResponse`](#schema-tenantmcppolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/mcp-policy/history` {#list-tenant-mcp-policy-history-v1-tenants-tenant-slug-mcp-policy-history-get}

**List tenant MCP policy change history**

Return newest-first append-only MCP policy change events with before/after tool-enablement snapshots (MTG-5.2, #4786). Tenant members may read.

Operation id: `list_tenant_mcp_policy_history_v1_tenants__tenant_slug__mcp_policy_history_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Max change rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list tenant mcp policy change history. | `application/json` [`TenantMcpPolicyHistoryResponse`](#schema-tenantmcppolicyhistoryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `TenantMcpPolicyHistoryResponse` {#schema-tenantmcppolicyhistoryresponse}

Newest-first list of tenant MCP policy changes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `changes` | array of `TenantMcpPolicyChangeEntry` | no | Changes. |

### `TenantMcpPolicyPutRequest` {#schema-tenantmcppolicyputrequest}

Writable tenant MCP policy body for ``PUT …/mcp-policy``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `default_mode` | enum `"all"`, `"inherit_registry"`, `"explicit"` | yes | How missing tool rows resolve: all, inherit_registry, or explicit. |
| `allow_anonymous_mcp` | boolean | no | Kill switch for anonymous tools/call against this tenant policy. |
| `tools` | array of `TenantMcpPolicyTool` | no | Full replace-all list of per-tool policy flags. |

### `TenantMcpPolicyResponse` {#schema-tenantmcppolicyresponse}

Stored (or synthesized unseeded) tenant MCP policy snapshot.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `default_mode` | enum `"all"`, `"inherit_registry"`, `"explicit"` | yes | Default Mode. |
| `allow_anonymous_mcp` | boolean | yes | Allow Anonymous MCP. |
| `tools` | array of `TenantMcpPolicyTool` | yes | Tools. |
| `updated_at` | string (date-time) or null | no | Last policy write time; null when no row has been persisted. |
| `updated_by` | string or null | no | User id of the last writer; null until first admin PUT after seed. |
