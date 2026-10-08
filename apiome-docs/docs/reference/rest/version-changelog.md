---
title: "Version changelog"
description: "REST endpoints tagged version-changelog: 2 operations."
sidebar_position: 77
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `version-changelog` · 2 operations

## `GET /v1/versions/{tenant_slug}/{project_id}/changelogs` {#list-project-version-changelogs-v1-versions-tenant-slug-project-id-changelogs-get}

**List Project Version Changelogs**

List changelog summaries for every published revision of a project.

Revisions without a stored classification row (pending or pre-backfill) are
included with ``status: null`` so callers can render a pending state.

Operation id: `list_project_version_changelogs_v1_versions__tenant_slug___project_id__changelogs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `limit` | query | integer or null | no | Optional max rows, newest publish first. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list project version changelogs. | `application/json` [`ProjectVersionChangelogsResponse`](#schema-projectversionchangelogsresponse) |
| 400 | Malformed project id. | — |
| 404 | Project not found in tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/changelog` {#get-version-changelog-v1-versions-tenant-slug-project-id-version-record-id-changelog-get}

**Get Version Changelog**

Return the stored classified changelog for one **published** revision.

The ``changelog`` field is the raw ``ctg.changelog.v1`` payload (entries in
breaking → non-breaking → docs-only order, grouped by path), or the
initial-publication marker when the revision had no published baseline.

Operation id: `get_version_changelog_v1_versions__tenant_slug___project_id___version_record_id__changelog_get`

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
| 200 | Successful response for get version changelog. | `application/json` [`VersionChangelogOut`](#schema-versionchangelogout) |
| 400 | Revision is not published. | — |
| 404 | Version not found, or no changelog stored for this revision. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ProjectVersionChangelogsResponse` {#schema-projectversionchangelogsresponse}

All published-revision changelog summaries for a project, newest publish first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `changelogs` | array of `VersionChangelogSummaryRow` | yes | Changelogs. |
| `filteredCount` | integer | yes | Number of filtered. |

### `VersionChangelogOut` {#schema-versionchangelogout}

Stored publish-time classified changelog for one published revision (CTG-3.1 row).

``changelog`` carries the raw ``ctg.changelog.v1`` payload (or the
initial-publication marker); it is ``None`` when classification failed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `publishedRevisionId` | string | yes | Published Revision ID. |
| `baselineRevisionId` | string or null | no | Baseline Revision ID. |
| `versionLabel` | string or null | no | Version Label. |
| `baselineVersionLabel` | string or null | no | Baseline Version Label. |
| `publishedAt` | string (date-time) or null | no | Published At. |
| `status` | string | yes | Status. |
| `maxSeverity` | string or null | no | Max Severity. |
| `error` | string or null | no | Error. |
| `changelog` | object or null | no | Changelog. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
