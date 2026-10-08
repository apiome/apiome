---
title: "Paths"
description: "REST endpoints tagged paths: 33 operations."
sidebar_position: 45
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `paths` · 33 operations

## `GET /v1/paths/{tenant_slug}/{version_id}` {#list-paths-v1-paths-tenant-slug-version-id-get}

**List Paths**

List all paths for a version.

Args:
    tenant_slug: The tenant slug
    version_id: The version ID (UUID)
    auth_data: Authentication data (injected by dependency)

Returns:
    List of paths for the version

Operation id: `list_paths_v1_paths__tenant_slug___version_id__get`

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
| 200 | Successful response for list paths. | `application/json` array of [`PathSchema`](#schema-pathschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}` {#create-path-v1-paths-tenant-slug-version-id-post}

**Create Path**

Create a new path.

Args:
    tenant_slug: The tenant slug
    version_id: The version ID
    request: Path creation data
    auth_data: Authentication data (injected by dependency)

Returns:
    The created path

Operation id: `create_path_v1_paths__tenant_slug___version_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create path.

- `application/json` — [`PathCreateRequest`](#schema-pathcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create path. | `application/json` [`PathSchema`](#schema-pathschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}` {#get-path-v1-paths-tenant-slug-version-id-path-id-get}

**Get Path**

Get a specific path with its operations.

Args:
    tenant_slug: The tenant slug
    version_id: The version ID
    path_id: The path ID
    auth_data: Authentication data (injected by dependency)

Returns:
    Path details with operations

Operation id: `get_path_v1_paths__tenant_slug___version_id___path_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get path. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/paths/{tenant_slug}/{version_id}/{path_id}` {#update-path-v1-paths-tenant-slug-version-id-path-id-put}

**Update Path**

Update an existing path.

Args:
    tenant_slug: The tenant slug
    version_id: The version ID
    path_id: The path ID
    request: Path update data
    auth_data: Authentication data (injected by dependency)

Returns:
    The updated path

Operation id: `update_path_v1_paths__tenant_slug___version_id___path_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update path.

- `application/json` — [`PathUpdateRequest`](#schema-pathupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update path. | `application/json` [`PathSchema`](#schema-pathschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}` {#delete-path-v1-paths-tenant-slug-version-id-path-id-delete}

**Delete Path**

Delete a path.

Args:
    tenant_slug: The tenant slug
    version_id: The version ID
    path_id: The path ID
    auth_data: Authentication data (injected by dependency)

Returns:
    Success status

Operation id: `delete_path_v1_paths__tenant_slug___version_id___path_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete path. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}/canvas` {#get-path-canvas-v1-paths-tenant-slug-version-id-path-id-canvas-get}

**Get Path Canvas**

Load persisted React Flow canvas (nodes, edges, viewport) for a path (#2642).
Tenant-safe; returns defaults when no row exists.

Operation id: `get_path_canvas_v1_paths__tenant_slug___version_id___path_id__canvas_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get path canvas. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/paths/{tenant_slug}/{version_id}/{path_id}/canvas` {#put-path-canvas-v1-paths-tenant-slug-version-id-path-id-canvas-put}

**Put Path Canvas**

Replace Paths canvas JSON for this path (last-write-wins, #2642).

Operation id: `put_path_canvas_v1_paths__tenant_slug___version_id___path_id__canvas_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put path canvas.

- `application/json` — [`PathsCanvasPayload`](#schema-pathscanvaspayload)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put path canvas. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}/full` {#get-path-full-v1-paths-tenant-slug-version-id-path-id-full-get}

**Get Path Full**

Get a path with full operation details (parameters, request bodies, responses).
Useful for loading complete path data for the canvas.

Operation id: `get_path_full_v1_paths__tenant_slug___version_id___path_id__full_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get path full. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations` {#list-operations-v1-paths-tenant-slug-version-id-path-id-operations-get}

**List Operations**

List all operations for a path.

Operation id: `list_operations_v1_paths__tenant_slug___version_id___path_id__operations_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list operations. | `application/json` array of [`OperationSchema`](#schema-operationschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations` {#create-operation-v1-paths-tenant-slug-version-id-path-id-operations-post}

**Create Operation**

Create a new operation for a path.

Operation id: `create_operation_v1_paths__tenant_slug___version_id___path_id__operations_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create operation.

- `application/json` — [`OperationCreateRequest`](#schema-operationcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create operation. | `application/json` [`OperationSchema`](#schema-operationschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}` {#update-operation-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-put}

**Update Operation**

Update an operation.

Operation id: `update_operation_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update operation.

- `application/json` — [`OperationUpdateRequest`](#schema-operationupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update operation. | `application/json` [`OperationSchema`](#schema-operationschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}` {#delete-operation-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-delete}

**Delete Operation**

Delete an operation.

Operation id: `delete_operation_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete operation. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/description` {#get-operation-description-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-description-get}

**Get Operation Description**

Get operation description (summary, description, operationId, tags, etc.)

Operation id: `get_operation_description_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__description_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get operation description. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/description` {#update-operation-description-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-description-put}

**Update Operation Description**

Create or update operation description.

Operation id: `update_operation_description_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__description_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update operation description.

- `application/json` — [`OperationDescriptionRequest`](#schema-operationdescriptionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update operation description. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/parameters/{parameter_id}/link` {#link-parameter-to-operation-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-parameters-parameter-id-link-post}

**Link Parameter To Operation**

Link a shared parameter to an operation.

Operation id: `link_parameter_to_operation_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__parameters__parameter_id__link_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `parameter_id` | path | string | yes | Path parameter identifying the parameter id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for link parameter to operation. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/parameters/{parameter_id}/link` {#unlink-parameter-from-operation-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-parameters-parameter-id-link-delete}

**Unlink Parameter From Operation**

Unlink a shared parameter from an operation.

Operation id: `unlink_parameter_from_operation_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__parameters__parameter_id__link_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `parameter_id` | path | string | yes | Path parameter identifying the parameter id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unlink parameter from operation. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/request-body/link` {#unlink-request-body-from-operation-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-request-body-link-delete}

**Unlink Request Body From Operation**

Unlink request body from an operation.

Operation id: `unlink_request_body_from_operation_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__request_body_link_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unlink request body from operation. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/request-body/{request_body_id}/link` {#link-request-body-to-operation-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-request-body-request-body-id-link-post}

**Link Request Body To Operation**

Link a shared request body to an operation.

Operation id: `link_request_body_to_operation_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__request_body__request_body_id__link_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `request_body_id` | path | string | yes | Path parameter identifying the request body id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for link request body to operation.

- `application/json` — [`LinkOperationRequest`](#schema-linkoperationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for link request body to operation. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/responses/{response_id}/link` {#link-response-to-operation-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-responses-response-id-link-post}

**Link Response To Operation**

Link a shared response to an operation.

Operation id: `link_response_to_operation_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__responses__response_id__link_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `response_id` | path | string | yes | Path parameter identifying the response id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for link response to operation.

- `application/json` — [`LinkOperationRequest`](#schema-linkoperationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for link response to operation. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}/operations/{operation_id}/responses/{response_id}/link` {#unlink-response-from-operation-v1-paths-tenant-slug-version-id-path-id-operations-operation-id-responses-response-id-link-delete}

**Unlink Response From Operation**

Unlink a shared response from an operation.

Operation id: `unlink_response_from_operation_v1_paths__tenant_slug___version_id___path_id__operations__operation_id__responses__response_id__link_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `operation_id` | path | string | yes | Operation identifier within the path. |
| `response_id` | path | string | yes | Path parameter identifying the response id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for unlink response from operation. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}/parameters` {#list-shared-parameters-v1-paths-tenant-slug-version-id-path-id-parameters-get}

**List Shared Parameters**

List all shared parameters for a path.

Operation id: `list_shared_parameters_v1_paths__tenant_slug___version_id___path_id__parameters_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list shared parameters. | `application/json` array of [`SharedParameterSchema`](#schema-sharedparameterschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/parameters` {#create-shared-parameter-v1-paths-tenant-slug-version-id-path-id-parameters-post}

**Create Shared Parameter**

Create a shared parameter for a path.

Operation id: `create_shared_parameter_v1_paths__tenant_slug___version_id___path_id__parameters_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create shared parameter.

- `application/json` — [`SharedParameterCreateRequest`](#schema-sharedparametercreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create shared parameter. | `application/json` [`SharedParameterSchema`](#schema-sharedparameterschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}/parameters/{parameter_id}` {#delete-shared-parameter-v1-paths-tenant-slug-version-id-path-id-parameters-parameter-id-delete}

**Delete Shared Parameter**

Delete a shared parameter.

Operation id: `delete_shared_parameter_v1_paths__tenant_slug___version_id___path_id__parameters__parameter_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `parameter_id` | path | string | yes | Path parameter identifying the parameter id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete shared parameter. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}/request-bodies` {#list-shared-request-bodies-v1-paths-tenant-slug-version-id-path-id-request-bodies-get}

**List Shared Request Bodies**

List all shared request bodies for a path.

Operation id: `list_shared_request_bodies_v1_paths__tenant_slug___version_id___path_id__request_bodies_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list shared request bodies. | `application/json` array of [`SharedRequestBodySchema`](#schema-sharedrequestbodyschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/request-bodies` {#create-shared-request-body-v1-paths-tenant-slug-version-id-path-id-request-bodies-post}

**Create Shared Request Body**

Create a shared request body for a path.

Operation id: `create_shared_request_body_v1_paths__tenant_slug___version_id___path_id__request_bodies_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create shared request body.

- `application/json` — [`SharedRequestBodyCreateRequest`](#schema-sharedrequestbodycreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create shared request body. | `application/json` [`SharedRequestBodySchema`](#schema-sharedrequestbodyschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}/request-bodies/{request_body_id}` {#delete-shared-request-body-v1-paths-tenant-slug-version-id-path-id-request-bodies-request-body-id-delete}

**Delete Shared Request Body**

Delete a shared request body.

Operation id: `delete_shared_request_body_v1_paths__tenant_slug___version_id___path_id__request_bodies__request_body_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `request_body_id` | path | string | yes | Path parameter identifying the request body id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete shared request body. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/request-bodies/{request_body_id}/content-types` {#add-request-body-content-type-v1-paths-tenant-slug-version-id-path-id-request-bodies-request-body-id-content-types-post}

**Add Request Body Content Type**

Add a content type to a request body.

Operation id: `add_request_body_content_type_v1_paths__tenant_slug___version_id___path_id__request_bodies__request_body_id__content_types_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `request_body_id` | path | string | yes | Path parameter identifying the request body id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for add request body content type.

- `application/json` — [`RequestBodyContentTypeRequest`](#schema-requestbodycontenttyperequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for add request body content type. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/request-bodies/{request_body_id}/content-types/{media_type}/copy-from-class` {#copy-class-to-request-body-inline-schema-v1-paths-tenant-slug-version-id-path-id-request-bodies-request-body-id-content-types-media-type-copy-from-class-post}

**Copy Class To Request Body Inline Schema**

Copy class properties to create an inline schema for the request body content type.
This creates a copy of the class schema, not a reference.

Operation id: `copy_class_to_request_body_inline_schema_v1_paths__tenant_slug___version_id___path_id__request_bodies__request_body_id__content_types__media_type__copy_from_class_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `request_body_id` | path | string | yes | Path parameter identifying the request body id segment. |
| `media_type` | path | string | yes | Path parameter identifying the media type segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for copy class to request body inline schema.

- `application/json` — [`CopyClassToInlineSchemaRequest`](#schema-copyclasstoinlineschemarequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for copy class to request body inline schema. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}/responses` {#list-shared-responses-v1-paths-tenant-slug-version-id-path-id-responses-get}

**List Shared Responses**

List all shared responses for a path.

Operation id: `list_shared_responses_v1_paths__tenant_slug___version_id___path_id__responses_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list shared responses. | `application/json` array of [`SharedResponseSchema`](#schema-sharedresponseschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/responses` {#create-shared-response-v1-paths-tenant-slug-version-id-path-id-responses-post}

**Create Shared Response**

Create a shared response for a path.

Operation id: `create_shared_response_v1_paths__tenant_slug___version_id___path_id__responses_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create shared response.

- `application/json` — [`SharedResponseCreateRequest`](#schema-sharedresponsecreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create shared response. | `application/json` [`SharedResponseSchema`](#schema-sharedresponseschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}/responses/{response_id}` {#delete-shared-response-v1-paths-tenant-slug-version-id-path-id-responses-response-id-delete}

**Delete Shared Response**

Delete a shared response.

Operation id: `delete_shared_response_v1_paths__tenant_slug___version_id___path_id__responses__response_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `response_id` | path | string | yes | Path parameter identifying the response id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete shared response. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/responses/{response_id}/content-types` {#add-response-content-type-v1-paths-tenant-slug-version-id-path-id-responses-response-id-content-types-post}

**Add Response Content Type**

Add a content type to a response.

Operation id: `add_response_content_type_v1_paths__tenant_slug___version_id___path_id__responses__response_id__content_types_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `response_id` | path | string | yes | Path parameter identifying the response id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for add response content type.

- `application/json` — [`ResponseContentTypeRequest`](#schema-responsecontenttyperequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for add response content type. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/paths/{tenant_slug}/{version_id}/{path_id}/responses/{response_id}/content-types/{media_type}/copy-from-class` {#copy-class-to-response-inline-schema-v1-paths-tenant-slug-version-id-path-id-responses-response-id-content-types-media-type-copy-from-class-post}

**Copy Class To Response Inline Schema**

Copy class properties to create an inline schema for the response content type.
This creates a copy of the class schema, not a reference.

Operation id: `copy_class_to_response_inline_schema_v1_paths__tenant_slug___version_id___path_id__responses__response_id__content_types__media_type__copy_from_class_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_id` | path | string | yes | Path identifier within the version. |
| `response_id` | path | string | yes | Path parameter identifying the response id segment. |
| `media_type` | path | string | yes | Path parameter identifying the media type segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for copy class to response inline schema.

- `application/json` — [`CopyClassToInlineSchemaRequest`](#schema-copyclasstoinlineschemarequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for copy class to response inline schema. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CopyClassToInlineSchemaRequest` {#schema-copyclasstoinlineschemarequest}

Request model for copying class properties to inline schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `class_id` | string | yes | Class identifier the resource is attached to. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `LinkOperationRequest` {#schema-linkoperationrequest}

Request model for linking entities to operations.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `metadata` | object or null | no | Additional JSON metadata bag. |

### `OperationCreateRequest` {#schema-operationcreaterequest}

Request body for creating an operation on a path.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `operation` | string | yes | HTTP method name (GET, POST, PUT, PATCH, DELETE, …). |
| `metadata` | object or null | no | Additional JSON metadata bag. |

### `OperationDescriptionRequest` {#schema-operationdescriptionrequest}

Request body for creating or updating operation description metadata.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `description` | string or null | no | Free-text description. |
| `operation_id` | string or null | no | OpenAPI ``operationId`` value when set. |
| `metadata` | object or null | no | Additional JSON metadata bag. |

### `OperationSchema` {#schema-operationschema}

An HTTP operation (method) attached to a version path.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `version_path_id` | string | yes | Identifier of the parent path row for this operation. |
| `operation` | string | yes | HTTP verb for the operation. |
| `metadata` | object or null | no | Additional JSON metadata bag. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `OperationUpdateRequest` {#schema-operationupdaterequest}

Partial update payload for an operation.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `operation` | string or null | no | HTTP method name (GET, POST, PUT, PATCH, DELETE, …). |
| `metadata` | object or null | no | Additional JSON metadata bag. |

### `PathCreateRequest` {#schema-pathcreaterequest}

Request body for creating a path on a version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pathname` | string | yes | HTTP path template (for example ``/pets/{petId}``). |
| `metadata` | object or null | no | Additional JSON metadata bag. |

### `PathSchema` {#schema-pathschema}

An HTTP path template attached to a project version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `pathname` | string | yes | HTTP path template (for example ``/pets/{petId}``). |
| `metadata` | object or null | no | Additional JSON metadata bag. |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `description` | string or null | no | Free-text description. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `PathUpdateRequest` {#schema-pathupdaterequest}

Partial update payload for a path.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pathname` | string or null | no | HTTP path template (for example ``/pets/{petId}``). |
| `metadata` | object or null | no | Additional JSON metadata bag. |

### `PathsCanvasPayload` {#schema-pathscanvaspayload}

Persisted React Flow layout for the Paths designer (nodes, edges, viewport).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `nodes` | array of any | no | Nodes. |
| `edges` | array of any | no | Edges. |
| `viewport` | `PathsCanvasViewport` | no | Viewport. |

### `RequestBodyContentTypeRequest` {#schema-requestbodycontenttyperequest}

Request model for adding a content type to a request body.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `media_type` | string | yes | Media Type. |
| `class_id` | string or null | no | Class identifier the resource is attached to. |
| `inline_schema` | object or null | no | Inline Schema. |
| `encoding` | object or null | no | Encoding. |
| `examples` | array of object or null | no | Examples. |

### `ResponseContentTypeRequest` {#schema-responsecontenttyperequest}

Request model for adding a content type to a response.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `media_type` | string | yes | Media Type. |
| `class_id` | string or null | no | Class identifier the resource is attached to. |
| `inline_schema` | object or null | no | Inline Schema. |
| `examples` | array of object or null | no | Examples. |

### `SharedParameterCreateRequest` {#schema-sharedparametercreaterequest}

Request model for creating a shared parameter.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `in_location` | string | yes | In Location. |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `description` | string or null | no | Free-text description. |
| `data` | object or null | no | Structured payload or extension data for the resource. |

### `SharedParameterSchema` {#schema-sharedparameterschema}

SharedParameterSchema schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `version_path_id` | string | yes | Identifier of the parent path row for this operation. |
| `name` | string | yes | Human-readable name. |
| `in_location` | string | yes | In Location. |
| `summary` | string or null | no | Short summary suitable for navigation and reference docs. |
| `description` | string or null | no | Free-text description. |
| `data` | object or null | no | Structured payload or extension data for the resource. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `SharedRequestBodyCreateRequest` {#schema-sharedrequestbodycreaterequest}

Request model for creating a shared request body.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `required` | boolean | no | Required. |

### `SharedRequestBodySchema` {#schema-sharedrequestbodyschema}

SharedRequestBodySchema schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `version_path_id` | string | yes | Identifier of the parent path row for this operation. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `required` | boolean | no | Required. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `SharedResponseCreateRequest` {#schema-sharedresponsecreaterequest}

Request model for creating a shared response.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `status_code` | string | yes | Status Code. |
| `description` | string or null | no | Free-text description. |
| `data` | object or null | no | Structured payload or extension data for the resource. |
| `class_id` | string or null | no | Class identifier the resource is attached to. |
| `inline_schema` | object or null | no | Inline Schema. |

### `SharedResponseSchema` {#schema-sharedresponseschema}

SharedResponseSchema schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `version_path_id` | string | yes | Identifier of the parent path row for this operation. |
| `status_code` | string | yes | Status Code. |
| `description` | string or null | no | Free-text description. |
| `data` | object or null | no | Structured payload or extension data for the resource. |
| `class_id` | string or null | no | Class identifier the resource is attached to. |
| `inline_schema` | object or null | no | Inline Schema. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |
