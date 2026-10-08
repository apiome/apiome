---
title: "Classes"
description: "REST endpoints tagged classes: 11 operations."
sidebar_position: 11
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `classes` · 11 operations

## `GET /v1/classes/{tenant_slug}` {#list-classes-v1-classes-tenant-slug-get}

**List Classes**

List all classes for a tenant, optionally filtered by version.

Supports authentication via:
- JWT token in Authorization header (Bearer token)
- API key in X-API-Key header

Args:
    tenant_slug: The tenant slug
    version_id: Optional version ID to filter by
    auth_data: Authentication data (injected by dependency)

Returns:
    List of classes for the tenant/version

Operation id: `list_classes_v1_classes__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | query | string or null | no | Filter by version ID |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list classes. | `application/json` array of [`ClassSchema`](#schema-classschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/classes/{tenant_slug}` {#create-class-v1-classes-tenant-slug-post}

**Create Class**

Create a new class.

Supports authentication via JWT token or API key.
The class will be created in the specified version.

Args:
    tenant_slug: The tenant slug
    request: Class creation data
    auth_data: Authentication data (injected by dependency)

Returns:
    The created class

Operation id: `create_class_v1_classes__tenant_slug__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create class.

- `application/json` — [`ClassCreateRequest`](#schema-classcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create class. | `application/json` [`ClassSchema`](#schema-classschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/classes/{tenant_slug}/version/{version_id}/with-properties-tags` {#get-classes-with-properties-and-tags-v1-classes-tenant-slug-version-version-id-with-properties-tags-get}

**Get Classes With Properties And Tags**

Get all classes for a version with their properties and tags.

Deprecated for canvas hydration (DUW-1.2, private-suite#2569). This read has no LIMIT: it
returns every class of the version with every property and every tag, which is why a large
catalog makes the designer canvas choke. Surfaces that need a *selection* — the unified
workspace and anything else hydrating what a user picked — must use
``GET /v1/workspace/{tenant_slug}/version/{version_id}/classes`` with ``class_ids`` or
``domain_id`` instead. It stays here, unchanged, for the surfaces that genuinely do need the
whole version (exports, scoring, readiness sweeps).

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    version_id: The version ID
    auth_data: Authentication data (injected by dependency)

Returns:
    List of classes with properties and tags

Operation id: `get_classes_with_properties_and_tags_v1_classes__tenant_slug__version__version_id__with_properties_tags_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get classes with properties and tags. | `application/json` array of object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/classes/{tenant_slug}/{class_id}` {#get-class-v1-classes-tenant-slug-class-id-get}

**Get Class**

Get a specific class by ID.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    class_id: The class ID
    auth_data: Authentication data (injected by dependency)

Returns:
    The class details

Operation id: `get_class_v1_classes__tenant_slug___class_id__get`

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
| 200 | Successful response for get class. | `application/json` [`ClassSchema`](#schema-classschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/classes/{tenant_slug}/{class_id}` {#update-class-v1-classes-tenant-slug-class-id-put}

**Update Class**

Update an existing class.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    class_id: The class ID
    request: Class update data
    auth_data: Authentication data (injected by dependency)

Returns:
    The updated class

Operation id: `update_class_v1_classes__tenant_slug___class_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `class_id` | path | string | yes | Class identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update class.

- `application/json` — [`ClassUpdateRequest`](#schema-classupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update class. | `application/json` [`ClassSchema`](#schema-classschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/classes/{tenant_slug}/{class_id}` {#delete-class-v1-classes-tenant-slug-class-id-delete}

**Delete Class**

Delete a class (soft delete).

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    class_id: The class ID
    auth_data: Authentication data (injected by dependency)

Returns:
    Success message

Operation id: `delete_class_v1_classes__tenant_slug___class_id__delete`

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
| 200 | Successful response for delete class. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/classes/{tenant_slug}/{class_id}/properties` {#get-class-properties-v1-classes-tenant-slug-class-id-properties-get}

**Get Class Properties**

Get all properties for a specific class.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    class_id: The class ID
    auth_data: Authentication data (injected by dependency)

Returns:
    List of properties for the class

Operation id: `get_class_properties_v1_classes__tenant_slug___class_id__properties_get`

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
| 200 | Successful response for get class properties. | `application/json` array of object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/classes/{tenant_slug}/{class_id}/properties` {#add-property-to-class-v1-classes-tenant-slug-class-id-properties-post}

**Add Property To Class**

Add a property to a class.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    class_id: The class ID
    request: Property data containing:
        - property_id: Optional library property ID
        - name: Property name (required)
        - description: Optional property description
        - data: Property schema data (required)
        - parent_id: Optional parent property ID for nested properties
    auth_data: Authentication data (injected by dependency)

Returns:
    The created class property

Operation id: `add_property_to_class_v1_classes__tenant_slug___class_id__properties_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `class_id` | path | string | yes | Class identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for add property to class.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for add property to class. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/classes/{tenant_slug}/{class_id}/properties/{class_property_id}` {#update-class-property-v1-classes-tenant-slug-class-id-properties-class-property-id-put}

**Update Class Property**

Update a property in a class.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    class_id: The class ID
    class_property_id: The class property ID
    request: Property update data containing:
        - name: Optional property name
        - description: Optional property description
        - data: Optional property schema data
    auth_data: Authentication data (injected by dependency)

Returns:
    The updated class property

Operation id: `update_class_property_v1_classes__tenant_slug___class_id__properties__class_property_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `class_id` | path | string | yes | Class identifier within the version. |
| `class_property_id` | path | string | yes | Path parameter identifying the class property id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update class property.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update class property. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/classes/{tenant_slug}/{class_id}/properties/{class_property_id}` {#delete-class-property-v1-classes-tenant-slug-class-id-properties-class-property-id-delete}

**Delete Class Property**

Delete a property from a class.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    class_id: The class ID
    class_property_id: The class property ID
    auth_data: Authentication data (injected by dependency)

Returns:
    Success message

Operation id: `delete_class_property_v1_classes__tenant_slug___class_id__properties__class_property_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `class_id` | path | string | yes | Class identifier within the version. |
| `class_property_id` | path | string | yes | Path parameter identifying the class property id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete class property. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/classes/{tenant_slug}/{class_id}/with-properties-tags` {#get-class-with-properties-and-tags-v1-classes-tenant-slug-class-id-with-properties-tags-get}

**Get Class With Properties And Tags**

Get a single class with its properties and tags.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    class_id: The class ID
    auth_data: Authentication data (injected by dependency)

Returns:
    Class with properties and tags

Operation id: `get_class_with_properties_and_tags_v1_classes__tenant_slug___class_id__with_properties_tags_get`

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
| 200 | Successful response for get class with properties and tags. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ClassCreateRequest` {#schema-classcreaterequest}

Request body for creating a new class on a project version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `schema` | object | no | Embedded JSON Schema document. |
| `enabled` | boolean | no | Whether the resource is active. |

### `ClassSchema` {#schema-classschema}

A version-scoped class (component schema) with its JSON Schema payload and tags.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `name` | string | yes | Class name as it appears in generated OpenAPI components. |
| `description` | string or null | no | Free-text description. |
| `schema` | object or null | no | Embedded JSON Schema document. |
| `enabled` | boolean | no | Whether the resource is active. |
| `tags` | array of `TagSchema` or null | no | Associated tag labels. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `ClassUpdateRequest` {#schema-classupdaterequest}

Partial update payload for a class, including canvas metadata when provided.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `schema` | object or null | no | Embedded JSON Schema document. |
| `enabled` | boolean or null | no | Whether the resource is active. |
| `canvas_metadata` | object or null | no | Canvas Metadata. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
