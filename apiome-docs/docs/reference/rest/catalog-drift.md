---
title: "Catalog drift"
description: "REST endpoints tagged catalog-drift: 4 operations."
sidebar_position: 13
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.440.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `catalog-drift` · 4 operations

## `GET /v1/catalog/{tenant_slug}/drift-notifications` {#get-catalog-drift-settings-v1-catalog-tenant-slug-drift-notifications-get}

**Get Catalog Drift Settings**

Read the tenant's catalog drift alert settings (``projects:view``).

Operation id: `get_catalog_drift_settings_v1_catalog__tenant_slug__drift_notifications_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get catalog drift settings. | `application/json` [`CatalogDriftSettingsOut`](#schema-catalogdriftsettingsout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/catalog/{tenant_slug}/drift-notifications` {#put-catalog-drift-settings-v1-catalog-tenant-slug-drift-notifications-put}

**Put Catalog Drift Settings**

Replace the tenant's catalog drift alert settings (``imports:edit``).

Which severities are announced (the rest only badge), immediate or daily-digest delivery,
whether breaking drift skips the digest, and the stored email opt-in. Announcements go to the
tenant's push-webhook subscriptions and the item's owner team; a version created by **Check
now** is never announced.

Operation id: `put_catalog_drift_settings_v1_catalog__tenant_slug__drift_notifications_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put catalog drift settings.

- `application/json` — [`CatalogDriftSettings`](#schema-catalogdriftsettings)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put catalog drift settings. | `application/json` [`CatalogDriftSettingsOut`](#schema-catalogdriftsettingsout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}/drift` {#list-catalog-item-drift-v1-catalog-tenant-slug-item-id-drift-get}

**List Catalog Item Drift**

List the item's drift events, newest first, with their classified changes (``projects:view``).

Operation id: `list_catalog_item_drift_v1_catalog__tenant_slug___item_id__drift_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list catalog item drift. | `application/json` [`CatalogDriftEventList`](#schema-catalogdrifteventlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/catalog/{tenant_slug}/{item_id}/drift/{event_id}/dismiss` {#dismiss-catalog-item-drift-v1-catalog-tenant-slug-item-id-drift-event-id-dismiss-post}

**Dismiss Catalog Item Drift**

Dismiss a drift event: its badge and banner go away; the event and its changes stay (``projects:edit``).

Dismissing an already-dismissed event changes nothing.

Raises:
    HTTPException: 404 when the item or the event is not found.

Operation id: `dismiss_catalog_item_drift_v1_catalog__tenant_slug___item_id__drift__event_id__dismiss_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `event_id` | path | string | yes | Path parameter identifying the event id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for dismiss catalog item drift. | `application/json` [`CatalogDriftEvent`](#schema-catalogdriftevent) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CatalogDriftEvent` {#schema-catalogdriftevent}

One drift event with its classified changes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `eventId` | string | yes | Event ID. |
| `severity` | enum `"safe"`, `"dangerous"`, `"breaking"` | yes | Severity. |
| `versionId` | string | yes | Version ID. |
| `versionLabel` | string | yes | Version Label. |
| `changeCount` | integer | yes | Number of change. |
| `counts` | map of integer | no | Counts. |
| `trigger` | enum `"sweep"`, `"manual"` | yes | Trigger. |
| `detectedAt` | string or null | no | Detected At. |
| `link` | string | yes | The item's Versions tab, opened on this drift. |
| `parentVersionId` | string or null | no | Parent Version ID. |
| `parentVersionLabel` | string or null | no | Parent Version Label. |
| `notification` | enum `"none"`, `"sent"`, `"pending_digest"`, `"digested"` | yes | Notification. |
| `notifiedAt` | string or null | no | Notified At. |
| `dismissedAt` | string or null | no | Dismissed At. |
| `parentVersionPruned` | boolean | no | The version it was compared with was pruned by version retention (MFI-31.5). |
| `compareBaseVersionId` | string or null | no | The version to diff against: the compared version while it is kept, else the newest kept version before this one; null when there is none. |
| `compareBaseVersionLabel` | string or null | no | Compare Base Version Label. |
| `changes` | array of `CatalogDriftChange` | no | Worst first; at most 200 (changeCount is the full count). |

### `CatalogDriftEventList` {#schema-catalogdrifteventlist}

An item's drift events, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `events` | array of [`CatalogDriftEvent`](#schema-catalogdriftevent) | yes | Events. |

### `CatalogDriftSettings` {#schema-catalogdriftsettings}

The tenant's drift alert settings.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `notifyBreaking` | boolean | no | Announce breaking drift. |
| `notifyDangerous` | boolean | no | Announce dangerous drift. |
| `notifySafe` | boolean | no | Announce safe drift. Off: safe drift only shows a badge. |
| `delivery` | enum `"immediate"`, `"daily_digest"` | no | immediate: one webhook per drift; daily_digest: one webhook a day listing it all. |
| `breakingImmediate` | boolean | no | With daily_digest, still send breaking drift right away. |
| `emailEnabled` | boolean | no | Also email drift to the item's owner team: each alert right away, or one email per digest. A no-op when the server has no mailer (SENDGRID_API_KEY / EMAIL_FROM). |

### `CatalogDriftSettingsOut` {#schema-catalogdriftsettingsout}

The settings plus when they last changed and when the last digest went out.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `notifyBreaking` | boolean | no | Announce breaking drift. |
| `notifyDangerous` | boolean | no | Announce dangerous drift. |
| `notifySafe` | boolean | no | Announce safe drift. Off: safe drift only shows a badge. |
| `delivery` | enum `"immediate"`, `"daily_digest"` | no | immediate: one webhook per drift; daily_digest: one webhook a day listing it all. |
| `breakingImmediate` | boolean | no | With daily_digest, still send breaking drift right away. |
| `emailEnabled` | boolean | no | Also email drift to the item's owner team: each alert right away, or one email per digest. A no-op when the server has no mailer (SENDGRID_API_KEY / EMAIL_FROM). |
| `configured` | boolean | yes | False when the tenant uses the defaults. |
| `updatedAt` | string or null | no | Updated At. |
| `lastDigestAt` | string or null | no | Last Digest At. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
