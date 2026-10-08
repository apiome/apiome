---
title: "Migration plans"
description: "REST endpoints tagged migration-plans: 3 operations."
sidebar_position: 39
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `migration-plans` · 3 operations

## `GET /v1/migration-plans/{tenant_slug}` {#get-migration-plan-rules-v1-migration-plans-tenant-slug-get}

**Get Migration Plan Rules**

Get migration plan rules for a (project, from_version, to_version, class_name).
Returns rules keyed by migration-edge-prop-{source_property}.

Operation id: `get_migration_plan_rules_v1_migration_plans__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `projectId` | query | string | yes | Required. Query parameter: project id. |
| `fromVersionId` | query | string | yes | Required. Query parameter: from version id. |
| `toVersionId` | query | string | yes | Required. Query parameter: to version id. |
| `className` | query | string | yes | Required. Query parameter: class name. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get migration plan rules. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/migration-plans/{tenant_slug}` {#save-migration-plan-rules-v1-migration-plans-tenant-slug-put}

**Save Migration Plan Rules**

Save migration plan rules for a (project, from_version, to_version, class_name).
Body: project_id, from_version_id, to_version_id, class_name, rules.

Operation id: `save_migration_plan_rules_v1_migration_plans__tenant_slug__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save migration plan rules.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save migration plan rules. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/migration-plans/{tenant_slug}/counts` {#get-migration-plan-rule-counts-v1-migration-plans-tenant-slug-counts-get}

**Get Migration Plan Rule Counts**

Get rule counts per class_name for a migration plan (project, from_version, to_version).
Returns { "counts": { "ClassName": 2, ... } }.

Operation id: `get_migration_plan_rule_counts_v1_migration_plans__tenant_slug__counts_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `projectId` | query | string | yes | Required. Query parameter: project id. |
| `fromVersionId` | query | string | yes | Required. Query parameter: from version id. |
| `toVersionId` | query | string | yes | Required. Query parameter: to version id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get migration plan rule counts. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
