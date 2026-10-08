---
title: "MCP trust drift"
description: "REST endpoints tagged mcp-trust-drift: 4 operations."
sidebar_position: 38
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mcp-trust-drift` · 4 operations

## `GET /v1/mcp/{tenant_slug}/data-quality/shadowing` {#get-shadowing-report-v1-mcp-tenant-slug-data-quality-shadowing-get}

**Get Shadowing Report**

Report tool/resource/prompt names shadowed across the tenant's enabled host scope (AC3).

Operation id: `get_shadowing_report_v1_mcp__tenant_slug__data_quality_shadowing_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get shadowing report. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/trust-baseline` {#get-trust-baseline-v1-mcp-tenant-slug-endpoints-endpoint-id-trust-baseline-get}

**Get Trust Baseline**

Return the endpoint's active trust baseline and its approval history.

Operation id: `get_trust_baseline_v1_mcp__tenant_slug__endpoints__endpoint_id__trust_baseline_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get trust baseline. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/trust-baseline` {#approve-trust-baseline-v1-mcp-tenant-slug-endpoints-endpoint-id-trust-baseline-post}

**Approve Trust Baseline**

Approve a new trust baseline for an endpoint (AC2).

Body: ``version_id`` (optional; defaults to the latest snapshot), ``rationale`` (required,
non-blank), and ``gating_categories`` (optional list of drift categories that block; defaults to
security_regression + coverage_loss). Composes the approved snapshot's trust manifest, supersedes
the prior baseline, and writes a policy event to the governance audit.

Operation id: `approve_trust_baseline_v1_mcp__tenant_slug__endpoints__endpoint_id__trust_baseline_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for approve trust baseline.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for approve trust baseline. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/trust-drift` {#get-trust-drift-v1-mcp-tenant-slug-endpoints-endpoint-id-trust-drift-get}

**Get Trust Drift**

Diff the current snapshot against the approved baseline and classify the drift (AC1/AC4).

Requires an approved baseline (404 otherwise) and a current discovered snapshot (409 otherwise).
The response carries every classified change with old→new evidence, the drift gate over the
baseline's configured risk deltas, and — when ``notify=true`` and the notification kill switch is
on — the ids of any alerts fanned out.

Operation id: `get_trust_drift_v1_mcp__tenant_slug__endpoints__endpoint_id__trust_drift_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `notify` | query | boolean | no | Fan out a push-webhook alert when a regression is found. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get trust drift. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
