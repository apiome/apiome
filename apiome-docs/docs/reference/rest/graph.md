---
title: "Graph"
description: "REST endpoints tagged graph: 1 operation."
sidebar_position: 29
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.237.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `graph` · 1 operation

## `GET /v1/graph/{tenant_slug}/entities/{kind}/{entity_id}/edges` {#get-entity-edges-v1-graph-tenant-slug-entities-kind-entity-id-edges-get}

**List an entity's graph edges**

The entity's edges in the catalog dependency graph. `direction` is `out` (edges from the entity, the default) or `in` (edges to it); `kind` and `provenance` filter and may repeat. `limit` is 1–500 (default 100); `truncated` is true when more edges match. Stale edges come last with `stale: true`.

Requires `projects:view`.

Operation id: `get_entity_edges_v1_graph__tenant_slug__entities__kind___entity_id__edges_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | path | string | yes | Path parameter identifying the kind segment. |
| `entity_id` | path | string | yes | Path parameter identifying the entity id segment. |
| `direction` | query | string | no | `out` or `in`. |
| `kind` | query | array of string or null | no | Edge kinds to keep. |
| `provenance` | query | array of string or null | no | Provenances to keep. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list an entity's graph edges. | `application/json` [`GraphEdgePage`](#schema-graphedgepage) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `GraphEdgePage` {#schema-graphedgepage}

One page of an entity's edges.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `edges` | array of `GraphEdge` | no | Edges. |
| `total` | integer | yes | How many edges match the filters. |
| `truncated` | boolean | yes | True when more edges match than this page holds. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
