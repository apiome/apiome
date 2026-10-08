---
title: "Identity"
description: "REST endpoints tagged identity: 4 operations."
sidebar_position: 26
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `identity` · 4 operations

## `POST /v1/identity/{tenant_slug}/link` {#link-artifacts-v1-identity-tenant-slug-link-post}

**Link Artifacts**

Link two projects into the same cross-format API identity group.

Operation id: `link_artifacts_v1_identity__tenant_slug__link_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for link artifacts.

- `application/json` — [`LinkArtifactsRequest`](#schema-linkartifactsrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for link artifacts. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/identity/{tenant_slug}/link` {#unlink-artifacts-v1-identity-tenant-slug-link-delete}

**Unlink Artifacts**

Remove ``relatedProjectId`` from the shared identity group.

Operation id: `unlink_artifacts_v1_identity__tenant_slug__link_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for unlink artifacts.

- `application/json` — [`UnlinkArtifactsRequest`](#schema-unlinkartifactsrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unlink artifacts. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/identity/{tenant_slug}/projects/{project_id}/related` {#get-related-artifacts-v1-identity-tenant-slug-projects-project-id-related-get}

**Get Related Artifacts**

List artifacts linked to ``project_id`` in the same identity group.

Operation id: `get_related_artifacts_v1_identity__tenant_slug__projects__project_id__related_get`

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
| 200 | Successful response for get related artifacts. | `application/json` array of [`RelatedArtifactRef`](#schema-relatedartifactref) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/identity/{tenant_slug}/projects/{project_id}/suggestions` {#get-identity-suggestions-v1-identity-tenant-slug-projects-project-id-suggestions-get}

**Get Identity Suggestions**

Heuristic link suggestions for ``project_id`` (never auto-applied).

Operation id: `get_identity_suggestions_v1_identity__tenant_slug__projects__project_id__suggestions_get`

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
| 200 | Successful response for get identity suggestions. | `application/json` array of [`IdentitySuggestionRef`](#schema-identitysuggestionref) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `IdentitySuggestionRef` {#schema-identitysuggestionref}

A heuristic suggestion to link two artifacts (MFI-6.4, #4410).

Suggestions are never auto-applied — the user must confirm a link action.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `name` | string | yes | Human-readable name. |
| `slug` | string | yes | URL-safe identifier. |
| `publishable` | boolean | no | Publishable. |
| `sourceFormat` | string or null | no | Source Format. |
| `protocol` | string or null | no | Protocol. |
| `reason` | string | yes | Reason. |
| `score` | integer | yes | Relative ranking score (higher = stronger match). |

### `LinkArtifactsRequest` {#schema-linkartifactsrequest}

Link two projects into the same cross-format API identity group.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `relatedProjectId` | string | yes | Related Project ID. |

### `RelatedArtifactRef` {#schema-relatedartifactref}

One related artifact in a cross-format API identity group (MFI-6.4, #4410).

Projects linked manually or via conversion provenance share an ``api_identity`` group; each member
carries enough catalog/project metadata for the Related artifacts panel (format pills, name, link
target) without a second round-trip.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `name` | string | yes | Human-readable name. |
| `slug` | string | yes | URL-safe identifier. |
| `publishable` | boolean | no | Publishable. |
| `sourceFormat` | string or null | no | Source Format. |
| `protocol` | string or null | no | Protocol. |
| `linkSource` | string | no | Link Source. |
| `deleted` | boolean | no | Deleted. |

### `UnlinkArtifactsRequest` {#schema-unlinkartifactsrequest}

Remove one project from a shared identity group (pairwise unlink).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `relatedProjectId` | string | yes | Related Project ID. |
