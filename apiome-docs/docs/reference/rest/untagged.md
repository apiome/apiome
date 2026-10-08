---
title: "Untagged"
description: "REST endpoints that declare no tag: 8 operations."
sidebar_position: 75
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

## `GET /` {#root-get}

**Root**

Root endpoint.

Operation id: `root__get`

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for root. | `application/json` any |

## `GET /v1/arazzo/{tenant_slug}/{project_slug}/{version_slug}` {#get-version-arazzo-spec-v1-arazzo-tenant-slug-project-slug-version-slug-get}

**Get Version Arazzo Spec**

Get the complete Arazzo workflow specification for all classes in a version.
Uses content negotiation to determine response format (JSON or YAML).

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    version_slug: The version ID (e.g., "1.0.0")
    x_api_key: Optional API key for private versions (header)
    api_key: Optional API key for private versions (query, for links)
    accept: Accept header for content negotiation

Returns:
    Arazzo 1.0.1 specification in JSON or YAML format

Operation id: `get_version_arazzo_spec_v1_arazzo__tenant_slug___project_slug___version_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `api_key` | query | string or null | no | API key for private versions (alternative to X-API-Key header) |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `accept` | header | string or null | no | Requested response content type (``Accept`` header). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get version arazzo spec. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/arazzo/{tenant_slug}/{project_slug}/{version_slug}/{class_name}` {#get-class-arazzo-spec-v1-arazzo-tenant-slug-project-slug-version-slug-class-name-get}

**Get Class Arazzo Spec**

Get the Arazzo workflow specification for a single class.
Uses content negotiation to determine response format (JSON or YAML).

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    version_slug: The version ID (e.g., "1.0.0")
    class_name: The name of the class
    x_api_key: Optional API key for private versions
    accept: Accept header for content negotiation

Returns:
    Arazzo 1.0.1 specification for the class in JSON or YAML format

Operation id: `get_class_arazzo_spec_v1_arazzo__tenant_slug___project_slug___version_slug___class_name__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `class_name` | path | string | yes | Class name within the version. |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `accept` | header | string or null | no | Requested response content type (``Accept`` header). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get class arazzo spec. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/json/{tenant_slug}/{project_slug}/{version_slug}` {#get-version-jsonschema-spec-v1-json-tenant-slug-project-slug-version-slug-get}

**Get Version Jsonschema Spec**

Get the complete JSON Schema specification for all classes in a version.
Uses content negotiation to determine response format (JSON or YAML).

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    version_slug: The version ID (e.g., "1.0.0")
    x_api_key: Optional API key for private versions (header)
    api_key: Optional API key for private versions (query, for links)
    accept: Accept header for content negotiation

Returns:
    JSON Schema specification in JSON or YAML format

Operation id: `get_version_jsonschema_spec_v1_json__tenant_slug___project_slug___version_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `api_key` | query | string or null | no | API key for private versions (alternative to X-API-Key header) |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `accept` | header | string or null | no | Requested response content type (``Accept`` header). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get version jsonschema spec. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/json/{tenant_slug}/{project_slug}/{version_slug}/{class_name}` {#get-class-jsonschema-spec-v1-json-tenant-slug-project-slug-version-slug-class-name-get}

**Get Class Jsonschema Spec**

Get the JSON Schema specification for a single class.
Uses content negotiation to determine response format (JSON or YAML).

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    version_slug: The version ID (e.g., "1.0.0")
    class_name: The name of the class
    x_api_key: Optional API key for private versions
    accept: Accept header for content negotiation

Returns:
    JSON Schema specification for the class in JSON or YAML format

Operation id: `get_class_jsonschema_spec_v1_json__tenant_slug___project_slug___version_slug___class_name__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `class_name` | path | string | yes | Class name within the version. |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `accept` | header | string or null | no | Requested response content type (``Accept`` header). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get class jsonschema spec. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/schema/{tenant_slug}/{project_slug}/{version_slug}` {#get-version-openapi-spec-v1-schema-tenant-slug-project-slug-version-slug-get}

**Get Version Openapi Spec**

Get the complete OpenAPI specification for all classes in a version.

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    version_slug: The version ID (e.g., "1.0.0")
    x_api_key: Optional API key for private versions (header)
    api_key: Optional API key for private versions (query, for links)

Returns:
    OpenAPI 3.1.0 specification in JSON format

Operation id: `get_version_openapi_spec_v1_schema__tenant_slug___project_slug___version_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `api_key` | query | string or null | no | API key for private versions (alternative to X-API-Key header) |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get version openapi spec. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/schema/{tenant_slug}/{project_slug}/{version_slug}/{class_name}` {#get-class-openapi-spec-v1-schema-tenant-slug-project-slug-version-slug-class-name-get}

**Get Class Openapi Spec**

Get the OpenAPI specification for a single class.
Uses content negotiation to determine response format (JSON or YAML).

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    version_slug: The version ID (e.g., "1.0.0")
    class_name: The name of the class
    x_api_key: Optional API key for private versions
    accept: Accept header for content negotiation

Returns:
    OpenAPI 3.1.0 specification for the class in JSON or YAML format

Operation id: `get_class_openapi_spec_v1_schema__tenant_slug___project_slug___version_slug___class_name__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `class_name` | path | string | yes | Class name within the version. |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `accept` | header | string or null | no | Requested response content type (``Accept`` header). |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get class openapi spec. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/swagger/{tenant_slug}/{project_slug}/{version_slug}` {#get-swagger-ui-v1-swagger-tenant-slug-project-slug-version-slug-get}

**Get Swagger Ui**

Display the OpenAPI specification in a Swagger UI interface.

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    version_slug: The version ID (e.g., "1.0.0")
    x_api_key: Optional API key for private versions (header)
    api_key: Optional API key for private versions (query, for links)

Returns:
    HTML page with Swagger UI displaying the schema

Operation id: `get_swagger_ui_v1_swagger__tenant_slug___project_slug___version_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `api_key` | query | string or null | no | API key for private versions (alternative to X-API-Key header) |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get swagger ui. | `text/html` string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
