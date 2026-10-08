---
title: "Version tags"
description: "REST endpoints tagged version-tags: 4 operations."
sidebar_position: 78
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `version-tags` · 4 operations

## `GET /v1/version-tags/{tenant_slug}/{project_id}` {#list-version-tags-v1-version-tags-tenant-slug-project-id-get}

**List Version Tags**

List all tags for a project.

Operation id: `list_version_tags_v1_version_tags__tenant_slug___project_id__get`

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
| 200 | Successful response for list version tags. | `application/json` array of [`VersionTagSchema`](#schema-versiontagschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/version-tags/{tenant_slug}/{project_id}` {#create-version-tag-v1-version-tags-tenant-slug-project-id-post}

**Create Version Tag**

Create a tag pointing at an existing schema revision.

Operation id: `create_version_tag_v1_version_tags__tenant_slug___project_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create version tag.

- `application/json` — [`VersionTagCreateRequest`](#schema-versiontagcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create version tag. | `application/json` [`VersionTagSchema`](#schema-versiontagschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/version-tags/{tenant_slug}/{project_id}/{tag_id}` {#patch-version-tag-v1-version-tags-tenant-slug-project-id-tag-id-patch}

**Patch Version Tag**

Move a tag to another revision and/or set immutable lock / protection policy.

Operation id: `patch_version_tag_v1_version_tags__tenant_slug___project_id___tag_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `tag_id` | path | string | yes | Tag identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for patch version tag.

- `application/json` — [`VersionTagUpdateRequest`](#schema-versiontagupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for patch version tag. | `application/json` [`VersionTagSchema`](#schema-versiontagschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/version-tags/{tenant_slug}/{project_id}/{tag_id}` {#delete-version-tag-v1-version-tags-tenant-slug-project-id-tag-id-delete}

**Delete Version Tag**

Delete a tag (not allowed when immutable; protected tags require admin).

Operation id: `delete_version_tag_v1_version_tags__tenant_slug___project_id___tag_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `tag_id` | path | string | yes | Tag identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete version tag. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `VersionTagCreateRequest` {#schema-versiontagcreaterequest}

Create a named tag at a revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `name` | string | yes | Human-readable name. |
| `message` | string or null | no | Message. |
| `channel` | string or null | no | Channel. |
| `immutable` | boolean or null | no | Immutable. |
| `protected` | boolean or null | no | Protected. |

### `VersionTagSchema` {#schema-versiontagschema}

Git-like tag pointing at a schema revision (versions.id).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `name` | string | yes | Human-readable name. |
| `message` | string or null | no | Message. |
| `channel` | string or null | no | Channel. |
| `immutable` | boolean | no | Immutable. |
| `protected` | boolean | no | Protected. |
| `created_by` | string or null | no | Created By. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |
| `target_version_string` | string or null | no | Target Version String. |

### `VersionTagUpdateRequest` {#schema-versiontagupdaterequest}

Move tag to another revision and/or lock it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string or null | no | Project version identifier or semantic version label, depending on context. |
| `immutable` | boolean or null | no | Immutable. |
| `protected` | boolean or null | no | Protected. |
