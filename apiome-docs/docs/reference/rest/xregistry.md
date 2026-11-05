---
title: "Xregistry"
description: "REST endpoints tagged xregistry: 18 operations."
sidebar_position: 112
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.528.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `xregistry` · 18 operations

## `GET /v1/browse/tenants/{tenant_slug}/xregistry` {#xregistry-root-public-v1-browse-tenants-tenant-slug-xregistry-get}

**The xRegistry registry entity (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_root_public_v1_browse_tenants__tenant_slug__xregistry_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `inline` | query | string or null | no | `*` (any value) embeds every collection below the requested entity. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the xregistry registry entity (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/browse/tenants/{tenant_slug}/xregistry/capabilities` {#xregistry-capabilities-public-v1-browse-tenants-tenant-slug-xregistry-capabilities-get}

**The xRegistry server capabilities (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_capabilities_public_v1_browse_tenants__tenant_slug__xregistry_capabilities_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the xregistry server capabilities (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/browse/tenants/{tenant_slug}/xregistry/model` {#xregistry-model-public-v1-browse-tenants-tenant-slug-xregistry-model-get}

**The xRegistry model (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_model_public_v1_browse_tenants__tenant_slug__xregistry_model_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the xregistry model (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/browse/tenants/{tenant_slug}/xregistry/{groups}` {#xregistry-groups-public-v1-browse-tenants-tenant-slug-xregistry-groups-get}

**An xRegistry group collection (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_groups_public_v1_browse_tenants__tenant_slug__xregistry__groups__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `inline` | query | string or null | no | `*` (any value) embeds every collection below the requested entity. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry group collection (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/browse/tenants/{tenant_slug}/xregistry/{groups}/{gid}` {#xregistry-group-public-v1-browse-tenants-tenant-slug-xregistry-groups-gid-get}

**An xRegistry group (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_group_public_v1_browse_tenants__tenant_slug__xregistry__groups___gid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `inline` | query | string or null | no | `*` (any value) embeds every collection below the requested entity. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry group (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/browse/tenants/{tenant_slug}/xregistry/{groups}/{gid}/{resources}` {#xregistry-resources-public-v1-browse-tenants-tenant-slug-xregistry-groups-gid-resources-get}

**An xRegistry resource collection (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_resources_public_v1_browse_tenants__tenant_slug__xregistry__groups___gid___resources__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `resources` | path | string | yes | Path parameter identifying the resources segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry resource collection (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/browse/tenants/{tenant_slug}/xregistry/{groups}/{gid}/{resources}/{rid}` {#xregistry-resource-public-v1-browse-tenants-tenant-slug-xregistry-groups-gid-resources-rid-get}

**An xRegistry resource (append $details for its attributes) (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_resource_public_v1_browse_tenants__tenant_slug__xregistry__groups___gid___resources___rid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `resources` | path | string | yes | Path parameter identifying the resources segment. |
| `rid` | path | string | yes | Path parameter identifying the rid segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry resource (append $details for its attributes) (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/browse/tenants/{tenant_slug}/xregistry/{groups}/{gid}/{resources}/{rid}/versions` {#xregistry-versions-public-v1-browse-tenants-tenant-slug-xregistry-groups-gid-resources-rid-versions-get}

**An xRegistry resource's versions (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_versions_public_v1_browse_tenants__tenant_slug__xregistry__groups___gid___resources___rid__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `resources` | path | string | yes | Path parameter identifying the resources segment. |
| `rid` | path | string | yes | Path parameter identifying the rid segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry resource's versions (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/browse/tenants/{tenant_slug}/xregistry/{groups}/{gid}/{resources}/{rid}/versions/{vid}` {#xregistry-version-public-v1-browse-tenants-tenant-slug-xregistry-groups-gid-resources-rid-versions-vid-get}

**An xRegistry resource version (append $details for its attributes) (no auth)**

xRegistry core API, read-only, over the tenant's published public artifacts (MFX-34.2).

Operation id: `xregistry_version_public_v1_browse_tenants__tenant_slug__xregistry__groups___gid___resources___rid__versions__vid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `resources` | path | string | yes | Path parameter identifying the resources segment. |
| `rid` | path | string | yes | Path parameter identifying the rid segment. |
| `vid` | path | string | yes | Path parameter identifying the vid segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry resource version (append $details for its attributes) (no auth). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}` {#xregistry-root-member-v1-xregistry-tenant-slug-get}

**The xRegistry registry entity (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_root_member_v1_xregistry__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `inline` | query | string or null | no | `*` (any value) embeds every collection below the requested entity. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the xregistry registry entity (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}/capabilities` {#xregistry-capabilities-member-v1-xregistry-tenant-slug-capabilities-get}

**The xRegistry server capabilities (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_capabilities_member_v1_xregistry__tenant_slug__capabilities_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the xregistry server capabilities (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}/model` {#xregistry-model-member-v1-xregistry-tenant-slug-model-get}

**The xRegistry model (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_model_member_v1_xregistry__tenant_slug__model_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the xregistry model (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}/{groups}` {#xregistry-groups-member-v1-xregistry-tenant-slug-groups-get}

**An xRegistry group collection (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_groups_member_v1_xregistry__tenant_slug___groups__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `inline` | query | string or null | no | `*` (any value) embeds every collection below the requested entity. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry group collection (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}/{groups}/{gid}` {#xregistry-group-member-v1-xregistry-tenant-slug-groups-gid-get}

**An xRegistry group (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_group_member_v1_xregistry__tenant_slug___groups___gid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `inline` | query | string or null | no | `*` (any value) embeds every collection below the requested entity. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry group (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}/{groups}/{gid}/{resources}` {#xregistry-resources-member-v1-xregistry-tenant-slug-groups-gid-resources-get}

**An xRegistry resource collection (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_resources_member_v1_xregistry__tenant_slug___groups___gid___resources__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `resources` | path | string | yes | Path parameter identifying the resources segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry resource collection (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}/{groups}/{gid}/{resources}/{rid}` {#xregistry-resource-member-v1-xregistry-tenant-slug-groups-gid-resources-rid-get}

**An xRegistry resource (append $details for its attributes) (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_resource_member_v1_xregistry__tenant_slug___groups___gid___resources___rid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `resources` | path | string | yes | Path parameter identifying the resources segment. |
| `rid` | path | string | yes | Path parameter identifying the rid segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry resource (append $details for its attributes) (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}/{groups}/{gid}/{resources}/{rid}/versions` {#xregistry-versions-member-v1-xregistry-tenant-slug-groups-gid-resources-rid-versions-get}

**An xRegistry resource's versions (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_versions_member_v1_xregistry__tenant_slug___groups___gid___resources___rid__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `resources` | path | string | yes | Path parameter identifying the resources segment. |
| `rid` | path | string | yes | Path parameter identifying the rid segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry resource's versions (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## `GET /v1/xregistry/{tenant_slug}/{groups}/{gid}/{resources}/{rid}/versions/{vid}` {#xregistry-version-member-v1-xregistry-tenant-slug-groups-gid-resources-rid-versions-vid-get}

**An xRegistry resource version (append $details for its attributes) (members)**

xRegistry core API, read-only, over the tenant's published artifacts (members) (MFX-34.2).

Operation id: `xregistry_version_member_v1_xregistry__tenant_slug___groups___gid___resources___rid__versions__vid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `groups` | path | string | yes | Path parameter identifying the groups segment. |
| `gid` | path | string | yes | Path parameter identifying the gid segment. |
| `resources` | path | string | yes | Path parameter identifying the resources segment. |
| `rid` | path | string | yes | Path parameter identifying the rid segment. |
| `vid` | path | string | yes | Path parameter identifying the vid segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for an xregistry resource version (append $details for its attributes) (members). | — |
| 404 | Unknown tenant, or the path names no entity of the registry. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | Public export rate limit exceeded. | — |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
