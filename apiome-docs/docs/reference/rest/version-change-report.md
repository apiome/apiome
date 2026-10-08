---
title: "Version change report"
description: "REST endpoints tagged version-change-report: 4 operations."
sidebar_position: 76
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `version-change-report` · 4 operations

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/change-report` {#get-version-change-report-v1-versions-tenant-slug-project-id-version-record-id-change-report-get}

**Get Version Change Report**

Return the persisted change report for a **published** revision, if present.

Authentication: JWT or API key (tenant-scoped). Read access follows the same tenant/project
scoping as other version APIs.

Operation id: `get_version_change_report_v1_versions__tenant_slug___project_id___version_record_id__change_report_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get version change report. | `application/json` [`VersionChangeReportOut`](#schema-versionchangereportout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/change-report` {#patch-version-change-report-v1-versions-tenant-slug-project-id-version-record-id-change-report-patch}

**Patch Version Change Report**

Save **user edit** snapshots (full replacement per field sent).

**Authorization:** JWT required. Only the revision **creator** or a **tenant administrator**
may edit. API-key-only authentication cannot PATCH.

**Semantics:** Each optional field is a full snapshot of that slice (not a diff). Sending
``null`` for a field clears that user override. ``clearEdits: true`` removes all overrides.

Operation id: `patch_version_change_report_v1_versions__tenant_slug___project_id___version_record_id__change_report_patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for patch version change report.

- `application/json` — [`VersionChangeReportPatch`](#schema-versionchangereportpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for patch version change report. | `application/json` [`VersionChangeReportOut`](#schema-versionchangereportout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/change-report/publish-preview` {#preview-change-report-for-publish-v1-versions-tenant-slug-project-id-version-record-id-change-report-publish-preview-post}

**Preview Change Report For Publish**

Preview the publication change report that would be generated after publish, without persisting.

Same baseline options as ``POST …/publish`` (``changeReportBaselineMode`` / ``changeReportBaselineRevisionId``).
Requires JWT; same authorization as publishing (revision creator or tenant admin).

Operation id: `preview_change_report_for_publish_v1_versions__tenant_slug___project_id___version_record_id__change_report_publish_preview_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for preview change report for publish.

- `application/json` — [`VersionPublishChangeReportPreviewRequest`](#schema-versionpublishchangereportpreviewrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview change report for publish. | `application/json` [`VersionPublishChangeReportPreviewOut`](#schema-versionpublishchangereportpreviewout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/change-report/regenerate` {#regenerate-version-change-report-v1-versions-tenant-slug-project-id-version-record-id-change-report-regenerate-post}

**Regenerate Version Change Report**

Re-run rendering from stored ``changeModelJson`` using the Mustache template pipeline (CR-03).

Resolution order: optional ``templateVersionId`` in the body, then project default, tenant
default, then the system template (**1.0.0**).

**Authorization:** Same as PATCH (creator or tenant admin, JWT required).

Operation id: `regenerate_version_change_report_v1_versions__tenant_slug___project_id___version_record_id__change_report_regenerate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for regenerate version change report.

- `application/json` — [`VersionChangeReportRegenerateRequest`](#schema-versionchangereportregeneraterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for regenerate version change report. | `application/json` [`VersionChangeReportOut`](#schema-versionchangereportout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `VersionChangeReportOut` {#schema-versionchangereportout}

Stored change report row plus effective (edited-over-rendered) snapshots.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenantId` | string | yes | Tenant ID. |
| `projectId` | string | yes | Project ID. |
| `publishedRevisionId` | string | yes | Published Revision ID. |
| `baselineRevisionId` | string or null | no | Baseline Revision ID. |
| `changeModelJson` | object | yes | Change Model JSON. |
| `renderedBody` | string or null | no | Rendered Body. |
| `headerSnapshot` | string or null | no | Header Snapshot. |
| `footnoteSnapshot` | string or null | no | Footnote Snapshot. |
| `editedRenderedBody` | string or null | no | Edited Rendered Body. |
| `editedHeaderSnapshot` | string or null | no | Edited Header Snapshot. |
| `editedFootnoteSnapshot` | string or null | no | Edited Footnote Snapshot. |
| `effectiveRenderedBody` | string or null | no | Effective Rendered Body. |
| `effectiveHeaderSnapshot` | string or null | no | Effective Header Snapshot. |
| `effectiveFootnoteSnapshot` | string or null | no | Effective Footnote Snapshot. |
| `editedAt` | string or null | no | Edited At. |
| `editedBy` | string or null | no | Edited By. |
| `templateVersionId` | string or null | no | Template Version ID. |
| `renderedAt` | string or null | no | Rendered At. |
| `regeneratedAt` | string or null | no | Regenerated At. |
| `createdAt` | string or null | no | Created At. |
| `updatedAt` | string or null | no | Updated At. |

### `VersionChangeReportPatch` {#schema-versionchangereportpatch}

PATCH user edits as full snapshots per field (null in JSON clears that override).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `editedRenderedBody` | string or null | no | Edited Rendered Body. |
| `editedHeaderSnapshot` | string or null | no | Edited Header Snapshot. |
| `editedFootnoteSnapshot` | string or null | no | Edited Footnote Snapshot. |
| `clearEdits` | boolean or null | no | When true, remove all user edit snapshots and clear editedAt/editedBy. |

### `VersionChangeReportRegenerateRequest` {#schema-versionchangereportregeneraterequest}

Optional template version id; effective template resolved per CR-03.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `templateVersionId` | string or null | no | Template Version ID. |
| `discardUserEdits` | boolean | no | Discard User Edits. |

### `VersionPublishChangeReportPreviewOut` {#schema-versionpublishchangereportpreviewout}

Draft change report Mustache output for pre-publish preview.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `headerSnapshot` | string | yes | Header Snapshot. |
| `renderedBody` | string | yes | Rendered Body. |
| `footnoteSnapshot` | string | yes | Footnote Snapshot. |
| `changeModelJson` | object | yes | Change Model JSON. |
| `baselineRevisionId` | string or null | no | Baseline Revision ID. |
| `templateVersionId` | string or null | no | Template Version ID. |
| `fromVersionLabel` | string | yes | From Version Label. |
| `toVersionLabel` | string | yes | To Version Label. |
| `initialPublication` | boolean | no | Initial Publication. |

### `VersionPublishChangeReportPreviewRequest` {#schema-versionpublishchangereportpreviewrequest}

Preview publication change report before publishing (same baseline fields as publish).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `changeReportBaselineMode` | enum `"auto"`, `"initial"`, `"manual"` | no | Change Report Baseline Mode. |
| `changeReportBaselineRevisionId` | string or null | no | Change Report Baseline Revision ID. |
