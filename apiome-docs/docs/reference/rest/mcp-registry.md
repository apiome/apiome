---
title: "MCP registry"
description: "REST endpoints tagged mcp-registry: 8 operations."
sidebar_position: 49
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.315.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mcp-registry` · 8 operations

## `GET /registry/mcp/{tenant_slug}/v0.1/schema` {#get-registry-schema-version-registry-mcp-tenant-slug-v0-1-schema-get}

**Get Registry Schema Version**

Return the registry API and ``server.json`` schema versions this registry serves (CDG-4.1).

Anonymous and tenant-independent in content (the tenant segment only mirrors the other routes'
base URL), so a client can check compatibility before paging.

Args:
    tenant_slug: The tenant whose registry base URL was called (not looked up).

Returns:
    ``{"registryApiVersion", "serverSchema", "apiSpec": {"version", "commit"}}``.

Operation id: `get_registry_schema_version_registry_mcp__tenant_slug__v0_1_schema_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get registry schema version. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/mcp/{tenant_slug}/v0.1/servers` {#list-registry-servers-registry-mcp-tenant-slug-v0-1-servers-get}

**List Registry Servers**

List a tenant's cataloged MCP servers in the MCP Registry API v0.1 ``ServerList`` shape (AAU-5.3).

Pages are keyset-ordered by endpoint slug, so a cursor stays valid while servers are added.
Anonymous callers see only published, public endpoints; a credential of the tenant (session,
workspace API key, or MCP API key) also lists private and unpublished ones. An unknown tenant
is an empty list, so the route never confirms whether a tenant exists.

Args:
    tenant_slug: The tenant whose catalog to list.
    cursor: The previous page's ``metadata.nextCursor``.
    limit: Page size, 1–100.
    search: Case-insensitive substring of the server's name or slug.
    updated_since: Lower bound on each entry's ``updatedAt``.
    version: ``latest`` or an exact version; only current versions are served.
    authorization: Optional session JWT or MCP API key (``Bearer``).
    x_api_key: Optional workspace or MCP API key.

Returns:
    A ``ServerList`` (``servers`` + ``metadata.count`` / ``metadata.nextCursor``).

Operation id: `list_registry_servers_registry_mcp__tenant_slug__v0_1_servers_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `cursor` | query | string or null | no | Opaque cursor from `metadata.nextCursor`. |
| `limit` | query | integer | no | Page size (1–100, default 30). |
| `search` | query | string or null | no | Substring matched against server name and slug. |
| `updated_since` | query | string (date-time) or null | no | Only servers whose entry changed at or after this RFC 3339 instant. |
| `version` | query | string or null | no | `latest` (every served entry) or an exact version string. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list registry servers. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/mcp/{tenant_slug}/v0.1/servers/{server_name}/versions` {#list-registry-server-versions-registry-mcp-tenant-slug-v0-1-servers-server-name-versions-get}

**List Registry Server Versions**

List the served versions of one server — a ``ServerList`` holding its current version (AAU-5.3).

Args:
    tenant_slug: The tenant whose catalog to read.
    server_name: The URL-encoded server name (``apiome.<tenant>%2F<endpoint>``).
    authorization: Optional session JWT or MCP API key (``Bearer``).
    x_api_key: Optional workspace or MCP API key.

Returns:
    A ``ServerList`` with the server's current version; ``404`` when the caller cannot see it.

Operation id: `list_registry_server_versions_registry_mcp__tenant_slug__v0_1_servers__server_name__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `server_name` | path | string | yes | Path parameter identifying the server name segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list registry server versions. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/mcp/{tenant_slug}/v0.1/servers/{server_name}/versions/{version}` {#get-registry-server-version-registry-mcp-tenant-slug-v0-1-servers-server-name-versions-version-get}

**Get Registry Server Version**

Return one server version as a registry ``ServerResponse``, with an ``ETag`` (AAU-5.3).

Args:
    tenant_slug: The tenant whose catalog to read.
    server_name: The URL-encoded server name (``apiome.<tenant>%2F<endpoint>``).
    version: ``latest`` or the exact (URL-encoded) version string.
    authorization: Optional session JWT or MCP API key (``Bearer``).
    x_api_key: Optional workspace or MCP API key.
    if_none_match: Conditional-request header; a match answers ``304``.

Returns:
    The ``ServerResponse``; ``304`` when unchanged; ``404`` for an unknown or hidden server
    or a version that is not the one served.

Operation id: `get_registry_server_version_registry_mcp__tenant_slug__v0_1_servers__server_name__versions__version__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `server_name` | path | string | yes | Path parameter identifying the server name segment. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get registry server version. | `application/json` any |
| 304 | Not modified (the `If-None-Match` ETag still matches). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/mcp-registry/v0.1/schema` {#get-registry-schema-version-v1-tenants-tenant-slug-mcp-registry-v0-1-schema-get}

**Get Registry Schema Version**

Return the registry API and ``server.json`` schema versions this registry serves (CDG-4.1).

Anonymous and tenant-independent in content (the tenant segment only mirrors the other routes'
base URL), so a client can check compatibility before paging.

Args:
    tenant_slug: The tenant whose registry base URL was called (not looked up).

Returns:
    ``{"registryApiVersion", "serverSchema", "apiSpec": {"version", "commit"}}``.

Operation id: `get_registry_schema_version_v1_tenants__tenant_slug__mcp_registry_v0_1_schema_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get registry schema version. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/mcp-registry/v0.1/servers` {#list-registry-servers-v1-tenants-tenant-slug-mcp-registry-v0-1-servers-get}

**List Registry Servers**

List a tenant's cataloged MCP servers in the MCP Registry API v0.1 ``ServerList`` shape (AAU-5.3).

Pages are keyset-ordered by endpoint slug, so a cursor stays valid while servers are added.
Anonymous callers see only published, public endpoints; a credential of the tenant (session,
workspace API key, or MCP API key) also lists private and unpublished ones. An unknown tenant
is an empty list, so the route never confirms whether a tenant exists.

Args:
    tenant_slug: The tenant whose catalog to list.
    cursor: The previous page's ``metadata.nextCursor``.
    limit: Page size, 1–100.
    search: Case-insensitive substring of the server's name or slug.
    updated_since: Lower bound on each entry's ``updatedAt``.
    version: ``latest`` or an exact version; only current versions are served.
    authorization: Optional session JWT or MCP API key (``Bearer``).
    x_api_key: Optional workspace or MCP API key.

Returns:
    A ``ServerList`` (``servers`` + ``metadata.count`` / ``metadata.nextCursor``).

Operation id: `list_registry_servers_v1_tenants__tenant_slug__mcp_registry_v0_1_servers_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `cursor` | query | string or null | no | Opaque cursor from `metadata.nextCursor`. |
| `limit` | query | integer | no | Page size (1–100, default 30). |
| `search` | query | string or null | no | Substring matched against server name and slug. |
| `updated_since` | query | string (date-time) or null | no | Only servers whose entry changed at or after this RFC 3339 instant. |
| `version` | query | string or null | no | `latest` (every served entry) or an exact version string. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list registry servers. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/mcp-registry/v0.1/servers/{server_name}/versions` {#list-registry-server-versions-v1-tenants-tenant-slug-mcp-registry-v0-1-servers-server-name-versions-get}

**List Registry Server Versions**

List the served versions of one server — a ``ServerList`` holding its current version (AAU-5.3).

Args:
    tenant_slug: The tenant whose catalog to read.
    server_name: The URL-encoded server name (``apiome.<tenant>%2F<endpoint>``).
    authorization: Optional session JWT or MCP API key (``Bearer``).
    x_api_key: Optional workspace or MCP API key.

Returns:
    A ``ServerList`` with the server's current version; ``404`` when the caller cannot see it.

Operation id: `list_registry_server_versions_v1_tenants__tenant_slug__mcp_registry_v0_1_servers__server_name__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `server_name` | path | string | yes | Path parameter identifying the server name segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list registry server versions. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/mcp-registry/v0.1/servers/{server_name}/versions/{version}` {#get-registry-server-version-v1-tenants-tenant-slug-mcp-registry-v0-1-servers-server-name-versions-version-get}

**Get Registry Server Version**

Return one server version as a registry ``ServerResponse``, with an ``ETag`` (AAU-5.3).

Args:
    tenant_slug: The tenant whose catalog to read.
    server_name: The URL-encoded server name (``apiome.<tenant>%2F<endpoint>``).
    version: ``latest`` or the exact (URL-encoded) version string.
    authorization: Optional session JWT or MCP API key (``Bearer``).
    x_api_key: Optional workspace or MCP API key.
    if_none_match: Conditional-request header; a match answers ``304``.

Returns:
    The ``ServerResponse``; ``304`` when unchanged; ``404`` for an unknown or hidden server
    or a version that is not the one served.

Operation id: `get_registry_server_version_v1_tenants__tenant_slug__mcp_registry_v0_1_servers__server_name__versions__version__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `server_name` | path | string | yes | Path parameter identifying the server name segment. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get registry server version. | `application/json` any |
| 304 | Not modified (the `If-None-Match` ETag still matches). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
