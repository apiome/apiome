---
title: "Agent access"
description: "REST endpoints tagged agent-access: 22 operations."
sidebar_position: 4
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `agent-access` · 22 operations

## `GET /v1/tenants/{tenant_slug}/agent-keys` {#list-agent-keys-route-v1-tenants-tenant-slug-agent-keys-get}

**List agent keys**

An agent key is the credential an AI agent presents to Apiome's MCP agent runtime. It is bound to one agent toolset, may only list and call the tools named in its allowlist (and enabled in the toolset), and can expire. It is not a REST credential: the REST API refuses it on every route.

Responses carry metadata only (name, prefix, toolset, allowlist, status, timestamps); the secret is returned once, by create, and never again.

Newest first. `toolsetId` narrows the list to one toolset's keys; revoked keys are left out unless `includeRevoked=true`.

Requires `api_keys:view`.

Operation id: `list_agent_keys_route_v1_tenants__tenant_slug__agent_keys_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolsetId` | query | string (uuid) or null | no | Query parameter: toolset id. |
| `includeRevoked` | query | boolean | no | Query parameter: include revoked. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list agent keys. | `application/json` [`AgentKeyListResponse`](#schema-agentkeylistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/agent-keys` {#create-agent-key-route-v1-tenants-tenant-slug-agent-keys-post}

**Create an agent key**

An agent key is the credential an AI agent presents to Apiome's MCP agent runtime. It is bound to one agent toolset, may only list and call the tools named in its allowlist (and enabled in the toolset), and can expire. It is not a REST credential: the REST API refuses it on every route.

The body names the key, the `toolsetId` it is bound to, its `toolAllowlist` (MCP tool names, `^[A-Za-z0-9_-]{1,64}$`, at most 1024; no wildcard, and an empty list permits nothing) and an optional future `expiresAt`.

The response includes `secret` (`ak_…`): **it is shown only once**. Present it to the MCP agent runtime as `Authorization: Bearer <secret>`.

Requires `api_keys:create`. Audited as `agent.key.create`.

Operation id: `create_agent_key_route_v1_tenants__tenant_slug__agent_keys_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create an agent key.

- `application/json` — [`AgentKeyCreate`](#schema-agentkeycreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create an agent key. | `application/json` [`AgentKeyCreated`](#schema-agentkeycreated) |
| 404 | No such agent toolset in this tenant. | — |
| 409 | The tenant already has an API key with that name. | — |
| 422 | A tool name, the name or the expiry is not acceptable. | — |

## `GET /v1/tenants/{tenant_slug}/agent-keys/{key_id}` {#get-agent-key-route-v1-tenants-tenant-slug-agent-keys-key-id-get}

**Describe an agent key**

Responses carry metadata only (name, prefix, toolset, allowlist, status, timestamps); the secret is returned once, by create, and never again. Revoked keys are described too, with `status: revoked`.

Requires `api_keys:view`.

Operation id: `get_agent_key_route_v1_tenants__tenant_slug__agent_keys__key_id__get`

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
| 200 | Successful response for describe an agent key. | `application/json` [`AgentKeyOut`](#schema-agentkeyout) |
| 404 | No such agent key in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/agent-keys/{key_id}` {#revoke-agent-key-route-v1-tenants-tenant-slug-agent-keys-key-id-delete}

**Revoke an agent key**

Revoke the key. The MCP runtime checks the key on every request, so the agent's next request is refused. Revoking a revoked key is a no-op `204`; the key stays listable with `includeRevoked=true`.

Requires `api_keys:delete`. Audited once as `agent.key.revoke`.

Operation id: `revoke_agent_key_route_v1_tenants__tenant_slug__agent_keys__key_id__delete`

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
| 204 | Successful response for revoke an agent key. | — |
| 404 | No such agent key in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/agent-keys/{key_id}/allowlist` {#update-agent-key-allowlist-route-v1-tenants-tenant-slug-agent-keys-key-id-allowlist-put}

**Replace an agent key's tool allowlist**

Replace the whole allowlist with `toolAllowlist`. The MCP runtime reads it on every request, so the agent's next `tools/list` shows the new set and its next `tools/call` is judged against it.

Requires `api_keys:edit`. Audited as `agent.key.allowlist_update`, with the list before and after.

Operation id: `update_agent_key_allowlist_route_v1_tenants__tenant_slug__agent_keys__key_id__allowlist_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `key_id` | path | string (uuid) | yes | Path parameter identifying the key id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace an agent key's tool allowlist.

- `application/json` — [`AgentKeyAllowlistUpdate`](#schema-agentkeyallowlistupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace an agent key's tool allowlist. | `application/json` [`AgentKeyOut`](#schema-agentkeyout) |
| 404 | No such agent key in this tenant. | — |
| 409 | The key is revoked; its allowlist can no longer change. | — |
| 422 | An entry is not an MCP tool name. | — |

## `GET /v1/tenants/{tenant_slug}/agent-keys/{key_id}/usage` {#get-agent-key-usage-route-v1-tenants-tenant-slug-agent-keys-key-id-usage-get}

**Agent key usage vs caps**

An agent key's limits and how much of them it has used today (AGX-3.2). Both limits come from the tenant's license tier and change when the tier changes: `rps.cap` is the sustained calls per second (burst of one second's worth), `dailyCalls.cap` the calls per UTC day. `null` means unlimited.

`dailyCalls.used` counts today's (UTC) `tools/call` invocations recorded for the key, without calls refused by a limit. It is the same number the agent usage rollups report for the key and day. Over either limit, the MCP agent runtime refuses calls with an `agent_rate_limited` / `agent_daily_cap_reached` error that says when to retry.

Revoked keys are reported too. Requires `api_keys:view`.

Operation id: `get_agent_key_usage_route_v1_tenants__tenant_slug__agent_keys__key_id__usage_get`

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
| 200 | Successful response for agent key usage vs caps. | `application/json` [`AgentKeyUsageOut`](#schema-agentkeyusageout) |
| 404 | No such agent key in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/agent-toolsets` {#list-agent-toolsets-route-v1-tenants-tenant-slug-agent-toolsets-get}

**List agent toolsets**

An agent toolset is Agent Access for one published version: which of its operations AI agents may call as MCP tools. Reads (`GET`/`HEAD`, GraphQL queries) are exposed by default; write operations are opt-in, one at a time, with an explicit confirmation.

Newest first, with tool counts. `versionId` narrows the list to one version's toolset.

Requires `api_keys:view`.

Operation id: `list_agent_toolsets_route_v1_tenants__tenant_slug__agent_toolsets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `versionId` | query | string (uuid) or null | no | Query parameter: version id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list agent toolsets. | `application/json` [`AgentToolsetListResponse`](#schema-agenttoolsetlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/agent-toolsets` {#create-agent-toolset-route-v1-tenants-tenant-slug-agent-toolsets-post}

**Create an agent toolset for a published version**

An agent toolset is Agent Access for one published version: which of its operations AI agents may call as MCP tools. Reads (`GET`/`HEAD`, GraphQL queries) are exposed by default; write operations are opt-in, one at a time, with an explicit confirmation.

Creates the toolset for `versionId`, which must be a published, undeleted version in this tenant, and seeds one tool per callable operation: reads enabled (deprecated ones excepted), write operations disabled. `target` is `prod` (default) or `mock`; `enabled` defaults to `true`.

Requires `api_keys:create`. Audited as `agent.toolset.create`.

Operation id: `create_agent_toolset_route_v1_tenants__tenant_slug__agent_toolsets_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create an agent toolset for a published version.

- `application/json` — [`AgentToolsetCreate`](#schema-agenttoolsetcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create an agent toolset for a published version. | `application/json` [`AgentToolsetDetail`](#schema-agenttoolsetdetail) |
| 404 | No such version in this tenant. | — |
| 409 | The version is unpublished or deleted, or already has a toolset. | — |
| 422 | The version's operations could not be read. | — |

## `GET /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}` {#get-agent-toolset-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-get}

**Describe an agent toolset**

The toolset's settings and every tool row.

Requires `api_keys:view`.

Operation id: `get_agent_toolset_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for describe an agent toolset. | `application/json` [`AgentToolsetDetail`](#schema-agenttoolsetdetail) |
| 404 | No such agent toolset in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}` {#update-agent-toolset-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-patch}

**Change an agent toolset's settings**

Switch the whole toolset on or off (`enabled`; a disabled toolset exposes no tools) and/or change its `target` (`prod` | `mock`), and/or opt out of description enrichment (`descriptionEnrichment: false` serves the spec-derived descriptions even where a proposal was accepted). Tool selections are untouched.

Requires `api_keys:edit`. Audited as `agent.toolset.update`, before and after.

Operation id: `update_agent_toolset_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change an agent toolset's settings.

- `application/json` — [`AgentToolsetUpdate`](#schema-agenttoolsetupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change an agent toolset's settings. | `application/json` [`AgentToolsetOut`](#schema-agenttoolsetout) |
| 404 | No such agent toolset in this tenant. | — |
| 422 | The body changes nothing. | — |

## `DELETE /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}` {#delete-agent-toolset-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-delete}

**Delete an agent toolset**

Delete the toolset and its tool selections. **Its upstream credentials and agent keys are deleted with it**: an agent holding one of its keys is refused on its next request.

Requires `api_keys:delete`. Audited as `agent.toolset.delete`.

Operation id: `delete_agent_toolset_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete an agent toolset. | — |
| 404 | No such agent toolset in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/compiled` {#compile-agent-toolset-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-compiled-get}

**Compile an agent toolset**

The toolset as agents are served it: the enabled tools as MCP `tools/list` entries. While `descriptionEnrichment` is on, accepted description proposals replace the spec-derived text (`enrichedTargets` lists which); proposed and rejected ones never do. A disabled toolset compiles to no tools.

Requires `api_keys:view`.

Operation id: `compile_agent_toolset_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__compiled_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for compile an agent toolset. | `application/json` [`CompiledToolsetOut`](#schema-compiledtoolsetout) |
| 404 | No such agent toolset in this tenant. | — |
| 422 | The version's operations could not be read or compiled. | — |

## `GET /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/enrichment` {#get-agent-toolset-enrichment-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-enrichment-get}

**Describe an agent toolset's enrichment**

The enrichment pass looks for tools an agent will struggle with. Each flag lists machine-readable reasons: `missing-description`, `thin-description`, `missing-examples`, `undocumented-errors`, `missing-parameter-description`, `thin-parameter-description`. When the copilot (an Ollama model, `APIOME_AGENT_ENRICHMENT_MODEL`) is configured, it also proposes descriptions for the thin ones, written only from the spec's own documentation. **Proposals are never served until a person accepts them.** Without the copilot, `mode` is `flag-only`.

Requires `api_keys:view`.

Operation id: `get_agent_toolset_enrichment_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__enrichment_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for describe an agent toolset's enrichment. | `application/json` [`EnrichmentReport`](#schema-enrichmentreport) |
| 404 | No such agent toolset in this tenant. | — |
| 422 | The version's operations could not be read. | — |

## `POST /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/enrichment` {#run-agent-toolset-enrichment-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-enrichment-post}

**Run the enrichment pass**

The enrichment pass looks for tools an agent will struggle with. Each flag lists machine-readable reasons: `missing-description`, `thin-description`, `missing-examples`, `undocumented-errors`, `missing-parameter-description`, `thin-parameter-description`. When the copilot (an Ollama model, `APIOME_AGENT_ENRICHMENT_MODEL`) is configured, it also proposes descriptions for the thin ones, written only from the spec's own documentation. **Proposals are never served until a person accepts them.** Without the copilot, `mode` is `flag-only`.

The pass is idempotent: a description that already has a proposal, whatever its status, is not asked about again. Each run asks the copilot about at most 20 operations and reports `remainingOperations`; run it again to continue, or pass `operations` to choose which.

Requires `api_keys:edit`. Audited as `agent.toolset.enrichment.run`.

Operation id: `run_agent_toolset_enrichment_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__enrichment_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for run the enrichment pass.

- `application/json` — [`EnrichmentRun`](#schema-enrichmentrun) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for run the enrichment pass. | `application/json` [`EnrichmentRunResult`](#schema-enrichmentrunresult) |
| 404 | No such agent toolset in this tenant. | — |
| 422 | The version's operations could not be read, or `operations` names an operation the toolset does not have. | — |

## `PATCH /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/enrichment/{proposal_id}` {#review-agent-toolset-enrichment-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-enrichment-proposal-id-patch}

**Accept or reject a description proposal**

`decision: accept` serves the proposal in the compiled toolset; pass `description` to serve an edited text instead. `decision: reject` withdraws it, including a previously accepted one. The reviewer and time are recorded on the proposal.

Requires `api_keys:edit`. Audited as `agent.toolset.enrichment.review`.

Operation id: `review_agent_toolset_enrichment_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__enrichment__proposal_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `proposal_id` | path | string (uuid) | yes | Path parameter identifying the proposal id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for accept or reject a description proposal.

- `application/json` — [`EnrichmentReview`](#schema-enrichmentreview)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for accept or reject a description proposal. | `application/json` [`EnrichmentProposalOut`](#schema-enrichmentproposalout) |
| 404 | No such proposal in this tenant's agent toolset. | — |
| 422 | A blank or over-long edit, or an edit with `reject`. | — |

## `GET /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/tools` {#list-agent-toolset-tools-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-tools-get}

**List an agent toolset's tools**

One row per callable operation of the toolset's version, ordered by operation key: the MCP tool name, whether it is a write op, and whether it is exposed.

Requires `api_keys:view`.

Operation id: `list_agent_toolset_tools_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__tools_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list an agent toolset's tools. | `application/json` [`AgentToolListResponse`](#schema-agenttoollistresponse) |
| 404 | No such agent toolset in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/tools/{tool_id}` {#update-agent-toolset-tool-route-v1-tenants-tenant-slug-agent-toolsets-toolset-id-tools-tool-id-patch}

**Enable or disable one tool**

Set `enabled` on one tool. **Enabling a write operation requires `confirmWriteOp: true`**; without it the request is refused with `agent-toolset-write-op-unconfirmed` and nothing changes. The confirmation is recorded on the tool (`writeConfirmedBy`, `writeConfirmedAt`) and cleared when the tool is disabled, so re-enabling needs a fresh one.

Requires `api_keys:edit`. Audited as `agent.toolset.tool.update`.

Operation id: `update_agent_toolset_tool_route_v1_tenants__tenant_slug__agent_toolsets__toolset_id__tools__tool_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `tool_id` | path | string (uuid) | yes | Path parameter identifying the tool id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for enable or disable one tool.

- `application/json` — [`AgentToolUpdate`](#schema-agenttoolupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for enable or disable one tool. | `application/json` [`AgentToolOut`](#schema-agenttoolout) |
| 404 | No such tool in this tenant's agent toolset. | — |
| 422 | A write operation was enabled without `confirmWriteOp: true`. | — |

## `GET /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/upstream-credentials` {#list-upstream-credentials-v1-tenants-tenant-slug-agent-toolsets-toolset-id-upstream-credentials-get}

**List a toolset's upstream credentials (metadata only)**

The credentials the AGX-2.1 invocation proxy injects when this toolset calls its upstream APIs.

A credential is **write-only**: the secret is stored envelope-encrypted and no route ever returns it. Responses carry metadata only: the server URL it is bound to, its kind and placement, the master-key version that sealed it, whether it currently opens (`readable`), and when it was created, rotated and last used.

Requires `api_keys:view`.

Operation id: `list_upstream_credentials_v1_tenants__tenant_slug__agent_toolsets__toolset_id__upstream_credentials_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a toolset's upstream credentials (metadata only). | `application/json` [`UpstreamCredentialListResponse`](#schema-upstreamcredentiallistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/upstream-credentials` {#create-upstream-credential-v1-tenants-tenant-slug-agent-toolsets-toolset-id-upstream-credentials-post}

**Store an upstream credential for a toolset**

Bind a new credential to this toolset and one upstream server. The credential is only ever injected into requests under `serverUrl`: an `https://` origin plus an optional base path. `https://api.example.com/v1` covers `/v1` and `/v1/…` on that exact host and port, and nothing else.

Kinds: `apiKey` (sent as the header or query parameter named by `in` / `name`, secret `{value}`), `bearer` (`Authorization: Bearer`, secret `{token}`) and `basic` (`Authorization: Basic`, secret `{username, password}`).

A credential is **write-only**: the secret is stored envelope-encrypted and no route ever returns it. Responses carry metadata only: the server URL it is bound to, its kind and placement, the master-key version that sealed it, whether it currently opens (`readable`), and when it was created, rotated and last used.

One credential per toolset and server: storing a second is a `409`; rotate the existing one instead.

Requires `api_keys:create`. Audited as `agent.upstream_credential.create`, with metadata only.

Operation id: `create_upstream_credential_v1_tenants__tenant_slug__agent_toolsets__toolset_id__upstream_credentials_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for store an upstream credential for a toolset.

- `application/json` — [`UpstreamCredentialCreate`](#schema-upstreamcredentialcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for store an upstream credential for a toolset. | `application/json` [`UpstreamCredentialOut`](#schema-upstreamcredentialout) |
| 404 | No such agent toolset in this tenant. | — |
| 409 | This toolset already has a credential for that server. | — |
| 422 | The server URL, placement or secret is not acceptable. | — |
| 503 | No upstream-credential encryption key is configured. | — |

## `DELETE /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/upstream-credentials/{credential_id}` {#delete-upstream-credential-v1-tenants-tenant-slug-agent-toolsets-toolset-id-upstream-credentials-credential-id-delete}

**Delete an upstream credential**

Remove the credential. The toolset's next call to that server goes out without it. Its use history is kept.

Requires `api_keys:delete`. Audited as `agent.upstream_credential.delete`.

Operation id: `delete_upstream_credential_v1_tenants__tenant_slug__agent_toolsets__toolset_id__upstream_credentials__credential_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `credential_id` | path | string (uuid) | yes | Path parameter identifying the credential id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete an upstream credential. | — |
| 404 | No such credential for this toolset. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/upstream-credentials/{credential_id}/rotate` {#rotate-upstream-credential-v1-tenants-tenant-slug-agent-toolsets-toolset-id-upstream-credentials-credential-id-rotate-post}

**Rotate an upstream credential's secret**

Replace the secret in place, atomically. The credential keeps its id, binding and placement. Invocations already in flight finish with the secret they opened, and the next invocation uses the new one: no window without a credential.

The body is `{secret}`, in the same shape as at creation. A credential is **write-only**: the secret is stored envelope-encrypted and no route ever returns it. Responses carry metadata only: the server URL it is bound to, its kind and placement, the master-key version that sealed it, whether it currently opens (`readable`), and when it was created, rotated and last used.

Requires `api_keys:edit`. Audited as `agent.upstream_credential.rotate`.

Operation id: `rotate_upstream_credential_v1_tenants__tenant_slug__agent_toolsets__toolset_id__upstream_credentials__credential_id__rotate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `toolset_id` | path | string (uuid) | yes | Path parameter identifying the toolset id segment. |
| `credential_id` | path | string (uuid) | yes | Path parameter identifying the credential id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for rotate an upstream credential's secret.

- `application/json` — [`UpstreamCredentialRotate`](#schema-upstreamcredentialrotate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for rotate an upstream credential's secret. | `application/json` [`UpstreamCredentialOut`](#schema-upstreamcredentialout) |
| 404 | No such credential for this toolset. | — |
| 422 | The secret does not fit the credential's kind. | — |
| 503 | No upstream-credential encryption key is configured. | — |

## `GET /v1/tenants/{tenant_slug}/agent-usage` {#get-agent-usage-route-v1-tenants-tenant-slug-agent-usage-get}

**Agent usage rollups**

The tenant's agent `tools/call` usage over the last `days` UTC days, today included, from the daily rollups: `daily` (zero-filled, oldest first), `tools` and `agents` (most calls first) and `totals` with errors broken down by outcome.

`errors` counts every call that did not succeed, quota rejections included. Latency is the calls-weighted mean (`latencyAvgMs`) and the worst p95 among the rollup groups covered (`latencyP95MaxMs`); percentiles cannot be merged exactly.

`days` is 1–366 (default 30). Requires `api_keys:view`.

Operation id: `get_agent_usage_route_v1_tenants__tenant_slug__agent_usage_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `days` | query | integer | no | Query parameter: days. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for agent usage rollups. | `application/json` [`AgentUsageOut`](#schema-agentusageout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AgentKeyAllowlistUpdate` {#schema-agentkeyallowlistupdate}

Body of ``PUT /v1/tenants/{t}/agent-keys/{id}/allowlist``: the whole new list.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `toolAllowlist` | array of string | yes | Tool Allowlist. |

### `AgentKeyCreate` {#schema-agentkeycreate}

Body of ``POST /v1/tenants/{t}/agent-keys``.

Attributes:
    name: Human name, unique in the tenant (across workspace and agent keys, revoked included).
    description: Optional purpose note.
    toolset_id: The agent toolset the key is bound to.
    tool_allowlist: MCP tool names the key may list and call.
    expires_at: Optional expiry; must be in the future. A naive value is read as UTC.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `toolsetId` | string (uuid) | yes | Toolset ID. |
| `toolAllowlist` | array of string | yes | Tool Allowlist. |
| `expiresAt` | string (date-time) or null | no | Expires At. |

### `AgentKeyCreated` {#schema-agentkeycreated}

The create response: the key's metadata plus its plaintext secret, shown this once.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `id` | string | yes | Stable resource identifier. |
| `kind` | `"agent"` | no | Kind. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `keyPrefix` | string | yes | Key Prefix. |
| `toolsetId` | string | yes | Toolset ID. |
| `toolAllowlist` | array of string | yes | Tool Allowlist. |
| `status` | enum `"active"`, `"disabled"`, `"expired"`, `"revoked"` | yes | Status. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `expiresAt` | string (date-time) or null | no | Expires At. |
| `revokedAt` | string (date-time) or null | no | Revoked At. |
| `lastUsedAt` | string (date-time) or null | no | Last Used At. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `createdBy` | string or null | no | Created By. |
| `secret` | string | yes | The agent key. Shown only in this response; store it now. |

### `AgentKeyListResponse` {#schema-agentkeylistresponse}

A tenant's agent keys, described.

Attributes:
    schema_version: The projection's shape.
    keys: One entry per key, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `keys` | array of [`AgentKeyOut`](#schema-agentkeyout) | yes | Keys. |

### `AgentKeyOut` {#schema-agentkeyout}

An agent key, described. Never carries the secret or its hash.

Attributes:
    schema_version: The projection's shape.
    id: The key id.
    kind: Always ``agent``.
    name: Human name.
    description: Purpose note, if any.
    key_prefix: The first 12 characters of the secret plus ``...``, for recognising it.
    toolset_id: The toolset the key is bound to.
    tool_allowlist: The tool names it may use, sorted.
    status: ``active``, ``disabled``, ``expired`` or ``revoked`` (see :func:`key_status`).
    enabled: The key's enabled flag.
    expires_at: When it stops working, if ever.
    revoked_at: When it was revoked, if it was.
    last_used_at: When it last authenticated, if ever.
    created_at: When it was created.
    updated_at: When its row last changed.
    created_by: The user who created it, if known.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `id` | string | yes | Stable resource identifier. |
| `kind` | `"agent"` | no | Kind. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `keyPrefix` | string | yes | Key Prefix. |
| `toolsetId` | string | yes | Toolset ID. |
| `toolAllowlist` | array of string | yes | Tool Allowlist. |
| `status` | enum `"active"`, `"disabled"`, `"expired"`, `"revoked"` | yes | Status. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `expiresAt` | string (date-time) or null | no | Expires At. |
| `revokedAt` | string (date-time) or null | no | Revoked At. |
| `lastUsedAt` | string (date-time) or null | no | Last Used At. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `createdBy` | string or null | no | Created By. |

### `AgentKeyUsageOut` {#schema-agentkeyusageout}

An agent key's current usage against its license-tier caps.

Attributes:
    schema_version: The projection's shape.
    key_id: The key.
    license_type: The tenant's license tier (``free`` / ``paid`` / ``sponsor``), or ``None``
        without a license (Free caps apply).
    rps: The rate limit.
    daily_calls: The daily cap and today's usage.
    as_of: When this was computed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `keyId` | string | yes | Key ID. |
| `licenseType` | string or null | no | License Type. |
| `rps` | `AgentKeyRateLimit` | yes | Rps. |
| `dailyCalls` | `AgentKeyDailyCalls` | yes | Daily Calls. |
| `asOf` | string (date-time) | yes | As Of. |

### `AgentToolListResponse` {#schema-agenttoollistresponse}

A toolset's tool rows.

Attributes:
    schema_version: The projection's shape.
    toolset_id: The toolset addressed.
    tools: One entry per callable operation, ordered by operation key.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `toolsetId` | string | yes | Toolset ID. |
| `tools` | array of [`AgentToolOut`](#schema-agenttoolout) | yes | Tools. |

### `AgentToolOut` {#schema-agenttoolout}

One operation's exposure decision.

Attributes:
    id: The tool row id (what the update route addresses).
    operation: The canonical operation key (``GET /pets/{id}``).
    tool_name: The MCP tool name agents see.
    write_op: Whether the operation mutates. A write op is opt-in.
    enabled: Whether agents may list and call it.
    write_confirmed_at: When enabling this write op was confirmed (only while enabled).
    write_confirmed_by: Who confirmed it.
    updated_at: When the row last changed.
    updated_by: Who last changed it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `operation` | string | yes | HTTP method name (GET, POST, PUT, PATCH, DELETE, …). |
| `toolName` | string | yes | Tool Name. |
| `writeOp` | boolean | yes | Write Op. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `writeConfirmedAt` | string (date-time) or null | no | Write Confirmed At. |
| `writeConfirmedBy` | string or null | no | Write Confirmed By. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |

### `AgentToolUpdate` {#schema-agenttoolupdate}

Body of ``PATCH /v1/tenants/{t}/agent-toolsets/{id}/tools/{toolId}``.

Attributes:
    enabled: Expose the operation to agents, or stop exposing it.
    confirm_write_op: Must be ``true`` to enable a write op. It is ignored when disabling,
        and when enabling a read.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | yes | Whether the resource is active. |
| `confirmWriteOp` | boolean | no | Confirm Write Op. |

### `AgentToolsetCreate` {#schema-agenttoolsetcreate}

Body of ``POST /v1/tenants/{t}/agent-toolsets``.

Attributes:
    version_id: The published version (``versions.id``) to give Agent Access.
    enabled: Whether the toolset serves agents straight away (default ``True``).
    target: ``prod`` (default) or ``mock``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `versionId` | string (uuid) | yes | Version ID. |
| `enabled` | boolean | no | Whether the resource is active. |
| `target` | enum `"prod"`, `"mock"` | no | Target. |

### `AgentToolsetDetail` {#schema-agenttoolsetdetail}

A toolset with every tool row, ordered by operation key.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `id` | string | yes | Stable resource identifier. |
| `versionId` | string | yes | Version ID. |
| `projectId` | string | yes | Project ID. |
| `versionLabel` | string or null | no | Version Label. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `target` | enum `"prod"`, `"mock"` | yes | Target. |
| `descriptionEnrichment` | boolean | no | Description Enrichment. |
| `toolCount` | integer | yes | Number of tool. |
| `enabledToolCount` | integer | yes | Number of enabled tool. |
| `enabledWriteOpCount` | integer | yes | Number of enabled write op. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `createdBy` | string or null | no | Created By. |
| `updatedBy` | string or null | no | Updated By. |
| `tools` | array of [`AgentToolOut`](#schema-agenttoolout) | yes | Tools. |

### `AgentToolsetListResponse` {#schema-agenttoolsetlistresponse}

A tenant's toolsets, described.

Attributes:
    schema_version: The projection's shape.
    toolsets: One entry per toolset, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `toolsets` | array of [`AgentToolsetOut`](#schema-agenttoolsetout) | yes | Toolsets. |

### `AgentToolsetOut` {#schema-agenttoolsetout}

A toolset, described with its tool counts.

Attributes:
    schema_version: The projection's shape.
    id: The toolset id (what agent keys and upstream credentials bind to).
    version_id: The published version it exposes.
    project_id: That version's project.
    version_label: The version's label (``1.0.0``).
    enabled: Whether it serves agents at all.
    target: ``prod`` or ``mock``.
    description_enrichment: Whether accepted description-enrichment proposals are served
        (AGX-1.3). ``False`` serves the spec-derived descriptions unchanged.
    tool_count: Callable operations in the version.
    enabled_tool_count: How many of them are exposed.
    enabled_write_op_count: How many exposed ones are write ops.
    created_at: When it was created.
    updated_at: When its settings last changed.
    created_by: Who created it.
    updated_by: Who last changed its settings.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `id` | string | yes | Stable resource identifier. |
| `versionId` | string | yes | Version ID. |
| `projectId` | string | yes | Project ID. |
| `versionLabel` | string or null | no | Version Label. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `target` | enum `"prod"`, `"mock"` | yes | Target. |
| `descriptionEnrichment` | boolean | no | Description Enrichment. |
| `toolCount` | integer | yes | Number of tool. |
| `enabledToolCount` | integer | yes | Number of enabled tool. |
| `enabledWriteOpCount` | integer | yes | Number of enabled write op. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `createdBy` | string or null | no | Created By. |
| `updatedBy` | string or null | no | Updated By. |

### `AgentToolsetUpdate` {#schema-agenttoolsetupdate}

Body of ``PATCH /v1/tenants/{t}/agent-toolsets/{id}``. At least one field is required.

Attributes:
    enabled: Switch the whole toolset on or off.
    target: ``prod`` or ``mock``.
    description_enrichment: Serve accepted description-enrichment proposals (AGX-1.3), or
        opt out and serve the spec-derived descriptions unchanged.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enabled` | boolean or null | no | Whether the resource is active. |
| `target` | enum `"prod"`, `"mock"` or null | no | Target. |
| `descriptionEnrichment` | boolean or null | no | Description Enrichment. |

### `AgentUsageOut` {#schema-agentusageout}

A tenant's agent usage over a window of UTC days.

Attributes:
    schema_version: The projection's shape.
    start_day: First UTC day of the window (inclusive).
    end_day: Last UTC day of the window (inclusive; today).
    days: Window length in days.
    totals: The whole window.
    daily: One entry per day, oldest first, zero-filled.
    tools: One entry per tool that was called, most calls first.
    agents: One entry per agent key that called, most calls first.
    as_of: When this was computed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `startDay` | string (date) | yes | Start Day. |
| `endDay` | string (date) | yes | End Day. |
| `days` | integer | yes | Days. |
| `totals` | `AgentUsageTotals` | yes | Totals. |
| `daily` | array of `AgentUsageDay` | yes | Daily. |
| `tools` | array of `AgentUsageTool` | yes | Tools. |
| `agents` | array of `AgentUsageAgent` | yes | Agents. |
| `asOf` | string (date-time) | yes | As Of. |

### `CompiledToolsetOut` {#schema-compiledtoolsetout}

The toolset as agents are served it: enabled tools, accepted descriptions applied.

Attributes:
    schema_version: The projection's shape.
    toolset_id: The toolset.
    version_id: Its published version.
    enabled: Whether the toolset serves agents (a disabled one compiles to no tools).
    description_enrichment: Whether accepted proposals were applied.
    enriched_targets: The target keys whose accepted text was applied.
    fingerprint: The compiled toolset's content hash.
    tools: The MCP ``tools/list`` entries, in canonical order.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `toolsetId` | string | yes | Toolset ID. |
| `versionId` | string | yes | Version ID. |
| `enabled` | boolean | yes | Whether the resource is active. |
| `descriptionEnrichment` | boolean | yes | Description Enrichment. |
| `enrichedTargets` | array of string | yes | Enriched Targets. |
| `fingerprint` | string | yes | Fingerprint. |
| `tools` | array of object | yes | Tools. |

### `EnrichmentProposalOut` {#schema-enrichmentproposalout}

One description proposal and its review.

Attributes:
    id: The proposal id (what the review route addresses).
    operation: The operation the description belongs to.
    target_kind: ``tool`` or ``parameter``.
    target_key: The operation key, or the canonical parameter key.
    parameter: For a parameter, its ``location.name`` label.
    original_description: The spec's description when the proposal was made.
    proposed_description: What the copilot proposed. Never served as is.
    model: The model that proposed it.
    status: ``proposed``, ``accepted`` or ``rejected``.
    accepted_description: The text served once accepted (the proposal or an edit of it).
    reviewed_by: Who accepted or rejected it.
    reviewed_at: When.
    created_at: When it was proposed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `operation` | string | yes | HTTP method name (GET, POST, PUT, PATCH, DELETE, …). |
| `targetKind` | enum `"tool"`, `"parameter"` | yes | Target Kind. |
| `targetKey` | string | yes | Target Key. |
| `parameter` | string or null | no | Parameter. |
| `originalDescription` | string or null | no | Original Description. |
| `proposedDescription` | string | yes | Proposed Description. |
| `model` | string | yes | Model. |
| `status` | enum `"proposed"`, `"accepted"`, `"rejected"` | yes | Status. |
| `acceptedDescription` | string or null | no | Accepted Description. |
| `reviewedBy` | string or null | no | Reviewed By. |
| `reviewedAt` | string (date-time) or null | no | Reviewed At. |
| `createdAt` | string (date-time) or null | no | Created At. |

### `EnrichmentReport` {#schema-enrichmentreport}

A toolset's enrichment state: flags, proposals and whether the copilot is on.

Attributes:
    schema_version: The projection's shape.
    toolset_id: The toolset.
    description_enrichment: Whether accepted proposals are served.
    mode: ``copilot`` when a model is configured, else ``flag-only``.
    model: The configured model, if any.
    flags: The agent-hostile tools, ordered by operation key.
    proposals: Every proposal, ordered by operation.
    counts: ``flagged`` tools and proposals by status.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `toolsetId` | string | yes | Toolset ID. |
| `descriptionEnrichment` | boolean | yes | Description Enrichment. |
| `mode` | enum `"copilot"`, `"flag-only"` | yes | Mode. |
| `model` | string or null | no | Model. |
| `flags` | array of `EnrichmentFlagOut` | yes | Flags. |
| `proposals` | array of [`EnrichmentProposalOut`](#schema-enrichmentproposalout) | yes | Proposals. |
| `counts` | map of integer | yes | Counts. |

### `EnrichmentReview` {#schema-enrichmentreview}

Body of ``PATCH …/agent-toolsets/{id}/enrichment/{proposalId}``.

Attributes:
    decision: ``accept`` serves the description; ``reject`` withdraws it.
    description: With ``accept``, an edited text to serve instead of the proposal.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `decision` | enum `"accept"`, `"reject"` | yes | Decision. |
| `description` | string or null | no | Free-text description. |

### `EnrichmentRun` {#schema-enrichmentrun}

Body of ``POST …/agent-toolsets/{id}/enrichment``. Every field is optional.

Attributes:
    operations: Only ask about these operation keys (``GET /pets``). Default: every operation
        with an undescribed target, in canonical order.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `operations` | array of string or null | no | Operations. |

### `EnrichmentRunResult` {#schema-enrichmentrunresult}

What one run of the pass did, plus the resulting report.

Attributes:
    generated: Proposals stored by this run.
    attempted_operations: Operations the copilot was asked about.
    failed_operations: Of those, how many got no usable answer (unreachable model, bad reply).
    remaining_operations: Operations with undescribed targets left for a later run.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `toolsetId` | string | yes | Toolset ID. |
| `descriptionEnrichment` | boolean | yes | Description Enrichment. |
| `mode` | enum `"copilot"`, `"flag-only"` | yes | Mode. |
| `model` | string or null | no | Model. |
| `flags` | array of `EnrichmentFlagOut` | yes | Flags. |
| `proposals` | array of [`EnrichmentProposalOut`](#schema-enrichmentproposalout) | yes | Proposals. |
| `counts` | map of integer | yes | Counts. |
| `generated` | integer | yes | Generated. |
| `attemptedOperations` | integer | yes | Attempted Operations. |
| `failedOperations` | integer | yes | Failed Operations. |
| `remainingOperations` | integer | yes | Remaining Operations. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `UpstreamCredentialCreate` {#schema-upstreamcredentialcreate}

Body for storing a new upstream credential.

Attributes:
    server_url: The only upstream the credential will be sent to.
    kind: ``apiKey``, ``bearer`` or ``basic``.
    api_key_in: ``apiKey`` only: ``header`` or ``query``.
    api_key_name: ``apiKey`` only: the header or query-parameter name.
    secret: The secret material. Sealed on arrival and never returned.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `serverUrl` | string | yes | The upstream server this credential is bound to: an `https://` origin plus an optional base path, e.g. `https://api.example.com/v1`. The credential is only injected into requests under this URL. |
| `kind` | enum `"apiKey"`, `"bearer"`, `"basic"` | yes | How the secret is presented, in OpenAPI security-scheme terms. |
| `in` | enum `"header"`, `"query"` or null | no | `apiKey` only: send the key as a header or a query parameter. |
| `name` | string or null | no | `apiKey` only: the header or query-parameter name, e.g. `X-Api-Key`. |
| `secret` | `UpstreamSecretInput` | yes | Write-only secret material: `{value}` for apiKey, `{token}` for bearer, `{username, password}` for basic. Stored encrypted; never returned by any route. |

### `UpstreamCredentialListResponse` {#schema-upstreamcredentiallistresponse}

A toolset's upstream credentials, described.

Attributes:
    schema_version: The projection's shape.
    toolset_id: The toolset addressed.
    encryption_configured: Whether this deployment can store credentials at all.
    kinds: The credential kinds the vault accepts.
    api_key_locations: Where an ``apiKey`` credential may be sent.
    credentials: One entry per stored credential, by server URL.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `toolsetId` | string | yes | Toolset ID. |
| `encryptionConfigured` | boolean | yes | Encryption Configured. |
| `kinds` | array of string | yes | Kinds. |
| `apiKeyLocations` | array of string | yes | API Key Locations. |
| `credentials` | array of [`UpstreamCredentialOut`](#schema-upstreamcredentialout) | yes | Credentials. |

### `UpstreamCredentialOut` {#schema-upstreamcredentialout}

A stored credential, described without being revealed.

Attributes:
    schema_version: The projection's shape.
    id: The credential id.
    toolset_id: The agent toolset it serves.
    server_url: The only upstream it is sent to.
    kind: ``apiKey``, ``bearer`` or ``basic``.
    api_key_in: ``apiKey`` only: ``header`` or ``query``.
    api_key_name: ``apiKey`` only: the header or parameter name.
    key_version: Which master key sealed the secret.
    readable: Whether the secret can be opened with the keys configured now. ``False`` means
        the credential is present but unusable: every call through it would fail closed.
    created_at: When it was stored.
    created_by: Who stored it.
    rotated_at: When its secret was last replaced, or ``None``.
    rotated_by: Who last replaced it.
    last_used_at: When it was last injected into a request, or ``None``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `id` | string | yes | Stable resource identifier. |
| `toolsetId` | string | yes | Toolset ID. |
| `serverUrl` | string | yes | Server URL. |
| `kind` | string | yes | Kind. |
| `in` | string or null | no | In. |
| `name` | string or null | no | Human-readable name. |
| `keyVersion` | integer or null | no | Key Version. |
| `readable` | boolean | no | Readable. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `createdBy` | string or null | no | Created By. |
| `rotatedAt` | string (date-time) or null | no | Rotated At. |
| `rotatedBy` | string or null | no | Rotated By. |
| `lastUsedAt` | string (date-time) or null | no | Last Used At. |

### `UpstreamCredentialRotate` {#schema-upstreamcredentialrotate}

Body for rotating a credential's secret in place.

Attributes:
    secret: The replacement secret. Must have the fields the credential's kind needs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `secret` | `UpstreamSecretInput` | yes | The replacement secret, in the same shape as at creation. |
