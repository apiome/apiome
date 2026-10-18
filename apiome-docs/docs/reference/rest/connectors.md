---
title: "Connectors"
description: "REST endpoints tagged connectors: 9 operations."
sidebar_position: 17
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.227.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `connectors` · 9 operations

## `GET /v1/tenants/{tenant_slug}/connectors` {#list-connectors-v1-tenants-tenant-slug-connectors-get}

**List Connectors**

List the tenant's catalog connectors (``imports:view``).

Also returns every connector kind and the kinds this deployment can sync.

Operation id: `list_connectors_v1_tenants__tenant_slug__connectors_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list connectors. | `application/json` [`ConnectorListResponse`](#schema-connectorlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/connectors` {#create-connector-v1-tenants-tenant-slug-connectors-post}

**Create Connector**

Register a catalog connector (``imports:create``).

The base URL, when given, must pass the SSRF rule: a private-range URL is a 422 with
``detail.reason = "private-address"`` unless the operator allowlisted the range. Credentials
are not accepted here; store them with ``PUT …/credentials``.

Operation id: `create_connector_v1_tenants__tenant_slug__connectors_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create connector.

- `application/json` — [`ConnectorCreate`](#schema-connectorcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create connector. | `application/json` [`ConnectorOut`](#schema-connectorout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/connectors/{connector_id}` {#get-connector-v1-tenants-tenant-slug-connectors-connector-id-get}

**Get Connector**

Read one connector (``imports:view``). ``hasCredentials`` says whether one is stored.

Operation id: `get_connector_v1_tenants__tenant_slug__connectors__connector_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get connector. | `application/json` [`ConnectorOut`](#schema-connectorout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/connectors/{connector_id}` {#update-connector-v1-tenants-tenant-slug-connectors-connector-id-patch}

**Update Connector**

Update a connector (``imports:edit``). The kind cannot change.

``status`` takes ``active`` or ``paused``; ``failing`` is set by runs only. Setting
``baseUrl`` re-runs the SSRF check.

Operation id: `update_connector_v1_tenants__tenant_slug__connectors__connector_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update connector.

- `application/json` — [`ConnectorUpdate`](#schema-connectorupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update connector. | `application/json` [`ConnectorOut`](#schema-connectorout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/connectors/{connector_id}` {#delete-connector-v1-tenants-tenant-slug-connectors-connector-id-delete}

**Delete Connector**

Delete a connector (``imports:delete``).

The connector stops syncing and its credential is destroyed. Its inventory, its runs and the
catalog items it imported are kept.

Operation id: `delete_connector_v1_tenants__tenant_slug__connectors__connector_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete connector. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/connectors/{connector_id}/credentials` {#put-connector-credentials-v1-tenants-tenant-slug-connectors-connector-id-credentials-put}

**Put Connector Credentials**

Store or replace a connector's credential (``imports:edit``).

The fields are sealed on arrival and the previous credential, if any, is replaced as a whole;
there is no partial edit. The response names the stored fields and never their values. A 503
means this deployment has no credential encryption key (``APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS``).

Operation id: `put_connector_credentials_v1_tenants__tenant_slug__connectors__connector_id__credentials_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put connector credentials.

- `application/json` — [`ConnectorCredentialsPut`](#schema-connectorcredentialsput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put connector credentials. | `application/json` [`ConnectorCredentialsOut`](#schema-connectorcredentialsout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/connectors/{connector_id}/items` {#list-connector-items-v1-tenants-tenant-slug-connectors-connector-id-items-get}

**List Connector Items**

List the remote APIs a connector has seen (``imports:view``).

``catalogItemId`` links an imported API to its catalog item. An API that left the inventory
is ``missing``; it is never deleted.

Operation id: `list_connector_items_v1_tenants__tenant_slug__connectors__connector_id__items_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `status` | query | string or null | no | discovered \| imported \| ignored \| missing |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list connector items. | `application/json` [`ConnectorItemPage`](#schema-connectoritempage) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/connectors/{connector_id}/runs` {#list-connector-runs-v1-tenants-tenant-slug-connectors-connector-id-runs-get}

**List Connector Runs**

List a connector's sync runs, newest first (``imports:view``).

Runs are rows of the same refresh ledger Git refresh jobs use (``refreshSource:
"connector"``), and their pulls count against the same tenant quota.

Operation id: `list_connector_runs_v1_tenants__tenant_slug__connectors__connector_id__runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list connector runs. | `application/json` [`ConnectorRunPage`](#schema-connectorrunpage) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/connectors/{connector_id}/sync` {#sync-connector-v1-tenants-tenant-slug-connectors-connector-id-sync-post}

**Sync Connector**

Sync a connector now (``imports:edit``) and return the finished run.

A manual sync runs even when the connector is paused and is not limited by the tenant quota
(like Git "Refresh now"), but its pulls still count against it. A provider failure is not an
HTTP error: the run comes back ``failed`` with ``errorClass`` and ``httpStatus``. A kind with
no source on this deployment, or a sync already running, is a 409.

Operation id: `sync_connector_v1_tenants__tenant_slug__connectors__connector_id__sync_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for sync connector. | `application/json` [`ConnectorRunOut`](#schema-connectorrunout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ConnectorCreate` {#schema-connectorcreate}

``POST /v1/tenants/{t}/connectors``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | enum `"kong-konnect"`, `"kong-admin"`, `"aws-apigateway"`, `"azure-apim"`, `"apigee"`, `"url"`, … | yes | Kind. |
| `name` | string | yes | Human-readable name. |
| `baseUrl` | string or null | no | Base URL. |
| `scope` | object | no | Kind-specific coordinates; never secrets. `kong-konnect`: `{"region": "us"\|"eu"\|"au"\|"me"\|"in"\|"sg", "controlPlanes": ["<control plane id>", …]}` (no control planes = every control plane the token can read). `kong-admin`: `{"workspace": "…", "environment": "…"}`, both optional. `aws-apigateway`: `{"roleArn": "arn:aws:iam::<account>:role/…", "externalId": "…", "regions": ["eu-west-1", …]}` (no base URL, no credential: Apiome assumes the role). `azure-apim`: `{"tenantId": "<guid>", "clientId": "<guid>", "subscriptionId": "<guid>", "resourceGroup": "…", "serviceName": "…", "authMethod": "client-secret"\|"federated", "includeNonCurrentRevisions": false}` (no base URL; the client secret goes in `PUT …/credentials` as `{"clientSecret": "…"}`). Kinds with a source check their scope on every write, and some dry-run it. |
| `refreshIntervalSeconds` | integer or null | no | Refresh Interval Seconds. |
| `conflictPolicy` | enum `"overwrite"`, `"hold-for-review"`, `"new-branch"` | no | Conflict Policy. |
| `status` | enum `"active"`, `"paused"` | no | Status. |

### `ConnectorCredentialsOut` {#schema-connectorcredentialsout}

What ``PUT …/credentials`` returns: that a credential is stored, never what it is.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `connectorId` | string | yes | Connector ID. |
| `hasCredentials` | boolean | yes | Has Credentials. |
| `fields` | array of string | yes | The names of the stored fields, never their values. |
| `replacedAt` | string or null | no | Replaced At. |

### `ConnectorCredentialsPut` {#schema-connectorcredentialsput}

``PUT /v1/tenants/{t}/connectors/{id}/credentials``: replaces the whole credential.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `credentials` | map of string (password) | yes | The secret fields the connector's kind needs (for example `{"token": "…"}` or `{"accessKeyId": "…", "secretAccessKey": "…"}`). Sealed on arrival and never returned. |

### `ConnectorItemPage` {#schema-connectoritempage}

``GET /v1/tenants/{t}/connectors/{id}/items``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `ConnectorItemOut` | yes | Items. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `ConnectorListResponse` {#schema-connectorlistresponse}

``GET /v1/tenants/{t}/connectors``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `connectors` | array of [`ConnectorOut`](#schema-connectorout) | yes | Connectors. |
| `kinds` | array of string | yes | Kinds. |
| `syncableKinds` | array of string | yes | Syncable Kinds. |

### `ConnectorOut` {#schema-connectorout}

A connector, described. Never carries a credential.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `kind` | string | yes | Kind. |
| `name` | string | yes | Human-readable name. |
| `baseUrl` | string or null | no | Base URL. |
| `scope` | object | no | Scope. |
| `refreshIntervalSeconds` | integer or null | no | Refresh Interval Seconds. |
| `conflictPolicy` | string | yes | Conflict Policy. |
| `status` | string | yes | Status. |
| `hasCredentials` | boolean | yes | Has Credentials. |
| `syncable` | boolean | yes | Whether this deployment has a source for the kind, so a sync can run. |
| `lastRunAt` | string or null | no | Last Run At. |
| `createdBy` | string or null | no | Created By. |
| `createdAt` | string or null | no | Created At. |
| `updatedAt` | string or null | no | Updated At. |

### `ConnectorRunOut` {#schema-connectorrunout}

One sync run of a connector (a row of the shared refresh ledger).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `connectorId` | string | yes | Connector ID. |
| `refreshSource` | string | yes | Refresh Source. |
| `trigger` | string or null | no | Trigger. |
| `status` | string | yes | Status. |
| `errorClass` | string or null | no | Error Class. |
| `httpStatus` | integer or null | no | HTTP Status. |
| `errorMessage` | string or null | no | Error Message. |
| `pullCount` | integer | no | Number of pull. |
| `summary` | object | no | Short summary suitable for navigation and reference docs. |
| `createdBy` | string or null | no | Created By. |
| `startedAt` | string or null | no | Started At. |
| `finishedAt` | string or null | no | Finished At. |

### `ConnectorRunPage` {#schema-connectorrunpage}

``GET /v1/tenants/{t}/connectors/{id}/runs``: newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`ConnectorRunOut`](#schema-connectorrunout) | yes | Runs. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `ConnectorUpdate` {#schema-connectorupdate}

``PATCH /v1/tenants/{t}/connectors/{id}``. The kind cannot change.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `baseUrl` | string or null | no | Base URL. |
| `scope` | object or null | no | Kind-specific coordinates; never secrets. `kong-konnect`: `{"region": "us"\|"eu"\|"au"\|"me"\|"in"\|"sg", "controlPlanes": ["<control plane id>", …]}` (no control planes = every control plane the token can read). `kong-admin`: `{"workspace": "…", "environment": "…"}`, both optional. `aws-apigateway`: `{"roleArn": "arn:aws:iam::<account>:role/…", "externalId": "…", "regions": ["eu-west-1", …]}` (no base URL, no credential: Apiome assumes the role). `azure-apim`: `{"tenantId": "<guid>", "clientId": "<guid>", "subscriptionId": "<guid>", "resourceGroup": "…", "serviceName": "…", "authMethod": "client-secret"\|"federated", "includeNonCurrentRevisions": false}` (no base URL; the client secret goes in `PUT …/credentials` as `{"clientSecret": "…"}`). Kinds with a source check their scope on every write, and some dry-run it. |
| `refreshIntervalSeconds` | integer or null | no | Refresh Interval Seconds. |
| `conflictPolicy` | enum `"overwrite"`, `"hold-for-review"`, `"new-branch"` or null | no | Conflict Policy. |
| `status` | enum `"active"`, `"paused"` or null | no | Status. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
