---
title: "Graph"
description: "REST endpoints tagged graph: 4 operations."
sidebar_position: 29
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.239.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `graph` · 4 operations

## `POST /v1/graph/{tenant_slug}/blast-radius` {#post-blast-radius-v1-graph-tenant-slug-blast-radius-post}

**Ask what a change affects**

Who depends on `entity` (optionally narrowed to `pointers` into it), directly and transitively, along inbound `consumes`, `depends_on` and `runtime_calls` edges — each with its edge path, provenance and owner team — and the evidence a change invalidates: verification runs, consumer contracts, deploy-gate evaluations, SDK regeneration targets, agent-toolset tools, mock fixture packs and scenarios, and consumers pinned to a deprecated or sunset version. The direct `consumes` layer is the consumer-impact intersection, so the two agree. At most 5 levels and 2,000 entities; `truncated` is true past that. `evidence_checked: true` with empty sections means nothing is affected.

Requires `projects:view`.

Operation id: `post_blast_radius_v1_graph__tenant_slug__blast_radius_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for ask what a change affects.

- `application/json` — [`BlastRadiusInput`](#schema-blastradiusinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ask what a change affects. | `application/json` [`BlastRadiusResponse`](#schema-blastradiusresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

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

## `GET /v1/graph/{tenant_slug}/entities/{kind}/{entity}/dependencies` {#get-entity-dependencies-v1-graph-tenant-slug-entities-kind-entity-dependencies-get}

**Read an entity's declared dependencies**

Every `declared` edge the entity has — written here (`source_ref: manual`), read from its spec's `x-apiome-depends-on` (`spec`) or from a Backstage `catalog-info.yaml` in its repository (`backstage:<path>`) — and the references that resolved to nothing (`unresolved`).

`kind` is `project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`; a project or catalog item may be named by slug instead of id. Reading needs the kind's `view` and changing needs its `edit` (`projects` for projects, catalog items and MCP endpoints, `consumer_contracts` for consumers, `imports` for connectors).

Operation id: `get_entity_dependencies_v1_graph__tenant_slug__entities__kind___entity__dependencies_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | path | string | yes | Path parameter identifying the kind segment. |
| `entity` | path | string | yes | Path parameter identifying the entity segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read an entity's declared dependencies. | `application/json` [`DependenciesResponse`](#schema-dependenciesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/graph/{tenant_slug}/entities/{kind}/{entity}/dependencies` {#put-entity-dependencies-v1-graph-tenant-slug-entities-kind-entity-dependencies-put}

**Replace an entity's manual dependencies**

Replace the entity's `manual` dependencies with `dependencies` — each `{to: {kind, id} | {slug}, pointer?, note?}` — as `depends_on` edges with provenance `declared`. An empty list clears them; spec and Backstage declarations are left alone. A target that does not exist is kept under `unresolved`, not refused. At most 200 entries. Audited as `graph.dependencies.update`.

`kind` is `project`, `catalog_item`, `mcp_endpoint`, `consumer` or `connector`; a project or catalog item may be named by slug instead of id. Reading needs the kind's `view` and changing needs its `edit` (`projects` for projects, catalog items and MCP endpoints, `consumer_contracts` for consumers, `imports` for connectors).

Operation id: `put_entity_dependencies_v1_graph__tenant_slug__entities__kind___entity__dependencies_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | path | string | yes | Path parameter identifying the kind segment. |
| `entity` | path | string | yes | Path parameter identifying the entity segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace an entity's manual dependencies.

- `application/json` — [`DependenciesInput`](#schema-dependenciesinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace an entity's manual dependencies. | `application/json` [`DependenciesResponse`](#schema-dependenciesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `BlastRadiusInput` {#schema-blastradiusinput}

One blast-radius question.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `entity` | `BlastRadiusEntity` | yes | Entity. |
| `pointers` | array of string | no | JSON pointers that change (`/paths/~1pets~1{id}/get`, `/components/schemas/Pet`); empty means the whole entity. |
| `depth` | integer | no | Levels of dependents to walk (1–5). |
| `provenance` | array of string | no | Edge provenances to follow. |
| `version` | string or null | no | Version label or id for the evidence; default the latest published. |

### `BlastRadiusResponse` {#schema-blastradiusresponse}

What a change affects.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `entity` | object | yes | Entity. |
| `version` | object or null | no | The version the evidence is from. |
| `pointers` | array of string | yes | Pointers. |
| `operations` | array of string or null | no | The operations the pointers reach; `null` means every operation. |
| `depth` | integer | yes | Depth. |
| `provenance` | array of string | yes | Provenance. |
| `direct` | array of `AffectedEntity` | yes | Direct. |
| `transitive` | array of `AffectedEntity` | yes | Transitive. |
| `invalidated_evidence` | `InvalidatedEvidence` | yes | Invalidated Evidence. |
| `evidence_checked` | boolean | yes | True whenever evidence was looked for: empty means none. |
| `truncated` | boolean | yes | True when the depth or the 2,000-entity bound cut the walk short. |
| `node_count` | integer | yes | Number of node. |
| `warnings` | array of string | no | Warnings. |

### `DependenciesInput` {#schema-dependenciesinput}

The entity's complete list of manual dependencies.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `dependencies` | array of `DependencyInput` | no | Dependencies. |

### `DependenciesResponse` {#schema-dependenciesresponse}

What an entity declares it depends on, from every source.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | string | yes | Kind. |
| `entity_id` | string | yes | Entity ID. |
| `declared` | array of `GraphEdge` | no | Outgoing `declared` edges. |
| `unresolved` | array of `UnresolvedDependency` | no | Unresolved. |
| `truncated` | boolean | yes | True when the entity has more than 500 declared edges. |

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
