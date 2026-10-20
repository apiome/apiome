---
title: "Properties"
description: "REST endpoints tagged properties: 5 operations."
sidebar_position: 62
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.261.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `properties` · 5 operations

## `GET /v1/properties/{tenant_slug}/{project_id}` {#list-properties-v1-properties-tenant-slug-project-id-get}

**List Properties**

List all properties for a project, each with ``used_by`` (the class names that use it, across the
project's live versions) and ``used_by_count`` (#3223).

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

Get a specific property by ID, with ``usage`` — every class attribute that uses it, across the
project's live versions (#3224).

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

Update an existing property. ``expectedUpdatedAt`` makes it conditional (409 ``update_conflict``
when the property changed since); ``requiredEverywhere`` also sets ``required`` on every class
attribute using it in an unpublished version, reported in ``required_everywhere_result`` (#3226).

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

Delete a property (soft delete). With ``force=true``, first remove the class attributes that use
it in unpublished versions — all in one transaction — and report how many as ``detached``; any use
in a published version refuses the whole delete with 409 (#3227).

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
| `force` | query | boolean | no | Also remove every class attribute that uses the property, in the same transaction (#3227). Refused with 409 `property_in_published_version` when any use is in a published version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete property. | `application/json` object |
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
| `used_by` | array of string or null | no | Distinct names of the classes (in any live version of the project) that use this property; list responses only (#3223). |
| `used_by_count` | integer or null | no | Number of class properties (across live versions) that reference this property; list responses only. |
| `usage` | array of `ProjectPropertyUsage` or null | no | Every class attribute (in any live version of the project) that uses this property, one entry per distinct class name, attribute name and required flag, sorted; single-property GET only (#3224). |
| `required_everywhere_result` | `PropertyRequiredEverywhereResult` or null | no | Counts from `required_everywhere` on the PUT that set it (#3226); null on other responses. |

### `ProjectPropertyUpdateRequest` {#schema-projectpropertyupdaterequest}

Partial update payload for a class property.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `data` | object or null | no | Structured payload or extension data for the resource. |
| `enabled` | boolean or null | no | Whether the resource is active. |
| `expectedUpdatedAt` | string (date-time) or null | no | Optimistic-concurrency precondition (CLI 6.4, #3226): the property's updated_at as the caller last read it. When set, the update applies only if the property is unchanged since; otherwise the request fails with 409 code 'update_conflict' and the property's current updated_at. |
| `requiredEverywhere` | boolean or null | no | Set `required` to this value on every class attribute that uses the property in an unpublished version of the project, in the same transaction (#3226). Published versions are left alone and counted in the response's `required_everywhere_result`. |
