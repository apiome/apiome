---
title: "Registry audit"
description: "REST endpoints tagged registry-audit: 1 operation."
sidebar_position: 52
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `registry-audit` · 1 operation

## `GET /v1/primitives/{tenant_slug}/audit` {#list-registry-audit-v1-primitives-tenant-slug-audit-get}

**List Registry Audit**

List type-registry audit events for the tenant (newest first).

Pagination: use **offset** + **limit**, or **cursor** + **limit**. Do not combine
**cursor** with a non-zero **offset**.

Operation id: `list_registry_audit_v1_primitives__tenant_slug__audit_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `action` | query | array of string or null | no | Filter by action (repeat for multiple, e.g. primitive.create). |
| `actorId` | query | string or null | no | Filter by actor user id (UUID). |
| `outcome` | query | string or null | no | Filter by outcome: success or failure. |
| `primitiveId` | query | string or null | no | Filter by affected primitive id (UUID). |
| `schemaId` | query | string or null | no | Filter by the affected type's derived $id. |
| `since` | query | string or null | no | Inclusive lower bound on createdAt (ISO 8601). |
| `until` | query | string or null | no | Inclusive upper bound on createdAt (ISO 8601). |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `cursor` | query | string or null | no | Opaque next-page token from pagination.nextCursor (cursor mode). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list registry audit. | `application/json` [`RegistryAuditPageResponse`](#schema-registryauditpageresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `RegistryAuditPageResponse` {#schema-registryauditpageresponse}

Stable JSON envelope for GET /v1/primitives/{tenant_slug}/audit (schemaVersion bumps on breaking changes).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | integer | no | Bumped only when item or pagination shape changes incompatibly. |
| `items` | array of `RegistryAuditEntryOut` | yes | Items. |
| `pagination` | `RegistryAuditPaginationOut` | yes | Pagination. |
