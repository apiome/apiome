---
title: "OpenAPI upgrade"
description: "REST endpoints tagged openapi-upgrade: 2 operations."
sidebar_position: 66
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.658.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `openapi-upgrade` · 2 operations

## `POST /v1/openapi-upgrade/{tenant_slug}/apply` {#apply-openapi-upgrade-v1-openapi-upgrade-tenant-slug-apply-post}

**Apply a reviewed OpenAPI upgrade**

Apply a reviewed plan: the upgraded document becomes a new version of the same project.

Raises:
    HTTPException: 404 unknown project / version; 409 ``plan-stale`` (the source plans
        differently now), ``nothing-to-upgrade`` (already at ``target``), ``version-exists``,
        or a source refusal (see :func:`load_version_source`); 422 when the plan or the
        import fails; 409 ``QUALITY_POLICY_BLOCKED`` when the tenant's import policy
        refuses the upgraded document.

Operation id: `apply_openapi_upgrade_v1_openapi_upgrade__tenant_slug__apply_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for apply a reviewed openapi upgrade.

- `application/json` — [`UpgradeApplyRequest`](#schema-upgradeapplyrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for apply a reviewed openapi upgrade. | `application/json` [`UpgradeApplyResponse`](#schema-upgradeapplyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/openapi-upgrade/{tenant_slug}/plan` {#plan-openapi-upgrade-v1-openapi-upgrade-tenant-slug-plan-post}

**Plan an OpenAPI version upgrade (no write)**

Plan the upgrade of a document or a version to ``target``; nothing is written.

Returns:
    The plan (:meth:`UpgradePlan.as_dict`) plus ``origin`` and, for a version source,
    ``project_id`` / ``version_record_id`` / ``version_label``.

Raises:
    HTTPException: 404 unknown project / version; 409 when the version has no single-file
        source; 413 / 422 for a document too large, unparseable, not OpenAPI, of an
        unsupported version, or newer than ``target``.

Operation id: `plan_openapi_upgrade_v1_openapi_upgrade__tenant_slug__plan_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for plan an openapi version upgrade (no write).

- `application/json` — [`UpgradePlanRequest`](#schema-upgradeplanrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for plan an openapi version upgrade (no write). | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `UpgradeApplyRequest` {#schema-upgradeapplyrequest}

Apply a reviewed plan to a project / catalog item version as a new version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target` | enum `"3.0"`, `"3.1"`, `"3.2"` | yes | Target OpenAPI version family (as planned). |
| `project_id` | string | yes | Project or catalog item to add the upgraded version to. |
| `version` | string or null | no | The version that was planned (default: the latest). |
| `plan_digest` | string | yes | The plan_digest of the reviewed plan; a mismatch is refused (409). |
| `version_label` | string or null | no | Label of the new version (for example 2.0.0). Default: a date/time label. |

### `UpgradeApplyResponse` {#schema-upgradeapplyresponse}

The version an apply created.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `version_record_id` | string | yes | The new version's id (versions.id). |
| `version_label` | string | yes | Version Label. |
| `source_version_record_id` | string | yes | The version that was upgraded. |
| `target_version` | string | yes | The OpenAPI version the new version declares. |
| `change_count` | integer | yes | Number of change. |

### `UpgradePlanRequest` {#schema-upgradeplanrequest}

What to plan: a pasted document, or a project / catalog item version, and the target.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target` | enum `"3.0"`, `"3.1"`, `"3.2"` | yes | Target OpenAPI version family. |
| `document_text` | string or null | no | The document itself (JSON or YAML). Set this or project_id, not both. |
| `project_id` | string or null | no | Project or catalog item whose version is upgraded. Set this or document_text. |
| `version` | string or null | no | The version to upgrade: a version id (UUID) or label (1.0.0). Default: the latest. |
| `include_document` | boolean | no | Return the upgraded document with the plan. |
