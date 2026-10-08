---
title: "Projects"
description: "REST endpoints tagged projects: 11 operations."
sidebar_position: 49
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `projects` · 11 operations

## `GET /v1/projects/domains` {#list-project-domain-categories-global-v1-projects-domains-get}

**List Project Domain Categories Global**

Allowlist of ``domainCategory`` ids for project metadata.

Public read (CLI prefetch uses no credentials). Register before ``/{tenant_slug}`` so
``/v1/projects/domains`` is not captured as a tenant slug.

Operation id: `list_project_domain_categories_global_v1_projects_domains_get`

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list project domain categories global. | `application/json` map of array of string |

## `GET /v1/projects/{tenant_slug}` {#list-projects-v1-projects-tenant-slug-get}

**List Projects**

List all projects for a tenant.

Supports authentication via:
- JWT token in Authorization header (Bearer token)
- API key in X-API-Key header

Args:
    tenant_slug: The tenant slug
    include_deleted: Include rows with deleted_at set (for trash / restore flows).
    auth_data: Authentication data (injected by dependency)

Returns:
    List of projects for the tenant

Operation id: `list_projects_v1_projects__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `include_deleted` | query | boolean | no | When true, include soft-deleted projects (active projects listed first). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list projects. | `application/json` array of [`ProjectSchema`](#schema-projectschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/projects/{tenant_slug}` {#create-project-v1-projects-tenant-slug-post}

**Create Project**

Create a new project.

Supports authentication via JWT token or API key.
When using JWT, the creator_id field will be set to the authenticated user.

Args:
    tenant_slug: The tenant slug
    request: Project creation data
    auth_data: Authentication data (injected by dependency)

Returns:
    The created project

Operation id: `create_project_v1_projects__tenant_slug__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create project.

- `application/json` — [`ProjectCreateRequest`](#schema-projectcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create project. | `application/json` [`ProjectSchema`](#schema-projectschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/by-slug/{project_slug}` {#get-project-by-slug-v1-projects-tenant-slug-by-slug-project-slug-get}

**Get Project By Slug**

Get a specific project by slug.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    auth_data: Authentication data (injected by dependency)

Returns:
    The project details

Operation id: `get_project_by_slug_v1_projects__tenant_slug__by_slug__project_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get project by slug. | `application/json` [`ProjectSchema`](#schema-projectschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/domains` {#list-project-domain-categories-for-tenant-v1-projects-tenant-slug-domains-get}

**List Project Domain Categories For Tenant**

Same allowlist under the tenant-scoped URL shape expected by the CLI.

Must be registered before ``/{tenant_slug}/{project_id}`` so the final segment
``domains`` is not interpreted as a project UUID.

Operation id: `list_project_domain_categories_for_tenant_v1_projects__tenant_slug__domains_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list project domain categories for tenant. | `application/json` map of array of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_id}` {#get-project-v1-projects-tenant-slug-project-id-get}

**Get Project**

Get a specific project by ID.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    project_id: The project ID
    auth_data: Authentication data (injected by dependency)

Returns:
    The project details

Operation id: `get_project_v1_projects__tenant_slug___project_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get project. | `application/json` [`ProjectSchema`](#schema-projectschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/projects/{tenant_slug}/{project_id}` {#update-project-v1-projects-tenant-slug-project-id-put}

**Update Project**

Update an existing project.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    project_id: The project ID
    request: Project update data
    auth_data: Authentication data (injected by dependency)

Returns:
    The updated project

Operation id: `update_project_v1_projects__tenant_slug___project_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update project.

- `application/json` — [`ProjectUpdateRequest`](#schema-projectupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update project. | `application/json` [`ProjectSchema`](#schema-projectschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/projects/{tenant_slug}/{project_id}` {#delete-project-v1-projects-tenant-slug-project-id-delete}

**Delete Project**

Delete a project (soft delete).

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    project_id: The project ID
    auth_data: Authentication data (injected by dependency)

Returns:
    Success message

Operation id: `delete_project_v1_projects__tenant_slug___project_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete project. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_id}/conversions` {#get-project-conversion-history-v1-projects-tenant-slug-project-id-conversions-get}

**List the conversions that produced a Project**

Return the conversion-provenance rows that produced this Project, newest first (CPDO-3.3).

The converted-project side of the conversion history: each entry links a target revision of this
Project back to the catalog item + source revision it was converted from, with the fidelity
outcome, the content-addressed evidence snapshot id, and whether that snapshot is replayable.
Empty for projects that were never a conversion target. Requires authentication + tenant
scoping only, like every other project read.

Args:
    tenant_slug: The tenant slug.
    project_id: The (target) project ID.
    auth_data: Authentication data (injected by dependency).

Returns:
    The :class:`~app.models.ProjectConversionHistoryResponse`, newest first.

Operation id: `get_project_conversion_history_v1_projects__tenant_slug___project_id__conversions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the conversions that produced a project. | `application/json` [`ProjectConversionHistoryResponse`](#schema-projectconversionhistoryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_id}/conversions/{provenance_id}/evidence` {#get-project-conversion-evidence-v1-projects-tenant-slug-project-id-conversions-provenance-id-evidence-get}

**Page through the stored evidence snapshot of one conversion of this Project**

Return one page of the exact evidence graph a conversion of this Project was approved with.

The project-side twin of the catalog evidence read, and deliberately reachable even when the
source catalog item has been deleted (``source_project_id`` is ``SET NULL`` on the ledger): the
converted artifact must keep its approved evidence readable regardless of what happened to the
source. Served from the content-addressed snapshot store (CPDO-3.3, V215), never rebuilt; an
unservable snapshot degrades to an explicit HTTP 200 state, never an error.

Carries source-native coordinates, so it is gated on the same ``imports:view`` permission as the
catalog-side reads, checked **after** the project lookup so a cross-tenant id 404s rather than
confirming its existence with a 403. A provenance row that did not target this Project 404s.

Args:
    tenant_slug: The tenant slug.
    project_id: The (target) project ID.
    provenance_id: The ``conversion_provenance`` row whose snapshot to page.
    scope: Restrict the page to one edge scope; omit to page every scope.
    cursor: Opaque page cursor.
    limit: Maximum edges per page.
    auth_data: Authentication data (injected by dependency).

Returns:
    The :class:`~app.models.ConversionEvidenceResponse` — snapshot state, summary, and one page.

Raises:
    HTTPException: 400 for an unknown scope, 404 for an unknown project/provenance row, 422 for
        a malformed cursor.

Operation id: `get_project_conversion_evidence_v1_projects__tenant_slug___project_id__conversions__provenance_id__evidence_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `provenance_id` | path | string | yes | Path parameter identifying the provenance id segment. |
| `scope` | query | string or null | no | Restrict the page to one edge scope: checklist / construct / loss / analysis. |
| `cursor` | query | string or null | no | Opaque cursor from a previous page; omit to start at the beginning. |
| `limit` | query | integer | no | Maximum edges per page; clamped server-side. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for page through the stored evidence snapshot of one conversion of this project. | `application/json` [`ConversionEvidenceResponse`](#schema-conversionevidenceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/projects/{tenant_slug}/{project_id}/restore` {#restore-project-v1-projects-tenant-slug-project-id-restore-post}

**Restore Project**

Restore a soft-deleted project (clears deleted_at, sets enabled).

Operation id: `restore_project_v1_projects__tenant_slug___project_id__restore_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for restore project. | `application/json` [`ProjectSchema`](#schema-projectschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ConversionEvidenceResponse` {#schema-conversionevidenceresponse}

One page of a historical conversion's stored evidence graph (CPDO-3.3).

Serves the exact approved manifest from the content-addressed snapshot store — never a rebuild —
so the evidence shown is the evidence the conversion was committed with, regardless of how the
source or the converter changed since. ``summary``/``page`` are ``null`` exactly when
``snapshot.status`` is ``unavailable``; degrade is HTTP 200, never a 5xx.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provenanceId` | string | yes | The conversion_provenance row served. |
| `itemId` | string or null | no | Catalog item id, on the catalog surface. |
| `projectId` | string or null | no | Target Project id, on the project surface. |
| `manifestHash` | string or null | no | Content-addressed snapshot id, or null. |
| `sourceHash` | string or null | no | Digest of the source text converted, or null. |
| `snapshot` | `ConversionSnapshotState` | yes | Snapshot availability + degrade reason. |
| `summary` | object or null | no | The bounded manifest summary of the stored snapshot; null when unavailable. |
| `page` | object or null | no | One page of the stored graph's edges + nodes; null when unavailable. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ProjectConversionHistoryResponse` {#schema-projectconversionhistoryresponse}

``GET /v1/projects/{tenant_slug}/{project_id}/conversions`` — the conversions that produced a
Project, newest first (CPDO-3.3). Empty for projects that were never a conversion target.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | The target Project id. |
| `conversions` | array of `ConversionProvenanceEntry` | no | Provenance rows targeting this Project, newest first. |

### `ProjectCreateRequest` {#schema-projectcreaterequest}

Request model for creating a project.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `slug` | string | yes | URL-safe identifier. |
| `metadata` | object or null | no | Additional JSON metadata bag. |

### `ProjectSchema` {#schema-projectschema}

ProjectSchema schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `creator_id` | string or null | no | Creator ID. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `slug` | string | yes | URL-safe identifier. |
| `enabled` | boolean | no | Whether the resource is active. |
| `deleted_at` | string (date-time) or string or null | no | Deleted At timestamp (ISO 8601). |
| `metadata` | object or null | no | Additional JSON metadata bag. |
| `changeReportTemplateVersionId` | string or null | no | Change Report Template Version ID. |
| `qualityScore` | integer or null | no | Quality Score. |
| `qualityGrade` | string or null | no | Quality Grade. |
| `versionsCount` | integer | no | Number of versions. |
| `publishable` | boolean | no | Publishable. |
| `identityGroupId` | string or null | no | Identity Group ID. |
| `relatedArtifacts` | array of `RelatedArtifactRef` | no | Related Artifacts. |
| `creator_name` | string or null | no | Creator Name. |
| `creator_email` | string or null | no | Creator Email. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `ProjectUpdateRequest` {#schema-projectupdaterequest}

Request model for updating a project.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `slug` | string or null | no | URL-safe identifier. |
| `enabled` | boolean or null | no | Whether the resource is active. |
| `metadata` | object or null | no | Additional JSON metadata bag. |
| `changeReportTemplateVersionId` | string or null | no | Change Report Template Version ID. |
