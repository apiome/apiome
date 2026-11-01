---
title: "Catalog upload"
description: "REST endpoints tagged catalog-upload: 4 operations."
sidebar_position: 17
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.453.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `catalog-upload` · 4 operations

## `GET /v1/catalog/{tenant_slug}/upload-policy` {#get-catalog-upload-policy-v1-catalog-tenant-slug-upload-policy-get}

**Get Catalog Upload Policy**

Read the tenant's staleness threshold for uploaded catalog items (``projects:view``).

Operation id: `get_catalog_upload_policy_v1_catalog__tenant_slug__upload_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get catalog upload policy. | `application/json` [`CatalogUploadPolicy`](#schema-cataloguploadpolicy) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/catalog/{tenant_slug}/upload-policy` {#set-catalog-upload-policy-v1-catalog-tenant-slug-upload-policy-put}

**Set Catalog Upload Policy**

Change how many days old an uploaded item's newest version is before it may be stale (``imports:edit``).

Operation id: `set_catalog_upload_policy_v1_catalog__tenant_slug__upload_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set catalog upload policy.

- `application/json` — [`CatalogUploadPolicy`](#schema-cataloguploadpolicy)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set catalog upload policy. | `application/json` [`CatalogUploadPolicy`](#schema-cataloguploadpolicy) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/catalog/{tenant_slug}/{item_id}/reupload` {#reupload-catalog-item-v1-catalog-tenant-slug-item-id-reupload-post}

**Reupload Catalog Item**

Re-import a new copy of the item's uploaded file with the import spec it recorded.

The file goes through the import pipeline with the importer and options of the original upload,
and the tenant's import quality gate, exactly as an upload would. A file identical to the
current version writes nothing (``unchanged``); a changed one adds a date/time-labelled version
with a change report against the version it supersedes (``changed``).

Raises:
    HTTPException: 404 when the item is not a catalog item in the tenant; 409 ``not-an-upload``
        when its newest version did not come from an upload; 409 ``QUALITY_POLICY_BLOCKED``;
        413 when the file is over the intake limit; 422 when the file is not valid base64 or
        cannot be imported.

Operation id: `reupload_catalog_item_v1_catalog__tenant_slug___item_id__reupload_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for reupload catalog item.

- `application/json` — [`CatalogReuploadRequest`](#schema-catalogreuploadrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for reupload catalog item. | `application/json` [`CatalogReuploadOut`](#schema-catalogreuploadout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}/upload` {#get-catalog-item-upload-v1-catalog-tenant-slug-item-id-upload-get}

**Get Catalog Item Upload**

Whether the item came from an upload, how old it is and whether it may be stale (``projects:view``).

Operation id: `get_catalog_item_upload_v1_catalog__tenant_slug___item_id__upload_get`

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
| 200 | Successful response for get catalog item upload. | `application/json` [`CatalogUploadOut`](#schema-cataloguploadout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CatalogReuploadOut` {#schema-catalogreuploadout}

What a re-upload did, and the item's upload state afterwards.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | enum `"changed"`, `"unchanged"` | yes | changed: the file differed, so a version was added; unchanged: it matches the current version and nothing was written. |
| `specReplayed` | boolean | yes | True when the stored import spec was replayed; false for an upload from before spec capture, which ran with default options. |
| `versionId` | string or null | no | Version ID. |
| `versionLabel` | string or null | no | Version Label. |
| `upload` | [`CatalogUploadOut`](#schema-cataloguploadout) | yes | Upload. |

### `CatalogReuploadRequest` {#schema-catalogreuploadrequest}

``POST …/{item_id}/reupload``: the new copy of the file.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `filename` | string | yes | The file's name. |
| `documentBase64` | string | yes | Standard base64 (RFC 4648) of the file bytes; no data: URL prefix. |
| `contentType` | string or null | no | Optional MIME type hint. |

### `CatalogUploadOut` {#schema-cataloguploadout}

Whether an item's current version came from an upload and whether it may be stale.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `itemId` | string | yes | Item ID. |
| `eligible` | boolean | yes | True when the item's newest version came from a file upload, so it can be re-uploaded. |
| `stale` | boolean | yes | True when it is eligible and at least `staleAfterDays` old. |
| `staleAfterDays` | integer | yes | Stale After Days. |
| `uploadedAt` | string or null | no | Uploaded At. |
| `ageDays` | integer or null | no | Age Days. |
| `versionId` | string or null | no | Version ID. |
| `versionLabel` | string or null | no | Version Label. |
| `sourceLabel` | string or null | no | The uploaded file's name. |
| `spec` | `CatalogUploadSpec` or null | no | The stored import spec; null for an upload from before spec capture, whose re-upload runs with default options. |

### `CatalogUploadPolicy` {#schema-cataloguploadpolicy}

The tenant's staleness threshold for uploaded catalog items.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `staleAfterDays` | integer | yes | An uploaded item's newest version this many days old or older may be stale (default 90). |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
