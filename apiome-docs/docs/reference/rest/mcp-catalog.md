---
title: "MCP catalog"
description: "REST endpoints tagged mcp-catalog: 80 operations."
sidebar_position: 33
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mcp-catalog` · 80 operations

## `GET /mcp/badge/{tenant}/{slug}.svg` {#get-mcp-status-badge-mcp-badge-tenant-slug-svg-get}

**Get Mcp Status Badge**

Render a published endpoint's status badge as a cacheable SVG (MCAT-19.3).

Resolves the endpoint by ``tenant`` + ``slug`` through the public gate, folds the requested
``metric`` into a badge, and returns it as SVG with caching headers. A target that is not a
published, public endpoint (or does not exist) renders the neutral ``unknown`` badge with a
``200`` — never a ``404`` — so the response never reveals whether such an endpoint exists.

Args:
    tenant: The owning tenant's URL slug.
    slug: The endpoint's tenant-unique catalog slug (the ``.svg`` suffix is part of the route).
    metric: ``grade`` / ``health`` / ``version``; unrecognized values normalize to ``grade``.
    theme: ``light`` / ``dark`` label variant; unrecognized values normalize to ``light``.
    if_none_match: Standard conditional-request header; a match yields ``304 Not Modified``.

Returns:
    A ``Response`` carrying the SVG (``200``) — or an empty ``304`` — with ``ETag`` and
    ``Cache-Control`` set.

Operation id: `get_mcp_status_badge_mcp_badge__tenant___slug__svg_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `metric` | query | string | no | Which signal to render: 'grade' (A–F lint grade), 'health' (operational label), or 'version' (server-reported version). Anything else falls back to 'grade'. |
| `theme` | query | string | no | Label variant: 'light' (default) or 'dark' — tones the label to suit the page. |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp status badge. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /mcp/feed/{tenant}` {#get-mcp-catalog-change-feed-mcp-feed-tenant-get}

**Get Mcp Catalog Change Feed**

Render a tenant's whole **published catalog** change feed (MCAT-19.4).

Renders recent changes across every published, public endpoint the tenant owns — a catalog-wide
activity stream, most recent first — as RSS/Atom/JSON. Private and unpublished endpoints are
excluded in SQL, so their changes never appear. An unknown or fully-private catalog renders an
empty feed with a ``200``. Breaking changes are flagged in every entry.

Args:
    request: The incoming request (used only to build the feed's self/home URLs).
    tenant: The catalog's tenant slug.
    format: ``rss`` / ``atom`` / ``json``; anything else is ``400``.
    if_none_match: Standard conditional-request header; a match yields ``304 Not Modified``.

Returns:
    A ``Response`` carrying the feed (``200``) — or an empty ``304`` — with ``ETag`` and
    ``Cache-Control`` set.

Operation id: `get_mcp_catalog_change_feed_mcp_feed__tenant__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `format` | query | string | no | Feed format: 'rss' (default), 'atom', or 'json' (JSON Feed 1.1). |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp catalog change feed. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /mcp/feed/{tenant}/{slug}` {#get-mcp-endpoint-change-feed-mcp-feed-tenant-slug-get}

**Get Mcp Endpoint Change Feed**

Render one **published** endpoint's change feed (MCAT-19.4).

Resolves the endpoint by ``tenant`` + ``slug`` through the public gate and renders its recent
change history (newest snapshot first) as RSS/Atom/JSON. A target that is not a published, public
endpoint (or does not exist) renders an identical **empty** feed with a ``200`` — never a
``404`` — so the response never reveals whether such an endpoint exists, and a private endpoint's
changes are never disclosed. Breaking changes are flagged in every entry.

Args:
    request: The incoming request (used only to build the feed's self/home URLs).
    tenant: The owning tenant's URL slug.
    slug: The endpoint's tenant-unique catalog slug.
    format: ``rss`` / ``atom`` / ``json``; anything else is ``400``.
    if_none_match: Standard conditional-request header; a match yields ``304 Not Modified``.

Returns:
    A ``Response`` carrying the feed (``200``) — or an empty ``304`` — with ``ETag`` and
    ``Cache-Control`` set.

Operation id: `get_mcp_endpoint_change_feed_mcp_feed__tenant___slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `format` | query | string | no | Feed format: 'rss' (default), 'atom', or 'json' (JSON Feed 1.1). |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint change feed. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/conformance/rules` {#get-mcp-conformance-rules-v1-mcp-conformance-rules-get}

**Get Mcp Conformance Rules**

Return the MCP conformance rule catalog and the profiles that select from it.

Every rule cites the MCP specification revision it derives from and a resolvable source
reference, so any finding can be traced back to a normative statement (CLX-3.1 AC-1).

The catalog is **registry-level** — it describes the engine, not any one endpoint — so it
authenticates with :func:`validate_session_credentials` rather than
:func:`validate_authentication`. That is not interchangeable: ``validate_authentication``
takes ``tenant_slug`` as its first parameter, which FastAPI resolves from the *path* on every
tenant-scoped route. This route has no ``{tenant_slug}`` segment, so it would instead be
resolved as a **required query parameter** — making the catalog return 422 unless the caller
invented a slug, and then authenticating against whatever they invented. The same reasoning is
why ``GET /v1/lint/rules`` uses ``validate_session_credentials``.

Operation id: `get_mcp_conformance_rules_v1_mcp_conformance_rules_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `profile` | query | string or null | no | Restrict the catalog to the rules this profile evaluates. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp conformance rules. | `application/json` [`McpConformanceRulesResponse`](#schema-mcpconformancerulesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/lint/rules` {#get-mcp-surface-lint-rules-v1-mcp-lint-rules-get}

**Get Mcp Surface Lint Rules**

Return the MCP surface-lint rule catalog with CLX-4.3 transparency metadata.

Registry-level (describes the engine, not any endpoint). Blocking rules carry
reference, remediation, false-positive guidance, fixture id, and scan modes.

Operation id: `get_mcp_surface_lint_rules_v1_mcp_lint_rules_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp surface lint rules. | `application/json` [`McpSurfaceLintRulesResponse`](#schema-mcpsurfacelintrulesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/trust-posture/rules` {#get-mcp-trust-posture-rules-v1-mcp-trust-posture-rules-get}

**Get Mcp Trust Posture Rules**

Return the trust-posture rule catalog, the profiles, and the OWASP MCP risk catalog.

Every rule declares which evidence lane it reads, which OWASP MCP risk it maps to, and what it
needs to run at all — so a consumer can see, before running anything, exactly what the scan can
and cannot tell them.

Registry-level (describes the engine, not any endpoint), so it authenticates with
:func:`validate_session_credentials` for the same reason ``/conformance/rules`` and
``/v1/lint/rules`` do: it has no ``{tenant_slug}`` path segment.

Operation id: `get_mcp_trust_posture_rules_v1_mcp_trust_posture_rules_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `profile` | query | string or null | no | Restrict the catalog to the rules this profile evaluates. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp trust posture rules. | `application/json` [`McpPostureRulesResponse`](#schema-mcpposturerulesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/browse` {#browse-mcp-endpoints-v1-mcp-tenant-slug-browse-get}

**Browse Mcp Endpoints**

Private browse: the caller's cataloged endpoints grouped by host (V2-MCP-23.1 / MCAT-9.1).

The browse-list half of the private catalog view (the detail half reuses the existing
endpoint and version-detail reads). Returns every live endpoint the caller's tenant owns,
bucketed by the host its URL points at, each carrying its current snapshot's capability
counts (tools/resources/resource templates/prompts), quality score/grade, and
last-discovered time. Like every catalog route, scoping comes from the token's
``tenant_id`` — never the URL slug — so a tenant only ever browses its own catalog.

Operation id: `browse_mcp_endpoints_v1_mcp__tenant_slug__browse_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for browse mcp endpoints. | `application/json` [`McpBrowseResponse`](#schema-mcpbrowseresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/capabilities` {#list-mcp-capability-directory-v1-mcp-tenant-slug-capabilities-get}

**List Mcp Capability Directory**

Capability directory — paginated index of every live tool/resource/prompt (MCAT-21.4).

A browsable "what can be done" index across the caller's catalog: every capability item from
each endpoint's *current* snapshot, with enough owning-server context to link back without a
second read. ``name`` matches item name or title case-insensitively (substring); ``type``,
``endpoint_id``, and the usual host/category/grade/visibility filters compose (ANDed). Like
every catalog route, scoping comes from the token's ``tenant_id`` — never the URL slug.

Operation id: `list_mcp_capability_directory_v1_mcp__tenant_slug__capabilities_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `name` | query | string or null | no | Case-insensitive substring match on capability name or title. |
| `type` | query | enum `"tool"`, `"resource"`, `"resource_template"`, `"prompt"` or null | no | Restrict to one capability kind (tool/resource/resource_template/prompt). |
| `endpoint_id` | query | string or null | no | Restrict to capabilities from one cataloged server. |
| `host` | query | string or null | no | Filter to endpoints on this host (case-insensitive). |
| `category` | query | string or null | no | Filter to endpoints in this category (case-insensitive). |
| `grade` | query | string or null | no | Filter to endpoints whose current snapshot earned this A-F grade. |
| `visibility` | query | enum `"public"`, `"private"` or null | no | Filter to 'private' or 'public' endpoints within the caller's own catalog. |
| `sort` | query | enum `"server"`, `"name"`, `"type"` | no | Sort column: server (default), name, or type. |
| `direction` | query | enum `"asc"`, `"desc"` | no | Sort direction: asc (default) or desc. |
| `limit` | query | integer | no | Maximum items to return. |
| `offset` | query | integer | no | Items to skip (pagination). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp capability directory. | `application/json` [`McpCapabilityDirectoryResponse`](#schema-mcpcapabilitydirectoryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/capabilities/search` {#cross-server-capability-search-v1-mcp-tenant-slug-capabilities-search-get}

**Cross Server Capability Search**

Cross-server capability search — keyword + semantic, grouped by owning server (MCAT-21.2).

Answers "which servers offer a capability like X?" across the caller's catalog. **Keyword**
matches use the V127 capability-item ``tsvector`` GIN index (``websearch_to_tsquery``). When
``APIOME_MCP_SIMILARITY_EMBEDDINGS_ENABLED`` is on and the Ollama embedding service is
reachable, **semantic** matches also rank stored per-item embeddings (V149) by cosine
similarity. Each distinct capability appears once with ``match_source`` ``keyword``,
``semantic``, or ``both``.

**Ranking** (MCAT-9.7 / MCAT-21.2): per-item ``relevance`` is ``max(fts_rank,
cosine_similarity)``; server groups sort by their best item relevance, then letter grade (A
first, ungraded last), then score, then endpoint name; capabilities within a group sort by
relevance desc, then ordinal. ``visibility`` and tenant scoping are enforced like the flat
search route — only the caller's own catalog is searched. An empty or whitespace-only query, or
a query that matches nothing, returns ``groups: []`` (not an error).

Operation id: `cross_server_capability_search_v1_mcp__tenant_slug__capabilities_search_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `q` | query | string | yes | Free-text query (websearch syntax for keyword matches; also embedded for semantic). |
| `scope` | query | enum `"tool"`, `"resource"`, `"resource_template"`, `"prompt"`, `"endpoint"` or null | no | Restrict to one capability kind (tool/resource/resource_template/prompt). Omit to search all capability kinds. |
| `host` | query | string or null | no | Filter to endpoints on this host (case-insensitive). |
| `category` | query | string or null | no | Filter to endpoints in this category (case-insensitive). |
| `grade` | query | string or null | no | Filter to endpoints whose current snapshot earned this A-F grade. |
| `visibility` | query | enum `"public"`, `"private"` or null | no | Filter to 'private' or 'public' endpoints within the caller's own catalog. |
| `limit` | query | integer | no | Maximum server groups to return. |
| `offset` | query | integer | no | Server groups to skip (pagination). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for cross server capability search. | `application/json` [`McpCrossServerCapabilitySearchResponse`](#schema-mcpcrossservercapabilitysearchresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/collections` {#list-mcp-collections-v1-mcp-tenant-slug-collections-get}

**List Mcp Collections**

List curated collections for the caller's tenant.

Operation id: `list_mcp_collections_v1_mcp__tenant_slug__collections_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp collections. | `application/json` [`McpCollectionListResponse`](#schema-mcpcollectionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/collections` {#create-mcp-collection-v1-mcp-tenant-slug-collections-post}

**Create Mcp Collection**

Create a curated collection, optionally with initial members.

Operation id: `create_mcp_collection_v1_mcp__tenant_slug__collections_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create mcp collection.

- `application/json` — [`McpCollectionCreate`](#schema-mcpcollectioncreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create mcp collection. | `application/json` [`McpCollectionOut`](#schema-mcpcollectionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/collections/{collection_id}` {#get-mcp-collection-v1-mcp-tenant-slug-collections-collection-id-get}

**Get Mcp Collection**

Fetch one curated collection with its members.

Operation id: `get_mcp_collection_v1_mcp__tenant_slug__collections__collection_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `collection_id` | path | string (uuid) | yes | Path parameter identifying the collection id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp collection. | `application/json` [`McpCollectionOut`](#schema-mcpcollectionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/mcp/{tenant_slug}/collections/{collection_id}` {#update-mcp-collection-v1-mcp-tenant-slug-collections-collection-id-patch}

**Update Mcp Collection**

Rename, describe, or publish/unpublish a curated collection.

Operation id: `update_mcp_collection_v1_mcp__tenant_slug__collections__collection_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `collection_id` | path | string (uuid) | yes | Path parameter identifying the collection id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update mcp collection.

- `application/json` — [`McpCollectionUpdate`](#schema-mcpcollectionupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update mcp collection. | `application/json` [`McpCollectionOut`](#schema-mcpcollectionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mcp/{tenant_slug}/collections/{collection_id}` {#delete-mcp-collection-v1-mcp-tenant-slug-collections-collection-id-delete}

**Delete Mcp Collection**

Delete a curated collection.

Operation id: `delete_mcp_collection_v1_mcp__tenant_slug__collections__collection_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `collection_id` | path | string (uuid) | yes | Path parameter identifying the collection id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete mcp collection. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mcp/{tenant_slug}/collections/{collection_id}/members` {#replace-mcp-collection-members-v1-mcp-tenant-slug-collections-collection-id-members-put}

**Replace Mcp Collection Members**

Replace the full membership list for a collection.

Operation id: `replace_mcp_collection_members_v1_mcp__tenant_slug__collections__collection_id__members_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `collection_id` | path | string (uuid) | yes | Path parameter identifying the collection id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace mcp collection members.

- `application/json` — [`McpCollectionMembersReplace`](#schema-mcpcollectionmembersreplace)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace mcp collection members. | `application/json` [`McpCollectionOut`](#schema-mcpcollectionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/collections/{collection_id}/members` {#add-mcp-collection-members-v1-mcp-tenant-slug-collections-collection-id-members-post}

**Add Mcp Collection Members**

Append endpoints to a collection.

Operation id: `add_mcp_collection_members_v1_mcp__tenant_slug__collections__collection_id__members_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `collection_id` | path | string (uuid) | yes | Path parameter identifying the collection id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for add mcp collection members.

- `application/json` — [`McpCollectionMembersAdd`](#schema-mcpcollectionmembersadd)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for add mcp collection members. | `application/json` [`McpCollectionOut`](#schema-mcpcollectionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mcp/{tenant_slug}/collections/{collection_id}/members/{endpoint_id}` {#remove-mcp-collection-member-v1-mcp-tenant-slug-collections-collection-id-members-endpoint-id-delete}

**Remove Mcp Collection Member**

Remove one endpoint from a collection.

Operation id: `remove_mcp_collection_member_v1_mcp__tenant_slug__collections__collection_id__members__endpoint_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `collection_id` | path | string (uuid) | yes | Path parameter identifying the collection id segment. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove mcp collection member. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/data-quality/duplicates` {#list-mcp-duplicate-report-v1-mcp-tenant-slug-data-quality-duplicates-get}

**List Mcp Duplicate Report**

Advisory duplicate review list for the caller's catalog (V2-MCP-36.1 / MCAT-22.1).

Flags endpoints that share a normalized ``endpoint_url``, the same network host (when
fingerprints do not prove they are distinct), or an identical current ``surface_fingerprint``.
Published endpoints in other tenants that match the same keys are returned as cross-tenant hints.
The report is advisory only — nothing is merged automatically.

Operation id: `list_mcp_duplicate_report_v1_mcp__tenant_slug__data_quality_duplicates_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp duplicate report. | `application/json` [`McpDuplicateReportResponse`](#schema-mcpduplicatereportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/data-quality/freshness` {#list-mcp-freshness-report-v1-mcp-tenant-slug-data-quality-freshness-get}

**List Mcp Freshness Report**

Freshness report for the caller's catalog (V2-MCP-36.2 / MCAT-22.2).

Flags endpoints that are overdue for re-discovery, in failure backoff/quarantine, or on a
failing streak. Each flagged row carries a ``last_known_good_at`` anchor from the current
snapshot (when one exists) plus the live cadence/backoff fields from ``mcp_endpoints``.
Healthy, in-cadence endpoints are omitted.

Operation id: `list_mcp_freshness_report_v1_mcp__tenant_slug__data_quality_freshness_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp freshness report. | `application/json` [`McpFreshnessReportResponse`](#schema-mcpfreshnessreportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/digest/config` {#get-mcp-digest-config-v1-mcp-tenant-slug-digest-config-get}

**Get Mcp Digest Config**

Read the calling tenant's scheduled catalog digest configuration (MCAT-19.5).

Returns the default disabled configuration when the tenant has never opted in (never a 404).

Args:
    tenant_slug: The tenant URL slug (validated by the auth dependency; scoping comes from the
        token).
    auth_data: The authenticated principal; ``tenant_id`` scopes the read.

Returns:
    The tenant's digest configuration.

Operation id: `get_mcp_digest_config_v1_mcp__tenant_slug__digest_config_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp digest config. | `application/json` [`McpDigestConfigResponse`](#schema-mcpdigestconfigresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mcp/{tenant_slug}/digest/config` {#put-mcp-digest-config-v1-mcp-tenant-slug-digest-config-put}

**Put Mcp Digest Config**

Create or update the calling tenant's digest configuration (MCAT-19.5).

Upserts the tenant's opt-in, cadence and empty-window policy. The window anchor
(``last_digest_at``) is not reset, so changing cadence mid-stream does not lose the current
window.

Args:
    tenant_slug: The tenant URL slug (validated by the auth dependency).
    body: The new digest preferences.
    auth_data: The authenticated principal; ``tenant_id`` scopes the write.

Returns:
    The stored digest configuration.

Operation id: `put_mcp_digest_config_v1_mcp__tenant_slug__digest_config_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put mcp digest config.

- `application/json` — [`McpDigestConfigUpdate`](#schema-mcpdigestconfigupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put mcp digest config. | `application/json` [`McpDigestConfigResponse`](#schema-mcpdigestconfigresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/digest/preview` {#preview-mcp-digest-v1-mcp-tenant-slug-digest-preview-post}

**Preview Mcp Digest**

Compile and return the tenant's digest for the current window without sending it (MCAT-19.5).

A dry run over real catalog data: the window ends now and spans one effective cadence back (the
per-tenant override, or the global default). Nothing is delivered and the anchor is not advanced,
so an operator can preview exactly what the next scheduled digest would contain. Respects tenant
scoping — only the caller's own catalog is read.

Args:
    tenant_slug: The tenant URL slug (validated by the auth dependency; also used as the digest's
        subject slug).
    auth_data: The authenticated principal; ``tenant_id`` scopes the reads.

Returns:
    The digest payload (same JSON shape the scheduled delivery would carry).

Operation id: `preview_mcp_digest_v1_mcp__tenant_slug__digest_preview_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview mcp digest. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints` {#list-mcp-endpoints-v1-mcp-tenant-slug-endpoints-get}

**List Mcp Endpoints**

List every catalog endpoint owned by the caller's tenant (newest first).

Operation id: `list_mcp_endpoints_v1_mcp__tenant_slug__endpoints_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp endpoints. | `application/json` [`McpEndpointListResponse`](#schema-mcpendpointlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints` {#create-mcp-endpoint-v1-mcp-tenant-slug-endpoints-post}

**Create Mcp Endpoint**

Register a new MCP endpoint in the tenant's catalog.

The slug is taken from ``body.slug`` when supplied, otherwise derived from the
name; either way it is uniquified within the tenant by the DB layer. Returns
the created endpoint with ``201``.

Operation id: `create_mcp_endpoint_v1_mcp__tenant_slug__endpoints_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create mcp endpoint.

- `application/json` — [`McpEndpointCreate`](#schema-mcpendpointcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create mcp endpoint. | `application/json` [`McpEndpointResponse`](#schema-mcpendpointresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}` {#get-mcp-endpoint-v1-mcp-tenant-slug-endpoints-endpoint-id-get}

**Get Mcp Endpoint**

Fetch a single catalog endpoint by id; 404 when it is not the tenant's.

Operation id: `get_mcp_endpoint_v1_mcp__tenant_slug__endpoints__endpoint_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint. | `application/json` [`McpEndpointResponse`](#schema-mcpendpointresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}` {#update-mcp-endpoint-v1-mcp-tenant-slug-endpoints-endpoint-id-patch}

**Update Mcp Endpoint**

Patch mutable fields on a catalog endpoint; 404 when not the tenant's.

Only the fields present in the request body are applied (the slug is not
patchable). An empty body is a no-op that returns the current record.

Operation id: `update_mcp_endpoint_v1_mcp__tenant_slug__endpoints__endpoint_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update mcp endpoint.

- `application/json` — [`McpEndpointUpdate`](#schema-mcpendpointupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update mcp endpoint. | `application/json` [`McpEndpointResponse`](#schema-mcpendpointresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}` {#delete-mcp-endpoint-v1-mcp-tenant-slug-endpoints-endpoint-id-delete}

**Delete Mcp Endpoint**

Retire a catalog endpoint and purge its child data (V2-MCP-17.5 / MCAT-3.5).

The endpoint is soft-deleted (stamped ``deleted_at``, disabled) so it vanishes
from browse/list/get and is skipped by the discovery sweep, while its slug stays
reserved. Its children are hard-deleted: the stored credentials (the security-
critical purge), every discovery job, and every version snapshot — whose
capability items, change logs and scores cascade away with it. Returns a
teardown summary, or ``404`` when the endpoint is not the caller's tenant's
(or was already deleted).

Operation id: `delete_mcp_endpoint_v1_mcp__tenant_slug__endpoints__endpoint_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete mcp endpoint. | `application/json` [`McpEndpointDeleteResponse`](#schema-mcpendpointdeleteresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/credentials` {#get-mcp-endpoint-credentials-v1-mcp-tenant-slug-endpoints-endpoint-id-credentials-get}

**Get Mcp Endpoint Credentials**

Return an endpoint's **redacted** credential status (never the secret itself).

Reports which ``auth_type`` is configured, whether a sealed secret is present (with a fixed
mask placeholder when it is), the sealing ``key_version``, non-secret ``oauth_metadata`` and
timestamps. An endpoint with no credential reads as the anonymous ``none`` status. 404 when the
endpoint is not the caller's tenant's.

Operation id: `get_mcp_endpoint_credentials_v1_mcp__tenant_slug__endpoints__endpoint_id__credentials_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint credentials. | `application/json` [`McpCredentialStatusResponse`](#schema-mcpcredentialstatusresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/credentials` {#set-mcp-endpoint-credentials-v1-mcp-tenant-slug-endpoints-endpoint-id-credentials-put}

**Set Mcp Endpoint Credentials**

Set or replace an endpoint's outbound credential, sealing the secret before storage.

The plaintext ``payload`` is validated against its ``auth_type`` (the same auth-type model used
to build request headers, so a malformed or injection-bearing secret is rejected here), sealed
via envelope encryption (MCAT-6.2), and upserted as ciphertext. The response is the **redacted**
status — the secret is never echoed back. Returns ``404`` when the endpoint is not the caller's
tenant's, ``422`` when the payload does not match its ``auth_type``, and ``503`` when credential
encryption is not configured (a secret cannot be stored safely without it).

Operation id: `set_mcp_endpoint_credentials_v1_mcp__tenant_slug__endpoints__endpoint_id__credentials_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set mcp endpoint credentials.

- `application/json` — [`McpCredentialUpsert`](#schema-mcpcredentialupsert)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set mcp endpoint credentials. | `application/json` [`McpCredentialStatusResponse`](#schema-mcpcredentialstatusresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/credentials` {#clear-mcp-endpoint-credentials-v1-mcp-tenant-slug-endpoints-endpoint-id-credentials-delete}

**Clear Mcp Endpoint Credentials**

Clear an endpoint's stored credential, removing the row (idempotent).

Returns ``removed=True`` when a credential was deleted and ``removed=False`` when the endpoint
had none — both are ``200``. 404 when the endpoint is not the caller's tenant's.

Operation id: `clear_mcp_endpoint_credentials_v1_mcp__tenant_slug__endpoints__endpoint_id__credentials_delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for clear mcp endpoint credentials. | `application/json` [`McpCredentialDeleteResponse`](#schema-mcpcredentialdeleteresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/discover` {#list-mcp-discovery-jobs-v1-mcp-tenant-slug-endpoints-endpoint-id-discover-get}

**List Mcp Discovery Jobs**

List an endpoint's discovery jobs, newest first; 404 when not the tenant's endpoint.

Operation id: `list_mcp_discovery_jobs_v1_mcp__tenant_slug__endpoints__endpoint_id__discover_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp discovery jobs. | `application/json` [`McpDiscoveryJobListResponse`](#schema-mcpdiscoveryjoblistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/discover` {#discover-mcp-endpoint-v1-mcp-tenant-slug-endpoints-endpoint-id-discover-post}

**Discover Mcp Endpoint**

Kick off a discovery run for an endpoint and return its job (submit→poll).

Creates a ``manual`` discovery job and starts the run out of band: the MCP client
connects, handshakes, paginates the capability listings, normalizes them, and persists a
new version when the surface changed (version 1 on first run). Poll the returned job's
``GET .../discover/{job_id}`` for the terminal state and the produced ``version_id``.

Concurrent discover requests on the same endpoint are de-duplicated: when a run is already
queued/running, that existing job is returned (with ``deduplicated=True``) and no second
run starts. Returns ``404`` when the endpoint is not the caller's tenant's.

Operation id: `discover_mcp_endpoint_v1_mcp__tenant_slug__endpoints__endpoint_id__discover_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for discover mcp endpoint. | `application/json` [`McpDiscoveryJobResponse`](#schema-mcpdiscoveryjobresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/discover/{job_id}` {#get-mcp-discovery-job-v1-mcp-tenant-slug-endpoints-endpoint-id-discover-job-id-get}

**Get Mcp Discovery Job**

Poll one discovery job's state/result; 404 when it is not this tenant+endpoint's job.

Operation id: `get_mcp_discovery_job_v1_mcp__tenant_slug__endpoints__endpoint_id__discover__job_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `job_id` | path | string (uuid) | yes | Asynchronous job identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp discovery job. | `application/json` [`McpDiscoveryJobResponse`](#schema-mcpdiscoveryjobresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/digest` {#get-mcp-endpoint-digest-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-digest-get}

**Get Mcp Endpoint Digest**

Return the caller's "changed since last view" digest for the endpoint (MCAT-16.5).

Compares the version the caller last saw (their per-user ``mcp_endpoint_views`` seen-marker)
against the endpoint's current version and summarizes the delta and its breaking severity:
``new_to_you`` on a first visit (or when the last-seen snapshot has been pruned),
``has_changes`` with the classified diff when the surface moved on since, or neither flag when
the caller is already up to date. A GET stays read-only — it does **not** advance the marker
(``POST …/views`` does), so the digest reflects the pre-advance state. An endpoint that was
never discovered yields a digest with no changes (a ``200``). Returns ``404`` when the endpoint
is not the caller's tenant's.

Operation id: `get_mcp_endpoint_digest_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_digest_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint digest. | `application/json` [`McpEndpointDigestResponse`](#schema-mcpendpointdigestresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/evolution` {#get-mcp-endpoint-insight-evolution-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-evolution-get}

**Get Mcp Endpoint Insight Evolution**

Return the endpoint's per-version evolution series (oldest snapshot first).

One point per discovery snapshot carrying its capability ``type_counts``, quality
``score`` / ``grade``, the ``change_counts`` (churn by direction) it introduced, and the
``severity_counts`` (V2-MCP-30.3) classifying that churn as breaking / additive / review —
the time series a "how has this server evolved" chart plots, with breaking-change markers.
An endpoint that was never discovered returns an empty ``series`` (a ``200`` with ``[]``,
never a ``500``). Returns ``404`` when the endpoint is not the caller's tenant's.

Operation id: `get_mcp_endpoint_insight_evolution_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_evolution_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint insight evolution. | `application/json` [`McpInsightEvolutionResponse`](#schema-mcpinsightevolutionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/graph` {#get-mcp-endpoint-insight-graph-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-graph-get}

**Get Mcp Endpoint Insight Graph**

Return the capability relationship graph for a version snapshot (defaults to the current one).

Resolves the target snapshot — the supplied ``version_id`` or, when omitted, the endpoint's
``current_version_id`` — reconstructs its normalized surface from the persisted rows, and runs
the deterministic :func:`app.mcp_capability_graph.compute_capability_graph` inference (one node
per capability plus edges for prompts that name a tool, tools that reference a resource URI, and
items that share a schema type) the 15.2 "Capability relationship graph" panel renders. Edges are
emitted only on concrete signals (precision over recall); isolated nodes are still returned. A GET
stays read-only. Returns ``404`` when the endpoint — or the named version under it — is not the
caller's tenant's, or when no ``version_id`` was given and the endpoint has never been discovered.

Operation id: `get_mcp_endpoint_insight_graph_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_graph_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | query | string (uuid) or null | no | Which snapshot to map; omit to map the endpoint's current surface. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint insight graph. | `application/json` [`McpInsightGraphResponse`](#schema-mcpinsightgraphresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/percentile` {#get-mcp-endpoint-insight-percentile-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-percentile-get}

**Get Mcp Endpoint Insight Percentile**

Return the endpoint's peer percentile & category ranking across four axes (MCAT-18.3).

"Is this a good weather server?" needs a *peer baseline*, not an absolute grade. This ranks the
endpoint against the other live endpoints in its catalog **category** — the *cohort* — on four
axes: **grade** (the stored lint score), **safety** (annotation coverage crossed with the
destructive/auth posture), **documentation** (documentation coverage), and **latency** (p95
responsiveness). Each axis reuses the same derivation the endpoint's own trust profile shows, so a
rank never disagrees with the numbers on its Insight tab, and each carries the server's percentile
(share of the cohort at or below it), its rank, and the "top N%" the UI badges render.

A blank/uncategorized endpoint is ranked within the uncategorized cohort. A **single-member**
category is handled — the sole server is trivially the category leader. Any axis the endpoint has
not measured (never scored, no tools, never tested) is an explicit *gap*, never a zero, so an
undiscovered endpoint yields a coherent all-gap profile (a ``200``, never a ``500``). Scoping comes
from the token's tenant, so the cohort never spans another tenant's catalog; returns ``404`` when
the endpoint is not the caller's tenant's. A GET stays read-only, recomputed live as the catalog
grows.

Operation id: `get_mcp_endpoint_insight_percentile_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_percentile_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint insight percentile. | `application/json` [`McpInsightPercentileResponse`](#schema-mcpinsightpercentileresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/reliability` {#get-mcp-endpoint-insight-reliability-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-reliability-get}

**Get Mcp Endpoint Insight Reliability**

Return the endpoint's discovery and test-invocation reliability aggregates + health timeline.

``discovery`` folds ``mcp_discovery_jobs`` into per-state tallies, a success rate over terminal
jobs, and run-latency statistics; ``invocation`` folds ``mcp_test_invocations`` into call/error
tallies, an error rate, and latency percentiles (p50/p95/p99). ``health`` (MCAT-17.1) adds the
recent per-job outcome timeline (newest-first, capped at the timeline window), a windowed
availability percentage, and the endpoint's live quarantine / backoff state. ``tools``
(MCAT-17.2) adds a per-tool latency & error-rate breakdown over the recent
:data:`TOOL_LATENCY_WINDOW_DAYS`-day window — p50/p95/p99 and error rate per tool, a latency
distribution, and the endpoint-wide totals. An endpoint with no discovery or test history returns
zero counts, an empty timeline, an empty tool list, and empty (``None``) statistics — a ``200``,
never a ``500``. Returns ``404`` when the endpoint is not the caller's tenant's.

Operation id: `get_mcp_endpoint_insight_reliability_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_reliability_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint insight reliability. | `application/json` [`McpInsightReliabilityResponse`](#schema-mcpinsightreliabilityresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/similar` {#get-mcp-endpoint-similar-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-similar-get}

**Get Mcp Endpoint Similar**

Return "servers like this one" from capability overlap + optional semantic embeddings (MCAT-18.4).

Ranks the caller's other live endpoints against this one by two independent signals. **overlap** —
always present — is the capability-name Jaccard overlap: peers sharing this server's tool / resource /
prompt names, ranked by set-overlap, with the shared names surfaced (a server with nothing in common
is not returned). **semantic** is a cosine nearest-neighbour over a per-snapshot capability embedding
and is populated only when ``embeddings_enabled`` — the feature flag is on *and* both this endpoint
and at least one peer carry a backfilled embedding. When embeddings are disabled or unbackfilled,
``semantic`` is empty and the endpoint page falls back to overlap-only (the "gracefully no-ops if
embeddings are disabled" acceptance criterion). A never-discovered endpoint has no capabilities, so
both lists are empty (a ``200``, never a ``500``). Scoping comes from the token's tenant, so neighbours
never span another tenant's catalog; returns ``404`` when the endpoint is not the caller's tenant's. A
GET stays read-only, recomputed live as the catalog grows.

Operation id: `get_mcp_endpoint_similar_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_similar_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint similar. | `application/json` [`McpSimilarServersResponse`](#schema-mcpsimilarserversresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/similar/reindex` {#reindex-mcp-endpoint-similar-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-similar-reindex-post}

**Reindex Mcp Endpoint Similar**

(Re)compute and store this endpoint's current-snapshot capability embedding (MCAT-18.4).

The backfill step behind the semantic similarity signal: it derives the deterministic capability text
of the endpoint's current surface (its tool/resource/prompt names + descriptions), embeds it via the
Ollama embedding service, and stores the vector on the snapshot (V143) so the ``insight/similar``
semantic list can find it. Every non-success is a labelled no-op, not an error (always a ``200``): the
feature flag being off, the endpoint having no discovered surface or no capabilities to embed, the
embedding service being unreachable, or pgvector being unavailable each return ``reindexed=false`` with
a ``detail`` explaining why. Returns ``404`` when the endpoint is not the caller's tenant's.

Operation id: `reindex_mcp_endpoint_similar_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_similar_reindex_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for reindex mcp endpoint similar. | `application/json` [`McpSimilarReindexResponse`](#schema-mcpsimilarreindexresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/summary` {#get-mcp-endpoint-summary-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-summary-get}

**Get Mcp Endpoint Summary**

Return the endpoint's usage examples and its cached AI digest, if any (MCAT-18.5).

Two things in one read. ``examples`` — one **schema-derived example call per tool** of the current
surface — is always present: it is synthesized deterministically from each tool's ``input_schema``
with no model call and no tool execution, so it needs neither the feature flag nor an API key. The
AI-written ``digest`` ("this server lets you …") is returned only when one has already been generated
and cached for the current ``surface_fingerprint`` (``null`` otherwise); ``ai_digest_enabled`` tells
the UI whether the gated ``…/insight/summary/generate`` action is available. Because the cache is keyed
on the fingerprint, a surface change automatically presents as "no digest yet" until regenerated. A
never-discovered endpoint yields empty ``examples`` and a ``null`` digest (a ``200``, never a ``500``).
Scoping comes from the token's tenant; ``404`` when the endpoint is not the caller's tenant's. Read-only.

Operation id: `get_mcp_endpoint_summary_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_summary_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint summary. | `application/json` [`McpServerDigestResponse`](#schema-mcpserverdigestresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/summary/generate` {#generate-mcp-endpoint-summary-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-summary-generate-post}

**Generate Mcp Endpoint Summary**

(Re)generate and cache the endpoint's AI digest for its current surface (MCAT-18.5).

The gated AI step. It (re)computes the schema-derived example calls (always), and — when
``APIOME_MCP_AI_DIGEST_ENABLED`` is on and an API key is configured — writes a short natural-language
digest of the server via the Claude API and caches it under the current ``surface_fingerprint`` so it
is computed once per surface. If a digest is already cached for this exact surface, it is returned as
is without calling the model (``from_cache=true``). Every non-success is a labelled no-op, not an
error (always a ``200``): the feature flag being off, no API key, the endpoint having no discovered
surface, or the model being unreachable / declining each return ``generated=false`` with a ``detail``.
No tool is executed — the examples are pure schema synthesis and the model is told the surface is
descriptive only. ``404`` when the endpoint is not the caller's tenant's.

Operation id: `generate_mcp_endpoint_summary_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_summary_generate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for generate mcp endpoint summary. | `application/json` [`McpServerDigestGenerateResponse`](#schema-mcpserverdigestgenerateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/surface` {#get-mcp-endpoint-insight-surface-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-surface-get}

**Get Mcp Endpoint Insight Surface**

Return the capability-surface metrics for a version snapshot (defaults to the current one).

Resolves the target snapshot — the supplied ``version_id`` or, when omitted, the endpoint's
``current_version_id`` — reconstructs its normalized surface from the persisted rows, and runs
the deterministic :func:`app.mcp_surface_metrics.compute_surface_metrics` roll-up (per-type
counts, per-tool schema complexity, annotation and documentation coverage) the 15.x panels
render. A GET stays read-only: nothing is written. Returns ``404`` when the endpoint — or the
named version under it — is not the caller's tenant's, or when no ``version_id`` was given and
the endpoint has never been discovered (no current surface to summarize).

Operation id: `get_mcp_endpoint_insight_surface_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_surface_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | query | string (uuid) or null | no | Which snapshot to summarize; omit to summarize the endpoint's current surface. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint insight surface. | `application/json` [`McpInsightSurfaceResponse`](#schema-mcpinsightsurfaceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/insight/trust` {#get-mcp-endpoint-insight-trust-v1-mcp-tenant-slug-endpoints-endpoint-id-insight-trust-get}

**Get Mcp Endpoint Insight Trust**

Return the endpoint's composite trust profile — five normalized 0-100 axes (MCAT-17.4).

The capstone of the single-server insight view: a synthesized "trust glance" across five axes,
each reading one already-computed metric layer —

* **quality** — the current snapshot's stored lint score;
* **safety** — behavioural-annotation coverage crossed with the endpoint's auth posture and its
  destructive-tool count;
* **documentation** — the snapshot's documentation coverage;
* **stability** — the breaking-change rate across the evolution series' snapshot transitions;
* **responsiveness** — the test-invocation error rate and p95 latency.

Every axis whose input is missing (a never-scored, never-changed, or never-tested server) is
returned as an explicit *gap* — ``value: null`` with ``available: false`` — never a zero, and the
``overall`` composite averages only the available axes. This is deliberately a **heuristic**
composite the panel labels as such, not an official rating. A never-discovered endpoint yields an
all-gap profile (a ``200``), never a ``500``. Returns ``404`` when the endpoint is not the
caller's tenant's. A GET stays read-only.

Operation id: `get_mcp_endpoint_insight_trust_v1_mcp__tenant_slug__endpoints__endpoint_id__insight_trust_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint insight trust. | `application/json` [`McpInsightTrustResponse`](#schema-mcpinsighttrustresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/jobs` {#list-mcp-endpoint-jobs-v1-mcp-tenant-slug-endpoints-endpoint-id-jobs-get}

**List Mcp Endpoint Jobs**

List an endpoint's discovery-job status snapshots, newest first.

404 when the endpoint is not the caller's tenant's (so an unknown id never
discloses another tenant's jobs as an empty list).

Operation id: `list_mcp_endpoint_jobs_v1_mcp__tenant_slug__endpoints__endpoint_id__jobs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp endpoint jobs. | `application/json` [`McpDiscoveryJobStatusListResponse`](#schema-mcpdiscoveryjobstatuslistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/jobs/{job_id}` {#get-mcp-endpoint-job-v1-mcp-tenant-slug-endpoints-endpoint-id-jobs-job-id-get}

**Get Mcp Endpoint Job**

Poll one discovery job's status snapshot (state, timings, version_id/error).

A terminal snapshot carries ``version_id`` (completed) or ``error`` /
``error_detail`` (failed). 404 when the job is not this tenant+endpoint's.

Operation id: `get_mcp_endpoint_job_v1_mcp__tenant_slug__endpoints__endpoint_id__jobs__job_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `job_id` | path | string (uuid) | yes | Asynchronous job identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint job. | `application/json` [`McpDiscoveryJobStatusResponse`](#schema-mcpdiscoveryjobstatusresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes` {#list-mcp-endpoint-notes-v1-mcp-tenant-slug-endpoints-endpoint-id-notes-get}

**List Mcp Endpoint Notes**

List cataloger notes for an endpoint (newest first).

Operation id: `list_mcp_endpoint_notes_v1_mcp__tenant_slug__endpoints__endpoint_id__notes_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp endpoint notes. | `application/json` [`McpEndpointNoteListResponse`](#schema-mcpendpointnotelistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes` {#create-mcp-endpoint-note-v1-mcp-tenant-slug-endpoints-endpoint-id-notes-post}

**Create Mcp Endpoint Note**

Add a cataloger note to an endpoint.

Operation id: `create_mcp_endpoint_note_v1_mcp__tenant_slug__endpoints__endpoint_id__notes_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create mcp endpoint note.

- `application/json` — [`McpEndpointNoteCreate`](#schema-mcpendpointnotecreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create mcp endpoint note. | `application/json` [`McpEndpointNoteOut`](#schema-mcpendpointnoteout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}` {#get-mcp-endpoint-note-v1-mcp-tenant-slug-endpoints-endpoint-id-notes-note-id-get}

**Get Mcp Endpoint Note**

Fetch one cataloger note on an endpoint.

Operation id: `get_mcp_endpoint_note_v1_mcp__tenant_slug__endpoints__endpoint_id__notes__note_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `note_id` | path | string (uuid) | yes | Path parameter identifying the note id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint note. | `application/json` [`McpEndpointNoteOut`](#schema-mcpendpointnoteout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}` {#update-mcp-endpoint-note-v1-mcp-tenant-slug-endpoints-endpoint-id-notes-note-id-patch}

**Update Mcp Endpoint Note**

Update a cataloger note on an endpoint.

Operation id: `update_mcp_endpoint_note_v1_mcp__tenant_slug__endpoints__endpoint_id__notes__note_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `note_id` | path | string (uuid) | yes | Path parameter identifying the note id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update mcp endpoint note.

- `application/json` — [`McpEndpointNoteUpdate`](#schema-mcpendpointnoteupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update mcp endpoint note. | `application/json` [`McpEndpointNoteOut`](#schema-mcpendpointnoteout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/notes/{note_id}` {#delete-mcp-endpoint-note-v1-mcp-tenant-slug-endpoints-endpoint-id-notes-note-id-delete}

**Delete Mcp Endpoint Note**

Delete a cataloger note from an endpoint.

Operation id: `delete_mcp_endpoint_note_v1_mcp__tenant_slug__endpoints__endpoint_id__notes__note_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `note_id` | path | string (uuid) | yes | Path parameter identifying the note id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete mcp endpoint note. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/report` {#export-mcp-endpoint-report-v1-mcp-tenant-slug-endpoints-endpoint-id-report-get}

**Export Mcp Endpoint Report**

Export a self-contained one-page report card for an endpoint version (MCAT-19.1).

Serializes the same panels the in-app Insight view shows — identity, grade + score breakdown,
capability surface, safety posture, documentation coverage, license & terms signals,
deprecation & lifecycle signals, the composite trust radar, and the change-since-previous
summary — into a shareable **Markdown**
or **HTML** document (the HTML
carries a print stylesheet, so "PDF" is the browser's print-to-PDF of the same file). No new
metric is computed: the route fetches the values the Insight endpoints already produce and the
pure :mod:`app.mcp_report_card` layer renders them.

Visibility is honoured by the standard token-tenant scoping — a cross-tenant (or private,
non-tenant) endpoint id reads as ``404``. A **never-discovered or never-scored** endpoint yields
a graceful *partial* report (identity present; the unavailable sections say so) rather than an
error. No credential secret ever reaches the report — only the auth posture and ``auth_type``.

Args:
    tenant_slug: Informational; scoping comes from the validated token's tenant.
    endpoint_id: The endpoint to report on.
    format: ``markdown`` / ``md`` / ``html`` (``400`` on anything else).
    version_id: The snapshot to report; defaults to the endpoint's current surface.
    auth_data: The validated caller identity (also what enforces visibility).

Returns:
    A ``Response`` carrying the rendered document with the right ``Content-Type`` and an
    ``attachment`` ``Content-Disposition`` filename.

Operation id: `export_mcp_endpoint_report_v1_mcp__tenant_slug__endpoints__endpoint_id__report_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `format` | query | string | no | Report format: 'markdown' (alias 'md') or 'html'. |
| `version_id` | query | string (uuid) or null | no | Which snapshot to report; omit to report the endpoint's current surface. |
| `include_cataloger_notes` | query | boolean | no | When true, include tenant cataloger commentary (not server-reported data). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export mcp endpoint report. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/sources` {#list-mcp-endpoint-sources-v1-mcp-tenant-slug-endpoints-endpoint-id-sources-get}

**List Mcp Endpoint Sources**

List an endpoint's linked sources, newest first. 404 when the endpoint is not the caller's.

Operation id: `list_mcp_endpoint_sources_v1_mcp__tenant_slug__endpoints__endpoint_id__sources_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `includeRetired` | query | boolean | no | Include retired source links (kept for historical evidence). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp endpoint sources. | `application/json` [`McpSourceListResponse`](#schema-mcpsourcelistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/sources` {#link-mcp-endpoint-source-v1-mcp-tenant-slug-endpoints-endpoint-id-sources-post}

**Link Mcp Endpoint Source**

Link a source artifact (git repo / package / image / registry identity) to an endpoint.

The reference is parsed and canonicalized by :mod:`app.mcp_source_link`; the pin strength is
*derived* from whether the reference actually carries an immutable digest, never from what the
caller asserts. Idempotent: re-linking the same live artifact returns the existing row.

404 when the endpoint is not the caller's tenant's; 400 on an unparseable reference.

Operation id: `link_mcp_endpoint_source_v1_mcp__tenant_slug__endpoints__endpoint_id__sources_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for link mcp endpoint source.

- `application/json` — [`McpSourceLinkRequest`](#schema-mcpsourcelinkrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for link mcp endpoint source. | `application/json` [`McpSourceResponse`](#schema-mcpsourceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/sources/{source_id}` {#retire-mcp-endpoint-source-v1-mcp-tenant-slug-endpoints-endpoint-id-sources-source-id-delete}

**Retire Mcp Endpoint Source**

Retire a linked source (soft delete). It stops backing new scans but stays readable.

404 when the source is not this endpoint's, or is already retired.

Operation id: `retire_mcp_endpoint_source_v1_mcp__tenant_slug__endpoints__endpoint_id__sources__source_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `source_id` | path | string (uuid) | yes | Path parameter identifying the source id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for retire mcp endpoint source. | `application/json` [`McpSourceResponse`](#schema-mcpsourceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/sources/{source_id}/sbom` {#attach-mcp-source-sbom-v1-mcp-tenant-slug-endpoints-endpoint-id-sources-source-id-sbom-post}

**Attach Mcp Source Sbom**

Attach a CycloneDX/SPDX SBOM to a linked source. Coordinates only — no source is stored.

The document is parsed for component coordinates (name / version / purl / license) and nothing
else; :mod:`app.mcp_sbom` has no field that could hold source or file content. The inventory is
keyed by the artifact digest it describes, defaulting to the source's own pinned digest.

400 when the source is not pinned and no ``subject_digest`` is given (an inventory must name the
artifact it inventories); 400 on an unrecognized SBOM; 404 when the source is not the caller's.

Operation id: `attach_mcp_source_sbom_v1_mcp__tenant_slug__endpoints__endpoint_id__sources__source_id__sbom_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `source_id` | path | string (uuid) | yes | Path parameter identifying the source id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for attach mcp source sbom.

- `application/json` — [`McpSbomAttachRequest`](#schema-mcpsbomattachrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for attach mcp source sbom. | `application/json` [`McpSbomOut`](#schema-mcpsbomout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/test` {#test-mcp-endpoint-capability-v1-mcp-tenant-slug-endpoints-endpoint-id-test-post}

**Test Mcp Endpoint Capability**

Invoke one cataloged capability against its live MCP server and report the outcome.

The test-harness surface for the UI/CLI: it names a ``tool``/``resource``/``prompt`` on the
endpoint's *current* discovered surface, validates the supplied ``arguments`` against the stored
schema (a tool's ``inputSchema``; a prompt's required arguments), attaches the endpoint's stored
credential — or an ephemeral ``auth_override`` that is **never persisted** — and invokes the one
method under ``timeout_seconds``. The response carries the three outcomes the invocation service
distinguishes: a successful result (``completed`` / not ``is_error``), a tool-level error
(``completed`` + ``is_error``, with the error content), or a transport/JSON-RPC failure
(``completed=False`` with a classified ``error``) — each with its ``latency_ms``.

Safety guards (V2-MCP-22.3 / MCAT-8.3):

* **Confirm gate** — a tool whose annotations assert ``destructiveHint`` or ``openWorldHint``
  is refused with ``428`` unless the request sets ``confirm=true``, so an irreversible or
  open-world tool is never fired by accident.
* **Per-endpoint rate limit** — accepted calls are throttled per endpoint (``429`` when the
  window is exhausted) so the console cannot flood the external server.
* **Redacted audit log** — every *dispatched* call is recorded in ``mcp_test_invocations`` with
  secret-named arguments/response fields masked; auth headers are never logged. The new row's id
  is returned as ``invocation_id``. Logging is best-effort and never fails the call.

Status codes:

* ``404`` — the endpoint is not the caller's tenant's, or the named capability is not on its
  current surface.
* ``409`` — the endpoint has never been discovered (no current surface to test).
* ``422`` — the arguments fail the stored schema, the override payload is malformed, or a
  resource has no concrete uri.
* ``428`` — the tool is flagged destructive/open-world and the request did not set ``confirm``.
* ``429`` — the per-endpoint test rate limit for the current window has been reached.

A remote-server failure is **not** an HTTP error here: it is reported in-band as
``completed=False`` with the classified ``error``, so "the tool is down" is data, not a 5xx.

Operation id: `test_mcp_endpoint_capability_v1_mcp__tenant_slug__endpoints__endpoint_id__test_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for test mcp endpoint capability.

- `application/json` — [`McpEndpointTestRequest`](#schema-mcpendpointtestrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for test mcp endpoint capability. | `application/json` [`McpEndpointTestResponse`](#schema-mcpendpointtestresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions` {#list-mcp-endpoint-versions-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-get}

**List Mcp Endpoint Versions**

List an endpoint's version history newest-first (seq, date tag, score, change counts).

Each entry carries the snapshot's sequence and human-readable ``version_tag``, its server
identity and fingerprint, the quality score/grade (when scored), and the per-direction
tally of changes it introduced. ``is_current`` marks the snapshot the endpoint currently
points at. 404 when the endpoint is not the caller's tenant's.

Operation id: `list_mcp_endpoint_versions_v1_mcp__tenant_slug__endpoints__endpoint_id__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp endpoint versions. | `application/json` [`McpEndpointVersionListResponse`](#schema-mcpendpointversionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/compare` {#compare-mcp-endpoint-versions-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-compare-get}

**Compare Mcp Endpoint Versions**

Compute an on-demand structured diff between any two of an endpoint's versions.

Works for *any* base/target pair — adjacent or arbitrarily distant — because the surfaces
are diffed directly (MCAT-4.2), not by chaining adjacent step-diffs. The order is
normalized to older→newer (by ``version_seq``) regardless of which id was passed as
``base``, so ``added``/``removed`` always read relative to the older surface. The same
version on both sides yields an empty diff with ``fingerprint_changed = False``. 404 when
the endpoint — or either version under it — is not the caller's tenant's.

Operation id: `compare_mcp_endpoint_versions_v1_mcp__tenant_slug__endpoints__endpoint_id__versions_compare_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `base` | query | string (uuid) | yes | The base (from) version id. |
| `target` | query | string (uuid) | yes | The target (to) version id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for compare mcp endpoint versions. | `application/json` [`McpVersionCompareResponse`](#schema-mcpversioncompareresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}` {#get-mcp-endpoint-version-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-get}

**Get Mcp Endpoint Version**

Fetch one version snapshot's full surface (identity, capabilities, and items).

Returns the server identity, declared capabilities, instructions, score/grade, change
counts, and every normalized capability item of the snapshot. 404 when the endpoint — or
the version under it — is not the caller's tenant's.

Operation id: `get_mcp_endpoint_version_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version. | `application/json` [`McpEndpointVersionResponse`](#schema-mcpendpointversionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/changes` {#get-mcp-endpoint-version-changes-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-changes-get}

**Get Mcp Endpoint Version Changes**

Return a version's stored ``previous → this`` change report (the diff it introduced).

Empty for the first version (which introduces no diff). The changes are in the same stable
order an on-demand compare of the same pair produces. 404 when the endpoint — or the
version under it — is not the caller's tenant's.

Operation id: `get_mcp_endpoint_version_changes_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__changes_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version changes. | `application/json` [`McpVersionChangesResponse`](#schema-mcpversionchangesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/conformance` {#get-mcp-endpoint-version-conformance-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-conformance-get}

**Get Mcp Endpoint Version Conformance**

Run and gate a conformance profile over one MCP version snapshot.

Assesses the snapshot's protocol behaviour and its tools' agent-readiness, then gates the
result: the response's ``gate`` says whether the run cleared ``failOn`` / ``minScore``, so a
CI job can act on this single call.

Read-only and side-effect free: the report is recomputed on each request from the persisted
surface and the snapshot's stored (redacted) protocol transcript, and nothing is written back.
Any rule that needs a transcript this snapshot never captured is reported in ``skippedRules``
rather than assumed to pass.

``format=sarif`` / ``format=junit`` return the CI artifact directly, through the same
serializer the compatibility gate uses. 404 when the endpoint — or the version under it — is
not the caller's tenant's; 400 on an unknown profile or threshold.

Operation id: `get_mcp_endpoint_version_conformance_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__conformance_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `profile` | query | string or null | no | Conformance profile to run (default: mcp-conformance). |
| `failOn` | query | string | no | Fail the gate on findings of this severity or worse; 'none' to disable. |
| `minScore` | query | integer or null | no | Optional score floor; a lower score fails the gate. |
| `format` | query | string or null | no | Response format: json (default), sarif, or junit. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version conformance. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint` {#get-mcp-endpoint-version-lint-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-lint-get}

**Get Mcp Endpoint Version Lint**

Return a version snapshot's lint report — the stored score, or a live recompute.

Serves the report persisted at discovery time (``source="stored"``) when one exists; when the
snapshot has never been scored (or only an empty placeholder row exists), the surface is
reconstructed and scored on the fly (``source="computed"``) without writing it back — a GET
stays read-only. Either way the response carries the deterministic score, A-F grade, per-rule
and per-severity tallies, the stable fingerprint, and every itemized finding. 404 when the
endpoint — or the version under it — is not the caller's tenant's.

Operation id: `get_mcp_endpoint_version_lint_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__lint_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version lint. | `application/json` [`McpLintReportResponse`](#schema-mcplintreportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint` {#recompute-mcp-endpoint-version-lint-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-lint-post}

**Recompute Mcp Endpoint Version Lint**

Recompute a version snapshot's lint report and persist the refreshed score.

Always reconstructs the snapshot's surface from its stored rows, re-runs the deterministic
scorer, and upserts the result into ``mcp_version_scores`` (overwriting any prior score and
moving ``scored_at`` to now). Returns the freshly computed report with ``source="computed"``
and the persisted ``scored_at``. 404 when the endpoint — or the version under it — is not the
caller's tenant's.

Operation id: `recompute_mcp_endpoint_version_lint_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__lint_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for recompute mcp endpoint version lint. | `application/json` [`McpLintReportResponse`](#schema-mcplintreportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint/axes` {#get-mcp-endpoint-version-lint-axes-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-lint-axes-get}

**Get Mcp Endpoint Version Lint Axes**

Return the multi-axis score and coverage evaluation for a version snapshot (CLX-1.2, #4849).

Prefers the latest stored ``lint_axis_evaluations`` row for algorithm ``clx-axis-v1``.
When none is stored, computes one from the persisted MCP score report. Legacy list
``score`` / ``grade`` fields are unchanged. 404 when the endpoint or version is not
the caller's tenant's.

Operation id: `get_mcp_endpoint_version_lint_axes_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__lint_axes_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version lint axes. | `application/json` [`LintAxesResponse`](#schema-lintaxesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint/evidence` {#get-mcp-endpoint-version-lint-evidence-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-lint-evidence-get}

**Get Mcp Endpoint Version Lint Evidence**

Return the immutable lint evidence recorded for a version snapshot (CLX-1.1, #4848).

Lists every evidence run captured for the snapshot — provenance (scanner, adapter,
profile, fingerprints), outcome, normalized findings, and coverage — plus a per-scanner
coverage summary in which a scanner that never ran reads as ``not_run`` (never as clean).
Raw output artifacts are access-controlled: responses expose only their availability,
never the storage reference or command metadata. 404 when the endpoint — or the version
under it — is not the caller's tenant's.

Operation id: `get_mcp_endpoint_version_lint_evidence_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__lint_evidence_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version lint evidence. | `application/json` [`LintEvidenceResponse`](#schema-lintevidenceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint/gate` {#get-mcp-endpoint-version-lint-gate-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-lint-gate-get}

**Get Mcp Endpoint Version Lint Gate**

Evaluate the lint CI gate for an MCP snapshot and emit a machine-readable artifact (CLX-4.2).

The MCP twin of ``GET /v1/versions/…/lint/gate``: policy verdict over the snapshot's
current evidence, optional baseline regression diff, and JSON / SARIF / JUnit / Markdown /
attestation serialization. HTTP status is always 200 — pass/fail lives in ``gate.passed``.

Operation id: `get_mcp_endpoint_version_lint_gate_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__lint_gate_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `format` | query | string or null | no | Artifact format: json (default) \| sarif \| junit \| markdown \| attestation. The Accept header is honored when the query parameter is absent. |
| `baselineVersionId` | query | string or null | no | Optional baseline snapshot (mcp_endpoint_versions.id) to diff regressions against; must belong to the same endpoint. |
| `newOnly` | query | boolean | no | Scope the CI verdict's unwaived-errors gate to newly introduced findings. |
| `policyVersionId` | query | string or null | no | Optional historical policy pack id; defaults to the latest for the assigned guide. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version lint gate. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/lint/policy` {#get-mcp-endpoint-version-lint-policy-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-lint-policy-get}

**Get Mcp Endpoint Version Lint Policy**

Evaluate the assigned style-guide policy pack against MCP version evidence (CLX-1.3, #4850).

Operation id: `get_mcp_endpoint_version_lint_policy_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__lint_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `policyVersionId` | query | string or null | no | Optional historical policy pack id; defaults to the latest for the assigned guide. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version lint policy. | `application/json` [`LintPolicyResponse`](#schema-lintpolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/versions/{version_id}/trust-posture` {#get-mcp-endpoint-version-trust-posture-v1-mcp-tenant-slug-endpoints-endpoint-id-versions-version-id-trust-posture-get}

**Get Mcp Endpoint Version Trust Posture**

Run and gate a trust-posture profile over one MCP version snapshot.

Assesses what the server is built from — its advertised metadata, its linked source, and its
dependencies — mapped to the OWASP MCP Top 10, then gates the result.

Two honesty guarantees are visible in every response and must not be ignored by a consumer:

* Every finding carries ``exploitability`` — always ``static_signal`` today, because no dynamic
  probe exists yet (CLX-3.3, #4857). ``proven_count`` is 0. Nothing here is a demonstrated
  exploit; each is a signal a reviewer should confirm.
* Rules whose evidence is absent (no linked source, no SBOM, no vulnerability lookup) appear in
  ``skipped_rules`` with a reason, never as passes. Use ``requireFullCoverage`` to fail the gate
  when the scan could not look at everything.

Read-only and side-effect free: recomputed on each request from persisted evidence. The metadata
lane is fully offline; the dependency lane transmits only package coordinates, and only when
vulnerability lookup is explicitly enabled. ``format=sarif`` / ``junit`` return the CI artifact.
404 when the endpoint or version is not the caller's tenant's; 400 on an unknown profile.

Operation id: `get_mcp_endpoint_version_trust_posture_v1_mcp__tenant_slug__endpoints__endpoint_id__versions__version_id__trust_posture_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `version_id` | path | string (uuid) | yes | Version identifier or semantic version label, depending on the route. |
| `profile` | query | string or null | no | Trust-posture profile to run (default: mcp-trust-posture). |
| `failOn` | query | string | no | Fail the gate on findings of this severity or worse; 'none' to disable. |
| `minScore` | query | integer or null | no | Optional score floor; a lower score fails the gate. |
| `requireFullCoverage` | query | boolean | no | Fail the gate when any rule was skipped for lack of evidence. |
| `format` | query | string or null | no | Response format: json (default), sarif, or junit. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp endpoint version trust posture. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/endpoints/{endpoint_id}/views` {#record-mcp-endpoint-view-v1-mcp-tenant-slug-endpoints-endpoint-id-views-post}

**Record Mcp Endpoint View**

Record that the caller viewed the endpoint, advancing their seen-marker (MCAT-16.5).

Upserts the caller's per-user ``mcp_endpoint_views`` marker to the snapshot they saw — the
``version_id`` they acknowledge in the body, or the endpoint's current version when omitted —
so the next "changed since last view" digest reads relative to it ("the marker advances on
view"). Requires a resolvable user (``403`` otherwise, as the marker is per-user). Returns
``404`` when the endpoint — or an explicitly named version under it — is not the caller's
tenant's, and ``400`` when the endpoint has no discovered version to mark.

Operation id: `record_mcp_endpoint_view_v1_mcp__tenant_slug__endpoints__endpoint_id__views_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `endpoint_id` | path | string (uuid) | yes | MCP endpoint identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for record mcp endpoint view.

- `application/json` — [`McpEndpointViewMarkRequest`](#schema-mcpendpointviewmarkrequest) or null

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record mcp endpoint view. | `application/json` [`McpEndpointViewResponse`](#schema-mcpendpointviewresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/endpoints:export` {#export-mcp-catalog-inventory-v1-mcp-tenant-slug-endpoints-export-get}

**Export Mcp Catalog Inventory**

Export the tenant's whole MCP catalog as streamed CSV or JSON data (MCAT-19.2).

Serializes every cataloged endpoint into a flat inventory row — id, name, host, transport,
category, visibility, published flag, current grade/score, per-kind capability counts (and their
total), last discovery status/time, and a derived health label — as **CSV** (RFC-4180 escaped)
or a **JSON** wrapper whose ``endpoints`` array carries the same fields. The catalog is walked one
bounded keyset page at a time and the body is streamed, so a large catalog exports without
loading every row into memory.

Like every catalog route, scoping comes from the validated token's ``tenant_id`` — never the URL
slug — so the export only ever contains the caller's own catalog. ``scope=public`` restricts the
export to published endpoints (the published-only variant a public directory would show). Only
each endpoint's *host* is exported; the stored URL, which may embed a credential, never appears.

Args:
    tenant_slug: Informational; scoping comes from the validated token's tenant.
    format: ``csv`` or ``json`` (``400`` on anything else).
    scope: ``all`` (full catalog) or ``public`` (published-only); ``400`` on anything else.
    auth_data: The validated caller identity (also what enforces tenant scoping).

Returns:
    A ``StreamingResponse`` carrying the rendered inventory with the right ``Content-Type`` and
    an ``attachment`` ``Content-Disposition`` filename.

Operation id: `export_mcp_catalog_inventory_v1_mcp__tenant_slug__endpoints_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `format` | query | string | no | Inventory format: 'csv' or 'json'. |
| `scope` | query | string | no | 'all' exports the tenant's full catalog; 'public' exports only published endpoints (the public-directory variant). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export mcp catalog inventory. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/facets` {#faceted-mcp-catalog-search-v1-mcp-tenant-slug-facets-get}

**Faceted Mcp Catalog Search**

Faceted search over the caller's MCP catalog with live facet counts (V2-MCP-35.1 / MCAT-21.1).

The catalog's rich metrics as queryable facets: filter by grade band, transport, category,
safety posture, complexity band, protocol version, and discovery health. Filters **AND across
facets** and **OR within a facet**; the response carries the matching endpoint page (browse-
shaped rows, each with its facet fields) plus per-dimension bucket counts aggregated over the
same filtered set, so the counts are live. Every bucket label — including the NULL-bucket
sentinels ``ungraded`` / ``uncategorized`` / ``unknown`` — is itself a valid filter value.

Like every catalog route, scoping comes from the token's ``tenant_id`` — never the URL slug —
so the search only ever spans the caller's own catalog, and ``visibility`` narrows the
caller's *own* private/public endpoints. A filter combination matching nothing returns an
empty page with zeroed counts, not an error; an invalid facet value is a ``422``.

Operation id: `faceted_mcp_catalog_search_v1_mcp__tenant_slug__facets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `grade` | query | array of string or null | no | Grade facet: A-F letters (any case) and/or 'ungraded'. Repeatable. |
| `transport` | query | array of string or null | no | Transport facet: streamable_http / sse / stdio. Repeatable. |
| `category` | query | array of string or null | no | Category facet: category names (case-insensitive) and/or 'uncategorized'. Repeatable. |
| `safety` | query | array of string or null | no | Safety-posture facet: 'has_destructive' (a tool asserts destructiveHint) and/or 'read_only_only' (every tool asserts readOnlyHint). Repeatable. |
| `complexity` | query | array of string or null | no | Complexity-band facet: simple / moderate / complex / unknown. Repeatable. |
| `protocol` | query | array of string or null | no | Protocol-version facet: exact reported versions (e.g. 2025-06-18) and/or 'unknown'. Repeatable. |
| `health` | query | array of string or null | no | Discovery-health facet: healthy / failing / undiscovered / disabled / quarantined. Repeatable. |
| `visibility` | query | enum `"public"`, `"private"` or null | no | Filter to 'private' or 'public' endpoints within the caller's own catalog. |
| `limit` | query | integer | no | Maximum endpoints to return. |
| `offset` | query | integer | no | Endpoints to skip (pagination). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for faceted mcp catalog search. | `application/json` [`McpFacetedSearchResponse`](#schema-mcpfacetedsearchresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/insight/catalog` {#get-mcp-catalog-insight-v1-mcp-tenant-slug-insight-catalog-get}

**Get Mcp Catalog Insight**

Return a tenant-wide roll-up of the caller's live MCP catalog (feeds 18.1).

Aggregates every live endpoint the caller's tenant owns: total / published / discovered counts,
the per-kind capability ``type_counts`` summed across each endpoint's current surface, the
average quality score, and the A-F ``grade_distribution``. Like every catalog route, scoping
comes from the token's ``tenant_id`` — never the URL slug — so the aggregate only ever spans the
caller's own catalog (an empty catalog returns zeroes, not a ``404``).

Operation id: `get_mcp_catalog_insight_v1_mcp__tenant_slug__insight_catalog_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp catalog insight. | `application/json` [`McpInsightCatalogResponse`](#schema-mcpinsightcatalogresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/saved-searches` {#list-mcp-saved-searches-v1-mcp-tenant-slug-saved-searches-get}

**List Mcp Saved Searches**

List the caller's saved catalog searches (pinned first, then newest).

Operation id: `list_mcp_saved_searches_v1_mcp__tenant_slug__saved_searches_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mcp saved searches. | `application/json` [`McpSavedSearchListResponse`](#schema-mcpsavedsearchlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mcp/{tenant_slug}/saved-searches` {#create-mcp-saved-search-v1-mcp-tenant-slug-saved-searches-post}

**Create Mcp Saved Search**

Save the current catalog filter bundle under a name.

Operation id: `create_mcp_saved_search_v1_mcp__tenant_slug__saved_searches_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create mcp saved search.

- `application/json` — [`McpSavedSearchCreate`](#schema-mcpsavedsearchcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create mcp saved search. | `application/json` [`McpSavedSearchOut`](#schema-mcpsavedsearchout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/saved-searches/{search_id}` {#get-mcp-saved-search-v1-mcp-tenant-slug-saved-searches-search-id-get}

**Get Mcp Saved Search**

Fetch one saved search owned by the caller.

Operation id: `get_mcp_saved_search_v1_mcp__tenant_slug__saved_searches__search_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `search_id` | path | string (uuid) | yes | Path parameter identifying the search id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mcp saved search. | `application/json` [`McpSavedSearchOut`](#schema-mcpsavedsearchout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/mcp/{tenant_slug}/saved-searches/{search_id}` {#update-mcp-saved-search-v1-mcp-tenant-slug-saved-searches-search-id-patch}

**Update Mcp Saved Search**

Update a saved search owned by the caller.

Operation id: `update_mcp_saved_search_v1_mcp__tenant_slug__saved_searches__search_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `search_id` | path | string (uuid) | yes | Path parameter identifying the search id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update mcp saved search.

- `application/json` — [`McpSavedSearchUpdate`](#schema-mcpsavedsearchupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update mcp saved search. | `application/json` [`McpSavedSearchOut`](#schema-mcpsavedsearchout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mcp/{tenant_slug}/saved-searches/{search_id}` {#delete-mcp-saved-search-v1-mcp-tenant-slug-saved-searches-search-id-delete}

**Delete Mcp Saved Search**

Delete a saved search owned by the caller.

Operation id: `delete_mcp_saved_search_v1_mcp__tenant_slug__saved_searches__search_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `search_id` | path | string (uuid) | yes | Path parameter identifying the search id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete mcp saved search. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/saved-searches/{search_id}/run` {#run-mcp-saved-search-v1-mcp-tenant-slug-saved-searches-search-id-run-get}

**Run Mcp Saved Search**

Re-run a saved search's facet-compatible filters and return matching endpoints.

Host/auth dimensions are applied client-side on the browse page; the server runs the facet
subset via the same faceted-search path as ``GET /facets``, so results match the equivalent
live facet filter for those dimensions.

Operation id: `run_mcp_saved_search_v1_mcp__tenant_slug__saved_searches__search_id__run_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `search_id` | path | string (uuid) | yes | Path parameter identifying the search id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for run mcp saved search. | `application/json` [`McpSavedSearchRunResponse`](#schema-mcpsavedsearchrunresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mcp/{tenant_slug}/search` {#search-mcp-catalog-v1-mcp-tenant-slug-search-get}

**Search Mcp Catalog**

Free-text search over the caller's MCP catalog, relevance-then-score ranked (V2-MCP-23.2 / MCAT-9.2).

Backed by the V127 capability-item ``tsvector`` GIN index. ``scope`` selects what is searched: a
single capability kind, every capability kind (the default), or the endpoints themselves
(``scope=endpoint``). Each hit carries its owning endpoint's browse context (host, category,
score/grade, visibility) so the result is renderable without a second read. The ``host`` /
``category`` / ``grade`` / ``visibility`` filters compose (each supplied filter is ANDed in).

Like every catalog route, scoping comes from the token's ``tenant_id`` — never the URL slug — so a
search only ever returns the caller's own catalog (the public-directory variant waits on the
MCAT-1.6 public read view). ``visibility`` therefore narrows the caller's *own* private/public
endpoints rather than exposing another tenant's. A query that reduces to nothing under full-text
parsing (e.g. only stop-words) is a valid request that simply returns no hits.

Operation id: `search_mcp_catalog_v1_mcp__tenant_slug__search_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `q` | query | string | yes | Free-text query (websearch syntax: quotes for phrases, OR, leading - to exclude). |
| `scope` | query | enum `"tool"`, `"resource"`, `"resource_template"`, `"prompt"`, `"endpoint"` or null | no | What to search: a single capability kind (tool/resource/resource_template/prompt), or 'endpoint' to search endpoints by name/description/category. Omit to search across all capability kinds. |
| `host` | query | string or null | no | Filter to endpoints on this host (case-insensitive). |
| `category` | query | string or null | no | Filter to endpoints in this category (case-insensitive). |
| `grade` | query | string or null | no | Filter to endpoints whose current snapshot earned this A-F grade. |
| `visibility` | query | enum `"public"`, `"private"` or null | no | Filter to 'private' or 'public' endpoints within the caller's own catalog. |
| `limit` | query | integer | no | Maximum hits to return. |
| `offset` | query | integer | no | Hits to skip (pagination). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for search mcp catalog. | `application/json` [`McpSearchResponse`](#schema-mcpsearchresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `LintAxesResponse` {#schema-lintaxesresponse}

Response envelope for GET …/lint/axes (CLX-1.2, #4849).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `evaluation` | `LintAxisEvaluationOut` | yes | Evaluation. |

### `LintEvidenceResponse` {#schema-lintevidenceresponse}

All lint evidence for one catalog revision or MCP endpoint version (CLX-1.1, #4848).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subjectType` | string | yes | Subject kind: catalog_revision or mcp_endpoint_version. |
| `subjectId` | string | yes | The revision (versions.id) or snapshot (mcp_endpoint_versions.id). |
| `runs` | array of `LintEvidenceRunOut` | no | Immutable evidence runs, most recent first. |
| `coverage` | array of `LintEvidenceCoverageOut` | no | Per-scanner coverage: expected scanners first, then any additional scanners with historical runs. Never-run scanners appear as not_run — never as clean. |
| `count` | integer | yes | Number of evidence runs (== len(runs)). |

### `LintPolicyResponse` {#schema-lintpolicyresponse}

GET …/lint/policy response: pack pin, evaluation, findings with decisions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `policyVersion` | `StyleGuidePolicyVersionOut` | yes | Policy Version. |
| `evaluation` | `LintPolicyEvaluationOut` | yes | Evaluation. |
| `findings` | array of `LintPolicyAnnotatedFindingOut` | no | Findings. |

### `McpBrowseResponse` {#schema-mcpbrowseresponse}

Response envelope for the private browse view — endpoints grouped by host (MCAT-9.1).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `host_count` | integer | yes | Number of host. |
| `endpoint_count` | integer | yes | Number of endpoint. |
| `groups` | array of `McpBrowseHostGroup` | yes | Groups. |

### `McpCapabilityDirectoryResponse` {#schema-mcpcapabilitydirectoryresponse}

Paginated capability directory envelope (MCAT-21.4).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |
| `total` | integer | yes | Total. |
| `count` | integer | yes | Number of count. |
| `items` | array of `McpCapabilityDirectoryEntry` | no | Items. |

### `McpCollectionCreate` {#schema-mcpcollectioncreate}

Body for creating a curated collection.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `slug` | string or null | no | URL-safe identifier. |
| `description` | string or null | no | Free-text description. |
| `isPublished` | boolean | no | Is Published. |
| `endpointIds` | array of string | no | Endpoint IDs. |

### `McpCollectionListResponse` {#schema-mcpcollectionlistresponse}

Envelope for listing curated collections.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `collections` | array of [`McpCollectionOut`](#schema-mcpcollectionout) | no | Collections. |

### `McpCollectionMembersAdd` {#schema-mcpcollectionmembersadd}

Append endpoints to a collection.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `endpointIds` | array of string | yes | Endpoint IDs. |

### `McpCollectionMembersReplace` {#schema-mcpcollectionmembersreplace}

Replace the full membership list for a collection.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `endpointIds` | array of string | no | Endpoint IDs. |

### `McpCollectionOut` {#schema-mcpcollectionout}

One tenant-scoped curated collection of MCP endpoints.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `slug` | string | yes | URL-safe identifier. |
| `description` | string or null | no | Free-text description. |
| `isPublished` | boolean | no | Is Published. |
| `memberCount` | integer | no | Number of member. |
| `createdBy` | string | yes | Created By. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) | yes | Updated At. |
| `members` | array of `McpCollectionMemberOut` or null | no | Members. |

### `McpCollectionUpdate` {#schema-mcpcollectionupdate}

Patch body for updating a curated collection.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `slug` | string or null | no | URL-safe identifier. |
| `description` | string or null | no | Free-text description. |
| `isPublished` | boolean or null | no | Is Published. |

### `McpConformanceRulesResponse` {#schema-mcpconformancerulesresponse}

The conformance rule catalog and the profiles that select from it (CLX-3.1, #4855).

Every rule cites the MCP specification version it derives from and a resolvable source
reference, so a finding is always traceable to a normative statement rather than an opinion.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `specVersion` | string | yes | The MCP specification revision this rule set is written against. |
| `profiles` | array of `McpConformanceProfileOut` | yes | Profiles. |
| `rules` | array of `McpConformanceRuleOut` | yes | Rules. |

### `McpCredentialDeleteResponse` {#schema-mcpcredentialdeleteresponse}

Outcome of clearing an endpoint's credential (MCAT-6.5).

``removed`` is ``True`` when a stored credential row was actually deleted, and ``False`` when
the endpoint had no credential to begin with (the clear is idempotent — both are ``200``).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `removed` | boolean | no | Removed. |

### `McpCredentialStatusResponse` {#schema-mcpcredentialstatusresponse}

McpCredentialStatusResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `credential` | `McpCredentialStatusOut` | yes | Credential. |

### `McpCredentialUpsert` {#schema-mcpcredentialupsert}

Set or replace an endpoint's outbound credential (MCAT-6.5).

The plaintext ``payload`` is sealed server-side (MCAT-6.2) before it is stored and is NEVER
echoed back by any response. ``auth_type`` must be a secret-bearing scheme
(:data:`MCP_CREDENTIAL_AUTH_TYPES`) — to remove a credential entirely (the anonymous ``none``
state) DELETE the resource instead. ``oauth_metadata`` is non-secret OAuth2 discovery metadata
persisted as cleartext. Accepts both camelCase and snake_case keys so UI and CLI can share it.

Expected ``payload`` shape per ``auth_type`` (validated against the auth-type model at the route):

* ``bearer`` — ``{"token": "<secret>"}``
* ``header`` — ``{"name": "<Header-Name>", "value": "<secret>"}``
* ``oauth2`` — ``{"access_token": "<token>", "token_type": "Bearer"?}``
* ``env``    — ``{"vars": {"NAME": "value", ...}}``

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `authType` | string | yes | Auth Type. |
| `payload` | object | no | Payload. |
| `oauthMetadata` | object or null | no | OAuth Metadata. |

### `McpCrossServerCapabilitySearchResponse` {#schema-mcpcrossservercapabilitysearchresponse}

Grouped cross-server capability search results (MCAT-21.2).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `query` | string | yes | Query. |
| `scope` | string or null | no | Scope. |
| `semantic_enabled` | boolean | no | Semantic Enabled. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |
| `total` | integer | yes | Total. |
| `count` | integer | yes | Number of count. |
| `groups` | array of `McpCrossServerCapabilityServerGroup` | no | Groups. |

### `McpDigestConfigResponse` {#schema-mcpdigestconfigresponse}

Response model for the tenant's digest configuration.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | yes | Whether the resource is active. |
| `cadenceSeconds` | integer or null | no | Cadence Seconds. |
| `effectiveCadenceSeconds` | integer | yes | Effective Cadence Seconds. |
| `sendEmpty` | boolean | yes | Send Empty. |
| `lastDigestAt` | string (date-time) or null | no | Last Digest At. |

### `McpDigestConfigUpdate` {#schema-mcpdigestconfigupdate}

Request body for ``PUT /digest/config`` — the tenant's digest preferences.

Attributes:
    enabled: Opt-in switch. When False the sweep never selects the tenant.
    cadence_seconds: Per-tenant cadence in seconds, or ``None`` to use the global default.
    send_empty: When True, an empty window still sends an explicit "no changes" digest.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | yes | Opt in (True) or out (False) of scheduled digests. |
| `cadenceSeconds` | integer or null | no | Digest cadence in seconds; null uses the global default. |
| `sendEmpty` | boolean | no | Send an explicit 'no changes' digest when the window is empty. |

### `McpDiscoveryJobListResponse` {#schema-mcpdiscoveryjoblistresponse}

Response envelope listing an endpoint's discovery jobs (newest first).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `jobs` | array of `McpDiscoveryJobOut` | yes | Jobs. |

### `McpDiscoveryJobResponse` {#schema-mcpdiscoveryjobresponse}

Response envelope for a single discovery job (trigger + poll).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `deduplicated` | boolean or null | no | Deduplicated. |
| `job` | `McpDiscoveryJobOut` | yes | Job. |

### `McpDiscoveryJobStatusListResponse` {#schema-mcpdiscoveryjobstatuslistresponse}

Response envelope listing an endpoint's discovery-job snapshots (newest first).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `jobs` | array of `McpDiscoveryJobStatus` | yes | Jobs. |

### `McpDiscoveryJobStatusResponse` {#schema-mcpdiscoveryjobstatusresponse}

Response envelope for a single discovery-job status snapshot.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `job` | `McpDiscoveryJobStatus` | yes | Job. |

### `McpDuplicateReportResponse` {#schema-mcpduplicatereportresponse}

Advisory duplicate review list for the caller's catalog.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `advisory` | boolean | no | Advisory. |
| `group_count` | integer | yes | Number of group. |
| `flagged_endpoint_count` | integer | yes | Number of flagged endpoint. |
| `groups` | array of `McpDuplicateGroup` | yes | Groups. |
| `cross_tenant_hints` | array of `McpDuplicateCrossTenantHint` | no | Cross Tenant Hints. |

### `McpEndpointCreate` {#schema-mcpendpointcreate}

Register an external MCP server in a tenant's catalog (MCAT-3.1).

``name`` and ``endpoint_url`` are required; ``transport`` defaults to
``streamable_http`` (the most common HTTP transport). ``slug`` is optional —
when omitted it is auto-derived from ``name`` and made unique within the
tenant. Accepts both camelCase and snake_case keys so UI and CLI can share
this model.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `endpointUrl` | string | yes | Endpoint URL. |
| `transport` | string | no | Transport. |
| `slug` | string or null | no | URL-safe identifier. |
| `description` | string or null | no | Free-text description. |
| `category` | string or null | no | Classification category for the primitive type. |
| `visibility` | string | no | Visibility. |
| `discoveryCadenceSeconds` | integer or null | no | Discovery Cadence Seconds. |

### `McpEndpointDeleteResponse` {#schema-mcpendpointdeleteresponse}

Outcome of soft-deleting a catalog endpoint (V2-MCP-17.5 / MCAT-3.5).

The endpoint row is retired with a ``deleted_at`` stamp (so it disappears
from browse but keeps its slug reserved), while its child data is purged:
``credentials_purged`` reports whether a stored credential row was dropped —
the security-critical part of the teardown — and ``versions_deleted`` /
``jobs_deleted`` count the version snapshots (with their cascaded capability
items, change logs and scores) and discovery jobs removed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `credentials_purged` | boolean | no | Credentials Purged. |
| `versions_deleted` | integer | no | Versions Deleted. |
| `jobs_deleted` | integer | no | Jobs Deleted. |

### `McpEndpointDigestResponse` {#schema-mcpendpointdigestresponse}

The "changed since last view" digest for one user + endpoint (V2-MCP-30.5 / MCAT-16.5).

Summarizes what changed on the endpoint's surface between the version the user *last saw*
(their ``mcp_endpoint_views`` seen-marker) and its *current* version, and how breaking that
change is:

* ``new_to_you`` — the user has no recorded marker (first visit), or the version they last saw
  has since been pruned (a ``NULL`` pointer). There is no "since" point to diff from, so
  ``changes`` is empty and ``current_type_counts`` describes the surface they are seeing fresh.
* ``has_changes`` — a marker exists and points at an older snapshot than the current one, so
  ``changes`` / ``change_counts`` / ``severity_counts`` describe the delta since it.
* Neither flag set — the user has already seen the current version; the endpoint is up to date.

Reading the digest does **not** advance the marker; a separate view-record call
(``POST …/views``) does, so the digest reflects the pre-advance state on load.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `new_to_you` | boolean | no | New To You. |
| `has_changes` | boolean | no | Whether changes. |
| `last_seen_version_id` | string or null | no | Last Seen Version ID. |
| `last_seen_version_seq` | integer or null | no | Last Seen Version Seq. |
| `last_seen_at` | string or null | no | Last Seen At timestamp (ISO 8601). |
| `current_version_id` | string or null | no | Current Version ID. |
| `current_version_seq` | integer or null | no | Current Version Seq. |
| `current_version_tag` | string or null | no | Current Version Tag. |
| `current_type_counts` | `McpTypeCountsOut` | no | Current Type Counts. |
| `change_counts` | `McpVersionChangeCounts` | no | Change Counts. |
| `severity_counts` | `McpChangeSeverityCounts` | no | Severity Counts. |
| `changes` | array of `McpVersionChangeOut` | no | Changes. |

### `McpEndpointListResponse` {#schema-mcpendpointlistresponse}

McpEndpointListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoints` | array of `McpEndpointOut` | yes | Endpoints. |

### `McpEndpointNoteCreate` {#schema-mcpendpointnotecreate}

Body for creating a cataloger note.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `body` | string | yes | Body. |

### `McpEndpointNoteListResponse` {#schema-mcpendpointnotelistresponse}

Envelope for a cataloger-notes list.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `notes` | array of [`McpEndpointNoteOut`](#schema-mcpendpointnoteout) | no | Notes. |

### `McpEndpointNoteOut` {#schema-mcpendpointnoteout}

One cataloger note on an MCP endpoint (human commentary, not server-reported data).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `endpointId` | string | yes | Endpoint ID. |
| `body` | string | yes | Body. |
| `createdBy` | string | yes | Created By. |
| `createdByName` | string or null | no | Created By Name. |
| `createdByEmail` | string or null | no | Created By Email. |
| `updatedBy` | string or null | no | Updated By. |
| `updatedByName` | string or null | no | Updated By Name. |
| `updatedByEmail` | string or null | no | Updated By Email. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) | yes | Updated At. |

### `McpEndpointNoteUpdate` {#schema-mcpendpointnoteupdate}

Patch body for updating a cataloger note.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `body` | string or null | no | Body. |

### `McpEndpointResponse` {#schema-mcpendpointresponse}

McpEndpointResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint` | `McpEndpointOut` | yes | Endpoint. |

### `McpEndpointTestRequest` {#schema-mcpendpointtestrequest}

Invoke one cataloged capability against its live MCP server and report the result.

Names the capability to exercise on the endpoint's *current* discovered surface and the
arguments to call it with. ``item_type`` selects the invocation method
(``tool`` → ``tools/call``, ``resource`` → ``resources/read``, ``prompt`` → ``prompts/get``);
``item_name`` is the capability's discovered name (for a resource, its name — the route resolves
it to the stored concrete ``uri``). ``arguments`` is validated against a tool's stored
``inputSchema`` (and a prompt's required arguments) before the call leaves the server.

``auth_override`` supplies an ephemeral credential for this one call only (never persisted);
when omitted the endpoint's stored credential is used. ``timeout_seconds`` bounds each request
in the connect → handshake → invoke sequence.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `itemType` | string | yes | The capability kind to invoke: 'tool', 'resource', or 'prompt'. |
| `itemName` | string | yes | The discovered capability name (a resource's name resolves to its uri). |
| `arguments` | object | no | Call arguments; validated against a tool's stored inputSchema. |
| `authOverride` | `McpAuthOverride` or null | no | Ephemeral credential for this call only (never persisted). |
| `timeoutSeconds` | number | no | Per-request timeout in seconds for the test call (1-120). |
| `confirm` | boolean | no | Explicit acknowledgement required to invoke a tool whose annotations flag it as destructive (destructiveHint) or open-world (openWorldHint). Ignored for safe tools. |

### `McpEndpointTestResponse` {#schema-mcpendpointtestresponse}

The outcome of one test-harness invocation: content, error, and latency.

A single shape covers the three outcomes the invocation service distinguishes, branchable on two
booleans (see :class:`app.mcp_invoke.InvocationResult`):

* ``completed=True,  is_error=False`` — the call ran and succeeded; ``content`` holds the result.
* ``completed=True,  is_error=True``  — the call ran but the tool reported a tool-level error
  (``tools/call`` only); ``content`` holds the error payload the tool produced.
* ``completed=False`` — the call failed (a JSON-RPC protocol error or a transport/handshake
  failure); ``error`` carries the classified reason and ``content`` is empty.

``auth_override_applied`` records whether the call used an ephemeral override (``True``) or the
endpoint's stored credential (``False``); the secret itself is never included either way.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpointId` | string | yes | Endpoint ID. |
| `itemType` | string | yes | Item Type. |
| `itemName` | string | yes | Item Name. |
| `method` | string | yes | The JSON-RPC method invoked (e.g. 'tools/call'). |
| `target` | string | yes | What was invoked: a tool/prompt name, or a resource uri. |
| `completed` | boolean | yes | True when the server returned a JSON-RPC result (success or tool error). |
| `isError` | boolean | yes | True when a tool ran but reported a tool-level error (tools/call only). |
| `content` | array of object | no | Returned payload items (tool content / resource contents / prompt messages). |
| `structuredContent` | object or null | no | A tool's optional structuredContent object, when present. |
| `latencyMs` | number | yes | Round-trip wall-clock in ms (connect + handshake + invoke). |
| `error` | object or null | no | The classified failure when completed is False; null otherwise. |
| `authOverrideApplied` | boolean | no | True when an ephemeral auth override was used instead of stored credentials. |
| `invocationId` | string or null | no | Id of the persisted mcp_test_invocations log row, or null if logging failed. |

### `McpEndpointUpdate` {#schema-mcpendpointupdate}

Patch mutable fields on a catalog endpoint (MCAT-3.1).

Every field is optional; only the keys present in the request body are
applied. ``slug`` is intentionally not patchable here — it is derived on
create and stable thereafter so existing references do not break.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `endpointUrl` | string or null | no | Endpoint URL. |
| `transport` | string or null | no | Transport. |
| `description` | string or null | no | Free-text description. |
| `category` | string or null | no | Classification category for the primitive type. |
| `visibility` | string or null | no | Visibility. |
| `published` | boolean or null | no | Published. |
| `enabled` | boolean or null | no | Whether the resource is active. |
| `discoveryCadenceSeconds` | integer or null | no | Discovery Cadence Seconds. |

### `McpEndpointVersionListResponse` {#schema-mcpendpointversionlistresponse}

Response envelope for an endpoint's version history (newest first).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `versions` | array of `McpEndpointVersionSummary` | yes | Versions. |

### `McpEndpointVersionResponse` {#schema-mcpendpointversionresponse}

Response envelope for a single version's full surface.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `version` | `McpEndpointVersionDetail` | yes | Version. |

### `McpEndpointViewMarkRequest` {#schema-mcpendpointviewmarkrequest}

Body for advancing a user's seen-marker (V2-MCP-30.5 / MCAT-16.5).

``version_id`` is the snapshot the client acknowledges having seen — normally the endpoint's
current version, passed explicitly so the marker records exactly what the user saw even if a
discovery advances "current" between the digest read and this call. When omitted the server
marks the endpoint's current version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string or null | no | Project version identifier or semantic version label, depending on context. |

### `McpEndpointViewResponse` {#schema-mcpendpointviewresponse}

Response for a recorded view: the advanced seen-marker (V2-MCP-30.5 / MCAT-16.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `last_seen_version_id` | string or null | no | Last Seen Version ID. |
| `seen_at` | string or null | no | Seen At timestamp (ISO 8601). |

### `McpFacetedSearchResponse` {#schema-mcpfacetedsearchresponse}

Response envelope of the faceted catalog search (MCAT-21.1).

``endpoints`` is the requested page of matches (browse-shaped rows, each carrying its facet
fields), ``count`` its length, and ``total`` the full match count across pages. ``facets``
holds the live bucket counts over the same filtered set, so the counts always describe
exactly the result the filters produced. An empty match is a valid response — empty page,
zero total, empty buckets — never an error.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `total` | integer | no | Total. |
| `count` | integer | no | Number of count. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |
| `endpoints` | array of `McpBrowseEndpointOut` | no | Endpoints. |
| `facets` | `McpCatalogFacetsOut` | no | Facets. |

### `McpFreshnessReportResponse` {#schema-mcpfreshnessreportresponse}

Freshness report over the caller's catalog — only non-fresh endpoints are listed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `default_cadence_seconds` | integer | yes | Default Cadence Seconds. |
| `flagged_endpoint_count` | integer | yes | Number of flagged endpoint. |
| `endpoints` | array of `McpFreshnessEndpointOut` | yes | Endpoints. |

### `McpInsightCatalogResponse` {#schema-mcpinsightcatalogresponse}

Response envelope for the tenant-wide catalog insight roll-up (feeds 18.1).

Spans every live endpoint the caller's tenant owns: how many there are, how many are published
/ discovered, the per-kind capability ``type_counts`` summed across every endpoint's current
surface, the ``average_score`` over scored current versions, and the A-F ``grade_distribution``.

The composition breakdowns power the catalog analytics dashboard's tiles: ``category_distribution``
/ ``transport_distribution`` / ``protocol_version_distribution`` / ``discovery_health`` (labelled
buckets, busiest first), ``tool_count_distribution`` (a fixed-bucket histogram of per-endpoint tool
counts), ``change_leaders`` (the most-churned endpoints), and ``top_capabilities`` (the most widely
exposed capability names). All default to empty, so an empty catalog yields an all-empty — never a
500 — body.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_count` | integer | no | Number of endpoint. |
| `published_count` | integer | no | Number of published. |
| `public_count` | integer | no | Number of public. |
| `private_count` | integer | no | Number of private. |
| `discovered_count` | integer | no | Number of discovered. |
| `scored_count` | integer | no | Number of scored. |
| `average_score` | number or null | no | Average Score. |
| `type_counts` | `McpTypeCountsOut` | yes | Type Counts. |
| `grade_distribution` | map of integer | no | Grade Distribution. |
| `category_distribution` | array of `McpCatalogBucketOut` | no | Category Distribution. |
| `transport_distribution` | array of `McpCatalogBucketOut` | no | Transport Distribution. |
| `protocol_version_distribution` | array of `McpCatalogBucketOut` | no | Protocol Version Distribution. |
| `tool_count_distribution` | array of `McpCatalogBucketOut` | no | Tool Count Distribution. |
| `discovery_health` | array of `McpCatalogBucketOut` | no | Discovery Health. |
| `change_leaders` | array of `McpCatalogLeaderOut` | no | Change Leaders. |
| `top_capabilities` | array of `McpCatalogCapabilityOut` | no | Top Capabilities. |

### `McpInsightEvolutionResponse` {#schema-mcpinsightevolutionresponse}

Response envelope for an endpoint's evolution series (oldest snapshot first).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `series` | array of `McpEvolutionPoint` | no | Series. |

### `McpInsightGraphResponse` {#schema-mcpinsightgraphresponse}

Response envelope for the capability relationship graph of one version snapshot.

Carries the resolved snapshot identity (``version_id`` / ``version_seq`` / ``version_tag`` and
whether it is the endpoint's ``is_current`` surface) alongside the inferred ``graph`` (nodes and
concrete-signal edges) for that surface.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `version_seq` | integer | yes | Version Seq. |
| `version_tag` | string or null | no | Version Tag. |
| `is_current` | boolean | no | Whether current. |
| `graph` | `McpCapabilityGraphOut` | yes | Graph. |

### `McpInsightPercentileResponse` {#schema-mcpinsightpercentileresponse}

Response envelope for an endpoint's peer percentile & category ranking (MCAT-18.3).

Ranks the endpoint against the other live endpoints in its catalog ``category`` on four axes
(grade, safety, documentation, latency), so the UI can render "top 10% for documentation"-style
badges — a *peer baseline*, not an absolute grade. A single-member category yields a coherent
profile (the sole server is the category leader), and any axis the server has not measured is an
explicit gap, so an undiscovered or never-tested endpoint returns a ``200``, never a ``500``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `profile` | `McpPeerPercentileOut` | yes | Profile. |

### `McpInsightReliabilityResponse` {#schema-mcpinsightreliabilityresponse}

Response envelope folding an endpoint's discovery and invocation reliability together.

``discovery`` / ``invocation`` are the aggregate roll-ups (state tallies, success/error rates,
latency); ``health`` adds the MCAT-17.1 discovery health timeline — the recent per-job outcome
events, a windowed availability percentage, and the endpoint's quarantine / backoff state;
``tools`` adds the MCAT-17.2 per-tool latency & error-rate breakdown (p50/p95/p99 and error rate
per tool, a latency distribution, and the endpoint-wide totals) over a recent window.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `discovery` | `McpDiscoveryReliabilityOut` | yes | Discovery. |
| `invocation` | `McpInvocationReliabilityOut` | yes | Invocation. |
| `health` | `McpDiscoveryHealthOut` | yes | Health. |
| `tools` | `McpToolInvocationReliabilityOut` | yes | Tools. |

### `McpInsightSurfaceResponse` {#schema-mcpinsightsurfaceresponse}

Response envelope for the capability-surface metrics of one version snapshot.

Carries the resolved snapshot identity (``version_id`` / ``version_seq`` / ``version_tag`` and
whether it is the endpoint's ``is_current`` surface) alongside the deterministic ``metrics``
roll-up for that surface.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `version_seq` | integer | yes | Version Seq. |
| `version_tag` | string or null | no | Version Tag. |
| `is_current` | boolean | no | Whether current. |
| `metrics` | `McpSurfaceMetricsOut` | yes | Metrics. |

### `McpInsightTrustResponse` {#schema-mcpinsighttrustresponse}

Response envelope for an endpoint's composite trust profile radar (MCAT-17.4).

``profile`` carries the five normalized axes (quality, safety, documentation, stability,
responsiveness), each 0-100 or an explicit gap, plus the mean of the available axes. It is an
explicitly heuristic composite — a synthesized "trust glance", not an official rating.
``version_id`` is the current snapshot the surface-derived axes (quality / safety /
documentation) were read from, or ``None`` when the endpoint has never been discovered;
``auth_type`` is the endpoint's configured scheme the safety axis cross-references.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `version_id` | string or null | no | Project version identifier or semantic version label, depending on context. |
| `auth_type` | string or null | no | Auth Type. |
| `profile` | `McpTrustProfileOut` | yes | Profile. |

### `McpLintReportResponse` {#schema-mcplintreportresponse}

Server-computed lint score + itemized findings for one MCP version snapshot (#3686).

The MCP catalog analogue of :class:`LintReportResponse`: the deterministic 0-100 ``score``,
its A-F ``grade``, the per-rule/per-severity tallies, the stable ``report_fingerprint``, and
every itemized finding for a discovery snapshot's normalized surface. ``source`` records
whether the report was served from the persisted ``mcp_version_scores`` row (``stored``) or
computed live for this request (``computed``); ``scored_at`` is the persisted timestamp (only
present when the report came from / was written to storage).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpointId` | string | yes | Endpoint ID. |
| `versionId` | string | yes | The version snapshot's id (mcp_endpoint_versions.id). |
| `versionSeq` | integer | yes | The snapshot's monotonic sequence number under its endpoint. |
| `versionTag` | string or null | no | Human-readable date/time tag for the snapshot, when present. |
| `score` | integer | yes | Deterministic 0-100 quality score. |
| `grade` | string | yes | A-F letter grade derived from the score. |
| `findings` | array of `LintFindingOut` | yes | Findings. |
| `ruleHits` | map of integer | no | Count of findings per rule id (deterministic). |
| `severityCounts` | map of integer | no | Count of findings per severity (error/warning/info). |
| `reportFingerprint` | string | yes | Stable hash over score, grade, and findings for a fixed surface. |
| `source` | string | yes | Where the report came from: 'stored' (persisted) or 'computed' (live). |
| `scoredAt` | string or null | no | When the persisted score was last (re)computed, when applicable. |
| `algorithmId` | string or null | no | Multi-axis scoring algorithm id (CLX-1.2), e.g. clx-axis-v1. |
| `axes` | array of `LintAxisOut` or null | no | Per-axis scores and coverage (CLX-1.2). Null when not evaluated. |
| `compositeScore` | integer or null | no | Weighted composite when required coverage is met; null otherwise. |
| `compositeGrade` | string or null | no | A-F grade of the composite; null when compositeScore is null. |
| `requiredCoverageMet` | boolean or null | no | True when required axes (v1: quality) are assessed. |

### `McpPostureRulesResponse` {#schema-mcpposturerulesresponse}

The trust-posture rule catalog, profiles, and OWASP risk catalog (CLX-3.2, #4856).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `owaspRevision` | string | yes | The OWASP MCP Top 10 revision this rule set's mapping tracks. |
| `profiles` | array of `McpPostureProfileOut` | yes | Profiles. |
| `rules` | array of `McpPostureRuleOut` | yes | Rules. |
| `owaspRisks` | array of `McpOwaspRiskOut` | yes | Owasp Risks. |

### `McpSavedSearchCreate` {#schema-mcpsavedsearchcreate}

Request body for creating a saved search.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `filters` | `McpSavedSearchFiltersOut` | no | Filters. |
| `query` | string | no | Query. |
| `sort` | string | no | Sort. |
| `isPinned` | boolean | no | Is Pinned. |

### `McpSavedSearchListResponse` {#schema-mcpsavedsearchlistresponse}

Envelope for listing saved searches.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `searches` | array of [`McpSavedSearchOut`](#schema-mcpsavedsearchout) | no | Searches. |

### `McpSavedSearchOut` {#schema-mcpsavedsearchout}

One saved catalog search owned by the caller.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `filters` | `McpSavedSearchFiltersOut` | yes | Filters. |
| `query` | string | no | Query. |
| `sort` | string | no | Sort. |
| `isPinned` | boolean | no | Is Pinned. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) | yes | Updated At. |

### `McpSavedSearchRunResponse` {#schema-mcpsavedsearchrunresponse}

Saved search definition plus the faceted result of running its facet-compatible filters.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `search` | [`McpSavedSearchOut`](#schema-mcpsavedsearchout) | yes | Search. |
| `result` | [`McpFacetedSearchResponse`](#schema-mcpfacetedsearchresponse) | yes | Result. |

### `McpSavedSearchUpdate` {#schema-mcpsavedsearchupdate}

Request body for patching a saved search (all fields optional).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `filters` | `McpSavedSearchFiltersOut` or null | no | Filters. |
| `query` | string or null | no | Query. |
| `sort` | string or null | no | Sort. |
| `isPinned` | boolean or null | no | Is Pinned. |

### `McpSbomAttachRequest` {#schema-mcpsbomattachrequest}

Request to attach a CycloneDX/SPDX SBOM to a linked source (CLX-3.2, #4856).

The document is read for component **coordinates only** — name / version / purl / license.
Source and file contents are never extracted or stored; the SBOM model has no field for them.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `document` | object | yes | A parsed CycloneDX (with 'bomFormat') or SPDX (with 'spdxVersion') document. |
| `subject_digest` | string or null | no | The artifact digest this inventory describes. Defaults to the source's own pinned digest; required when the source is not pinned, since an inventory must name the specific artifact it inventories. |

### `McpSbomOut` {#schema-mcpsbomout}

The dependency inventory of a source artifact — coordinates only (CLX-3.2, #4856).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `sourceId` | string | yes | Source ID. |
| `subjectDigest` | string | yes | Subject Digest. |
| `sbomFormat` | string | yes | Sbom Format. |
| `origin` | string | yes | operator_supplied (authoritative) \| manifest_derived (best-effort). |
| `componentCount` | integer | yes | Number of component. |
| `sbomFingerprint` | string or null | no | Sbom Fingerprint. |
| `authoritative` | boolean | yes | Whether this inventory came from a real SBOM rather than lockfile derivation. |

### `McpSearchResponse` {#schema-mcpsearchresponse}

Response envelope for a catalog search — ranked hits plus the echoed query/scope (MCAT-9.2).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `query` | string | yes | Query. |
| `scope` | string or null | no | Scope. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |
| `count` | integer | yes | Number of count. |
| `hits` | array of `McpSearchHit` | yes | Hits. |

### `McpServerDigestGenerateResponse` {#schema-mcpserverdigestgenerateresponse}

Response envelope for the gated digest generation step (MCAT-18.5).

Extends :class:`McpServerDigestResponse` with the outcome of a ``POST …/insight/digest/generate``:
``generated`` is true only when the model actually produced (and cached) a digest on this call;
``from_cache`` is true when an already-cached digest for the current surface was returned without
calling the model. When the feature flag is off, no API key is configured, the surface has nothing to
summarize, or the model call fails, ``generated`` is false and ``detail`` explains why — always a
``200`` describing the no-op, never an error.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `version_id` | string or null | no | Project version identifier or semantic version label, depending on context. |
| `surface_fingerprint` | string or null | no | Surface Fingerprint. |
| `ai_digest_enabled` | boolean | no | Ai Digest Enabled. |
| `ai_generated` | boolean | no | Ai Generated. |
| `digest` | string or null | no | Digest. |
| `model` | string or null | no | Model. |
| `generated_at` | string or null | no | Generated At timestamp (ISO 8601). |
| `tool_count` | integer | no | Number of tool. |
| `examples` | array of `McpToolExampleOut` | no | Examples. |
| `generated` | boolean | no | Generated. |
| `from_cache` | boolean | no | From Cache. |
| `detail` | string | no | Detail. |

### `McpServerDigestResponse` {#schema-mcpserverdigestresponse}

Response envelope for an endpoint's natural-language digest + usage examples (MCAT-18.5).

Pairs an **AI-generated** plain-language summary of the server (``digest`` — clearly labelled AI
content, ``null`` until generated) with one **deterministic, schema-derived example call per tool**
(``examples`` — always present, computed offline from the current surface, never requiring the model
or tool execution). ``ai_digest_enabled`` reflects the ``APIOME_MCP_AI_DIGEST_ENABLED`` feature flag
so the UI knows whether a "generate" action is available. The digest is cached per
``surface_fingerprint`` and regenerated when the surface changes; ``model`` / ``generated_at`` record
the provenance of a cached digest. A never-discovered endpoint yields empty ``examples`` and a ``null``
digest — a ``200``, never a ``500``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `version_id` | string or null | no | Project version identifier or semantic version label, depending on context. |
| `surface_fingerprint` | string or null | no | Surface Fingerprint. |
| `ai_digest_enabled` | boolean | no | Ai Digest Enabled. |
| `ai_generated` | boolean | no | Ai Generated. |
| `digest` | string or null | no | Digest. |
| `model` | string or null | no | Model. |
| `generated_at` | string or null | no | Generated At timestamp (ISO 8601). |
| `tool_count` | integer | no | Number of tool. |
| `examples` | array of `McpToolExampleOut` | no | Examples. |

### `McpSimilarReindexResponse` {#schema-mcpsimilarreindexresponse}

Response envelope for the similar-servers embedding backfill (MCAT-18.4).

Records the outcome of (re)computing and storing this endpoint's current-snapshot capability
embedding for the semantic similarity signal. ``embeddings_enabled`` reflects the feature flag;
``reindexed`` is true only when an embedding was actually generated and stored. When the flag is off,
the endpoint has no discovered surface, or the embedding service / pgvector is unavailable,
``reindexed`` is false and ``detail`` explains why — always a ``200`` describing the no-op, never an
error.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `embeddings_enabled` | boolean | no | Embeddings Enabled. |
| `reindexed` | boolean | no | Reindexed. |
| `version_id` | string or null | no | Project version identifier or semantic version label, depending on context. |
| `detail` | string | no | Detail. |

### `McpSimilarServersResponse` {#schema-mcpsimilarserversresponse}

Response envelope for an endpoint's "similar servers" discovery (MCAT-18.4).

Surfaces "servers like this one" from two independent signals, each ranked against the caller's own
live catalog: ``overlap`` — always present — ranks peers by capability-name Jaccard overlap;
``semantic`` ranks peers by cosine nearest-neighbour over a capability embedding, and is only
populated when ``embeddings_enabled`` is true (the flag is on and both this endpoint and at least one
peer have a backfilled embedding). When embeddings are disabled or unbackfilled, ``embeddings_enabled``
is false and ``semantic`` is empty — the feature gracefully falls back to overlap-only, never a
``500``. ``target_capability_count`` is this endpoint's own distinct capability-name count (``0`` when
it was never discovered, in which case ``overlap`` is empty too).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpoint_id` | string | yes | Endpoint ID. |
| `embeddings_enabled` | boolean | no | Embeddings Enabled. |
| `target_capability_count` | integer | no | Number of target capability. |
| `overlap` | array of `McpSimilarOverlapNeighborOut` | no | Overlap. |
| `semantic` | array of `McpSimilarEmbeddingNeighborOut` | no | Semantic. |

### `McpSourceLinkRequest` {#schema-mcpsourcelinkrequest}

Request to link a source artifact to an MCP endpoint (CLX-3.2, #4856).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `source_kind` | string | yes | git \| package \| image \| registry. |
| `reference` | string | yes | The source reference. A git remote URL, a Package URL, an OCI image reference, or an MCP registry server id — meaning depends on source_kind. |
| `revision` | string or null | no | For git, the branch / tag / commit sha. A full 40-hex commit pins the source; a branch or tag leaves it a moving reference (verification_state 'unverified'). |
| `provenance` | string | no | How this association is known: operator_declared \| registry_published \| discovery_advertised \| attested. Never inferred. |

### `McpSourceListResponse` {#schema-mcpsourcelistresponse}

An endpoint's linked source associations (CLX-3.2, #4856).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `endpointId` | string | yes | Endpoint ID. |
| `sources` | array of `McpSourceOut` | yes | Sources. |

### `McpSourceResponse` {#schema-mcpsourceresponse}

A single linked source association (CLX-3.2, #4856).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `source` | `McpSourceOut` | yes | Provenance source for the record (for example human or imported). |

### `McpSurfaceLintRulesResponse` {#schema-mcpsurfacelintrulesresponse}

MCP surface-lint rule catalog (CLX-4.3, #4861).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `transparencyRevision` | string | yes | Revision of the blocking-rule transparency catalog. |
| `docsPage` | string | yes | Repository-relative docs page for MCP surface lint rules. |
| `rules` | array of `McpSurfaceLintRuleOut` | yes | Rules. |
| `count` | integer | yes | Number of count. |

### `McpVersionChangesResponse` {#schema-mcpversionchangesresponse}

Response envelope for a version's stored ``previous → this`` change report.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `version_seq` | integer | yes | Version Seq. |
| `counts` | `McpVersionChangeCounts` | yes | Counts. |
| `changes` | array of `McpVersionChangeOut` | yes | Changes. |

### `McpVersionCompareResponse` {#schema-mcpversioncompareresponse}

On-demand structured diff between any two versions, normalized older→newer.

``base``/``target`` are returned in chronological order regardless of the order they were
requested, so ``added``/``removed`` always read relative to the older surface.
``fingerprint_changed`` is ``False`` exactly when the two surfaces are semantically
identical (equal fingerprints) — including ``base == target``, which yields an empty diff.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `base` | `McpVersionRef` | yes | Base. |
| `target` | `McpVersionRef` | yes | Target. |
| `fingerprint_changed` | boolean | yes | Fingerprint Changed. |
| `counts` | `McpVersionChangeCounts` | yes | Counts. |
| `changes` | array of `McpVersionChangeOut` | yes | Changes. |
