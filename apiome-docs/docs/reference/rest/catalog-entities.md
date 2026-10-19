---
title: "Catalog entities"
description: "REST endpoints tagged catalog-entities: 2 operations."
sidebar_position: 13
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.253.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `catalog-entities` · 2 operations

## `GET /v1/catalog/{tenant_slug}/entities` {#list-catalog-entities-v1-catalog-tenant-slug-entities-get}

**List Catalog Entities**

List the catalog's entities across kinds, in one envelope with a `kind` discriminator.

Ordered by name (case-insensitive), then registry kind order, then id; page with `cursor`. One
bounded read per kind, whatever the page holds. Kinds the caller may not view are left out; a
`team` filter leaves out kinds that cannot have an owner (teams). An unknown `kind` is a 422 and a
malformed `cursor` a 400.

Operation id: `list_catalog_entities_v1_catalog__tenant_slug__entities_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | query | array of string or null | no | Only these kinds (repeat the parameter, or comma-separate). |
| `team` | query | string or null | no | Only entities whose owner (confirmed, else suggested) is this team slug. |
| `q` | query | string or null | no | Only entities whose name, slug or description contains this. |
| `cursor` | query | string or null | no | `pagination.nextCursor` of the previous page. |
| `limit` | query | integer | no | Page size. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list catalog entities. | `application/json` [`CatalogEntityPage`](#schema-catalogentitypage) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/entities/summary` {#summarize-catalog-entities-v1-catalog-tenant-slug-entities-summary-get}

**Summarize Catalog Entities**

Count every kind the caller may view, and compute the catalog home's callouts.

`unowned` counts live entities (of kinds that can have owners) with no confirmed owner team;
`stale` counts connectors (not paused) and enabled MCP servers whose last successful refresh is
older than twice their cadence; `shadow` is the shadow-API report's count (needs `imports:view`).
The callouts ignore `team` and `q`.

Operation id: `summarize_catalog_entities_v1_catalog__tenant_slug__entities_summary_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `team` | query | string or null | no | Count only entities this team owns. |
| `q` | query | string or null | no | Count only entities matching this text. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for summarize catalog entities. | `application/json` [`CatalogEntitySummary`](#schema-catalogentitysummary) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CatalogEntityPage` {#schema-catalogentitypage}

One page of entities, ordered by name, then kind, then id.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `CatalogEntity` | yes | Items. |
| `pagination` | `EntityPagination` | yes | Pagination. |

### `CatalogEntitySummary` {#schema-catalogentitysummary}

Every visible kind with its count, and the home callouts.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kinds` | array of `EntityKindSummary` | yes | Kinds. |
| `callouts` | `CatalogCallouts` | yes | Callouts. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
