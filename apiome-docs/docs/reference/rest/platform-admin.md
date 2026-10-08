---
title: "Platform admin"
description: "REST endpoints tagged platform-admin: 1 operation."
sidebar_position: 46
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `platform-admin` · 1 operation

## `POST /v1/platform/access-overrides` {#record-platform-override-v1-platform-access-overrides-post}

**Record Platform Override**

Record a platform-admin override against a tenant's audit ledger (``source='admin'``).

This is the platform plane: the caller must be a platform administrator (``platform_administrators``),
which is independent of any tenant's admin/Owner role. The action is logged for the named tenant.

Operation id: `record_platform_override_v1_platform_access_overrides_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record platform override.

- `application/json` — [`PlatformOverrideRequest`](#schema-platformoverriderequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for record platform override. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PlatformOverrideRequest` {#schema-platformoverriderequest}

A platform-admin override action to record against a tenant's audit ledger.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `target` | string | yes | Target. |
| `detail` | object or null | no | Detail. |
