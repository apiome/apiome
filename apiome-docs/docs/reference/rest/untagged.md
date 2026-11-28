---
title: "Untagged"
description: "REST endpoints that declare no tag: 8 operations."
sidebar_position: 116
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.708.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

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
    arazzo_version: Arazzo version to write (``1.0.1`` / ``1.1.0`` …); ``None`` for the default

Returns:
    Arazzo 1.0.x / 1.1.x specification in JSON or YAML format

Raises:
    HTTPException: 400 when ``arazzo_version`` is not a supported Arazzo version

Operation id: `get_version_arazzo_spec_v1_arazzo__tenant_slug___project_slug___version_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `api_key` | query | string or null | no | API key for private versions (alternative to X-API-Key header) |
| `arazzo_version` | query | string or null | no | Arazzo specification version to write: any 1.0.x or 1.1.x version, for example `1.0.1` or `1.1.0`. Defaults to 1.0.1, because the generated document's only source description is the version's OpenAPI schema. |
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
    arazzo_version: Arazzo version to write (``1.0.1`` / ``1.1.0`` …); ``None`` for the default

Returns:
    Arazzo 1.0.x / 1.1.x specification for the class in JSON or YAML format

Raises:
    HTTPException: 400 when ``arazzo_version`` is not a supported Arazzo version

Operation id: `get_class_arazzo_spec_v1_arazzo__tenant_slug___project_slug___version_slug___class_name__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `class_name` | path | string | yes | Class name within the version. |
| `arazzo_version` | query | string or null | no | Arazzo specification version to write: any 1.0.x or 1.1.x version, for example `1.0.1` or `1.1.0`. Defaults to 1.0.1, because the generated document's only source description is the version's OpenAPI schema. |
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

The document is rendered once per change of the version and kept in the document store
(COA-5.5, #7081); later requests stream the stored bytes. The response carries
``ETag: "<sha256>"``, the SHA-256 of the body. Send it back as ``If-None-Match`` to get
``304 Not Modified`` with no body while the document is unchanged.

Args:
    tenant_slug: The tenant slug
    project_slug: The project slug
    version_slug: The version ID (e.g., "1.0.0")
    x_api_key: Optional API key for private versions (header)
    api_key: Optional API key for private versions (query, for links)
    if_none_match: Optional ETag(s) the client already holds

Returns:
    OpenAPI 3.1.0 specification in JSON format, or 304 when ``If-None-Match`` matches

Operation id: `get_version_openapi_spec_v1_schema__tenant_slug___project_slug___version_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_slug` | path | string | yes | URL-safe project slug within the tenant. |
| `version_slug` | path | string | yes | Semantic version label or version slug (for example ``1.0.0``). |
| `api_key` | query | string or null | no | API key for private versions (alternative to X-API-Key header) |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `If-None-Match` | header | string or null | no | An ETag from an earlier response; the answer is 304 with no body when the document has not changed. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The version's OpenAPI document. | `application/json` any |
| 304 | The document still matches an ETag sent in If-None-Match; no body. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 503 | The version is frozen and its stored document cannot be read. | — |

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
