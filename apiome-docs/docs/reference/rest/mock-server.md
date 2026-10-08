---
title: "Mock server"
description: "REST endpoints tagged mock-server: 20 operations."
sidebar_position: 40
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mock-server` · 20 operations

## `GET /v1/mock/{mock_id}` {#serve-mock-root-get-v1-mock-mock-id-get}

**Serve Mock Root Get**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_get_v1_mock__mock_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root get. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mock/{mock_id}` {#serve-mock-root-put-v1-mock-mock-id-put}

**Serve Mock Root Put**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_put_v1_mock__mock_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root put. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mock/{mock_id}` {#serve-mock-root-post-v1-mock-mock-id-post}

**Serve Mock Root Post**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_post_v1_mock__mock_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root post. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/mock/{mock_id}` {#serve-mock-root-patch-v1-mock-mock-id-patch}

**Serve Mock Root Patch**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_patch_v1_mock__mock_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root patch. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mock/{mock_id}` {#serve-mock-root-delete-v1-mock-mock-id-delete}

**Serve Mock Root Delete**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_delete_v1_mock__mock_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root delete. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `HEAD /v1/mock/{mock_id}` {#serve-mock-root-head-v1-mock-mock-id-head}

**Serve Mock Root Head**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_head_v1_mock__mock_id__head`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root head. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `OPTIONS /v1/mock/{mock_id}` {#serve-mock-root-options-v1-mock-mock-id-options}

**Serve Mock Root Options**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_options_v1_mock__mock_id__options`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root options. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-get-v1-mock-mock-id-sub-path-get}

**Serve Mock Path Get**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_get_v1_mock__mock_id___sub_path__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path get. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-put-v1-mock-mock-id-sub-path-put}

**Serve Mock Path Put**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_put_v1_mock__mock_id___sub_path__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path put. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-post-v1-mock-mock-id-sub-path-post}

**Serve Mock Path Post**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_post_v1_mock__mock_id___sub_path__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path post. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-patch-v1-mock-mock-id-sub-path-patch}

**Serve Mock Path Patch**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_patch_v1_mock__mock_id___sub_path__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path patch. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-delete-v1-mock-mock-id-sub-path-delete}

**Serve Mock Path Delete**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_delete_v1_mock__mock_id___sub_path__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path delete. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `HEAD /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-head-v1-mock-mock-id-sub-path-head}

**Serve Mock Path Head**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_head_v1_mock__mock_id___sub_path__head`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path head. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `OPTIONS /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-options-v1-mock-mock-id-sub-path-options}

**Serve Mock Path Options**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_options_v1_mock__mock_id___sub_path__options`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path options. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mocks/{tenant_slug}` {#list-mocks-v1-mocks-tenant-slug-get}

**List Mocks**

List the tenant's mock instances, newest first.

Operation id: `list_mocks_v1_mocks__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mocks. | `application/json` array of [`MockInstanceResponse`](#schema-mockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mocks/{tenant_slug}` {#provision-mock-v1-mocks-tenant-slug-post}

**Provision Mock**

Provision a mock instance from a published version and return its stable base URL.

The version must be published. Its OpenAPI document is generated once and frozen into the
instance so the mock is stable for its lifetime. Free-tier expiry and the per-instance rate limit
are applied from configuration (overridable within bounds).

Caller-supplied scenarios keep the RC1-2.2 request shape — a list of rules — and are folded into
the engine's settings shape at provision time (#5532, MSC-2.2), with the same translator that
migrates instances provisioned before the fold. Rules that cannot be translated are reported on
the instance rather than dropped.

Operation id: `provision_mock_v1_mocks__tenant_slug__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for provision mock.

- `application/json` — [`MockProvisionRequest`](#schema-mockprovisionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for provision mock. | `application/json` [`MockInstanceResponse`](#schema-mockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mocks/{tenant_slug}/usage` {#get-mock-usage-v1-mocks-tenant-slug-usage-get}

**Get Mock Usage**

Return mock usage counters and daily rollups for the tenant (#4420, SIM-1.5).

Note: ``project_slug`` and ``version_label`` filter the ``dailyRollups`` only.
``monthlyRequestCount``, ``monthlyQuota``, and ``mockRps`` are always tenant-wide
totals, regardless of any filter parameters.

Operation id: `get_mock_usage_v1_mocks__tenant_slug__usage_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `days` | query | integer | no | Query parameter: days. |
| `project_slug` | query | string or null | no | URL-safe project slug within the tenant. |
| `version_label` | query | string or null | no | Query parameter: version label. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mock usage. | `application/json` [`MockUsageResponse`](#schema-mockusageresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mocks/{tenant_slug}/{mock_id}` {#get-mock-v1-mocks-tenant-slug-mock-id-get}

**Get Mock**

Inspect one mock instance owned by the tenant.

Operation id: `get_mock_v1_mocks__tenant_slug___mock_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mock. | `application/json` [`MockInstanceResponse`](#schema-mockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mocks/{tenant_slug}/{mock_id}` {#destroy-mock-v1-mocks-tenant-slug-mock-id-delete}

**Destroy Mock**

Destroy a mock instance and all of its state.

Operation id: `destroy_mock_v1_mocks__tenant_slug___mock_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for destroy mock. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mocks/{tenant_slug}/{mock_id}/active-scenario` {#switch-active-scenario-v1-mocks-tenant-slug-mock-id-active-scenario-put}

**Switch Active Scenario**

Switch the instance's default scenario (takes effect immediately, no restart).

The switch writes ``activeScenario`` into the instance's settings — the same key, read the same
way, as a version's stored active scenario (#5531, MSC-2.1). The two spellings that used to
describe this one concept are now one.

Operation id: `switch_active_scenario_v1_mocks__tenant_slug___mock_id__active_scenario_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for switch active scenario.

- `application/json` — [`MockScenarioSwitchRequest`](#schema-mockscenarioswitchrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for switch active scenario. | `application/json` [`MockInstanceResponse`](#schema-mockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MockInstanceResponse` {#schema-mockinstanceresponse}

Public view of a provisioned mock instance.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `baseUrl` | string | yes | Base URL. |
| `tenantSlug` | string | yes | Tenant Slug. |
| `projectSlug` | string | yes | Project Slug. |
| `versionSlug` | string | yes | Version Slug. |
| `status` | string | yes | Status. |
| `activeScenario` | string | yes | Active Scenario. |
| `scenarios` | array of string | yes | Scenarios. |
| `operationCount` | integer | yes | Number of operation. |
| `rateLimitPerMinute` | integer | yes | Rate Limit Per Minute. |
| `requestCount` | integer | yes | Number of request. |
| `createdAt` | string or null | no | Created At. |
| `expiresAt` | string or null | no | Expires At. |
| `lastActivityAt` | string or null | no | Last Activity At. |
| `migrationNotes` | array of string | no | Rules from the pre-#5532 configuration that could not be translated onto the single mock engine, reported rather than silently dropped. Empty when the fold was lossless. |

### `MockProvisionRequest` {#schema-mockprovisionrequest}

Request body to provision a mock instance from a published version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectSlug` | string | yes | Project Slug. |
| `versionSlug` | string | yes | Version Slug. |
| `name` | string or null | no | Display name; defaults to the coordinates. |
| `ttlHours` | integer or null | no | Auto-expiry in hours; clamped to the configured maximum. |
| `rateLimitPerMinute` | integer or null | no | Rate Limit Per Minute. |
| `seed` | integer or null | no | Deterministic data-generation seed. |
| `scenarios` | array of `MockScenario` or null | no | Scenarios. |
| `activeScenario` | string or null | no | Active Scenario. |

### `MockScenarioSwitchRequest` {#schema-mockscenarioswitchrequest}

Request body to switch a mock instance's active scenario.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `activeScenario` | string | yes | Active Scenario. |

### `MockUsageResponse` {#schema-mockusageresponse}

Mock usage counters for a tenant (#4420, SIM-1.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `monthlyRequestCount` | integer | yes | Number of monthly request. |
| `monthlyQuota` | integer | yes | Monthly Quota. |
| `mockRps` | number | yes | Mock Rps. |
| `dailyRollups` | array of `MockUsageDailyRollup` | yes | Daily Rollups. |
