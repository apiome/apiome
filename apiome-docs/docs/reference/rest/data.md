---
title: "Data"
description: "REST endpoints tagged data: 6 operations."
sidebar_position: 17
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `data` · 6 operations

## `GET /v1/data/{tenant_slug}` {#data-api-info-v1-data-tenant-slug-get}

**Data Api Info**

Verify data API is mounted and tenant is authenticated. Returns 200 with tenant_slug.

Operation id: `data_api_info_v1_data__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for data api info. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/data/{tenant_slug}/records` {#create-data-record-v1-data-tenant-slug-records-post}

**Create Data Record**

Create a new data record and data_snapshot row.
Embedding is computed asynchronously and stored in data_snapshot.

Operation id: `create_data_record_v1_data__tenant_slug__records_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create data record.

- `application/json` — [`DataRecordCreateBody`](#schema-datarecordcreatebody)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create data record. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/data/{tenant_slug}/records/{record_id}` {#get-data-record-v1-data-tenant-slug-records-record-id-get}

**Get Data Record**

Get the current snapshot data for a record (for edit form).
Returns 404 if record not found or deleted.

Operation id: `get_data_record_v1_data__tenant_slug__records__record_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `record_id` | path | string | yes | Data record identifier. |
| `class_schema_id` | query | string | yes | Class schema ID |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get data record. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/data/{tenant_slug}/records/{record_id}` {#update-data-record-v1-data-tenant-slug-records-record-id-patch}

**Update Data Record**

Update an existing data record and data_snapshot.
Embedding is recomputed asynchronously and stored in data_snapshot.

Operation id: `update_data_record_v1_data__tenant_slug__records__record_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `record_id` | path | string | yes | Data record identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update data record.

- `application/json` — [`DataRecordUpdateBody`](#schema-datarecordupdatebody)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update data record. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/data/{tenant_slug}/records/{record_id}` {#delete-data-record-v1-data-tenant-slug-records-record-id-delete}

**Delete Data Record**

Delete a data record (append deleted event, remove data_snapshot row).

Operation id: `delete_data_record_v1_data__tenant_slug__records__record_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `record_id` | path | string | yes | Data record identifier. |
| `class_schema_id` | query | string | yes | Class schema ID |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete data record. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/data/{tenant_slug}/records/{record_id}/restore` {#restore-data-record-v1-data-tenant-slug-records-record-id-restore-post}

**Restore Data Record**

Restore a deleted data record (recreate data_snapshot from deleted event, append restored event).

Operation id: `restore_data_record_v1_data__tenant_slug__records__record_id__restore_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `record_id` | path | string | yes | Data record identifier. |
| `class_schema_id` | query | string | yes | Class schema ID |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for restore data record. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `DataRecordCreateBody` {#schema-datarecordcreatebody}

DataRecordCreateBody schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `class_schema_id` | string | yes | Class schema ID (frozen version class) |
| `data` | object | yes | Record payload validated against schema |

### `DataRecordUpdateBody` {#schema-datarecordupdatebody}

DataRecordUpdateBody schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `class_schema_id` | string | yes | Class schema ID |
| `data` | object | yes | Updated record payload |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
