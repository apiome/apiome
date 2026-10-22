---
title: "Gateway configs"
description: "REST endpoints tagged gateway-configs: 2 operations."
sidebar_position: 31
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.286.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `gateway-configs` · 2 operations

## `GET /v1/tenants/{tenant_slug}/gateway-configs` {#list-tenant-gateway-configs-v1-tenants-tenant-slug-gateway-configs-get}

**List gateway configs**

Every live gateway config: one per (connector, environment), with its API count, auth and
rate-limit posture, declared losses and push-back target (`imports:view`).

Operation id: `list_tenant_gateway_configs_v1_tenants__tenant_slug__gateway_configs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector` | query | string or null | no | Only this connector's environments. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list gateway configs. | `application/json` [`GatewayConfigList`](#schema-gatewayconfiglist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/gateway-configs/{ref}` {#read-tenant-gateway-config-v1-tenants-tenant-slug-gateway-configs-ref-get}

**Read a gateway config**

One gateway config, by slug or id, with the APIs its environment serves (`imports:view`).

`pushBack.target` is the export target that writes this gateway's format (`kong`,
`aws-apigateway`, `azure-apim`, `apigee`), or `null` with `pushBack.reason` `unsupported`.

Operation id: `read_tenant_gateway_config_v1_tenants__tenant_slug__gateway_configs__ref__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `ref` | path | string | yes | Path parameter identifying the ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a gateway config. | `application/json` [`GatewayConfigOut`](#schema-gatewayconfigout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `GatewayConfigList` {#schema-gatewayconfiglist}

The tenant's live gateway configs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `gatewayConfigs` | array of [`GatewayConfigOut`](#schema-gatewayconfigout) | yes | Gateway Configs. |

### `GatewayConfigOut` {#schema-gatewayconfigout}

A gateway config.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `connector` | `GatewayConnectorRef` | yes | Connector. |
| `environment` | string | yes | Environment. |
| `flavor` | string | yes | Flavor. |
| `apiCount` | integer | yes | Number of api. |
| `posture` | `GatewayPosture` | yes | Posture. |
| `declaredLosses` | array of `GatewayLoss` | no | Declared Losses. |
| `pushBack` | `GatewayPushBack` | yes | Push Back. |
| `owner` | `EntityOwnerRef` or null | no | Owner. |
| `apis` | array of `GatewayServedApi` | no | On a single read only. |
| `lastSyncedAt` | string (date-time) or null | no | Last Synced At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
