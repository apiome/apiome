---
title: "Catalog refresh"
description: "REST endpoints tagged catalog-refresh: 6 operations."
sidebar_position: 16
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.440.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `catalog-refresh` · 6 operations

## `GET /v1/catalog/{tenant_slug}/refresh-policy` {#get-catalog-refresh-policy-v1-catalog-tenant-slug-refresh-policy-get}

**Get Catalog Refresh Policy**

Read the tenant kill switch for catalog item refresh (``projects:view``).

Operation id: `get_catalog_refresh_policy_v1_catalog__tenant_slug__refresh_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get catalog refresh policy. | `application/json` [`CatalogRefreshPolicy`](#schema-catalogrefreshpolicy) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/catalog/{tenant_slug}/refresh-policy` {#set-catalog-refresh-policy-v1-catalog-tenant-slug-refresh-policy-put}

**Set Catalog Refresh Policy**

Turn catalog item refresh on or off for the whole tenant (``imports:edit``).

Off stops the scheduled sweep and manual checks for every item in the tenant; each item's
setting is kept and resumes when the switch is turned back on.

Operation id: `set_catalog_refresh_policy_v1_catalog__tenant_slug__refresh_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set catalog refresh policy.

- `application/json` — [`CatalogRefreshPolicy`](#schema-catalogrefreshpolicy)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set catalog refresh policy. | `application/json` [`CatalogRefreshPolicy`](#schema-catalogrefreshpolicy) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}/refresh` {#get-catalog-item-refresh-v1-catalog-tenant-slug-item-id-refresh-get}

**Get Catalog Item Refresh**

Read an item's refresh setting and last check (``projects:view``).

An item with no setting answers ``configured: false`` with cadence ``off``.

Operation id: `get_catalog_item_refresh_v1_catalog__tenant_slug___item_id__refresh_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get catalog item refresh. | `application/json` [`CatalogRefreshOut`](#schema-catalogrefreshout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/catalog/{tenant_slug}/{item_id}/refresh` {#put-catalog-item-refresh-v1-catalog-tenant-slug-item-id-refresh-put}

**Put Catalog Item Refresh**

Create or replace an item's refresh setting (``projects:edit``).

The adapter must support live discovery and have a refresh runner (``graphql``, ``grpc``, ``fhir``);
the endpoint must pass the SSRF URL policy. Changing the adapter or endpoint resets the check
history; saving always clears any failure backoff.

Raises:
    HTTPException: 404 for an unknown item; 422 ``adapter-not-refreshable`` /
        ``invalid-endpoint`` / ``invalid-credential``; 503 when credential encryption is not
        configured and a credential is supplied.

Operation id: `put_catalog_item_refresh_v1_catalog__tenant_slug___item_id__refresh_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put catalog item refresh.

- `application/json` — [`CatalogRefreshUpdate`](#schema-catalogrefreshupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put catalog item refresh. | `application/json` [`CatalogRefreshOut`](#schema-catalogrefreshout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/catalog/{tenant_slug}/{item_id}/refresh` {#delete-catalog-item-refresh-v1-catalog-tenant-slug-item-id-refresh-delete}

**Delete Catalog Item Refresh**

Remove an item's refresh setting and its credential (``projects:edit``). Idempotent.

Operation id: `delete_catalog_item_refresh_v1_catalog__tenant_slug___item_id__refresh_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete catalog item refresh. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/catalog/{tenant_slug}/{item_id}/refresh/check` {#check-catalog-item-refresh-v1-catalog-tenant-slug-item-id-refresh-check-post}

**Check Catalog Item Refresh**

Run one live check now and return the recorded outcome (``projects:edit``).

Works for every cadence except ``off``, including ``manual``. When the live source differs from
the item's current version, the check adds a version through the import pipeline exactly as a
manual re-import would, with a change report, and answers ``status: changed``; its provenance
records ``refreshTrigger: manual``. An unchanged source creates nothing. A failed check answers
200 with ``status: failed`` and the reason; like a scheduled failure it backs off the next
scheduled check and never creates a version.

Raises:
    HTTPException: 404 when the item has no refresh setting; 409 ``refresh-off`` when its
        cadence is off, ``refresh-disabled`` when the tenant or deployment switch is off.

Operation id: `check_catalog_item_refresh_v1_catalog__tenant_slug___item_id__refresh_check_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for check catalog item refresh. | `application/json` [`CatalogRefreshOut`](#schema-catalogrefreshout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CatalogRefreshOut` {#schema-catalogrefreshout}

An item's refresh setting and the outcome of its last check. Never carries a credential.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `itemId` | string | yes | Item ID. |
| `configured` | boolean | yes | False when the item has no refresh setting (the defaults below). |
| `cadence` | enum `"off"`, `"manual"`, `"hourly"`, `"daily"`, `"weekly"` | yes | Cadence. |
| `adapter` | string or null | no | Adapter. |
| `endpoint` | string or null | no | Endpoint. |
| `options` | object | no | Options. |
| `authType` | enum `"none"`, `"bearer"`, `"header"`, `"oauth2"` | no | Auth Type. |
| `hasCredential` | boolean | no | Has Credential. |
| `status` | enum `"never"`, `"unchanged"`, `"changed"`, `"failed"` | no | The last check: never (not run yet), unchanged (the live source matches the item's current version), changed (the live source differed, so the check added a version), failed. |
| `lastCheckedAt` | string or null | no | Last Checked At. |
| `lastSuccessAt` | string or null | no | Last Success At. |
| `lastFailureAt` | string or null | no | Last Failure At. |
| `lastError` | string or null | no | Last Error. |
| `lastFingerprint` | string or null | no | Last Fingerprint. |
| `consecutiveFailures` | integer | no | Consecutive Failures. |
| `nextCheckAt` | string or null | no | When the sweep next checks the item (null for off / manual). |
| `keepVersions` | integer | no | Refresh-created versions kept; older ones are pruned (MFI-31.5). |
| `tenantEnabled` | boolean | no | Tenant Enabled. |
| `cadences` | array of string | no | Cadences. |
| `adapters` | array of string | no | Adapters that can be refreshed. |
| `authTypes` | array of string | no | Auth Types. |

### `CatalogRefreshPolicy` {#schema-catalogrefreshpolicy}

The tenant kill switch for catalog item refresh.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | yes | Whether the resource is active. |

### `CatalogRefreshUpdate` {#schema-catalogrefreshupdate}

``PUT …/{item_id}/refresh``: the whole setting.

Leave ``credential`` out to keep the stored one, send ``null`` to clear it, or send an object
to replace it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `cadence` | enum `"off"`, `"manual"`, `"hourly"`, `"daily"`, `"weekly"` | yes | off · manual · hourly · daily · weekly. |
| `adapter` | string | yes | The import adapter: `graphql`, `grpc` or `fhir`. |
| `endpoint` | string | yes | An http(s) URL for GraphQL; a `host:port` target for gRPC; a FHIR server's base URL (its `/metadata` is read). |
| `options` | object | no | Adapter options; gRPC reads `secure` (TLS, default false). |
| `credential` | `CatalogRefreshCredential` or null | no | Credential. |
| `keepVersions` | integer or null | no | How many refresh-created versions to keep (MFI-31.5); older ones are pruned unless tagged, a conversion source, breaking drift or its baseline, locked, or the newest. Leave out to keep the stored value (50 for a new setting). |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
