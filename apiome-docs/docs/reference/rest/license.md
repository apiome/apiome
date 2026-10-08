---
title: "License"
description: "REST endpoints tagged license: 1 operation."
sidebar_position: 29
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `license` · 1 operation

## `GET /v1/tenants/{tenant_slug}/license` {#get-tenant-license-v1-tenants-tenant-slug-license-get}

**Get Tenant License**

Read the tenant's plan, seat usage, and effective features (OLO-5.4).

Args:
    tenant_slug: Tenant slug from the path; membership is validated by
        ``validate_authentication``.
    auth_data: The authenticated principal (tenant_id resolved from the slug).

Returns:
    The tenant's license summary. ``plan`` is null for a tenant with no
    license row; ``seats.max`` then falls back to the Free default so the
    numbers always match what the OLO-5.3 guard enforces.

Operation id: `get_tenant_license_v1_tenants__tenant_slug__license_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant license. | `application/json` [`TenantLicenseResponse`](#schema-tenantlicenseresponse) |
| 401 | Missing or invalid credentials. | — |
| 403 | Caller is not a member, or lacks billing:view. | — |
| 404 | Tenant not found. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `TenantLicenseResponse` {#schema-tenantlicenseresponse}

Payload of ``GET /v1/tenants/{tenant_slug}/license``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `plan` | `LicensePlanSchema` or null | no | Attached plan; null when the tenant has no license row (pre-V183 tenant). |
| `seats` | `LicenseSeatsSchema` | yes | Seats. |
| `quotas` | `LicenseQuotasSchema` | yes | Quotas. |
| `features` | array of `LicenseFeatureSchema` | no | Features. |
