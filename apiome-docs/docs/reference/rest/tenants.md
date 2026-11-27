---
title: "Tenants"
description: "REST endpoints tagged tenants: 7 operations."
sidebar_position: 113
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.691.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `tenants` · 7 operations

## `GET /v1/tenants/me` {#list-my-tenants-v1-tenants-me-get}

**List My Tenants**

Tenants accessible to the caller, enriched for the tenant switcher (OLO-6.2, #4219).

Ordered by slug. Pages by ``cursor``: pass the previous page's ``next_cursor`` until
``has_more`` is false. ``total`` is the caller's own membership count — a list one user
bounds — so it is always present.

- JWT: all memberships for the user, each carrying the effective RBAC role slug
  (V119 assignment; legacy administrators read as ``owner``; Editor default),
  the V121 member lifecycle status, and the tenant's attached license plan —
  resolved in a single query, no per-tenant follow-ups.
- API key: the key's tenant only (single-item list) with role ``member`` and
  the tenant's license plan.

Operation id: `list_my_tenants_v1_tenants_me_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `limit` | query | integer | no | Page size. At most 100. |
| `cursor` | query | string or null | no | Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). Omit for the first page. |
| `offset` | query | integer | no | Rows to skip. Deprecated: page with `cursor` instead. At most 10,000. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list my tenants. | `application/json` [`TenantsMeResponse`](#schema-tenantsmeresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}` {#get-tenant-info-v1-tenants-tenant-slug-get}

**Get Tenant Info**

Tenant summary including usage counts; 403 when the caller cannot access the tenant.

Operation id: `get_tenant_info_v1_tenants__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tenant info. | `application/json` [`TenantInfoResponse`](#schema-tenantinforesponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `HEAD /v1/tenants/{tenant_slug}` {#verify-tenant-access-v1-tenants-tenant-slug-head}

**Verify Tenant Access**

Lightweight access check for CLI default-tenant selection (#3199).

Operation id: `verify_tenant_access_v1_tenants__tenant_slug__head`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Caller has access to the tenant. | — |
| 401 | Missing or invalid session credentials. | — |
| 403 | Credentials valid but caller has no access to this tenant. | — |
| 404 | Tenant not found. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/document-store` {#get-tenant-document-store-v1-tenants-tenant-slug-document-store-get}

**Read where the workspace's documents are kept**

Whether originals and rendered documents are kept in the install's store (`platform`) or in the workspace's own S3-compatible bucket (`tenant`), the bucket settings, whether the bucket answered the last time it was used, and the progress of a move. `allowed` is false when the install does not offer tenant buckets. A credential is never returned — only the id and name of the storage credential in use.

Requires `document_store:manage`.

Operation id: `get_tenant_document_store_v1_tenants__tenant_slug__document_store_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read where the workspace's documents are kept. | `application/json` [`TenantDocumentStore`](#schema-tenantdocumentstore) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/document-store` {#put-tenant-document-store-v1-tenants-tenant-slug-document-store-put}

**Choose where the workspace's documents are kept**

Set `mode` to `tenant` with a `credentialId` and `bucket` to keep documents in your own bucket, or to `platform` to go back to the install's store. Fields left out keep their saved value.

Before a bucket is saved it must pass the same write, read and delete test as `POST …/document-store/test`; a failed test answers `400 tenant-document-store-test-failed` and changes nothing. The endpoint must pass the SSRF guard.

Changing `mode` starts a move of the existing objects in the background. New documents go to the new place at once; each existing one is copied, verified and only then read from the new place, so nothing fails while the move runs. `GET` reports its progress. Old copies stay until `POST …/document-store/cleanup`.

`409 tenant-document-store-move-running` while a move runs. `409 tenant-document-store-bucket-in-use` when the bucket, folder or endpoint is changed while documents are stored there. `403 tenant-document-store-disabled` when the install does not offer tenant buckets.

Audited as `document_store.settings_updated`. Requires `document_store:manage`.

Operation id: `put_tenant_document_store_v1_tenants__tenant_slug__document_store_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for choose where the workspace's documents are kept.

- `application/json` — [`TenantDocumentStoreInput`](#schema-tenantdocumentstoreinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for choose where the workspace's documents are kept. | `application/json` [`TenantDocumentStore`](#schema-tenantdocumentstore) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/document-store/cleanup` {#cleanup-tenant-document-store-v1-tenants-tenant-slug-document-store-cleanup-post}

**Delete the copies a move left behind**

After a move, every moved object still has a copy in the place it came from. This deletes those copies. It needs `{"confirm": true}`; anything else answers `400 tenant-document-store-confirm-required`. An object that failed to move is never touched, so no document's only copy can be deleted. In your own bucket only keys under Apiome's folder for this workspace are removed.

`409 tenant-document-store-move-running` while a move runs.

Audited as `document_store.old_copies_deleted`. Requires `document_store:manage`.

Operation id: `cleanup_tenant_document_store_v1_tenants__tenant_slug__document_store_cleanup_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for delete the copies a move left behind.

- `application/json` — [`TenantDocumentStoreCleanupInput`](#schema-tenantdocumentstorecleanupinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete the copies a move left behind. | `application/json` [`TenantDocumentStoreCleanupResult`](#schema-tenantdocumentstorecleanupresult) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/document-store/test` {#test-tenant-document-store-v1-tenants-tenant-slug-document-store-test-post}

**Test the workspace's bucket**

Writes, reads back and deletes one small probe object under `<prefix>/tenants/<tenant id>/objects/sha256/…` — the key layout every document uses — so a bucket policy that does not allow it fails here and not during an import. Send settings in the body to test them before saving; send no body to test the saved settings.

Answers `200` whether or not the test passed: `ok` and each step's `error` say what failed. An error never contains a credential.

Requires `document_store:manage`.

Operation id: `test_tenant_document_store_v1_tenants__tenant_slug__document_store_test_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for test the workspace's bucket.

- `application/json` — [`TenantDocumentStoreInput`](#schema-tenantdocumentstoreinput) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for test the workspace's bucket. | `application/json` [`TenantDocumentStoreProbeResult`](#schema-tenantdocumentstoreproberesult) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `TenantDocumentStore` {#schema-tenantdocumentstore}

A tenant's document store settings, health and move progress. Never a credential.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `allowed` | boolean | yes | Whether this install lets workspaces use their own bucket. |
| `mode` | enum `"platform"`, `"tenant"` | yes | Mode. |
| `credentialId` | string or null | no | Credential ID. |
| `credentialName` | string or null | no | Credential Name. |
| `bucket` | string or null | no | Bucket. |
| `prefix` | string | no | Prefix. |
| `region` | string | no | Region. |
| `endpointUrl` | string | no | Endpoint URL. |
| `addressingStyle` | enum `"auto"`, `"path"`, `"virtual"` | no | Addressing Style. |
| `sse` | enum `""`, `"s3"`, `"kms"` | no | Sse. |
| `kmsKeyId` | string | no | Kms Key ID. |
| `health` | `TenantDocumentStoreHealth` | yes | Health. |
| `move` | `TenantDocumentStoreMove` | yes | Move. |
| `cleanupPending` | boolean | no | A finished move left old copies that `POST …/cleanup` deletes. |

### `TenantDocumentStoreCleanupInput` {#schema-tenantdocumentstorecleanupinput}

The explicit confirm that old copies may be deleted.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `confirm` | boolean | no | Confirm. |

### `TenantDocumentStoreCleanupResult` {#schema-tenantdocumentstorecleanupresult}

What the cleanup removed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `checked` | integer | yes | Checked. |
| `deleted` | integer | yes | Deleted. |

### `TenantDocumentStoreInput` {#schema-tenantdocumentstoreinput}

Where a tenant's documents should be kept.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `mode` | enum `"platform"`, `"tenant"` | yes | `platform` keeps documents in the install's store; `tenant` keeps them in your own bucket. |
| `credentialId` | string or null | no | A storage credential of this workspace (`POST /v1/export/{tenant}/storage-credentials`). |
| `bucket` | string or null | no | The bucket. It must already exist. |
| `prefix` | string or null | no | Folder inside the bucket. Defaults to `apiome`; empty writes at the root. |
| `region` | string or null | no | Signing region; empty takes the credential's. |
| `endpointUrl` | string or null | no | Service URL for a non-AWS store; empty takes the credential's. |
| `addressingStyle` | enum `"auto"`, `"path"`, `"virtual"` or null | no | Addressing Style. |
| `sse` | enum `""`, `"s3"`, `"kms"` or null | no | Server-side encryption: empty, `s3` (SSE-S3) or `kms` (SSE-KMS). |
| `kmsKeyId` | string or null | no | The KMS key for `sse = kms`. |

### `TenantDocumentStoreProbeResult` {#schema-tenantdocumentstoreproberesult}

The outcome of writing, reading back and deleting one probe object in the bucket.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Ok. |
| `bucket` | string or null | no | Bucket. |
| `error` | string or null | no | Why the test could not run at all. |
| `steps` | array of `TenantDocumentStoreProbeStep` | no | Steps. |

### `TenantInfoResponse` {#schema-tenantinforesponse}

Tenant summary for ``GET /v1/tenants/{slug}``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `plan` | string or null | no | Plan. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `members_count` | integer | no | Number of members. |
| `projects_count` | integer | no | Number of projects. |
| `versions_count` | integer | no | Number of versions. |
| `published_versions_count` | integer | no | Number of published versions. |
| `storage_used_bytes` | integer or null | no | Storage Used Bytes. |
| `storage_quota_bytes` | integer or null | no | Storage Quota Bytes. |

### `TenantsMeResponse` {#schema-tenantsmeresponse}

Paginated list of tenants for the current principal (JWT user or API key tenant).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `TenantMembershipSchema` | yes | Items. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | The offset used (deprecated; `0` when paging by cursor). |
| `has_more` | boolean | no | Whether another page exists. |
| `next_cursor` | string or null | no | Pass as `cursor` to read the next page; null on the last page. |
