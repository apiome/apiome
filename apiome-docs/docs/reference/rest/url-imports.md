---
title: "URL imports"
description: "REST endpoints tagged url-imports: 3 operations."
sidebar_position: 99
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.429.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `url-imports` · 3 operations

## `GET /v1/tenants/{tenant_slug}/url-imports` {#list-url-imports-v1-tenants-tenant-slug-url-imports-get}

**List URL imports and their refresh state**

List the tenant's URL imports, newest first, with when each was last checked and refreshed.

Operation id: `list_url_imports_v1_tenants__tenant_slug__url_imports_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `projectId` | query | string or null | no | Only this project's. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list url imports and their refresh state. | `application/json` [`UrlImportList`](#schema-urlimportlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/url-imports` {#record-url-import-route-v1-tenants-tenant-slug-url-imports-post}

**Record a URL import for auto-refresh**

Record a URL import that just succeeded, so the URL refresh sweep keeps it up to date.

REST fetches the URL once (SSRF-guarded) to store the ``ETag``, ``Last-Modified`` and SHA-256
a refresh compares with. When that fetch fails the lineage is still recorded, with the error,
and the first check anchors on what the URL serves then. Recording the same URL for the same
project again replaces the stored spec and anchors and keeps the refresh settings.

Raises:
    HTTPException: 404 when the project is not the tenant's; 422 for a URL that is not
        http/https or carries credentials, or a version that is not the project's.

Operation id: `record_url_import_route_v1_tenants__tenant_slug__url_imports_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record a url import for auto-refresh.

- `application/json` — [`UrlImportRecordRequest`](#schema-urlimportrecordrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for record a url import for auto-refresh. | `application/json` [`UrlImportOut`](#schema-urlimportout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/url-imports/{url_import_id}` {#patch-url-import-v1-tenants-tenant-slug-url-imports-url-import-id-patch}

**Turn a URL import's refresh on or off, or set its cadence**

Change a URL import's refresh (``imports:edit``). Turning it on clears any backoff.

Raises:
    HTTPException: 404 when the URL import is not the tenant's.

Operation id: `patch_url_import_v1_tenants__tenant_slug__url_imports__url_import_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `url_import_id` | path | string | yes | Path parameter identifying the url import id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for turn a url import's refresh on or off, or set its cadence.

- `application/json` — [`UrlImportSettingsPatch`](#schema-urlimportsettingspatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for turn a url import's refresh on or off, or set its cadence. | `application/json` [`UrlImportOut`](#schema-urlimportout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `UrlImportList` {#schema-urlimportlist}

URL import lineages, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `urlImports` | array of [`UrlImportOut`](#schema-urlimportout) | yes | URL Imports. |

### `UrlImportOut` {#schema-urlimportout}

A URL import lineage and its refresh state.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `projectId` | string | yes | Project ID. |
| `projectName` | string or null | no | Project Name. |
| `projectSlug` | string or null | no | Project Slug. |
| `url` | string | yes | URL. |
| `sourceKind` | string | yes | Source Kind. |
| `authenticated` | boolean | yes | Imported with credentials: never refreshed. |
| `refreshable` | boolean | yes | On, and not authenticated: the sweep checks it. |
| `autoRefreshEnabled` | boolean | yes | Auto Refresh Enabled. |
| `refreshIntervalSeconds` | integer or null | no | Own cadence; null means the default. |
| `effectiveIntervalSeconds` | integer | yes | The cadence the sweep uses. |
| `etag` | string or null | no | ETag recorded at the last import. |
| `lastModified` | string or null | no | Last-Modified recorded at the last import. |
| `lastVersionId` | string or null | no | Last Version ID. |
| `lastCheckedAt` | string or null | no | Last Checked At. |
| `lastRefreshedAt` | string or null | no | Last Refreshed At. |
| `lastStatus` | enum `"up-to-date"`, `"refreshing"`, `"refreshed"`, `"diverged"`, `"failed"` or null | no | Last Status. |
| `lastReason` | string or null | no | Why: not-modified, idempotent, stale, newer-content, baseline, manual-edit, or an error class. |
| `lastError` | string or null | no | Last Error. |
| `consecutiveFailures` | integer | no | Consecutive Failures. |
| `backoffUntil` | string or null | no | Backoff Until. |
| `createdAt` | string or null | no | Created At. |
| `updatedAt` | string or null | no | Updated At. |

### `UrlImportRecordRequest` {#schema-urlimportrecordrequest}

A URL import that just succeeded.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | The project the import landed in. |
| `url` | string | yes | The http/https URL the spec was imported from. |
| `versionId` | string or null | no | The version the import produced (versions.id); its content is the manual-edit baseline. |
| `sourceKind` | string | no | Importer kind (openapi, arazzo). |
| `formatOverride` | string or null | no | Resolved spec format, when recorded. |
| `contentType` | string or null | no | MIME type the document was parsed as. |
| `options` | object | no | The import options, verbatim; a refresh replays them. |
| `authenticated` | boolean | no | The import was fetched with credentials. Recorded but never refreshed; credentials are not sent. |

### `UrlImportSettingsPatch` {#schema-urlimportsettingspatch}

Change a URL lineage's refresh; an omitted field is left as it is.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `autoRefreshEnabled` | boolean or null | no | Refresh this URL on its cadence. |
| `refreshIntervalSeconds` | integer or null | no | Seconds between checks (raised to the deployment floor). Omit to keep it. |
| `useDefaultInterval` | boolean | no | Go back to the deployment's default cadence. |
