---
title: "Properties"
description: "REST endpoints tagged properties: 5 operations."
sidebar_position: 50
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `properties` · 5 operations

## `GET /v1/properties/{tenant_slug}/{project_id}` {#list-properties-v1-properties-tenant-slug-project-id-get}

**List Properties**

List all properties for a project.

Supports authentication via:
- JWT token in Authorization header (Bearer token)
- API key in X-API-Key header

Args:
    tenant_slug: The tenant slug
    project_id: The project ID
    auth_data: Authentication data (injected by dependency)

Returns:
    List of properties for the project

Operation id: `list_properties_v1_properties__tenant_slug___project_id__get`

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
| 200 | Successful response for list properties. | `application/json` array of [`ProjectPropertySchema`](#schema-projectpropertyschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/properties/{tenant_slug}/{project_id}` {#create-property-v1-properties-tenant-slug-project-id-post}

**Create Property**

Create a new property.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    project_id: The project ID
    request: Property creation data
    auth_data: Authentication data (injected by dependency)

Returns:
    The created property

Operation id: `create_property_v1_properties__tenant_slug___project_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create property.

- `application/json` — [`ProjectPropertyCreateRequest`](#schema-projectpropertycreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create property. | `application/json` [`ProjectPropertySchema`](#schema-projectpropertyschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/properties/{tenant_slug}/{project_id}/{property_id}` {#get-property-v1-properties-tenant-slug-project-id-property-id-get}

**Get Property**

Get a specific property by ID.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    project_id: The project ID
    property_id: The property ID
    auth_data: Authentication data (injected by dependency)

Returns:
    The property details

Operation id: `get_property_v1_properties__tenant_slug___project_id___property_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `property_id` | path | string | yes | Property identifier on the class. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get property. | `application/json` [`ProjectPropertySchema`](#schema-projectpropertyschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/properties/{tenant_slug}/{project_id}/{property_id}` {#update-property-v1-properties-tenant-slug-project-id-property-id-put}

**Update Property**

Update an existing property.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    project_id: The project ID
    property_id: The property ID
    request: Property update data
    auth_data: Authentication data (injected by dependency)

Returns:
    The updated property

Operation id: `update_property_v1_properties__tenant_slug___project_id___property_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `property_id` | path | string | yes | Property identifier on the class. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update property.

- `application/json` — [`ProjectPropertyUpdateRequest`](#schema-projectpropertyupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update property. | `application/json` [`ProjectPropertySchema`](#schema-projectpropertyschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/properties/{tenant_slug}/{project_id}/{property_id}` {#delete-property-v1-properties-tenant-slug-project-id-property-id-delete}

**Delete Property**

Delete a property (soft delete).

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    project_id: The project ID
    property_id: The property ID
    auth_data: Authentication data (injected by dependency)

Returns:
    Success message

Operation id: `delete_property_v1_properties__tenant_slug___project_id___property_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `property_id` | path | string | yes | Property identifier on the class. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete property. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ProjectPropertyCreateRequest` {#schema-projectpropertycreaterequest}

Request body for creating a property on a class.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `data` | object | yes | Structured payload or extension data for the resource. |

### `ProjectPropertySchema` {#schema-projectpropertyschema}

A property on a project class, including nested structure and optional primitive binding.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `data` | object | yes | Structured payload or extension data for the resource. |
| `enabled` | boolean | no | Whether the resource is active. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `ProjectPropertyUpdateRequest` {#schema-projectpropertyupdaterequest}

Partial update payload for a class property.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `data` | object or null | no | Structured payload or extension data for the resource. |
| `enabled` | boolean or null | no | Whether the resource is active. |
