---
title: "Export mock"
description: "REST endpoints tagged export-mock: 6 operations."
sidebar_position: 23
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `export-mock` · 6 operations

## `GET /v1/export/{tenant_slug}/mock` {#list-export-mocks-v1-export-tenant-slug-mock-get}

**List the tenant's live test-drive mocks**

The live test-drive mocks this workspace holds, newest first — what the per-tenant concurrency cap is measured against. Expired instances are omitted; hosted mocks provisioned from a published version (#3615) are managed on ``/v1/mocks/…`` and never appear here.

Operation id: `list_export_mocks_v1_export__tenant_slug__mock_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the tenant's live test-drive mocks. | `application/json` array of [`ExportMockInstanceResponse`](#schema-exportmockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/mock` {#provision-export-mock-v1-export-tenant-slug-mock-post}

**Start an ephemeral mock of an emitted export artifact**

Emit the source revision to the requested target, freeze the resulting OpenAPI document into a short-lived, tenant-scoped mock instance, and return its live base URL. The instance is served by the existing Mock Server data plane (``/v1/mock/{mock_id}/…``) and auto-tears-down at its TTL — after which the same URL answers ``410 Gone``. Only targets the engine can serve (the capability endpoint's ``supportedTargets``) are accepted.

Operation id: `provision_export_mock_v1_export__tenant_slug__mock_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for start an ephemeral mock of an emitted export artifact.

- `application/json` — [`ExportMockProvisionRequest`](#schema-exportmockprovisionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for start an ephemeral mock of an emitted export artifact. | `application/json` [`ExportMockInstanceResponse`](#schema-exportmockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/mock/capability` {#get-export-mock-capability-v1-export-tenant-slug-mock-capability-get}

**Can this server start a mock of an emitted artifact?**

The capability signal the Export Studio renders its Test-drive tab from (MFX-44.1's flag, answered for the mock tool). Reports whether the Mock Server engine is deployed and the export binding enabled, which target keys the engine can serve, and the TTL / concurrency / rate bounds a provision will apply — so a disabled panel can say why and an enabled one can state the terms before the user clicks Start.

Operation id: `get_export_mock_capability_v1_export__tenant_slug__mock_capability_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for can this server start a mock of an emitted artifact?. | `application/json` [`ExportMockCapabilityResponse`](#schema-exportmockcapabilityresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/mock/{mock_id}` {#get-export-mock-v1-export-tenant-slug-mock-mock-id-get}

**Inspect one test-drive mock**

One instance with a freshly computed expiry countdown and request count — what the Studio polls while a mock is live, and how it learns the mock has expired.

Operation id: `get_export_mock_v1_export__tenant_slug__mock__mock_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for inspect one test-drive mock. | `application/json` [`ExportMockInstanceResponse`](#schema-exportmockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/export/{tenant_slug}/mock/{mock_id}` {#destroy-export-mock-v1-export-tenant-slug-mock-mock-id-delete}

**Stop a test-drive mock now**

Tear the instance down before its TTL and discard its request log. The base URL stops resolving immediately, and the workspace's concurrency budget is freed.

Operation id: `destroy_export_mock_v1_export__tenant_slug__mock__mock_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for stop a test-drive mock now. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/mock/{mock_id}/requests` {#get-export-mock-requests-v1-export-tenant-slug-mock-mock-id-requests-get}

**Read a test-drive mock's request log**

The requests this mock served, newest first: method, path, status, whether an operation matched, the scenario in force, and whether the body agreed with the response schema. The log is a bounded in-memory ring buffer scoped to the serving replica — a live view of a mock that expires in minutes, not a durable audit trail.

Operation id: `get_export_mock_requests_v1_export__tenant_slug__mock__mock_id__requests_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `limit` | query | integer | no | Most entries to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a test-drive mock's request log. | `application/json` [`ExportMockRequestLogResponse`](#schema-exportmockrequestlogresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ExportMockCapabilityResponse` {#schema-exportmockcapabilityresponse}

Whether this server can start test-drive mocks, and the bounds it applies (MFX-44.5).

The Studio calls this **before** it renders anything mock-shaped: an unavailable server means
no Test-drive tab (or a disabled one carrying :attr:`reason`), and ``supported_targets`` keeps
the decision of *which* targets can be mocked on the server, where the emitter registry lives.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `available` | boolean | yes | Whether a mock can be provisioned on this server now. |
| `reason` | string or null | no | Why mocking is unavailable, or ``null`` when it is available. |
| `supportedTargets` | array of string | yes | Target emitter keys whose emitted document the mock engine can serve. |
| `defaultTtlMinutes` | integer | yes | TTL applied when a provision request names none. |
| `maxTtlMinutes` | integer | yes | Ceiling a requested TTL is clamped to. |
| `maxPerTenant` | integer | yes | Concurrent live test-drive mocks one tenant may hold. |
| `rateLimitPerMinute` | integer | yes | Per-instance request budget the data plane enforces. |

### `ExportMockInstanceResponse` {#schema-exportmockinstanceresponse}

A live test-drive mock: where to reach it, what it serves, and when it disappears.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | The mock instance id. |
| `baseUrl` | string | yes | Stable base URL of the mock's data plane; append an operation path to it. |
| `status` | string | yes | ``active`` while it serves, ``expired`` once past its TTL. |
| `target` | string | yes | The resolved target format key the mock was emitted from. |
| `targetKey` | string | yes | The emitter *key* the mock was started for (``openapi``) — what the Studio holds, so it can recognise a mock of the configuration it is showing. |
| `targetLabel` | string | yes | Human label of that target (e.g. ``OpenAPI 3.1``). |
| `artifact` | string | yes | The artifact (project) id the mock was provisioned from. |
| `version` | string or null | no | The resolved revision's version label, when it has one. |
| `operationCount` | integer | yes | How many operations the frozen document exposes. |
| `operations` | array of `ExportMockOperation` | no | The operations themselves, ordered by path then method. |
| `scenarios` | array of string | no | Selectable scenario names; send one as ``X-Mock-Scenario`` per request. |
| `activeScenario` | string | yes | The scenario in force when a request names none. |
| `rateLimitPerMinute` | integer | yes | Per-instance request budget the data plane enforces. |
| `requestCount` | integer | yes | Lifetime data-plane requests served (best-effort). |
| `createdAt` | string or null | no | ISO-8601 provision time. |
| `expiresAt` | string or null | no | ISO-8601 auto-teardown time. |
| `expiresInSeconds` | integer | yes | Seconds until auto-teardown, computed server-side so the countdown is immune to browser clock skew; ``0`` once expired. |
| `lastActivityAt` | string or null | no | ISO-8601 time of the last served request, or null if none yet. |

### `ExportMockProvisionRequest` {#schema-exportmockprovisionrequest}

Start a test-drive mock for one (source, target, options) export configuration.

The same coordinates ``/verify``, ``/document`` and ``/roundtrip`` take, so the mock serves
*exactly* the artifact the Studio is showing: the emit is re-run server-side from the source
revision rather than trusting a document posted by the browser.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to mock an export of. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. |
| `ttlMinutes` | integer or null | no | Auto-teardown TTL in minutes; clamped to the configured maximum. |
| `seed` | integer or null | no | Deterministic response-generation seed; defaults to 0 (stable bodies). |

### `ExportMockRequestLogResponse` {#schema-exportmockrequestlogresponse}

The retained request log for one mock instance, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mockId` | string | yes | The instance the log is for. |
| `entries` | array of `ExportMockRequestEntryResponse` | no | Retained requests, newest first. |
| `retained` | integer | yes | How many requests the log currently holds. |
| `capacity` | integer | yes | How many the ring buffer retains per instance before discarding the oldest. |
| `truncated` | boolean | yes | True when the instance has served more requests than the log retains. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
