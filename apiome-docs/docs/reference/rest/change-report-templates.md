---
title: "Change report templates"
description: "REST endpoints tagged change-report-templates: 4 operations."
sidebar_position: 10
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `change-report-templates` · 4 operations

## `PUT /v1/tenants/{tenant_slug}/change-report-template-default` {#put-tenant-change-report-template-default-v1-tenants-tenant-slug-change-report-template-default-put}

**Put Tenant Change Report Template Default**

Set the tenant default template pointer. **Tenant administrators only** (JWT).
``templateVersionId: null`` clears the tenant default (fall back to system default).

Operation id: `put_tenant_change_report_template_default_v1_tenants__tenant_slug__change_report_template_default_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put tenant change report template default.

- `application/json` — [`ChangeReportTemplateDefaultPut`](#schema-changereporttemplatedefaultput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put tenant change report template default. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/change-report-template-versions` {#list-change-report-template-versions-v1-tenants-tenant-slug-change-report-template-versions-get}

**List Change Report Template Versions**

List system templates and templates owned by this tenant (ids + semver; not full bodies).

Operation id: `list_change_report_template_versions_v1_tenants__tenant_slug__change_report_template_versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list change report template versions. | `application/json` array of [`ChangeReportTemplateVersionSummary`](#schema-changereporttemplateversionsummary) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/change-report-template-versions` {#create-change-report-template-version-v1-tenants-tenant-slug-change-report-template-versions-post}

**Create Change Report Template Version**

Create a tenant-scoped template triple (Mustache). **Tenant administrators only** (JWT).

Invalid templates return **400** with a short validation message.

Operation id: `create_change_report_template_version_v1_tenants__tenant_slug__change_report_template_versions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create change report template version.

- `application/json` — [`ChangeReportTemplateVersionCreate`](#schema-changereporttemplateversioncreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create change report template version. | `application/json` [`ChangeReportTemplateVersionOut`](#schema-changereporttemplateversionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/projects/{project_id}/change-report-template-default` {#put-project-change-report-template-default-v1-tenants-tenant-slug-projects-project-id-change-report-template-default-put}

**Put Project Change Report Template Default**

Set project-level template override. **JWT** — **project creator** or **tenant administrator**.

``templateVersionId: null`` clears the project override.

Operation id: `put_project_change_report_template_default_v1_tenants__tenant_slug__projects__project_id__change_report_template_default_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put project change report template default.

- `application/json` — [`ChangeReportTemplateDefaultPut`](#schema-changereporttemplatedefaultput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put project change report template default. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ChangeReportTemplateDefaultPut` {#schema-changereporttemplatedefaultput}

Set tenant or project default template pointer; null clears override.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `templateVersionId` | string or null | no | Template Version ID. |

### `ChangeReportTemplateVersionCreate` {#schema-changereporttemplateversioncreate}

ChangeReportTemplateVersionCreate schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `semver` | string | yes | Semver. |
| `headerTemplate` | string | yes | Header Template. |
| `bodyTemplate` | string | yes | Body Template. |
| `footnoteTemplate` | string | yes | Footnote Template. |

### `ChangeReportTemplateVersionOut` {#schema-changereporttemplateversionout}

ChangeReportTemplateVersionOut schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `semver` | string | yes | Semver. |
| `ownerTenantId` | string or null | no | Owner Tenant ID. |
| `headerTemplate` | string | yes | Header Template. |
| `bodyTemplate` | string | yes | Body Template. |
| `footnoteTemplate` | string | yes | Footnote Template. |
| `createdAt` | string or null | no | Created At. |
| `createdBy` | string or null | no | Created By. |

### `ChangeReportTemplateVersionSummary` {#schema-changereporttemplateversionsummary}

ChangeReportTemplateVersionSummary schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `semver` | string | yes | Semver. |
| `ownerTenantId` | string or null | no | Owner Tenant ID. |
| `createdAt` | string or null | no | Created At. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
