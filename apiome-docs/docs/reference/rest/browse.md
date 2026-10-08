---
title: "Browse"
description: "REST endpoints tagged browse: 9 operations."
sidebar_position: 8
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `browse` · 9 operations

## `GET /v1/browse/tenants` {#list-public-browse-tenants-v1-browse-tenants-get}

**List Public Browse Tenants**

Operation id: `list_public_browse_tenants_v1_browse_tenants_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `search` | query | string or null | no | Case-insensitive substring filter on tenant name and slug. |
| `sort` | query | enum `"latest"`, `"name"`, `"projects"` | no | Sort order: name (default), projects (desc), or latest activity (desc). |
| `protocol` | query | string or null | no | Filter by canonical paradigm: rest, rpc, event, graph, data_schema, agent. Punctuation-insensitive (``data-schema`` works) and unknown values simply match nothing. |
| `format` | query | string or null | no | Filter by specific source format key as captured at import (e.g. openapi-3.1, protobuf, graphql). Case-insensitive; unknown values simply match nothing. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list public browse tenants. | `application/json` [`BrowsePublicTenantsResponse`](#schema-browsepublictenantsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/browse/tenants/{tenant_slug}/projects` {#list-public-browse-projects-v1-browse-tenants-tenant-slug-projects-get}

**List Public Browse Projects**

Operation id: `list_public_browse_projects_v1_browse_tenants__tenant_slug__projects_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `search` | query | string or null | no | Case-insensitive substring filter on project slug and name. |
| `domain` | query | string or null | no | Filter by project metadata domain or domainCategory (case-insensitive). |
| `has_published` | query | boolean | no | Only include projects with at least one published version (visibility rules apply). |
| `protocol` | query | string or null | no | Filter by canonical paradigm: rest, rpc, event, graph, data_schema, agent. Punctuation-insensitive (``data-schema`` works) and unknown values simply match nothing. |
| `format` | query | string or null | no | Filter by specific source format key as captured at import (e.g. openapi-3.1, protobuf, graphql). Case-insensitive; unknown values simply match nothing. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list public browse projects. | `application/json` [`BrowsePublicProjectsResponse`](#schema-browsepublicprojectsresponse) |
| 401 | Credentials provided but could not be validated. | — |
| 403 | Credentials provided but not authorized for this tenant. | — |
| 404 | Tenant not found. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions` {#list-public-browse-versions-v1-browse-tenants-tenant-slug-projects-project-slug-versions-get}

**List Public Browse Versions**

Operation id: `list_public_browse_versions_v1_browse_tenants__tenant_slug__projects__project_slug__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `since` | query | string (date-time) or null | no | Include only versions whose published_at is at or after this timestamp (ISO 8601). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list public browse versions. | `application/json` [`BrowsePublicVersionsResponse`](#schema-browsepublicversionsresponse) |
| 401 | Credentials provided but could not be validated. | — |
| 403 | Credentials provided but not authorized for this tenant. | — |
| 404 | Tenant or project not found. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions/{version_slug}/export/document` {#emit-public-export-document-v1-browse-tenants-tenant-slug-projects-project-slug-versions-version-slug-export-document-post}

**Emit the export document for a published public version (no auth)**

Emit the published public version to one ``target`` through the Emitter SPI and return the document itself — JSON by default, YAML when ``Accept: application/yaml`` is sent — as a download. The anonymous counterpart of ``POST /v1/export/{tenant_slug}/document``. Strictly read-only: no field-identity state is persisted for anonymous exports.

Operation id: `emit_public_export_document_v1_browse_tenants__tenant_slug__projects__project_slug__versions__version_slug__export_document_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `accept` | header | string or null | no | Requested response content type (``Accept`` header). |

**Request body** (required)

Request body for emit the export document for a published public version (no auth).

- `application/json` — [`PublicExportDocumentRequest`](#schema-publicexportdocumentrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for emit the export document for a published public version (no auth). | — |
| 404 | No published public version matches the slugs (private, draft, and unknown versions are indistinguishable). | — |
| 413 | Emitted document exceeds the public download size cap (MFX-7.3). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded (MFX-7.3). | — |

## `POST /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions/{version_slug}/export/preview` {#preview-public-export-fidelity-v1-browse-tenants-tenant-slug-projects-project-slug-versions-version-slug-export-preview-post}

**Preview export fidelity for a published public version (no auth)**

Compute the full fidelity report for exporting the published public version to one target — the per-construct LossinessReport, the user-facing advisory (MFX-2.4), and the tier summary — **without producing the artifact**. The anonymous counterpart of ``POST /v1/export/{tenant_slug}/preview``; backs the public fidelity advisory (MFX-7.2).

Operation id: `preview_public_export_fidelity_v1_browse_tenants__tenant_slug__projects__project_slug__versions__version_slug__export_preview_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |

**Request body** (required)

Request body for preview export fidelity for a published public version (no auth).

- `application/json` — [`PublicExportPreviewRequest`](#schema-publicexportpreviewrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview export fidelity for a published public version (no auth). | `application/json` [`PublicExportPreviewResponse`](#schema-publicexportpreviewresponse) |
| 404 | No published public version matches the slugs (private, draft, and unknown versions are indistinguishable). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded (MFX-7.3). | — |

## `GET /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions/{version_slug}/export/targets` {#list-public-export-targets-v1-browse-tenants-tenant-slug-projects-project-slug-versions-version-slug-export-targets-get}

**List export targets for a published public version (no auth)**

For the published public version identified by the slugs, enumerate every registered export target (descriptor + capability profile + options) with a cheap per-target fidelity badge (tier + preserved-%). The anonymous counterpart of ``GET /v1/export/{tenant_slug}/targets``; drives the public export dialog's target cards and fidelity warning (MFX-7.1).

Operation id: `list_public_export_targets_v1_browse_tenants__tenant_slug__projects__project_slug__versions__version_slug__export_targets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list export targets for a published public version (no auth). | `application/json` [`PublicExportTargetsResponse`](#schema-publicexporttargetsresponse) |
| 404 | No published public version matches the slugs (private, draft, and unknown versions are indistinguishable). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded (MFX-7.3). | — |

## `GET /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions/{version_slug}/sdk` {#get-public-sdk-info-v1-browse-tenants-tenant-slug-projects-project-slug-versions-version-slug-sdk-get}

**Describe the public SDK available for a published public version (no auth)**

Return what the browse Get SDK panel needs to render itself.

A 404 is the panel's instruction to render nothing at all — it is what an unpublished, private
or non-opted-in project returns, so the caller needs no second question.

Args:
    tenant_slug: The owning tenant's slug.
    project_slug: The project (artifact) slug within the tenant.
    version_slug: The version label (e.g. ``1.0.0``) of the published revision.

Returns:
    The :class:`PublicSdkInfoResponse`.

Operation id: `get_public_sdk_info_v1_browse_tenants__tenant_slug__projects__project_slug__versions__version_slug__sdk_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for describe the public sdk available for a published public version (no auth). | `application/json` [`PublicSdkInfoResponse`](#schema-publicsdkinforesponse) |
| 404 | No published public version matches the slugs, or the project has not enabled public SDK access. The two are deliberately indistinguishable. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded (MFX-7.3). | — |

## `GET /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions/{version_slug}/sdk/download` {#download-public-sdk-v1-browse-tenants-tenant-slug-projects-project-slug-versions-version-slug-sdk-download-get}

**Download the client kit for a published public version (no auth)**

Serve the ``sdk.client-kit.v1`` archive for one published public version.

The archive is built per request and is byte-deterministic, so its ``ETag`` is a digest of the
bytes themselves and a repeat request with ``If-None-Match`` short-circuits to 304 without the
body being sent.

Args:
    request: The incoming request, for the running API version.
    tenant_slug: The owning tenant's slug.
    project_slug: The project (artifact) slug within the tenant.
    version_slug: The version label (e.g. ``1.0.0``) of the published revision.
    if_none_match: Standard conditional-request header.

Returns:
    The zip archive, or an empty 304.

Raises:
    HTTPException: 404 when no public SDK is available; 413 when the kit exceeds the public
        download cap.

Operation id: `download_public_sdk_v1_browse_tenants__tenant_slug__projects__project_slug__versions__version_slug__sdk_download_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The client kit archive. | `application/zip` any |
| 304 | Not modified (ETag matched If-None-Match). | — |
| 404 | No published public version matches the slugs, or the project has not enabled public SDK access. The two are deliberately indistinguishable. | — |
| 413 | The kit exceeds the public download limit. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded (MFX-7.3). | — |

## `GET /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions/{version_slug}/snippets/{operation_id}` {#get-public-operation-snippet-v1-browse-tenants-tenant-slug-projects-project-slug-versions-version-slug-snippets-operation-id-get}

**Render a usage snippet for one operation of a published public version (no auth)**

Return the install + call snippet for one operation of a published public version.

The anonymous counterpart of the authenticated snippet route, addressed by URL slugs.
Backs the browse operation pages' snippet tabs (SDK-3.3) and the Try It copy-as-code
feature (SIM-3.5) so both consume one source of truth.

Args:
    tenant_slug: The owning tenant's slug.
    project_slug: The project (artifact) slug within the tenant.
    version_slug: The version label (e.g. ``1.0.0``) of the published revision.
    operation_id: operationId, canonical name, or URL-encoded canonical key.
    lang: ``ts`` / ``python`` / ``curl`` (aliases ``fetch`` / ``httpx``).
    if_none_match: Standard conditional-request header.

Returns:
    The :class:`PublicSnippetResponse` JSON, or an empty 304.

Operation id: `get_public_operation_snippet_v1_browse_tenants__tenant_slug__projects__project_slug__versions__version_slug__snippets__operation_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `lang` | query | string | yes | Snippet language: ts \| python \| curl (aliases: fetch → ts, httpx → python). |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for render a usage snippet for one operation of a published public version (no auth). | `application/json` any |
| 304 | Not modified (ETag matched If-None-Match). | — |
| 400 | Unknown lang value. | — |
| 404 | No published public version matches the slugs (private, draft, and unknown versions are indistinguishable), the project has not enabled public SDK access (SDK-3.3), or the operation is unknown. | — |
| 422 | The operation has no HTTP binding (no snippet is defined). | — |
| 429 | Public export rate limit exceeded (MFX-7.3). | — |

## Schemas used {#schemas-used}

### `BrowsePublicProjectsResponse` {#schema-browsepublicprojectsresponse}

Published-public projects for a tenant (anonymous), or full tenant project list for members.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_slug` | string | yes | URL-safe tenant slug used in path parameters. |
| `tenant_name` | string | yes | Tenant Name. |
| `projects` | array of `BrowsePublicProjectRow` | yes | Projects. |
| `filtered_count` | integer | yes | Number of filtered. |
| `facets` | `BrowseFacets` | no | Protocol/format facet counts for this tenant, honouring ``search``/``domain`` (MFI-6.1). |

### `BrowsePublicTenantsResponse` {#schema-browsepublictenantsresponse}

Public tenant directory for CLI and integrations (no authentication).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `directory_stats` | `BrowseDirectoryStats` | yes | Directory Stats. |
| `tenants` | array of `BrowsePublicTenantRow` | yes | Tenants. |
| `filtered_count` | integer | yes | Number of filtered. |
| `facets` | `BrowseFacets` | no | Protocol/format facet counts across the directory, honouring ``search`` (MFI-6.1). |

### `BrowsePublicVersionsResponse` {#schema-browsepublicversionsresponse}

Published versions for browse parity (anonymous public slice or member-authenticated view).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_slug` | string | yes | URL-safe tenant slug used in path parameters. |
| `tenant_name` | string | yes | Tenant Name. |
| `project_slug` | string | yes | Project Slug. |
| `project_name` | string | yes | Project Name. |
| `versions` | array of `BrowsePublicVersionRow` | yes | Versions. |
| `filtered_count` | integer | yes | Number of filtered. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PublicExportDocumentRequest` {#schema-publicexportdocumentrequest}

An emit request for the public path: the chosen target + per-emit options.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target` | string | yes | Target emitter key (``asyncapi``) or format key (``asyncapi-3``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. |

### `PublicExportPreviewRequest` {#schema-publicexportpreviewrequest}

A dry-run fidelity preview request for the public path: just the chosen target.

Unlike the authenticated surface, the source coordinates live in the URL (the slugs), so
the body only selects the target and the advisory threshold.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `min_severity` | `LossinessSeverity` | no | Lowest loss severity that raises the advisory (MFX-2.4); does not affect the report or counts. |

### `PublicExportPreviewResponse` {#schema-publicexportpreviewresponse}

The dry-run fidelity preview for one (published source, target) pair (MFX-7.1).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_slug` | string | yes | The owning tenant's slug, as requested. |
| `project_slug` | string | yes | The project (artifact) slug, as requested. |
| `version_slug` | string | yes | The version label, as requested (e.g. ``1.0.0``). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's source-declared version label. |
| `fidelity` | `ExportFidelity` | yes | The full fidelity envelope (target + tier + report + advisory), no artifact. |

### `PublicExportTargetsResponse` {#schema-publicexporttargetsresponse}

The per-target fidelity list for one published public revision (MFX-7.1).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_slug` | string | yes | The owning tenant's slug, as requested. |
| `project_slug` | string | yes | The project (artifact) slug, as requested. |
| `version_slug` | string | yes | The version label, as requested (e.g. ``1.0.0``). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's source-declared version label. |
| `targets` | array of `ExportTargetFidelity` | no | Every registered target with its per-source fidelity, in registry order. |

### `PublicSdkInfoResponse` {#schema-publicsdkinforesponse}

Everything the browse Get SDK panel needs, in one anonymous call.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenant_slug` | string | yes | The owning tenant's slug, as requested. |
| `project_slug` | string | yes | The project (artifact) slug, as requested. |
| `version_slug` | string | yes | The version label, as requested (e.g. ``1.0.0``). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's source-declared version label. |
| `api_title` | string or null | no | The API's declared title. |
| `languages` | array of `SdkLanguageModel` | no | Languages offered, in documentation order. |
| `packages` | array of `SdkPackageModel` | no | Resolved package names for this project, empty when none are configured. |
| `operation_count` | integer | yes | Operations the kit carries a snippet for (non-HTTP ones are excluded). |
| `total_operation_count` | integer | yes | Operations the API declares in total. |
| `truncated` | boolean | yes | True when the API has more operations than one kit carries. |
| `license_header` | string or null | no | The licence text stamped on every snippet, when configured. |
| `settings_fingerprint` | string or null | no | Fingerprint of the merged SDK settings the kit was branded with (SDK-3.4). |
| `go_client` | `SdkGoClientModel` | yes | The generated Go client the download carries (SDK-2.4). |
| `server_stubs` | `SdkServerStubsModel` | yes | The generated server stubs the download carries (SDK-2.5). |
| `download` | `SdkDownloadModel` | yes | Download. |
