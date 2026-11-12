---
title: "Export auto"
description: "REST endpoints tagged export-auto: 6 operations."
sidebar_position: 33
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.546.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `export-auto` · 6 operations

## `GET /v1/export/{tenant_slug}/auto-export-runs` {#list-auto-export-runs-v1-export-tenant-slug-auto-export-runs-get}

**List auto-export runs**

What each publish's auto-exports did, newest first: the export job, the loss it measured, whether delivery was halted, and every delivery's outcome. `projectId` or `subscriptionId` narrow. Requires `projects:view`.

Operation id: `list_auto_export_runs_v1_export__tenant_slug__auto_export_runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `projectId` | query | string or null | no | Query parameter: project id. |
| `subscriptionId` | query | string or null | no | Query parameter: subscription id. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list auto-export runs. | `application/json` [`AutoExportRunListResponse`](#schema-autoexportrunlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/auto-export-runs/{run_id}/release` {#release-auto-export-run-v1-export-tenant-slug-auto-export-runs-run-id-release-post}

**Deliver a halted auto-export anyway**

Delivers a **halted** auto-export through its preset's delivery profile, as the caller, while the export's artifact is retained. Requires `versions:publish`; audited as `export.auto_export.released`. `409` when the run is not halted or the preset names no delivery profile; `410` when the artifact has expired.

Operation id: `release_auto_export_run_v1_export__tenant_slug__auto_export_runs__run_id__release_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for deliver a halted auto-export anyway. | `application/json` [`AutoExportRunModel`](#schema-autoexportrunmodel) |
| 404 | Unknown run for this tenant. | — |
| 409 | Not halted, or nothing to deliver with. | — |
| 410 | The export's artifact has expired. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/auto-exports` {#list-auto-exports-v1-export-tenant-slug-auto-exports-get}

**List auto-export subscriptions**

Every export preset run on publish, by project. `projectId` or `preset` (id or name) narrow. Requires `projects:view`.

Operation id: `list_auto_exports_v1_export__tenant_slug__auto_exports_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `projectId` | query | string or null | no | Query parameter: project id. |
| `preset` | query | string or null | no | Query parameter: preset. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list auto-export subscriptions. | `application/json` [`AutoExportSubscriptionListResponse`](#schema-autoexportsubscriptionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/auto-exports` {#create-auto-export-v1-export-tenant-slug-auto-exports-post}

**Run an export preset on every publish of a project**

Subscribes an export preset (by id or name) to a project: every later publish runs the preset's export on the published version and delivers it through the preset's delivery profile — unless the export's loss reaches `haltAt` (`critical`, the default: a severe or near-empty conversion, a types-only result or any critical construct; `warn`: any loss). A halted export is not delivered; the publisher and the subscriber are notified, and a person can release it. `approveLoss` pre-approves the loss: the export is delivered anyway. Requires `projects:edit` and `versions:publish`; audited as `export.auto_export.subscription.created`. `400` for an unknown project or preset; `409` when the project already runs that preset.

Operation id: `create_auto_export_v1_export__tenant_slug__auto_exports_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for run an export preset on every publish of a project.

- `application/json` — [`AutoExportSubscriptionCreate`](#schema-autoexportsubscriptioncreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for run an export preset on every publish of a project. | `application/json` [`AutoExportSubscriptionModel`](#schema-autoexportsubscriptionmodel) |
| 400 | Unknown project or preset. | — |
| 409 | The project already runs that preset on publish. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/export/{tenant_slug}/auto-exports/{subscription_id}` {#update-auto-export-v1-export-tenant-slug-auto-exports-subscription-id-patch}

**Change an auto-export subscription**

Changes `haltAt`, `approveLoss` or `active`. Turning a subscription on or pre-approving loss requires `versions:publish` as well as `projects:edit`. Audited as `export.auto_export.subscription.updated`.

Operation id: `update_auto_export_v1_export__tenant_slug__auto_exports__subscription_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subscription_id` | path | string | yes | Path parameter identifying the subscription id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change an auto-export subscription.

- `application/json` — [`AutoExportSubscriptionUpdate`](#schema-autoexportsubscriptionupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change an auto-export subscription. | `application/json` [`AutoExportSubscriptionModel`](#schema-autoexportsubscriptionmodel) |
| 404 | Unknown subscription for this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/export/{tenant_slug}/auto-exports/{subscription_id}` {#delete-auto-export-v1-export-tenant-slug-auto-exports-subscription-id-delete}

**Remove an auto-export subscription**

Stops running the preset on publish. Its past runs keep their record. Requires `projects:edit`; audited as `export.auto_export.subscription.deleted`.

Operation id: `delete_auto_export_v1_export__tenant_slug__auto_exports__subscription_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subscription_id` | path | string | yes | Path parameter identifying the subscription id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for remove an auto-export subscription. | — |
| 404 | Unknown subscription for this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AutoExportRunListResponse` {#schema-autoexportrunlistresponse}

Auto-export runs, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`AutoExportRunModel`](#schema-autoexportrunmodel) | no | Runs. |

### `AutoExportRunModel` {#schema-autoexportrunmodel}

One auto-export: a publish × a subscription.

Attributes:
    status: ``pending``, ``running``, ``delivered``, ``exported`` (no delivery profile), ``halted`` (the
        loss reached ``haltAt``: nothing delivered, people notified), ``delivery_failed`` or ``failed``.
    loss_severity: The loss the export measured: ``info``, ``warn`` or ``critical``.
    loss_reasons: Why, one line per target.
    deliveries: Each delivery's outcome.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `projectId` | string | yes | Project ID. |
| `projectName` | string or null | no | Project Name. |
| `versionRecordId` | string | yes | Version Record ID. |
| `subscriptionId` | string or null | no | Subscription ID. |
| `presetId` | string or null | no | Preset ID. |
| `presetName` | string | yes | Preset Name. |
| `haltAt` | string | yes | Halt At. |
| `approveLoss` | boolean | yes | Approve Loss. |
| `status` | string | yes | Status. |
| `jobId` | string or null | no | Job ID. |
| `lossSeverity` | string or null | no | Loss Severity. |
| `lossReasons` | array of string | no | Loss Reasons. |
| `deliveries` | array of object | no | Deliveries. |
| `errorCode` | string or null | no | Error Code. |
| `errorMessage` | string or null | no | Error Message. |
| `publishedBy` | string or null | no | Published By. |
| `releasedBy` | string or null | no | Released By. |
| `releasedAt` | string (date-time) or null | no | Released At. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `finishedAt` | string (date-time) or null | no | Finished At. |

### `AutoExportSubscriptionCreate` {#schema-autoexportsubscriptioncreate}

Subscribe a preset to a project's publishes: ``POST /v1/export/{tenant}/auto-exports``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | The project whose publishes trigger the export. |
| `preset` | string | yes | The export preset (MFX-39.3), by id or name. |
| `haltAt` | enum `"warn"`, `"critical"` | no | Halt auto-delivery when the export's loss reaches this severity: `critical` (default) for a severe or near-empty conversion, a types-only result or any critical construct; `warn` for any loss at all. |
| `approveLoss` | boolean | no | Pre-approve the loss: deliver even when it reaches `haltAt`. Recorded on every run. |
| `active` | boolean | no | Whether publishes trigger it. |

### `AutoExportSubscriptionListResponse` {#schema-autoexportsubscriptionlistresponse}

Auto-export subscriptions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subscriptions` | array of [`AutoExportSubscriptionModel`](#schema-autoexportsubscriptionmodel) | no | Subscriptions. |

### `AutoExportSubscriptionModel` {#schema-autoexportsubscriptionmodel}

An export preset subscribed to a project's publishes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `projectId` | string | yes | Project ID. |
| `projectName` | string or null | no | Project Name. |
| `presetId` | string | yes | Preset ID. |
| `presetName` | string or null | no | Preset Name. |
| `haltAt` | string | yes | `warn` or `critical`. |
| `approveLoss` | boolean | yes | Approve Loss. |
| `active` | boolean | yes | Active. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `createdBy` | string or null | no | Created By. |

### `AutoExportSubscriptionUpdate` {#schema-autoexportsubscriptionupdate}

A change to a subscription: ``PATCH /v1/export/{tenant}/auto-exports/{id}``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `haltAt` | enum `"warn"`, `"critical"` or null | no | Halt At. |
| `approveLoss` | boolean or null | no | Approve Loss. |
| `active` | boolean or null | no | Active. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
