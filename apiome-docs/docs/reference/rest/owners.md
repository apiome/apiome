---
title: "Owners"
description: "REST endpoints tagged owners: 10 operations."
sidebar_position: 49
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.240.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `owners` · 10 operations

## `GET /v1/tenants/{tenant_slug}/owners/{kind}/{entity_id}` {#get-entity-owner-v1-tenants-tenant-slug-owners-kind-entity-id-get}

**Read an entity's owner**

The confirmed owner team, if any, and every suggested owner with its `source` (`gateway_tag`, `codeowners`, `spec_extension`, …) and `source_ref`.

`kind` is `project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`; reading needs the kind's `view` and changing needs its `edit` (`projects` for projects, catalog items and MCP endpoints, `consumer_contracts` for consumers, `imports` for connectors).

Operation id: `get_entity_owner_v1_tenants__tenant_slug__owners__kind___entity_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | path | string | yes | Path parameter identifying the kind segment. |
| `entity_id` | path | string | yes | Path parameter identifying the entity id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read an entity's owner. | `application/json` [`OwnersResponse`](#schema-ownersresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/owners/{kind}/{entity_id}` {#put-entity-owner-v1-tenants-tenant-slug-owners-kind-entity-id-put}

**Assign an entity's owner**

Make `team` (a team slug) the confirmed owner, replacing any previous one. A previous owner that came from a suggestion goes back to being a suggestion.

Audited as `owner.assign`. `kind` is `project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`; reading needs the kind's `view` and changing needs its `edit` (`projects` for projects, catalog items and MCP endpoints, `consumer_contracts` for consumers, `imports` for connectors).

Operation id: `put_entity_owner_v1_tenants__tenant_slug__owners__kind___entity_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | path | string | yes | Path parameter identifying the kind segment. |
| `entity_id` | path | string | yes | Path parameter identifying the entity id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for assign an entity's owner.

- `application/json` — [`OwnerAssignInput`](#schema-ownerassigninput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for assign an entity's owner. | `application/json` [`OwnersResponse`](#schema-ownersresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/owners/{kind}/{entity_id}` {#delete-entity-owner-v1-tenants-tenant-slug-owners-kind-entity-id-delete}

**Remove an entity's owner**

Remove the confirmed owner. Suggestions are kept; an owner that came from a suggestion becomes a suggestion again.

Audited as `owner.remove`. `kind` is `project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`; reading needs the kind's `view` and changing needs its `edit` (`projects` for projects, catalog items and MCP endpoints, `consumer_contracts` for consumers, `imports` for connectors).

Operation id: `delete_entity_owner_v1_tenants__tenant_slug__owners__kind___entity_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | path | string | yes | Path parameter identifying the kind segment. |
| `entity_id` | path | string | yes | Path parameter identifying the entity id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove an entity's owner. | `application/json` [`OwnersResponse`](#schema-ownersresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/owners/{kind}/{entity_id}/confirm` {#confirm-entity-owner-v1-tenants-tenant-slug-owners-kind-entity-id-confirm-post}

**Confirm a suggested owner**

Make a suggested owner the confirmed owner. Name it with `team`; it may be omitted when only one team is suggested. The owner keeps its `source` and records who confirmed it (`confirmed_by`, `confirmed_at`).

Audited as `owner.confirm`. `kind` is `project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`; reading needs the kind's `view` and changing needs its `edit` (`projects` for projects, catalog items and MCP endpoints, `consumer_contracts` for consumers, `imports` for connectors).

Operation id: `confirm_entity_owner_v1_tenants__tenant_slug__owners__kind___entity_id__confirm_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | path | string | yes | Path parameter identifying the kind segment. |
| `entity_id` | path | string | yes | Path parameter identifying the entity id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confirm a suggested owner.

- `application/json` — [`OwnerConfirmInput`](#schema-ownerconfirminput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confirm a suggested owner. | `application/json` [`OwnersResponse`](#schema-ownersresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/owners:assign` {#bulk-assign-entity-owner-v1-tenants-tenant-slug-owners-assign-post}

**Assign one owner to many entities**

Make `team` the confirmed owner of every entity in `entities` (`[{kind, id}]`, up to 200), all or nothing: an entity that does not exist fails the whole request with 404.

Needs `edit` on every kind in the list. Audited as one `owner.bulk_assign`.

Operation id: `bulk_assign_entity_owner_v1_tenants__tenant_slug__owners_assign_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for assign one owner to many entities.

- `application/json` — [`BulkAssignInput`](#schema-bulkassigninput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for assign one owner to many entities. | `application/json` [`BulkAssignResponse`](#schema-bulkassignresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/ownership-drift` {#get-ownership-drift-v1-tenants-tenant-slug-ownership-drift-get}

**List ownership drift**

Entities whose confirmed owner team was deleted (`deleted_team`) or has no members (`empty_team`), and suggested owners nobody confirmed in 30 days (`stale_suggestion`). At most 200 rows per reason; `counts` has the totals.

Requires `teams:view`.

Operation id: `get_ownership_drift_v1_tenants__tenant_slug__ownership_drift_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list ownership drift. | `application/json` [`DriftResponse`](#schema-driftresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/ownership-policy` {#get-ownership-policy-v1-tenants-tenant-slug-ownership-policy-get}

**Read the ownership policy**

The catch-all team for findings on entities with no confirmed owner, and whether a project needs a confirmed owner to publish.

Requires `teams:view`.

Operation id: `get_ownership_policy_v1_tenants__tenant_slug__ownership_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the ownership policy. | `application/json` [`OwnershipPolicy`](#schema-ownershippolicy) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/ownership-policy` {#put-ownership-policy-v1-tenants-tenant-slug-ownership-policy-put}

**Change the ownership policy**

Set `unowned_findings_team` (a team slug, or `null` for none) and/or `require_owner_to_publish`. Omitted fields are left alone.

Audited as `ownership_policy.update`. Requires `teams:edit`.

Operation id: `put_ownership_policy_v1_tenants__tenant_slug__ownership_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change the ownership policy.

- `application/json` — [`OwnershipPolicyInput`](#schema-ownershippolicyinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change the ownership policy. | `application/json` [`OwnershipPolicy`](#schema-ownershippolicy) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/ownership-policy/publish-gate` {#get-owner-publish-gate-v1-tenants-tenant-slug-ownership-policy-publish-gate-get}

**Preview the owner gate for a project**

What the owner gate will say when a version of `project` is published: `disabled` (the gate is off), `satisfied` (the project has a confirmed owner) or `blocked` (reason `no-owner`).

Requires `versions:view`.

Operation id: `get_owner_publish_gate_v1_tenants__tenant_slug__ownership_policy_publish_gate_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project` | query | string | yes | The project's id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview the owner gate for a project. | `application/json` [`OwnerGateResponse`](#schema-ownergateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/unowned-findings` {#get-unowned-findings-v1-tenants-tenant-slug-unowned-findings-get}

**List unowned findings**

Findings that reached no team because their entity has no confirmed owner — never dropped, kept here, newest first. One row per entity and finding type, with `occurrences` and the latest `payload`. Assigning an owner (`PUT /v1/tenants/{tenant}/owners/{kind}/{id}`) routes the next occurrence to the team and clears the row.

Requires `teams:view`.

Operation id: `get_unowned_findings_v1_tenants__tenant_slug__unowned_findings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `type` | query | enum `"owner_finding"`, `"owner_breaking_change"`, `"owner_verification_drift"`, `"owner_gate_blocked"`, `"owner_trust_drift"`, `"owner_shadow_api"`, … or null | no | Query parameter: type. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list unowned findings. | `application/json` [`UnownedFindingsResponse`](#schema-unownedfindingsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `BulkAssignInput` {#schema-bulkassigninput}

Make one team the confirmed owner of many entities.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `team` | string | yes | Team. |
| `entities` | array of `EntityRef` | yes | Entities. |

### `BulkAssignResponse` {#schema-bulkassignresponse}

The owners of every entity a bulk assignment touched.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `results` | array of [`OwnersResponse`](#schema-ownersresponse) | no | Results. |
| `count` | integer | yes | Number of count. |

### `DriftResponse` {#schema-driftresponse}

The ownership drift report.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `DriftItem` | no | Items. |
| `counts` | map of integer | no | Rows per reason (before the per-reason cap). |
| `stale_after_days` | integer | yes | Stale After Days. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `OwnerAssignInput` {#schema-ownerassigninput}

Make a team the confirmed owner.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `team` | string | yes | The team's slug. |

### `OwnerConfirmInput` {#schema-ownerconfirminput}

Confirm a suggestion. ``team`` may be omitted when there is exactly one suggestion.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `team` | string or null | no | Team. |

### `OwnerGateResponse` {#schema-ownergateresponse}

The owner gate's verdict for one project.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | string | yes | `disabled`, `satisfied` or `blocked`. |
| `message` | string | yes | Message. |
| `reason` | string or null | no | `no-owner` when blocked. |
| `team` | map of string or null or null | no | Team. |

### `OwnersResponse` {#schema-ownersresponse}

An entity's owner and suggestions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | string | yes | Kind. |
| `entity_id` | string | yes | Entity ID. |
| `owner` | `OwnerRecord` or null | no | The confirmed owner, if any. |
| `suggestions` | array of `OwnerRecord` | no | Suggested owners with their source; none of them receives findings. |
| `facts` | map of boolean or null | no | `owner.present` (a confirmed, live owner team) and `owner.contactable` (it has an on-call or chat link) — the facts GVM-1.x ladders read (CDG-2.5). |

### `OwnershipPolicy` {#schema-ownershippolicy}

The tenant's ownership policy.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `unowned_findings_team` | `PolicyTeam` or null | no | Catch-all team for findings on entities with no confirmed owner; null when none. |
| `require_owner_to_publish` | boolean | yes | When true, a version of a project with no confirmed owner cannot be published. |

### `OwnershipPolicyInput` {#schema-ownershippolicyinput}

A policy change. Omitted fields are left alone; ``unowned_findings_team: null`` clears it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `unowned_findings_team` | string or null | no | A team slug. |
| `require_owner_to_publish` | boolean or null | no | Require Owner To Publish. |

### `UnownedFindingsResponse` {#schema-unownedfindingsresponse}

A page of the report.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `UnownedFinding` | no | Items. |
| `total` | integer | yes | Total. |
