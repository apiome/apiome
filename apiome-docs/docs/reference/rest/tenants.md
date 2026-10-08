---
title: "Tenants"
description: "REST endpoints tagged tenants: 3 operations."
sidebar_position: 72
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `tenants` · 3 operations

## `GET /v1/tenants/me` {#list-my-tenants-v1-tenants-me-get}

**List My Tenants**

Tenants accessible to the caller, enriched for the tenant switcher (OLO-6.2, #4219).

- JWT: all memberships for the user, each carrying the effective RBAC role slug
  (V119 assignment; legacy administrators read as ``owner``; Editor default),
  the V121 member lifecycle status, and the tenant's attached license plan —
  resolved in a single query, no per-tenant follow-ups.
- API key: the key's tenant only (single-item list) with role ``member`` and
  the tenant's license plan.

Operation id: `list_my_tenants_v1_tenants_me_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list my tenants. | `application/json` [`TenantsMeResponse`](#schema-tenantsmeresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}` {#get-tenant-info-v1-tenants-tenant-slug-get}

**Get Tenant Info**

Tenant summary including usage counts; 403 when the caller cannot access the tenant.

Operation id: `get_tenant_info_v1_tenants__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant info. | `application/json` [`TenantInfoResponse`](#schema-tenantinforesponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `HEAD /v1/tenants/{tenant_slug}` {#verify-tenant-access-v1-tenants-tenant-slug-head}

**Verify Tenant Access**

Lightweight access check for CLI default-tenant selection (#3199).

Operation id: `verify_tenant_access_v1_tenants__tenant_slug__head`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Caller has access to the tenant. | — |
| 401 | Missing or invalid session credentials. | — |
| 403 | Credentials valid but caller has no access to this tenant. | — |
| 404 | Tenant not found. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `TenantInfoResponse` {#schema-tenantinforesponse}

Tenant summary for ``GET /v1/tenants/{slug}``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `plan` | string or null | no | Plan. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `members_count` | integer | no | Number of members. |
| `projects_count` | integer | no | Number of projects. |
| `versions_count` | integer | no | Number of versions. |
| `published_versions_count` | integer | no | Number of published versions. |
| `storage_used_bytes` | integer or null | no | Storage Used Bytes. |
| `storage_quota_bytes` | integer or null | no | Storage Quota Bytes. |

### `TenantsMeResponse` {#schema-tenantsmeresponse}

Paginated list of tenants for the current principal (JWT user or API key tenant).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `TenantMembershipSchema` | yes | Items. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |
