---
title: "Workflow audit"
description: "REST endpoints tagged workflow-audit: 1 operation."
sidebar_position: 81
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `workflow-audit` · 1 operation

## `GET /v1/versions/{tenant_slug}/workflow-audit` {#list-workflow-audit-v1-versions-tenant-slug-workflow-audit-get}

**List Workflow Audit**

List workflow audit events for the tenant (newest first).

Pagination: use **offset** + **limit**, or **cursor** + **limit**. Do not combine
**cursor** with a non-zero **offset**.

Operation id: `list_workflow_audit_v1_versions__tenant_slug__workflow_audit_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `action` | query | array of string or null | no | Filter by action (repeat for multiple, e.g. version.push). |
| `actorId` | query | string or null | no | Filter by actor user id (UUID). |
| `outcome` | query | string or null | no | Filter by outcome: success or failure. |
| `versionId` | query | string or null | no | Filter by revision id (versions.id) stored on the audit row. |
| `projectId` | query | string or null | no | Restrict to a project id (UUID); must belong to the tenant. |
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
| 200 | Successful response for list workflow audit. | `application/json` [`WorkflowAuditPageResponse`](#schema-workflowauditpageresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `WorkflowAuditPageResponse` {#schema-workflowauditpageresponse}

Stable JSON envelope for GET .../workflow-audit (schemaVersion bumps on breaking changes).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | integer | no | Bumped only when item or pagination shape changes incompatibly. |
| `items` | array of `WorkflowAuditEntryOut` | yes | Items. |
| `pagination` | `WorkflowAuditPaginationOut` | yes | Pagination. |
