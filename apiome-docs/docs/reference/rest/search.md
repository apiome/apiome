---
title: "Search"
description: "REST endpoints tagged search: 1 operation."
sidebar_position: 81
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.447.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `search` · 1 operation

## `GET /v1/search/{tenant_slug}/model` {#search-normalized-model-v1-search-tenant-slug-model-get}

**Search Normalized Model**

Search the tenant's normalized model across every format (MFI-6.2, #3754).

Matches operations, types and messages of catalog items and Projects alike. Values within one
facet OR together and facets AND; each facet's counts are computed over the matches every
*other* facet keeps, so ticking a value shows exactly that many. An unknown facet value narrows
to nothing rather than failing. Matches are ranked by full-text relevance; at most 2 000 are
considered, and ``truncated`` says when that cap was reached.

Args:
    tenant_slug: The tenant slug.
    q: The search text (1–200 characters after trimming).
    kind: Element kinds to keep.
    protocol: Paradigms to keep.
    format_: Source formats to keep.
    grade: Grades to keep.
    all_versions: Search every live revision.
    limit: Page size.
    offset: Matches to skip.
    auth_data: Authentication data (injected by dependency).

Returns:
    The page of matches, the totals and the four facets.

Raises:
    HTTPException: 422 when ``q`` is blank or longer than 200 characters.

Operation id: `search_normalized_model_v1_search__tenant_slug__model_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `q` | query | string | yes | Search text: words AND together, "quoted phrases" match in order, 'or' alternates and -word excludes (Postgres websearch syntax, English stemming). |
| `kind` | query | array of string or null | no | Element kind, repeatable: operation, type, message. |
| `protocol` | query | array of string or null | no | Paradigm, repeatable: rest, rpc, event, graph, data_schema, agent (aliases such as grpc and graphql work). |
| `format` | query | array of string or null | no | Source-format key, repeatable (openapi-3.1, protobuf, …). |
| `grade` | query | array of string or null | no | Captured quality grade, repeatable: A, B, C, D, F or ungraded. |
| `all_versions` | query | boolean | no | Search every live revision instead of each project's latest. |
| `limit` | query | integer | no | Page size. |
| `offset` | query | integer | no | Matches to skip. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for search normalized model. | `application/json` [`ModelSearchResponse`](#schema-modelsearchresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ModelSearchResponse` {#schema-modelsearchresponse}

``GET /v1/search/{tenant}/model`` (MFI-6.2): matches across every format, with facets.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | yes | The search text as received (trimmed). |
| `total` | integer | yes | Matches before any facet is applied (at most the cap). |
| `matched` | integer | yes | Matches the selected facets keep. |
| `truncated` | boolean | yes | True when the search hit its cap; counts then cover the best-ranked matches only. |
| `offset` | integer | yes | Offset. |
| `limit` | integer | yes | Limit. |
| `hits` | array of `ModelSearchHit` | no | This page of matches, best first. |
| `facets` | `ModelSearchFacets` | yes | Facets. |
