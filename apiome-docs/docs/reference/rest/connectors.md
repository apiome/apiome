---
title: "Connectors"
description: "REST endpoints tagged connectors: 16 operations."
sidebar_position: 17
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.241.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `connectors` · 16 operations

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

## `POST /v1/tenants/{tenant_slug}/connectors/dry-run` {#dry-run-connector-route-v1-tenants-tenant-slug-connectors-dry-run-post}

**Dry Run Connector Route**

Ask the provider once what a connector would sync, storing nothing (``imports:create``).

The add-connector flow calls this before saving: the kind, base URL, scope and credentials are
checked exactly as on create, then the source lists its inventory and the answer is the item
count, a sample of up to 20 items and the source's findings. The credentials are used for this
call only — never stored, logged or returned. A provider refusal is a 422
``connector-check-failed`` whose ``reason`` is the error class (``auth``, ``not-found``, …) and whose
message is the provider's; a kind with no source on this deployment is a 409.

Operation id: `dry_run_connector_route_v1_tenants__tenant_slug__connectors_dry_run_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for dry run connector route.

- `application/json` — [`ConnectorDryRunRequest`](#schema-connectordryrunrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for dry run connector route. | `application/json` [`ConnectorDryRunOut`](#schema-connectordryrunout) |
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

## `POST /v1/tenants/{tenant_slug}/connectors/{connector_id}/items/{item_id}/ignore` {#ignore-connector-item-v1-tenants-tenant-slug-connectors-connector-id-items-item-id-ignore-post}

**Ignore Connector Item**

Ignore an inventory row, with a reason (``imports:edit``).

An ignored row is never fetched by a sync and leaves the report's Shadow and Possible-matches
sections. Its reason is kept, with the hosts and base path it had: when the gateway serves it
somewhere else, the report shows it again with the reason beside it.

Operation id: `ignore_connector_item_v1_tenants__tenant_slug__connectors__connector_id__items__item_id__ignore_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `item_id` | path | string (uuid) | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for ignore connector item.

- `application/json` — [`ConnectorItemIgnore`](#schema-connectoritemignore)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ignore connector item. | `application/json` [`ConnectorItemOut`](#schema-connectoritemout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/connectors/{connector_id}/items/{item_id}/import` {#import-connector-item-v1-tenants-tenant-slug-connectors-connector-id-items-item-id-import-post}

**Import Connector Item**

Import one inventory row now (``imports:edit``) and return the finished run.

The connector syncs with only this API selected: its inventory is listed as usual, and this
API is fetched and imported even when it is ignored, not newer than its last import, or a
revision the connector would not import by default. A kind with no source on this deployment,
or a sync already running, is a 409.

Operation id: `import_connector_item_v1_tenants__tenant_slug__connectors__connector_id__items__item_id__import_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `item_id` | path | string (uuid) | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for import connector item. | `application/json` [`ConnectorRunOut`](#schema-connectorrunout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/connectors/{connector_id}/items/{item_id}/link` {#link-connector-item-v1-tenants-tenant-slug-connectors-connector-id-items-item-id-link-post}

**Link Connector Item**

Link an inventory row to a catalog item or Project (``imports:edit``).

The row becomes ``imported``, and the gateway's current revision becomes its freshness anchor,
so drift is measured from now. The target must be a live catalog item or Project of the tenant
(404 otherwise). Linking is always a person's decision: the shadow-API report only suggests.

Operation id: `link_connector_item_v1_tenants__tenant_slug__connectors__connector_id__items__item_id__link_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `item_id` | path | string (uuid) | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for link connector item.

- `application/json` — [`ConnectorItemLink`](#schema-connectoritemlink)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for link connector item. | `application/json` [`ConnectorItemOut`](#schema-connectoritemout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/connectors/{connector_id}/items/{item_id}/unignore` {#unignore-connector-item-v1-tenants-tenant-slug-connectors-connector-id-items-item-id-unignore-post}

**Unignore Connector Item**

Stop ignoring an inventory row (``imports:edit``); its reason is cleared.

Operation id: `unignore_connector_item_v1_tenants__tenant_slug__connectors__connector_id__items__item_id__unignore_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector_id` | path | string (uuid) | yes | Path parameter identifying the connector id segment. |
| `item_id` | path | string (uuid) | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unignore connector item. | `application/json` [`ConnectorItemOut`](#schema-connectoritemout) |
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

## `GET /v1/tenants/{tenant_slug}/refresh-runs` {#list-refresh-runs-v1-tenants-tenant-slug-refresh-runs-get}

**List Refresh Runs**

The refresh ledger: Git refresh jobs and connector runs, interleaved newest first (``imports:view``).

Each run says its ``source`` — ``git`` (with the repository, branch and path) or ``connector`` (with
the connector's name and kind) — so one list can badge both. ``connector`` narrows it to one
connector (a 404 for an unknown one).

Operation id: `list_refresh_runs_v1_tenants__tenant_slug__refresh_runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector` | query | string (uuid) or null | no | Only this connector's runs. |
| `source` | query | string or null | no | git \| connector (both when omitted). |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list refresh runs. | `application/json` [`RefreshRunPage`](#schema-refreshrunpage) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/shadow-report` {#get-shadow-report-v1-tenants-tenant-slug-shadow-report-get}

**Get Shadow Report**

The shadow-API report (``imports:view``).

**Shadow** lists gateway APIs with no catalog item and no plausible match; **possibleMatches**
lists those that look like a catalog item or published Project, with the match tier and
confidence (link one with ``POST …/connectors/{id}/items/{itemId}/link``); **undeployed** lists
described APIs with HTTP servers that no connected gateway serves; **drift** lists linked APIs
whose deployed revision the catalog does not have; **ignored** lists ignored rows with their
reasons. An unknown connector id is a 404.

Operation id: `get_shadow_report_v1_tenants__tenant_slug__shadow_report_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `connector` | query | string (uuid) or null | no | Only this connector's inventory. |
| `environment` | query | string or null | no | Only inventory rows in this environment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get shadow report. | `application/json` [`ShadowReport`](#schema-shadowreport) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ConnectorCreate` {#schema-connectorcreate}

``POST /v1/tenants/{t}/connectors``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | enum `"kong-konnect"`, `"kong-admin"`, `"aws-apigateway"`, `"azure-apim"`, `"apigee"`, `"url"`, … | yes | Kind. |
| `name` | string | yes | Human-readable name. |
| `baseUrl` | string or null | no | Base URL. |
| `scope` | object | no | Kind-specific coordinates; never secrets. `kong-konnect`: `{"region": "us"\|"eu"\|"au"\|"me"\|"in"\|"sg", "controlPlanes": ["<control plane id>", …]}` (no control planes = every control plane the token can read). `kong-admin`: `{"workspace": "…", "environment": "…"}`, both optional. `aws-apigateway`: `{"roleArn": "arn:aws:iam::<account>:role/…", "externalId": "…", "regions": ["eu-west-1", …]}` (no base URL, no credential: Apiome assumes the role). `azure-apim`: `{"tenantId": "<guid>", "clientId": "<guid>", "subscriptionId": "<guid>", "resourceGroup": "…", "serviceName": "…", "authMethod": "client-secret"\|"federated", "includeNonCurrentRevisions": false}` (no base URL; the client secret goes in `PUT …/credentials` as `{"clientSecret": "…"}`). `apigee`: `{"organization": "…", "environments": ["test", …]}` (environments optional; the service-account key or workload-identity configuration goes in `PUT …/credentials` as `{"credentialJson": "…"}`). Kinds with a source check their scope on every write, and some dry-run it. |
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

### `ConnectorDryRunOut` {#schema-connectordryrunout}

The dry run's answer: how many APIs the connector would sync, and a sample of them.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `itemCount` | integer | yes | Number of item. |
| `items` | array of `ConnectorDryRunItem` | yes | Items. |
| `truncated` | boolean | yes | True when more APIs exist than the sample lists. |
| `findings` | array of object | no | Findings. |

### `ConnectorDryRunRequest` {#schema-connectordryrunrequest}

``POST /v1/tenants/{t}/connectors/dry-run``: what a connector would be, nothing stored.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | enum `"kong-konnect"`, `"kong-admin"`, `"aws-apigateway"`, `"azure-apim"`, `"apigee"`, `"url"`, … | yes | Kind. |
| `baseUrl` | string or null | no | Base URL. |
| `scope` | object | no | Kind-specific coordinates; never secrets. `kong-konnect`: `{"region": "us"\|"eu"\|"au"\|"me"\|"in"\|"sg", "controlPlanes": ["<control plane id>", …]}` (no control planes = every control plane the token can read). `kong-admin`: `{"workspace": "…", "environment": "…"}`, both optional. `aws-apigateway`: `{"roleArn": "arn:aws:iam::<account>:role/…", "externalId": "…", "regions": ["eu-west-1", …]}` (no base URL, no credential: Apiome assumes the role). `azure-apim`: `{"tenantId": "<guid>", "clientId": "<guid>", "subscriptionId": "<guid>", "resourceGroup": "…", "serviceName": "…", "authMethod": "client-secret"\|"federated", "includeNonCurrentRevisions": false}` (no base URL; the client secret goes in `PUT …/credentials` as `{"clientSecret": "…"}`). `apigee`: `{"organization": "…", "environments": ["test", …]}` (environments optional; the service-account key or workload-identity configuration goes in `PUT …/credentials` as `{"credentialJson": "…"}`). Kinds with a source check their scope on every write, and some dry-run it. |
| `credentials` | map of string (password) or null | no | The credential fields the kind needs, used for this call only and never stored or returned. |

### `ConnectorItemIgnore` {#schema-connectoritemignore}

``POST …/connectors/{id}/items/{itemId}/ignore``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `reason` | string | yes | Why this API is not described in the catalog. |

### `ConnectorItemLink` {#schema-connectoritemlink}

``POST …/connectors/{id}/items/{itemId}/link``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `catalogItemId` | string (uuid) | yes | The catalog item or Project this API is (a project id of the tenant). |

### `ConnectorItemOut` {#schema-connectoritemout}

One remote API in a connector's inventory.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `remoteId` | string | yes | Remote ID. |
| `remoteName` | string or null | no | Remote Name. |
| `environment` | string or null | no | Environment. |
| `hosts` | array of string | no | Hosts. |
| `basePath` | string or null | no | Base Path. |
| `remoteRevision` | string or null | no | Remote Revision. |
| `remoteUpdatedAt` | string or null | no | Remote Updated At. |
| `importedRevision` | string or null | no | Imported Revision. |
| `status` | string | yes | Status. |
| `catalogItemId` | string or null | no | Catalog Item ID. |
| `firstSeenAt` | string or null | no | First Seen At. |
| `lastSeenAt` | string or null | no | Last Seen At. |
| `deployment` | object | no | Where and how the provider serves this API, as the latest sync saw it. Kong connectors record `controlPlaneId`, `controlPlaneName`, `tags`, `enabled`, `protocols`, `hosts`, `paths`, `updatedAt` and `suggestedOwners` (from `owner:<team-slug>` tags; suggestions only, never confirmed owners). |
| `ignoredReason` | string or null | no | Why the item was ignored in the shadow-API report (CDG-1.6). |
| `ignoredAt` | string or null | no | Ignored At. |
| `linkedAt` | string or null | no | When a person linked the item to a catalog item or Project; null for a sync import. |

### `ConnectorItemPage` {#schema-connectoritempage}

``GET /v1/tenants/{t}/connectors/{id}/items``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of [`ConnectorItemOut`](#schema-connectoritemout) | yes | Items. |
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
| `scope` | object or null | no | Kind-specific coordinates; never secrets. `kong-konnect`: `{"region": "us"\|"eu"\|"au"\|"me"\|"in"\|"sg", "controlPlanes": ["<control plane id>", …]}` (no control planes = every control plane the token can read). `kong-admin`: `{"workspace": "…", "environment": "…"}`, both optional. `aws-apigateway`: `{"roleArn": "arn:aws:iam::<account>:role/…", "externalId": "…", "regions": ["eu-west-1", …]}` (no base URL, no credential: Apiome assumes the role). `azure-apim`: `{"tenantId": "<guid>", "clientId": "<guid>", "subscriptionId": "<guid>", "resourceGroup": "…", "serviceName": "…", "authMethod": "client-secret"\|"federated", "includeNonCurrentRevisions": false}` (no base URL; the client secret goes in `PUT …/credentials` as `{"clientSecret": "…"}`). `apigee`: `{"organization": "…", "environments": ["test", …]}` (environments optional; the service-account key or workload-identity configuration goes in `PUT …/credentials` as `{"credentialJson": "…"}`). Kinds with a source check their scope on every write, and some dry-run it. |
| `refreshIntervalSeconds` | integer or null | no | Refresh Interval Seconds. |
| `conflictPolicy` | enum `"overwrite"`, `"hold-for-review"`, `"new-branch"` or null | no | Conflict Policy. |
| `status` | enum `"active"`, `"paused"` or null | no | Status. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `RefreshRunPage` {#schema-refreshrunpage}

``GET /v1/tenants/{t}/refresh-runs``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of `RefreshRunOut` | yes | Runs. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `ShadowReport` {#schema-shadowreport}

``GET /v1/tenants/{t}/shadow-report``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `generatedAt` | string | yes | Generated At. |
| `filters` | map of string or null | yes | Filters. |
| `connectors` | array of `ShadowConnector` | yes | Connectors. |
| `stale` | array of `ShadowStale` | yes | Stale. |
| `summary` | `ShadowSummary` | yes | Short summary suitable for navigation and reference docs. |
| `shadow` | array of `ShadowItem` | yes | Shadow. |
| `possibleMatches` | array of `ShadowItem` | yes | Possible Matches. |
| `undeployed` | array of `ShadowUndeployed` | yes | Undeployed. |
| `drift` | array of `ShadowItem` | yes | Drift. |
| `ignored` | array of `ShadowItem` | yes | Ignored. |
