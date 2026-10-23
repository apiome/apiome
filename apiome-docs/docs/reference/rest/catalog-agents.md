---
title: "Catalog agents"
description: "REST endpoints tagged catalog-agents: 12 operations."
sidebar_position: 12
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.298.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `catalog-agents` · 12 operations

## `GET /v1/tenants/{tenant_slug}/catalog-agents` {#list-catalog-agents-v1-tenants-tenant-slug-catalog-agents-get}

**List agents**

The tenant's live agents with their model (and its deprecation) and owner (`consumer_contracts:view`).

Operation id: `list_catalog_agents_v1_tenants__tenant_slug__catalog_agents_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list agents. | `application/json` [`AgentList`](#schema-agentlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/catalog-agents` {#create-catalog-agent-v1-tenants-tenant-slug-catalog-agents-post}

**Register an agent**

Register an agent, optionally with its agent keys (`consumer_contracts:create`, plus `api_keys:view` for keys).

The agent becomes a consumer of every project its keys' toolsets reach, with a contract (source
`agent`) holding the operations those keys may call; the graph derives one `consumes` edge per
operation. `slug` is derived from `name` when omitted. A key must be a live agent key of the
workspace that no other agent uses (409 `agent-key-taken`).

Operation id: `create_catalog_agent_v1_tenants__tenant_slug__catalog_agents_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register an agent.

- `application/json` — [`AgentInput`](#schema-agentinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for register an agent. | `application/json` [`AgentOut`](#schema-agentout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/catalog-agents/{slug}` {#read-catalog-agent-v1-tenants-tenant-slug-catalog-agents-slug-get}

**Read an agent**

One agent: model, owner, keys (prefix and status only), and the consumer it is per project.

Operation id: `read_catalog_agent_v1_tenants__tenant_slug__catalog_agents__slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read an agent. | `application/json` [`AgentOut`](#schema-agentout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/catalog-agents/{slug}` {#update-catalog-agent-v1-tenants-tenant-slug-catalog-agents-slug-patch}

**Change an agent**

Change an agent's name, description, runtime, model (`null` clears it) or status (`consumer_contracts:edit`).

Retiring an agent (`status: retired`) records empty contracts, so its `consumes` edges go stale.

Operation id: `update_catalog_agent_v1_tenants__tenant_slug__catalog_agents__slug__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change an agent.

- `application/json` — [`AgentPatch`](#schema-agentpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change an agent. | `application/json` [`AgentOut`](#schema-agentout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/catalog-agents/{slug}` {#delete-catalog-agent-v1-tenants-tenant-slug-catalog-agents-slug-delete}

**Delete an agent**

Soft-delete an agent (`consumer_contracts:delete`); its contracts are emptied and its edges go stale.

Operation id: `delete_catalog_agent_v1_tenants__tenant_slug__catalog_agents__slug__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete an agent. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/catalog-agents/{slug}/keys/{key_id}` {#link-catalog-agent-key-v1-tenants-tenant-slug-catalog-agents-slug-keys-key-id-put}

**Link an agent key**

Add an agent key to the agent and re-derive its consumers (`consumer_contracts:edit` + `api_keys:view`).

Operation id: `link_catalog_agent_key_v1_tenants__tenant_slug__catalog_agents__slug__keys__key_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `key_id` | path | string | yes | Path parameter identifying the key id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for link an agent key. | `application/json` [`AgentOut`](#schema-agentout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/catalog-agents/{slug}/keys/{key_id}` {#unlink-catalog-agent-key-v1-tenants-tenant-slug-catalog-agents-slug-keys-key-id-delete}

**Unlink an agent key**

Remove an agent key from the agent (`consumer_contracts:edit`); what only it allowed goes stale.

Operation id: `unlink_catalog_agent_key_v1_tenants__tenant_slug__catalog_agents__slug__keys__key_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `key_id` | path | string | yes | Path parameter identifying the key id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unlink an agent key. | `application/json` [`AgentOut`](#schema-agentout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/catalog-models` {#list-catalog-models-v1-tenants-tenant-slug-catalog-models-get}

**List models**

The tenant's live models with their deprecation and owner (`consumer_contracts:view`).

Operation id: `list_catalog_models_v1_tenants__tenant_slug__catalog_models_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list models. | `application/json` [`ModelList`](#schema-modellist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/catalog-models` {#create-catalog-model-v1-tenants-tenant-slug-catalog-models-post}

**Register a model**

Register a model: provider, name and version, hosting (`api` or `self_hosted`), data handling, deprecation.

Operation id: `create_catalog_model_v1_tenants__tenant_slug__catalog_models_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register a model.

- `application/json` — [`ModelInput`](#schema-modelinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for register a model. | `application/json` [`ModelOut`](#schema-modelout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/catalog-models/{slug}` {#read-catalog-model-v1-tenants-tenant-slug-catalog-models-slug-get}

**Read a model**

One model with the live agents that run on it.

Operation id: `read_catalog_model_v1_tenants__tenant_slug__catalog_models__slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a model. | `application/json` [`ModelOut`](#schema-modelout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/catalog-models/{slug}` {#update-catalog-model-v1-tenants-tenant-slug-catalog-models-slug-patch}

**Change a model**

Change a model (`consumer_contracts:edit`); `deprecatedAt` shows on every agent that runs on it.

Operation id: `update_catalog_model_v1_tenants__tenant_slug__catalog_models__slug__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change a model.

- `application/json` — [`ModelPatch`](#schema-modelpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change a model. | `application/json` [`ModelOut`](#schema-modelout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/catalog-models/{slug}` {#delete-catalog-model-v1-tenants-tenant-slug-catalog-models-slug-delete}

**Delete a model**

Soft-delete a model (`consumer_contracts:delete`); agents that ran on it show no model.

Operation id: `delete_catalog_model_v1_tenants__tenant_slug__catalog_models__slug__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a model. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AgentInput` {#schema-agentinput}

Register an agent.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string or null | no | Derived from `name` when omitted. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `runtime` | string or null | no | Framework or host (LangGraph, a Lambda, …). |
| `model` | string or null | no | The slug of the model it runs on. |
| `keyIds` | array of string | no | Agent keys (AGX-3.1) the agent uses. |

### `AgentList` {#schema-agentlist}

The tenant's live agents.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `agents` | array of [`AgentOut`](#schema-agentout) | yes | Agents. |

### `AgentOut` {#schema-agentout}

An agent.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `runtime` | string or null | no | Runtime. |
| `status` | string | yes | Status. |
| `model` | `AgentModelRef` or null | no | Model. |
| `owner` | `EntityOwnerRef` or null | no | Owner. |
| `keys` | array of `AgentKeyRef` | no | Keys. |
| `consumers` | array of `AgentConsumerRef` | no | Consumers. |
| `usageHref` | string | no | The agent usage page. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |

### `AgentPatch` {#schema-agentpatch}

Change an agent; an omitted field is kept, `model: null` clears the model.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `runtime` | string or null | no | Runtime. |
| `model` | string or null | no | Model. |
| `status` | string or null | no | `active` or `retired`; a retired agent consumes nothing. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ModelInput` {#schema-modelinput}

Register a model.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string or null | no | Derived from `name` when omitted. |
| `name` | string or null | no | Display name; defaults to `modelName`. |
| `provider` | string | yes | Anthropic, OpenAI, Mistral, an internal team… |
| `modelName` | string | yes | Model Name. |
| `modelVersion` | string or null | no | Model Version. |
| `hosting` | string | no | `api` (a provider's API) or `self_hosted`. |
| `dataHandling` | string or null | no | What the provider retains, where data is processed, opt-outs. |
| `deprecatedAt` | string (date-time) or null | no | When the model is (or was) deprecated. |

### `ModelList` {#schema-modellist}

The tenant's live models.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `models` | array of [`ModelOut`](#schema-modelout) | yes | Models. |

### `ModelOut` {#schema-modelout}

A model.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `provider` | string | yes | Provider. |
| `modelName` | string | yes | Model Name. |
| `modelVersion` | string or null | no | Model Version. |
| `hosting` | string | yes | Hosting. |
| `dataHandling` | string or null | no | Data Handling. |
| `deprecatedAt` | string (date-time) or null | no | Deprecated At. |
| `deprecated` | boolean | yes | Whether `deprecatedAt` has arrived. |
| `owner` | `EntityOwnerRef` or null | no | Owner. |
| `agents` | array of `AgentRef` | no | Live agents that run on this model. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |

### `ModelPatch` {#schema-modelpatch}

Change a model; an omitted field is kept, `deprecatedAt: null` clears the date.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `provider` | string or null | no | Provider. |
| `modelName` | string or null | no | Model Name. |
| `modelVersion` | string or null | no | Model Version. |
| `hosting` | string or null | no | Hosting. |
| `dataHandling` | string or null | no | Data Handling. |
| `deprecatedAt` | string (date-time) or null | no | Deprecated At. |
