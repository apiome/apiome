---
title: "Project tags"
description: "REST endpoints tagged project-tags: 7 operations."
sidebar_position: 48
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `project-tags` · 7 operations

## `GET /v1/project-tags/{tenant_slug}/classes/{class_id}` {#list-class-tags-v1-project-tags-tenant-slug-classes-class-id-get}

**List Class Tags**

List tags assigned to a class.

Operation id: `list_class_tags_v1_project_tags__tenant_slug__classes__class_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `class_id` | path | string | yes | Class identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list class tags. | `application/json` array of [`ClassTagSchema`](#schema-classtagschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/project-tags/{tenant_slug}/classes/{class_id}` {#assign-tag-to-class-v1-project-tags-tenant-slug-classes-class-id-post}

**Assign Tag To Class**

Assign a project tag to a class.

Operation id: `assign_tag_to_class_v1_project_tags__tenant_slug__classes__class_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `class_id` | path | string | yes | Class identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for assign tag to class.

- `application/json` — [`ClassTagAssignRequest`](#schema-classtagassignrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for assign tag to class. | `application/json` [`ClassTagSchema`](#schema-classtagschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/project-tags/{tenant_slug}/classes/{class_id}/{tag_id}` {#remove-tag-from-class-v1-project-tags-tenant-slug-classes-class-id-tag-id-delete}

**Remove Tag From Class**

Remove a tag assignment from a class.

Operation id: `remove_tag_from_class_v1_project_tags__tenant_slug__classes__class_id___tag_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `class_id` | path | string | yes | Class identifier within the version. |
| `tag_id` | path | string | yes | Tag identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove tag from class. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/project-tags/{tenant_slug}/{project_id}` {#list-project-tags-v1-project-tags-tenant-slug-project-id-get}

**List Project Tags**

List all class tags for a project.

Operation id: `list_project_tags_v1_project_tags__tenant_slug___project_id__get`

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
| 200 | Successful response for list project tags. | `application/json` array of [`TagSchema`](#schema-tagschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/project-tags/{tenant_slug}/{project_id}` {#create-project-tag-v1-project-tags-tenant-slug-project-id-post}

**Create Project Tag**

Create a class tag in a project.

Operation id: `create_project_tag_v1_project_tags__tenant_slug___project_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create project tag.

- `application/json` — [`TagCreateRequest`](#schema-tagcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create project tag. | `application/json` [`TagSchema`](#schema-tagschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/project-tags/{tenant_slug}/{tag_id}` {#update-project-tag-v1-project-tags-tenant-slug-tag-id-patch}

**Update Project Tag**

Update a project class tag.

Operation id: `update_project_tag_v1_project_tags__tenant_slug___tag_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `tag_id` | path | string | yes | Tag identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update project tag.

- `application/json` — [`TagUpdateRequest`](#schema-tagupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update project tag. | `application/json` [`TagSchema`](#schema-tagschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/project-tags/{tenant_slug}/{tag_id}` {#delete-project-tag-v1-project-tags-tenant-slug-tag-id-delete}

**Delete Project Tag**

Delete a project class tag.

Operation id: `delete_project_tag_v1_project_tags__tenant_slug___tag_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `tag_id` | path | string | yes | Tag identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete project tag. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ClassTagAssignRequest` {#schema-classtagassignrequest}

Request body that assigns a tag to a class by tag id.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tag_id` | string | yes | Tag ID. |

### `ClassTagSchema` {#schema-classtagschema}

Association between a class and a project tag.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `class_id` | string | yes | Class identifier the resource is attached to. |
| `tag_id` | string | yes | Tag ID. |
| `tag_name` | string or null | no | Tag Name. |
| `tag_color` | string or null | no | Tag Color. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `TagCreateRequest` {#schema-tagcreaterequest}

Request model for creating a project class tag.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `color` | string | no | Color. |
| `description` | string or null | no | Free-text description. |

### `TagSchema` {#schema-tagschema}

TagSchema schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `name` | string | yes | Human-readable name. |
| `color` | string | no | Color. |
| `description` | string or null | no | Free-text description. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |

### `TagUpdateRequest` {#schema-tagupdaterequest}

Request model for updating a project class tag.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `color` | string or null | no | Color. |
| `description` | string or null | no | Free-text description. |
