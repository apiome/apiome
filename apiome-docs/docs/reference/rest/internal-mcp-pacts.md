---
title: "Internal MCP pacts"
description: "REST endpoints tagged internal-mcp-pacts: 4 operations."
sidebar_position: 49
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.700.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `internal-mcp-pacts` · 4 operations

## `POST /v1/internal/mcp/pacts/can-i-deploy` {#mcp-pact-can-i-deploy-v1-internal-mcp-pacts-can-i-deploy-post}

**Can I deploy? for the MCP `pact.can_i_deploy` tool**

Internal (`X-Internal-Service-Token`). `GET …/pact-broker/can-i-deploy`: one pacticipant version to `toEnvironment` or `toTag` (exactly one). The same bounded answer as the matrix route; `retryAfterSeconds` is set while the verdict is unknown. Requires the key owner's `pacts:view`.

Operation id: `mcp_pact_can_i_deploy_v1_internal_mcp_pacts_can_i_deploy_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Request body** (required)

Request body for can i deploy? for the mcp `pact.can_i_deploy` tool.

- `application/json` — [`McpPactCanIDeployRequest`](#schema-mcppactcanideployrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for can i deploy? for the mcp `pact.can_i_deploy` tool. | `application/json` [`McpPactMatrixResponse`](#schema-mcppactmatrixresponse) |
| 400 | `pact-matrix-invalid` or `mcp-pact-invalid`: the request cannot be answered as sent. | — |
| 403 | `mcp-pact-key-unknown`, `mcp-pact-key-has-no-owner`, or the key's owner lacks `pacts`. | — |
| 404 | `pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/internal/mcp/pacts/list` {#mcp-pact-list-v1-internal-mcp-pacts-list-post}

**Latest pacts for the MCP `pact.list` tool**

Internal (`X-Internal-Service-Token`). The latest pact of every consumer → provider integration of the tenant, with its latest verification result; optional `provider` / `consumer` filters; cursor-paginated. Requires the key owner's `pacts:view`.

Operation id: `mcp_pact_list_v1_internal_mcp_pacts_list_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Request body** (required)

Request body for latest pacts for the mcp `pact.list` tool.

- `application/json` — [`McpPactListRequest`](#schema-mcppactlistrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for latest pacts for the mcp `pact.list` tool. | `application/json` [`McpPactListResponse`](#schema-mcppactlistresponse) |
| 400 | `pact-matrix-invalid` or `mcp-pact-invalid`: the request cannot be answered as sent. | — |
| 403 | `mcp-pact-key-unknown`, `mcp-pact-key-has-no-owner`, or the key's owner lacks `pacts`. | — |
| 404 | `pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/internal/mcp/pacts/matrix` {#mcp-pact-matrix-v1-internal-mcp-pacts-matrix-post}

**Matrix query for the MCP `pact.matrix` tool**

Internal (`X-Internal-Service-Token`). `GET …/pact-broker/matrix` from structured selectors: the verdict (`summary.deployable` true / false / null), its notices and at most `maxRows` compact rows, with `rowsTotal` and `rowsTruncated`. `latestby` is one of cvp, cvpv, cp. Requires the key owner's `pacts:view`.

Operation id: `mcp_pact_matrix_v1_internal_mcp_pacts_matrix_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Request body** (required)

Request body for matrix query for the mcp `pact.matrix` tool.

- `application/json` — [`McpPactMatrixRequest`](#schema-mcppactmatrixrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for matrix query for the mcp `pact.matrix` tool. | `application/json` [`McpPactMatrixResponse`](#schema-mcppactmatrixresponse) |
| 400 | `pact-matrix-invalid` or `mcp-pact-invalid`: the request cannot be answered as sent. | — |
| 403 | `mcp-pact-key-unknown`, `mcp-pact-key-has-no-owner`, or the key's owner lacks `pacts`. | — |
| 404 | `pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/internal/mcp/pacts/record-deployment` {#mcp-pact-record-deployment-v1-internal-mcp-pacts-record-deployment-post}

**Record a deployment for the MCP `pact.record_deployment` tool**

Internal (`X-Internal-Service-Token`). `pact-broker record-deployment`: the version is now deployed to the named environment (and application instance); the previous deployment there is marked undeployed. `created: false` when it already was the current deployment. Requires the key owner's `pacts:create`.

Operation id: `mcp_pact_record_deployment_v1_internal_mcp_pacts_record_deployment_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Request body** (required)

Request body for record a deployment for the mcp `pact.record_deployment` tool.

- `application/json` — [`McpPactRecordDeploymentRequest`](#schema-mcppactrecorddeploymentrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record a deployment for the mcp `pact.record_deployment` tool. | `application/json` [`McpPactDeploymentResponse`](#schema-mcppactdeploymentresponse) |
| 400 | `pact-matrix-invalid` or `mcp-pact-invalid`: the request cannot be answered as sent. | — |
| 403 | `mcp-pact-key-unknown`, `mcp-pact-key-has-no-owner`, or the key's owner lacks `pacts`. | — |
| 404 | `pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`. | — |
| 422 | `pact-deployment-invalid`: a malformed application instance. | — |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `McpPactCanIDeployRequest` {#schema-mcppactcanideployrequest}

``pact.can_i_deploy``: one version to an environment or a tag.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenantId` | string | yes | The MCP key's tenant (trusted: internal route). |
| `keyId` | string | yes | The MCP key; its owner's `pacts` role is applied. |
| `pacticipant` | string | yes | What is being deployed. |
| `version` | string | yes | Its version number, exactly as recorded. |
| `toEnvironment` | string or null | no | Where it goes. |
| `toTag` | string or null | no | Or: the tag it is checked against. |
| `ignore` | array of `McpPactIgnore` | no | Rows that do not count. |
| `maxRows` | integer | no | The most rows returned (the verdict reads them all). |

### `McpPactDeploymentResponse` {#schema-mcppactdeploymentresponse}

The recorded deployment.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `created` | boolean | yes | False when this version already was the current deployment there. |
| `deployment` | object | yes | Deployment. |

### `McpPactListRequest` {#schema-mcppactlistrequest}

``pact.list``: optional filters and a page.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenantId` | string | yes | The MCP key's tenant (trusted: internal route). |
| `keyId` | string | yes | The MCP key; its owner's `pacts` role is applied. |
| `provider` | string or null | no | Only pacts for this provider (handle, id or name). |
| `consumer` | string or null | no | Only pacts of this consumer (handle, id or name). |
| `limit` | integer | no | Pacts per page. |
| `cursor` | string or null | no | `nextCursor` of the previous page. |

### `McpPactListResponse` {#schema-mcppactlistresponse}

One page of pacts.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of object | yes | Items. |
| `hasMore` | boolean | yes | Has More. |
| `nextCursor` | string or null | no | Next Cursor. |

### `McpPactMatrixRequest` {#schema-mcppactmatrixrequest}

``pact.matrix``: the selectors and options of a broker matrix query.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenantId` | string | yes | The MCP key's tenant (trusted: internal route). |
| `keyId` | string | yes | The MCP key; its owner's `pacts` role is applied. |
| `selectors` | array of `McpPactSelector` | yes | The versions in question (1 or more). |
| `latestby` | enum `"cvp"`, `"cvpv"`, `"cp"` or null | no | How rows collapse. |
| `toEnvironment` | string or null | no | Destination: everything in this environment. |
| `toTag` | string or null | no | Destination: the latest version with this tag. |
| `latest` | boolean or null | no | Destination: each other pacticipant's latest. |
| `mainBranch` | boolean or null | no | Destination: each other pacticipant's main branch. |
| `ignore` | array of `McpPactIgnore` | no | Rows that do not count. |
| `limit` | integer or null | no | The most rows the query reads. |
| `maxRows` | integer | no | The most rows returned (the verdict reads them all). |

### `McpPactMatrixResponse` {#schema-mcppactmatrixresponse}

The verdict and a bounded set of the rows it was reached from.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `summary` | object | yes | Short summary suitable for navigation and reference docs. |
| `notices` | array of object | yes | Notices. |
| `noticesTruncated` | boolean | yes | Notices Truncated. |
| `rows` | array of object | yes | Rows. |
| `rowsTotal` | integer | yes | Rows Total. |
| `rowsTruncated` | boolean | yes | Rows Truncated. |
| `retryAfterSeconds` | integer or null | no | Retry After Seconds. |

### `McpPactRecordDeploymentRequest` {#schema-mcppactrecorddeploymentrequest}

``pact.record_deployment``: a version is now deployed to a named environment.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenantId` | string | yes | The MCP key's tenant (trusted: internal route). |
| `keyId` | string | yes | The MCP key; its owner's `pacts` role is applied. |
| `pacticipant` | string | yes | The deployed pacticipant. |
| `version` | string | yes | The deployed version number, exactly as recorded. |
| `environment` | string | yes | The environment's name (as `pact-broker record-deployment --environment`). |
| `applicationInstance` | string or null | no | The instance deployed to; omit for the only one. |
