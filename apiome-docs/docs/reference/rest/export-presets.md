---
title: "Export presets"
description: "REST endpoints tagged export-presets: 5 operations."
sidebar_position: 36
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.543.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `export-presets` · 5 operations

## `GET /v1/export/{tenant_slug}/presets` {#list-export-presets-v1-export-tenant-slug-presets-get}

**List the workspace's export presets**

Every export preset, by name. Requires `projects:view`.

Operation id: `list_export_presets_v1_export__tenant_slug__presets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the workspace's export presets. | `application/json` [`ExportPresetListResponse`](#schema-exportpresetlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/presets` {#create-export-preset-v1-export-tenant-slug-presets-post}

**Store an export preset**

Saves a named export combination for the workspace: 1–16 `targets`, each with its emit `options` (validated against that emitter's options schema, MFX-1.4; no two targets may resolve to the same format), and an optional `deliveryProfileId` (MFX-38.4) the export is delivered with on completion. Apply it with `POST /v1/export/{tenant}/jobs` and `"preset": "<name or id>"`. Requires `projects:edit`; audited as `export.preset.created`. `400` for an invalid field, target, option or unknown delivery profile (every problem in `errors`); `409` for a name already in use.

Operation id: `create_export_preset_v1_export__tenant_slug__presets_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for store an export preset.

- `application/json` — [`ExportPresetCreate`](#schema-exportpresetcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for store an export preset. | `application/json` [`ExportPresetModel`](#schema-exportpresetmodel) |
| 400 | Invalid name, target, option or delivery profile. | — |
| 409 | A preset of that name exists. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/export/{tenant_slug}/presets/{preset_id}` {#update-export-preset-v1-export-tenant-slug-presets-preset-id-patch}

**Change an export preset**

Changes a preset's `name`, `description`, `targets` (replaced whole, validated again) or `deliveryProfileId` (`null` removes delivery). Omitted fields keep their value. Requires `projects:edit`; audited as `export.preset.updated`.

Operation id: `update_export_preset_v1_export__tenant_slug__presets__preset_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `preset_id` | path | string | yes | Path parameter identifying the preset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for change an export preset.

- `application/json` — [`ExportPresetUpdate`](#schema-exportpresetupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for change an export preset. | `application/json` [`ExportPresetModel`](#schema-exportpresetmodel) |
| 400 | Invalid name, target, option or delivery profile. | — |
| 404 | Unknown preset for this tenant. | — |
| 409 | Another preset has that name. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/export/{tenant_slug}/presets/{preset_id}` {#delete-export-preset-v1-export-tenant-slug-presets-preset-id-delete}

**Delete an export preset**

Removes the preset (by id or name). Exports already started with it are unaffected. Requires `projects:edit`; audited as `export.preset.deleted`. `404` when the workspace has no such preset.

Operation id: `delete_export_preset_v1_export__tenant_slug__presets__preset_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `preset_id` | path | string | yes | Path parameter identifying the preset id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete an export preset. | — |
| 404 | Unknown preset for this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/presets/{preset}` {#get-export-preset-v1-export-tenant-slug-presets-preset-get}

**Read an export preset**

One export preset, by id or name. Requires `projects:view`. `404` when the workspace has no such preset.

Operation id: `get_export_preset_v1_export__tenant_slug__presets__preset__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `preset` | path | string | yes | Path parameter identifying the preset segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read an export preset. | `application/json` [`ExportPresetModel`](#schema-exportpresetmodel) |
| 404 | Unknown preset for this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ExportPresetCreate` {#schema-exportpresetcreate}

A new preset: ``POST /v1/export/{tenant}/presets``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | A name unique in the workspace (`nightly-sync`), up to 120 characters. |
| `description` | string or null | no | What the preset is for. |
| `targets` | array of `PresetTarget` | yes | The targets, in order: one is a single-target export, 2–16 a multi-target export with one directory per target. |
| `deliveryProfileId` | string or null | no | A delivery profile (MFX-38.4) the export is delivered with as soon as it completes. Ignored when `deliveryProfileIds` is sent. |
| `deliveryProfileIds` | array of string or null | no | Up to 5 delivery profiles (MFX-46.4), in the order the export is delivered with them; takes precedence over `deliveryProfileId`. |

### `ExportPresetListResponse` {#schema-exportpresetlistresponse}

A workspace's export presets, by name.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `presets` | array of [`ExportPresetModel`](#schema-exportpresetmodel) | no | Presets. |

### `ExportPresetModel` {#schema-exportpresetmodel}

A stored export preset.

Attributes:
    id: The preset.
    name: Its unique name in the workspace.
    description: What it is for.
    targets: The targets, in order, each with its emit options.
    delivery_profile_id: The first delivery profile the export is delivered with, or null.
    delivery_profile_name: That profile's name (null when none, or the profile was deleted).
    delivery_profile_ids: Every delivery profile, in the order the export is delivered with them (MFX-46.4).
    delivery_profile_names: Their names, in the same order.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `targets` | array of `PresetTarget` | no | Targets. |
| `deliveryProfileId` | string or null | no | Delivery Profile ID. |
| `deliveryProfileName` | string or null | no | Delivery Profile Name. |
| `deliveryProfileIds` | array of string | no | Delivery Profile IDs. |
| `deliveryProfileNames` | array of string | no | Delivery Profile Names. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `createdBy` | string or null | no | Created By. |
| `updatedBy` | string or null | no | Updated By. |

### `ExportPresetUpdate` {#schema-exportpresetupdate}

A change to a preset: ``PATCH /v1/export/{tenant}/presets/{id}``. Omitted fields keep their value.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | A new name. |
| `description` | string or null | no | A new description; `""` clears it. |
| `targets` | array of `PresetTarget` or null | no | A new target list (replaces it). |
| `deliveryProfileId` | string or null | no | A new (single) delivery profile; `null` removes delivery from the preset. Ignored when `deliveryProfileIds` is sent. |
| `deliveryProfileIds` | array of string or null | no | A new ordered list of delivery profiles (MFX-46.4), replacing the preset's; `[]` removes delivery. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
