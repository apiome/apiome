---
title: "Slate cache"
description: "REST endpoints tagged slate-cache: 10 operations."
sidebar_position: 62
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `slate-cache` · 10 operations

## `GET /v1/slate/cache/presets` {#get-cache-presets-v1-slate-cache-presets-get}

**Get Cache Presets**

Return the four presets as data.

The UI renders what this returns. A preset whose numbers lived in the client as well as
here would drift, and the copy that drifted silently would be the one on screen.

Operation id: `get_cache_presets_v1_slate_cache_presets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get cache presets. | `application/json` [`PresetsResponse`](#schema-presetsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/cache` {#get-cache-policy-v1-slate-environments-environment-id-cache-get}

**Get Cache Policy**

Return a lane's cache policy, its expert rules and what it actually enforces.

Operation id: `get_cache_policy_v1_slate_environments__environment_id__cache_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get cache policy. | `application/json` [`CachePolicyResponse`](#schema-cachepolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/cache/audit` {#get-cache-audit-v1-slate-environments-environment-id-cache-audit-get}

**Get Cache Audit**

Return a lane's append-only cache audit trail, most recent first.

Operation id: `get_cache_audit_v1_slate_environments__environment_id__cache_audit_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get cache audit. | `application/json` [`SlateCacheAuditResponse`](#schema-slatecacheauditresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/cache/preset` {#set-cache-preset-v1-slate-environments-environment-id-cache-preset-put}

**Set Cache Preset**

Change a lane's preset.

Bypass without an expiry is refused here and again by V187's CHECK, because an incident
mode that outlives its incident becomes the configuration.

Operation id: `set_cache_preset_v1_slate_environments__environment_id__cache_preset_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set cache preset.

- `application/json` — [`SetPresetRequest`](#schema-setpresetrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set cache preset. | `application/json` [`SetPresetResponse`](#schema-setpresetresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/cache/purge` {#purge-cache-v1-slate-environments-environment-id-cache-purge-post}

**Purge Cache**

Estimate a purge's scope and record it.

**Nothing is evicted.** No delivery tier is attached to this environment, so what this
writes is evidence: who asked, for what scope, with what estimated blast radius computed
from which table, and why. The response says so in ``delivery``, and V187 refuses at the
database any row claiming otherwise.

A refused purge still writes a purge record and an audit entry when it is not a dry run:
refusing to purge during an incident is precisely the event that needs to be in the
timeline afterwards.

Operation id: `purge_cache_v1_slate_environments__environment_id__cache_purge_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for purge cache.

- `application/json` — [`PurgeRequest`](#schema-purgerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for purge cache. | `application/json` [`PurgeResponse`](#schema-purgeresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/cache/purges` {#get-purge-history-v1-slate-environments-environment-id-cache-purges-get}

**Get Purge History**

Return a lane's purge history, most recent first.

Operation id: `get_purge_history_v1_slate_environments__environment_id__cache_purges_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `scopeKind` | query | string or null | no | Query parameter: scope kind. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get purge history. | `application/json` [`PurgeHistoryResponse`](#schema-purgehistoryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/cache/rules` {#create-cache-rule-v1-slate-environments-environment-id-cache-rules-post}

**Create Cache Rule**

Create an expert cache rule, refusing an unsafe variant by name.

Operation id: `create_cache_rule_v1_slate_environments__environment_id__cache_rules_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create cache rule.

- `application/json` — [`SlateCacheWriteRuleRequest`](#schema-slatecachewriterulerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create cache rule. | `application/json` [`SlateCacheWriteRuleResponse`](#schema-slatecachewriteruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/cache/rules/{rule_id}` {#replace-cache-rule-v1-slate-environments-environment-id-cache-rules-rule-id-put}

**Replace Cache Rule**

Replace an expert cache rule, running the same gates as a create.

Operation id: `replace_cache_rule_v1_slate_environments__environment_id__cache_rules__rule_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `rule_id` | path | string | yes | Path parameter identifying the rule id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace cache rule.

- `application/json` — [`SlateCacheWriteRuleRequest`](#schema-slatecachewriterulerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace cache rule. | `application/json` [`SlateCacheWriteRuleResponse`](#schema-slatecachewriteruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/cache/rules/{rule_id}` {#remove-cache-rule-v1-slate-environments-environment-id-cache-rules-rule-id-delete}

**Remove Cache Rule**

Remove an expert cache rule.

Operation id: `remove_cache_rule_v1_slate_environments__environment_id__cache_rules__rule_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `rule_id` | path | string | yes | Path parameter identifying the rule id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove cache rule. | `application/json` [`SlateSecurityDeleteRuleResponse`](#schema-slatesecuritydeleteruleresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/cache/trace` {#trace-cache-request-v1-slate-environments-environment-id-cache-trace-post}

**Trace Cache Request**

Explain what this lane's policy decides for a test request.

A read, not a write, unless ``persist`` is set. The verdict answers eligibility, cache key,
TTLs, bypass and the winning rule, and reports every rule that was considered together with
the reason it did not win — because "why did my rule not fire" is the question that brings
an operator here.

Operation id: `trace_cache_request_v1_slate_environments__environment_id__cache_trace_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for trace cache request.

- `application/json` — [`TraceCommandBody`](#schema-tracecommandbody)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for trace cache request. | `application/json` [`TraceResponse`](#schema-traceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CachePolicyResponse` {#schema-cachepolicyresponse}

A lane's complete cache policy.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | The lane. |
| `preset` | string | yes | Active preset. |
| `presetExpiresAt` | string or null | no | Preset Expires At. |
| `presetOverrides` | object | no | Preset Overrides. |
| `policyVersion` | integer | yes | Optimistic-concurrency token. |
| `edgeAttached` | boolean | yes | Whether a delivery tier serves this lane. |
| `edgeProvider` | string or null | no | Edge Provider. |
| `enforcement` | `SlateCacheEnforcementBody` | yes | Whether the policy shapes responses. |
| `rules` | array of `CacheRuleBody` | yes | Expert rules, in precedence order. |
| `presetRules` | array of `CacheRuleBody` | yes | The preset's own rules, which decide where no expert rule matches. |
| `updatedAt` | string or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PresetsResponse` {#schema-presetsresponse}

Every available preset.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `presets` | array of `PresetBody` | yes | The four presets. |

### `PurgeHistoryResponse` {#schema-purgehistoryresponse}

A lane's purge history.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `purges` | array of `PurgeRecordBody` | yes | Most recent first. |

### `PurgeRequest` {#schema-purgerequest}

Estimate and record a purge.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `scopeKind` | enum `"release"`, `"tag"`, `"prefix"`, `"host"`, `"url"` | yes | One of the five roadmap scopes. |
| `scopeValue` | string | yes | Release id, tag, prefix, host or URL. |
| `reason` | string | yes | Why. Recorded, because a purge must be explicable later. |
| `dryRun` | boolean | no | Estimate without recording a purge. |
| `confirmEstimatedObjects` | integer or null | no | The estimate the operator confirmed. When it disagrees with the server's recomputed estimate the purge is refused: they approved a different blast radius. |

### `PurgeResponse` {#schema-purgeresponse}

The outcome of a purge.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `outcome` | string | yes | estimated (dry run) or recorded. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `estimate` | `PurgeEstimateBody` | yes | The scope and its provenance. |
| `purgeId` | string or null | no | Purge ID. |
| `edgeAttached` | boolean | yes | Whether a delivery tier serves this lane. |
| `delivery` | `DeliveryBody` | yes | Whether anything was evicted. |

### `SetPresetRequest` {#schema-setpresetrequest}

Change a lane's preset.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `preset` | string | yes | standard, aggressive, bypass or personalized. |
| `presetExpiresAt` | string or null | no | Required for bypass, which is an incident mode. |
| `overrides` | object | no | Overrides. |
| `reason` | string | no | Why the preset changed; recorded in audit. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Run every gate and write nothing. |

### `SetPresetResponse` {#schema-setpresetresponse}

The outcome of a preset change.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `preset` | string | yes | The preset now in effect, or that would be. |
| `policyVersion` | integer | yes | The version after the change. |
| `resolvedRules` | array of `CacheRuleBody` | yes | What the preset resolves to. |
| `warnings` | array of `CacheWarningBody` | no | Warnings. |

### `SlateCacheAuditResponse` {#schema-slatecacheauditresponse}

A lane's cache audit trail.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `entries` | array of `SlateCacheAuditEntryBody` | yes | Most recent first. |

### `SlateCacheWriteRuleRequest` {#schema-slatecachewriterulerequest}

Create or replace an expert rule.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string or null | no | Rule id, absent for preset rules. |
| `ordinal` | integer | yes | Precedence; lower wins. |
| `enabled` | boolean | no | Whether the rule participates. |
| `label` | string | yes | Operator-facing rule name. |
| `matcherKind` | string | no | exact, prefix, glob or regex. |
| `matcherValue` | string | no | The route pattern. |
| `matcherMethods` | array of string | no | Matcher Methods. |
| `matcherHosts` | array of string | no | Matcher Hosts. |
| `eligibility` | string | no | cacheable, private or no-store. |
| `browserTtlSeconds` | integer | no | Browser Ttl Seconds. |
| `edgeTtlSeconds` | integer | no | Edge Ttl Seconds. |
| `staleWhileRevalidateSeconds` | integer | no | Stale While Revalidate Seconds. |
| `staleIfErrorSeconds` | integer | no | Stale If Error Seconds. |
| `cacheKeyBase` | string | no | Cache Key Base. |
| `varyQueryMode` | string | no | Vary Query Mode. |
| `varyQueryKeys` | array of string | no | Vary Query Keys. |
| `varyHeaders` | array of string | no | Vary Headers. |
| `varyCookies` | array of string | no | Vary Cookies. |
| `bypassConditions` | array of object | no | Bypass Conditions. |
| `tags` | array of string | no | Associated tag labels. |
| `expiresAt` | string or null | no | Expires At. |
| `acknowledgedWarnings` | array of string | no | Acknowledged Warnings. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Validate without writing. |
| `reason` | string | no | Why the rule changed; recorded in audit. |

### `SlateCacheWriteRuleResponse` {#schema-slatecachewriteruleresponse}

The outcome of a rule write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `rule` | `CacheRuleBody` or null | no | Rule. |
| `policyVersion` | integer | yes | The version after the write. |
| `warnings` | array of `CacheWarningBody` | no | Warnings. |

### `SlateSecurityDeleteRuleResponse` {#schema-slatesecuritydeleteruleresponse}

The outcome of a rule deletion.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `policyVersion` | integer | yes | The version after the write. |

### `TraceCommandBody` {#schema-tracecommandbody}

A trace request, optionally over a what-if ruleset.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `request` | `TraceRequestBody` | yes | The test request. |
| `rules` | array of `CacheRuleBody` or null | no | What-if overlay. When absent, the lane's stored rules are used. |
| `persist` | boolean | no | Record the trace as evidence. |

### `TraceResponse` {#schema-traceresponse}

What the policy decides for a test request, and why.

One field per clause of the acceptance criterion, so a partial answer is impossible.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `eligibility` | string | yes | cacheable, private or no-store. |
| `eligibilityReason` | string | yes | Why, naming what decided. |
| `cacheKey` | string | yes | The resolved cache key. |
| `cacheKeyComponents` | array of `TraceKeyComponentBody` | yes | How it was built. |
| `browserTtlSeconds` | integer | yes | Browser TTL. |
| `edgeTtlSeconds` | integer | yes | Shared-tier TTL. |
| `staleWhileRevalidateSeconds` | integer | yes | Stale-while-revalidate window. |
| `staleIfErrorSeconds` | integer | yes | Stale-if-error window. |
| `ttlSource` | string | yes | Which rule or preset set the TTLs. |
| `bypassed` | boolean | yes | Whether a bypass condition fired. |
| `bypassReason` | string or null | no | Bypass Reason. |
| `winningRuleId` | string or null | no | Null when the preset default decided, which is an answer. |
| `winningRuleLabel` | string | yes | What decided. |
| `considered` | array of `TraceStepBody` | yes | Every rule, and why it did not win. |
| `warnings` | array of `CacheWarningBody` | no | Warnings. |
| `rulesDigest` | string | yes | Determinism receipt over the evaluated ruleset. |
| `policyVersion` | integer | yes | Which policy generation answered. |
| `basis` | `"policy-evaluation"` | no | This is an evaluation of recorded policy against a test request, not a replay of an observed edge hit. When a delivery tier lands, 'edge-observed' becomes the second value of this field rather than a change of meaning for the first. |
| `observed` | boolean | no | False: no delivery tier reported this request. |
| `traceId` | string or null | no | Set when the trace was recorded. |
| `basisReleaseId` | string or null | no | Basis Release ID. |
