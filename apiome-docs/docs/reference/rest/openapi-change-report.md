---
title: "OpenAPI change report"
description: "REST endpoints tagged openapi-change-report: 1 operation."
sidebar_position: 43
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `openapi-change-report` · 1 operation

## `POST /v1/openapi/change-report` {#post-openapi-change-report-v1-openapi-change-report-post}

**Post Openapi Change Report**

Compare **baselineOpenApi** to **candidateOpenApi** and return a deterministic
:class:`ChangeReportModel` (schemas, properties, references, relationships, documentation).
Both bodies must be resolved OpenAPI 3.x JSON (internal ``components``, normalized ``$ref``).

Operation id: `post_openapi_change_report_v1_openapi_change_report_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for post openapi change report.

- `application/json` — [`OpenApiChangeReportRequest`](#schema-openapichangereportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for post openapi change report. | `application/json` [`ChangeReportModel`](#schema-changereportmodel) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ChangeReportModel` {#schema-changereportmodel}

Versioned semantic diff between two resolved OpenAPI documents.
``schemaVersion`` bumps when this JSON shape changes incompatibly.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | yes | Schema Version. |
| `schemas` | `SchemasChangeSection` | yes | Schemas. |
| `properties` | array of object | yes | Properties. |
| `references` | array of object | yes | References. |
| `relationships` | array of object | yes | Relationships. |
| `documentation` | array of object | yes | Documentation. |
| `warnings` | array of object | yes | Warnings. |
| `skipped` | array of object | yes | Skipped. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `OpenApiChangeReportRequest` {#schema-openapichangereportrequest}

Two resolved OpenAPI 3.x JSON documents for semantic comparison.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `baselineOpenApi` | object | yes | Older / baseline resolved OpenAPI JSON. |
| `candidateOpenApi` | object | yes | Newer / candidate resolved OpenAPI JSON. |
