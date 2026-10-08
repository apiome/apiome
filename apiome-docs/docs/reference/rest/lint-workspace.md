---
title: "Lint workspace"
description: "REST endpoints tagged lint-workspace: 9 operations."
sidebar_position: 32
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `lint-workspace` · 9 operations

## `POST /v1/lint/workspace/decisions/bulk` {#bulk-decision-action-v1-lint-workspace-decisions-bulk-post}

**Bulk Decision Action**

Apply one decision change to up to :data:`BULK_ITEM_CAP` findings (CLX-4.1, #4859).

**Authorized**: requires ``lint_findings:edit``; items whose transition is approval-tier
(entering/leaving ``waived``, resolving a ``waiver_requested`` row) additionally require
``lint_findings:publish`` and fail per-item without it.
**Audited**: every applied item appends an immutable ``lint_finding_decision_events`` row
(plus the standard denial audit on 403).
**Reversible**: each result carries ``beforeState`` so the client can issue the exact
inverse request; approval-tier inversions require the same publish permission.

Operation id: `bulk_decision_action_v1_lint_workspace_decisions_bulk_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for bulk decision action.

- `application/json` — [`LintWorkspaceBulkDecisionRequest`](#schema-lintworkspacebulkdecisionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for bulk decision action. | `application/json` [`LintWorkspaceBulkDecisionResponse`](#schema-lintworkspacebulkdecisionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/workspace/findings` {#list-workspace-findings-v1-lint-workspace-findings-get}

**List Workspace Findings**

Cross-catalog findings queue over the latest evidence per subject (CLX-4.1, #4859).

"All new unwaived security errors" (acceptance criterion 1) is
``?new=true&severity=error&axis=security&state=open``; missing required coverage lives in
``GET /summary``'s coverage block. Facets are computed over the filtered, pre-pagination
set so the toolbar can show counts for the current queue.

Operation id: `list_workspace_findings_v1_lint_workspace_findings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `severity` | query | string or null | no | CSV of error,warning,info |
| `state` | query | string or null | no | CSV of effective decision states |
| `axis` | query | string or null | no | CSV of scoring axis keys |
| `grade` | query | string or null | no | CSV of composite grades A–F |
| `coverage` | query | string or null | no | missing \| met |
| `profile` | query | string or null | no | CSV of execution profiles |
| `scanner` | query | string or null | no | CSV of scanner ids (source) |
| `subjectType` | query | string or null | no | catalog_revision \| mcp_endpoint_version |
| `projectId` | query | string or null | no | Query parameter: project id. |
| `ownerUserId` | query | string or null | no | Query parameter: owner user id. |
| `ruleId` | query | string or null | no | Query parameter: rule id. |
| `category` | query | string or null | no | Query parameter: category. |
| `new` | query | boolean or null | no | True restricts to regressions (new since previous run) |
| `q` | query | string or null | no | Free-text search |
| `sort` | query | string or null | no | severity \| newest \| rule \| subject |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list workspace findings. | `application/json` [`LintWorkspaceFindingsResponse`](#schema-lintworkspacefindingsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/workspace/quality-ranks` {#workspace-quality-ranks-v1-lint-workspace-quality-ranks-get}

**Workspace Quality Ranks**

Per-format import/export grade distribution and drift over a window (IXH-2.7, #5102).

Scores are captured per revision, but a single revision's grade cannot show that a team's
imports are trending downward or that one format grades low because its *adapter* is
incomplete. This series answers both: grades are grouped by ``(scope, format)`` and each
group reports its distribution, its drift (``scoreDelta`` — newest scored observation minus
the oldest in the window), the style-guide versions that produced those grades, and the
**attribution split** that separates adapter-attributable findings from spec-attributable
ones. Export readiness ranks ride the same series, so a target whose readiness is sliding
shows up beside the specs feeding it.

The window is bounded (``days`` ≤ 180, matching the retention default) and the response
describes at most 24 format groups, stating ``truncated`` when it dropped any.

Operation id: `workspace_quality_ranks_v1_lint_workspace_quality_ranks_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `days` | query | integer | no | Query parameter: days. |
| `scope` | query | string or null | no | import \| export (both when omitted) |
| `stage` | query | string or null | no | preflight \| committed (both when omitted) |
| `projectId` | query | string or null | no | Query parameter: project id. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for workspace quality ranks. | `application/json` [`QualityRankSeriesResponse`](#schema-qualityrankseriesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/workspace/summary` {#workspace-summary-v1-lint-workspace-summary-get}

**Workspace Summary**

Tenant-wide posture rollup: grades, axes, coverage gaps, finding/waiver counts.

Operation id: `workspace_summary_v1_lint_workspace_summary_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `projectId` | query | string or null | no | Query parameter: project id. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for workspace summary. | `application/json` [`LintWorkspaceSummaryResponse`](#schema-lintworkspacesummaryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/workspace/trends` {#workspace-trends-v1-lint-workspace-trends-get}

**Workspace Trends**

Daily series separating genuine remediation from policy / waiver / coverage change.

``remediatedFindings`` counts only fingerprints that disappeared from evidence and were
NOT waived or false-positived; waiver grants, expiries, false-positive marks, and policy
pack publications are their own series (acceptance criterion 4).

Operation id: `workspace_trends_v1_lint_workspace_trends_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `days` | query | integer | no | Query parameter: days. |
| `projectId` | query | string or null | no | Query parameter: project id. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for workspace trends. | `application/json` [`LintWorkspaceTrendsResponse`](#schema-lintworkspacetrendsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/workspace/views` {#list-workspace-saved-views-v1-lint-workspace-views-get}

**List Workspace Saved Views**

List the caller's saved workspace views (pinned first, then newest).

Operation id: `list_workspace_saved_views_v1_lint_workspace_views_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list workspace saved views. | `application/json` [`LintWorkspaceSavedViewListResponse`](#schema-lintworkspacesavedviewlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/lint/workspace/views` {#create-workspace-saved-view-v1-lint-workspace-views-post}

**Create Workspace Saved View**

Save the current workspace filter bundle under a name.

Operation id: `create_workspace_saved_view_v1_lint_workspace_views_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create workspace saved view.

- `application/json` — [`LintWorkspaceSavedViewCreate`](#schema-lintworkspacesavedviewcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create workspace saved view. | `application/json` [`LintWorkspaceSavedViewOut`](#schema-lintworkspacesavedviewout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/lint/workspace/views/{view_id}` {#update-workspace-saved-view-v1-lint-workspace-views-view-id-patch}

**Update Workspace Saved View**

Update a saved workspace view owned by the caller.

Operation id: `update_workspace_saved_view_v1_lint_workspace_views__view_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `view_id` | path | string (uuid) | yes | Path parameter identifying the view id segment. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update workspace saved view.

- `application/json` — [`LintWorkspaceSavedViewUpdate`](#schema-lintworkspacesavedviewupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update workspace saved view. | `application/json` [`LintWorkspaceSavedViewOut`](#schema-lintworkspacesavedviewout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/lint/workspace/views/{view_id}` {#delete-workspace-saved-view-v1-lint-workspace-views-view-id-delete}

**Delete Workspace Saved View**

Delete a saved workspace view owned by the caller.

Operation id: `delete_workspace_saved_view_v1_lint_workspace_views__view_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `view_id` | path | string (uuid) | yes | Path parameter identifying the view id segment. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete workspace saved view. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `LintWorkspaceBulkDecisionRequest` {#schema-lintworkspacebulkdecisionrequest}

Bulk assign / state-change request over workspace findings (CLX-4.1, #4859).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `LintWorkspaceBulkItem` | yes | Items. |
| `set` | `LintWorkspaceBulkSet` | yes | Set. |

### `LintWorkspaceBulkDecisionResponse` {#schema-lintworkspacebulkdecisionresponse}

Bulk decision outcome: per-item results plus applied/failed tallies (CLX-4.1).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `results` | array of `LintWorkspaceBulkItemResultOut` | no | Results. |
| `appliedCount` | integer | no | Number of applied. |
| `failedCount` | integer | no | Number of failed. |

### `LintWorkspaceFindingsResponse` {#schema-lintworkspacefindingsresponse}

Paged workspace findings queue with pre-pagination facet counts (CLX-4.1).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `findings` | array of `LintWorkspaceFindingOut` | no | Findings. |
| `count` | integer | no | Number of count. |
| `total` | integer | no | Total. |
| `limit` | integer | no | Limit. |
| `offset` | integer | no | Offset. |
| `facets` | map of map of integer | no | Facets. |

### `LintWorkspaceSavedViewCreate` {#schema-lintworkspacesavedviewcreate}

Request body for creating a saved workspace view (CLX-4.1, #4859).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `filters` | object | no | Filters. |
| `query` | string | no | Query. |
| `sort` | string | no | Sort. |
| `isPinned` | boolean | no | Is Pinned. |

### `LintWorkspaceSavedViewListResponse` {#schema-lintworkspacesavedviewlistresponse}

Envelope for listing saved workspace views (CLX-4.1, #4859).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `views` | array of [`LintWorkspaceSavedViewOut`](#schema-lintworkspacesavedviewout) | no | Views. |
| `count` | integer | no | Number of count. |

### `LintWorkspaceSavedViewOut` {#schema-lintworkspacesavedviewout}

One saved workspace view owned by the caller (CLX-4.1, #4859).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `filters` | object | no | Filters. |
| `query` | string | no | Query. |
| `sort` | string | no | Sort. |
| `isPinned` | boolean | no | Is Pinned. |
| `createdAt` | string or null | no | Created At. |
| `updatedAt` | string or null | no | Updated At. |

### `LintWorkspaceSavedViewUpdate` {#schema-lintworkspacesavedviewupdate}

Request body for patching a saved workspace view (all fields optional).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `filters` | object or null | no | Filters. |
| `query` | string or null | no | Query. |
| `sort` | string or null | no | Sort. |
| `isPinned` | boolean or null | no | Is Pinned. |

### `LintWorkspaceSummaryResponse` {#schema-lintworkspacesummaryresponse}

Tenant-wide lint posture rollup for the workspace header (CLX-4.1, #4859).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subjects` | map of integer | no | Subjects. |
| `gradeDistribution` | map of integer | no | Grade Distribution. |
| `axes` | array of `LintWorkspaceAxisSummaryOut` | no | Axes. |
| `coverage` | object | no | Coverage. |
| `findings` | map of integer | no | Findings. |
| `waivers` | map of integer | no | Waivers. |

### `LintWorkspaceTrendsResponse` {#schema-lintworkspacetrendsresponse}

Daily trend series separating genuine remediation from policy change (CLX-4.1).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `days` | integer | yes | Days. |
| `series` | array of `LintWorkspaceTrendPointOut` | no | Series. |

### `QualityRankSeriesResponse` {#schema-qualityrankseriesresponse}

Per-format quality-grade distribution and drift over a window (IXH-2.7, #5102).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `days` | integer | yes | Window size actually aggregated, in days. |
| `windowStart` | string | yes | Window Start. |
| `windowEnd` | string | yes | Window End. |
| `observationCount` | integer | no | Observations folded into this response. |
| `truncated` | boolean | no | True when more formats were observed than the response describes. |
| `formatLimit` | integer | no | Most format groups this response will describe. |
| `stages` | map of integer | no | Observation tally by stage: preflight / committed. |
| `outcomes` | map of integer | no | Observation tally by gate outcome: pass / warn / block / error. |
| `formats` | array of `QualityRankFormatOut` | no | Format groups, busiest first. |
