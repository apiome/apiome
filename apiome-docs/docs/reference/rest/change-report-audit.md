---
title: "Change report audit"
description: "REST endpoints tagged change-report-audit: 1 operation."
sidebar_position: 18
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.557.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `change-report-audit` · 1 operation

## `GET /v1/tenants/{tenant_slug}/change-report-audit` {#list-change-report-audit-v1-tenants-tenant-slug-change-report-audit-get}

**List Change Report Audit**

List the tenant's change-report audit trail, newest first.

One entry per report edit, regeneration, submission, approval, rejection and PDF export,
and per template creation or default change.

**Authorization:** JWT required; **tenant administrators only**.

Operation id: `list_change_report_audit_v1_tenants__tenant_slug__change_report_audit_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `action` | query | array of string or null | no | Only these audit verbs (repeat for several, e.g. report.approve). |
| `actorId` | query | string or null | no | Only events by this user (UUID). |
| `projectId` | query | string or null | no | Only events of this project (UUID). |
| `versionId` | query | string or null | no | Only events of this published version's report (UUID). |
| `since` | query | string or null | no | Inclusive lower bound on createdAt (ISO 8601). |
| `until` | query | string or null | no | Inclusive upper bound on createdAt (ISO 8601). |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `cursor` | query | string or null | no | The `nextCursor` of the previous page, for the next (older) one. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list change report audit. | `application/json` [`ChangeReportAuditPageOut`](#schema-changereportauditpageout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ChangeReportAuditPageOut` {#schema-changereportauditpageout}

One page of the change-report audit trail, newest first (#2705).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `ChangeReportAuditEntryOut` | no | Items. |
| `limit` | integer | yes | The page size that was applied. |
| `nextCursor` | string or null | no | Pass as `cursor` for the next (older) page; null on the last page. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
