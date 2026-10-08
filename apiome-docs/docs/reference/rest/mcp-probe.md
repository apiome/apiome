---
title: "MCP probe"
description: "REST endpoints tagged mcp-probe: 6 operations."
sidebar_position: 37
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mcp-probe` · 6 operations

## `GET /v1/mcp/probes/catalog` {#get-mcp-probe-catalog-v1-mcp-probes-catalog-get}

**Get Mcp Probe Catalog**

Return the probe catalog: every probe, the three profiles, and the classification tiers.

Registry-level (describes the engine, not any endpoint), authenticated like the other MCP rule
catalogs. Lets a consumer see, before running anything, which probe belongs to which profile,
the strongest classification each can reach, and what the three tiers mean.

Operation id: `get_mcp_probe_catalog_v1_mcp_probes_catalog_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `profile` | query | string or null | no | Restrict the probe list to this profile's probes. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp probe catalog. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/probe-runs` {#list-probe-runs-v1-mcp-tenant-slug-endpoints-endpoint-id-probe-runs-get}

**List Probe Runs**

Return an endpoint's probe-run audit trail, newest first. 404 for a cross-tenant endpoint.

Operation id: `list_probe_runs_v1_mcp__tenant_slug__endpoints__endpoint_id__probe_runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list probe runs. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/probe-targets` {#list-probe-targets-v1-mcp-tenant-slug-endpoints-endpoint-id-probe-targets-get}

**List Probe Targets**

List an endpoint's live allowlist entries. 404 for a cross-tenant endpoint.

Operation id: `list_probe_targets_v1_mcp__tenant_slug__endpoints__endpoint_id__probe_targets_get`

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
| 200 | Successful response for list probe targets. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/probe-targets` {#enroll-probe-target-v1-mcp-tenant-slug-endpoints-endpoint-id-probe-targets-post}

**Enroll Probe Target**

Enrol an endpoint on the active-probe allowlist.

The operator asserts ownership/authorization (``ownership_declared: true``, required) and may name
the dedicated test credential (``test_credential_id``) a probe authenticates as. Refuses without
the ownership assertion — probing a system nobody vouched for is exactly what the allowlist
exists to prevent. Idempotent per ``(endpoint, transport)``. 404 for a cross-tenant endpoint.

Operation id: `enroll_probe_target_v1_mcp__tenant_slug__endpoints__endpoint_id__probe_targets_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for enroll probe target.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for enroll probe target. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/probe-targets/{target_id}` {#retire-probe-target-v1-mcp-tenant-slug-endpoints-endpoint-id-probe-targets-target-id-delete}

**Retire Probe Target**

Retire an allowlist entry (soft; historical audit rows citing it stay interpretable).

404 for a cross-tenant endpoint or a target id that is not this endpoint's live entry.

Operation id: `retire_probe_target_v1_mcp__tenant_slug__endpoints__endpoint_id__probe_targets__target_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `target_id` | path | string (uuid) | yes | Path parameter identifying the target id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for retire probe target. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/probe` {#run-probe-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-probe-post}

**Run Probe**

Run a probe profile against one version snapshot.

``profile`` (body) defaults to ``passive``. The passive profile re-reads the captured transcript,
sends nothing, needs no consent, and is always available (subject to nothing but the snapshot
existing). Active profiles (``safe-active``, ``payload-fuzzing``) pass, in order: the global kill
switch and this tenant's concurrency/rate budget, then consent (the target must be allowlisted,
ownership declared, the run acknowledged, a dedicated identity used, and — for fuzzing — explicitly
approved), then isolation (a stdio target needs a least-privilege sandbox). Every refusal and
every completed active run is recorded in the audit trail.

404 when the endpoint/version is not the caller's; 400 on an unknown profile; 403 when a gate
refuses; 503 when active probing is requested but this deployment has no probe runner configured.

Operation id: `run_probe_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__probe_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for run probe.

- `application/json` — object or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for run probe. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
