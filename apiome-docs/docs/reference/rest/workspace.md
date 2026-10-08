---
title: "Workspace"
description: "REST endpoints tagged workspace: 10 operations."
sidebar_position: 82
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `workspace` · 10 operations

## `GET /v1/workspace/{tenant_slug}/custom-actions` {#list-custom-actions-v1-workspace-tenant-slug-custom-actions-get}

**List Custom Actions**

List the tenant's live custom actions, alphabetically by name.

Operation id: `list_custom_actions_v1_workspace__tenant_slug__custom_actions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list custom actions. | `application/json` [`WorkspaceCustomActionListResponse`](#schema-workspacecustomactionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/workspace/{tenant_slug}/custom-actions` {#create-custom-action-v1-workspace-tenant-slug-custom-actions-post}

**Create Custom Action**

Create a custom action in the tenant.

Operation id: `create_custom_action_v1_workspace__tenant_slug__custom_actions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create custom action.

- `application/json` — [`WorkspaceCustomActionCreate`](#schema-workspacecustomactioncreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create custom action. | `application/json` [`WorkspaceCustomActionOut`](#schema-workspacecustomactionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workspace/{tenant_slug}/custom-actions/{action_id}` {#get-custom-action-v1-workspace-tenant-slug-custom-actions-action-id-get}

**Get Custom Action**

Fetch one custom action in the tenant.

Operation id: `get_custom_action_v1_workspace__tenant_slug__custom_actions__action_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `action_id` | path | string | yes | Path parameter identifying the action id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get custom action. | `application/json` [`WorkspaceCustomActionOut`](#schema-workspacecustomactionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/workspace/{tenant_slug}/custom-actions/{action_id}` {#update-custom-action-v1-workspace-tenant-slug-custom-actions-action-id-patch}

**Update Custom Action**

Update a custom action's name, matcher, or effects.

Only supplied fields change. The cross-field rule (a consumption query needs a class subject)
is checked against the row as it *will be* — the supplied half merged over the stored half —
so a PATCH cannot leave a contradiction behind by changing one side of it.

Operation id: `update_custom_action_v1_workspace__tenant_slug__custom_actions__action_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `action_id` | path | string | yes | Path parameter identifying the action id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update custom action.

- `application/json` — [`WorkspaceCustomActionUpdate`](#schema-workspacecustomactionupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update custom action. | `application/json` [`WorkspaceCustomActionOut`](#schema-workspacecustomactionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/workspace/{tenant_slug}/custom-actions/{action_id}` {#delete-custom-action-v1-workspace-tenant-slug-custom-actions-action-id-delete}

**Delete Custom Action**

Soft-delete a custom action, freeing its name for reuse.

Operation id: `delete_custom_action_v1_workspace__tenant_slug__custom_actions__action_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `action_id` | path | string | yes | Path parameter identifying the action id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete custom action. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workspace/{tenant_slug}/version/{version_id}/classes` {#get-scoped-classes-v1-workspace-tenant-slug-version-version-id-classes-get}

**Get Scoped Classes**

Classes with their properties and tags, scoped to a selection or a domain folder.

Requesting three ids returns those three classes and nothing else, whatever the version
contains. Requesting a domain returns one page of that folder plus ``total``, so the workspace
can decide whether hydrating the rest fits its node budget before asking for it.

Operation id: `get_scoped_classes_v1_workspace__tenant_slug__version__version_id__classes_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `class_ids` | query | array of string or null | no | Explicit selection. Repeat the parameter or comma-separate the values; duplicates collapse. At most 200 ids per request — a larger selection is a 400, not a truncated response. Mutually exclusive with domain_id. |
| `domain_id` | query | string or null | no | Domain folder to list, or the literal 'shared' for items with no domain. Paginated. Mutually exclusive with the id selector. |
| `limit` | query | integer or null | no | Page size for a domain listing, default 50, clamped to 200. Ignored for an id selection, which is bounded by the id cap instead. |
| `cursor` | query | string or null | no | Opaque token from a previous next_cursor. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get scoped classes. | `application/json` [`ScopedCatalogPage`](#schema-scopedcatalogpage) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workspace/{tenant_slug}/version/{version_id}/consumption` {#get-consumption-index-v1-workspace-tenant-slug-version-version-id-consumption-get}

**Get Consumption Index**

Which operations consume which classes in this version, directly or through a parent.

Every edge carries both members, how the consumption arrives (``request``, ``parameter``,
``response.<status>``) and — for a nested one — the chain of classes it hangs off, so the
combined lens, the tree, the palette, the inspector and the status bar all render from one
request. The same facts arrive twice: flat in ``edges``, the shape the canvas draws, and rolled
up per path in ``paths``, the shape the tree nests under a path.

Operation id: `get_consumption_index_v1_workspace__tenant_slug__version__version_id__consumption_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `domain_id` | query | string or null | no | Restrict to operations on paths in this folder, or the literal 'shared' for paths with no folder. Mutually exclusive with path_ids. Nested edges may still name classes outside the folder — that is what 'nested via parent' means. |
| `path_ids` | query | array of string or null | no | Restrict to these paths. Repeat the parameter or comma-separate the values; duplicates collapse. At most 200 ids per request. Mutually exclusive with domain_id. |
| `class_ids` | query | array of string or null | no | Restrict to edges consuming these classes — 'every path that consumes X'. Filters the class side only, so it composes with domain_id or path_ids. At most 200 ids. |
| `If-None-Match` | header | string or null | no | ETag from a prior response; returns 304 when unchanged. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get consumption index. | `application/json` [`ConsumptionIndex`](#schema-consumptionindex) |
| 304 | Not modified (ETag matched If-None-Match). | — |
| 400 | Conflicting path selectors, or an id list over the cap. | — |
| 404 | Version, or scoped domain, not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workspace/{tenant_slug}/version/{version_id}/paths` {#get-scoped-paths-v1-workspace-tenant-slug-version-version-id-paths-get}

**Get Scoped Paths**

Paths with their operations, scoped to a selection or a domain folder.

The bulk form of ``GET /v1/paths/{tenant}/{version}/{path}/full``'s first query: each path
carries its operations, each operation its ``operation_id``, ``summary``, ``deprecated`` flag
and ``response_codes`` — the status codes it declares, as strings, in ascending order, empty
when it declares none. Parameters, request bodies and the responses *themselves*
(descriptions, schemas, content types, examples) stay with the per-path endpoint: those are
inspector-sized data for one selected operation, whereas a status code is a label the paths
lens draws on every lane (private-suite#2583).

Operation id: `get_scoped_paths_v1_workspace__tenant_slug__version__version_id__paths_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `path_ids` | query | array of string or null | no | Explicit selection. Repeat the parameter or comma-separate the values; duplicates collapse. At most 200 ids per request — a larger selection is a 400, not a truncated response. Mutually exclusive with domain_id. |
| `domain_id` | query | string or null | no | Domain folder to list, or the literal 'shared' for items with no domain. Paginated. Mutually exclusive with the id selector. |
| `limit` | query | integer or null | no | Page size for a domain listing, default 50, clamped to 200. Ignored for an id selection, which is bounded by the id cap instead. |
| `cursor` | query | string or null | no | Opaque token from a previous next_cursor. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get scoped paths. | `application/json` [`ScopedCatalogPage`](#schema-scopedcatalogpage) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workspace/{tenant_slug}/version/{version_id}/properties` {#search-workspace-properties-v1-workspace-tenant-slug-version-version-id-properties-get}

**Search Workspace Properties**

Which properties of this version a query names, and how many classes carry each.

Enough to draw the palette's `Properties` band with no further request: each hit carries the
usage count the band prints and the classes behind it, so ⏎ opens the top owner and the
secondary action lists the rest without asking again.

Operation id: `search_workspace_properties_v1_workspace__tenant_slug__version__version_id__properties_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `q` | query | string or null | no | The property name to search for, matched case-insensitively anywhere in the name. Shorter than 2 characters answers with no hits rather than with most of the catalog; '%' and '_' match themselves rather than acting as wildcards. |
| `limit` | query | integer or null | no | Property names to return. Default 25, clamped to 50; 0 returns no hits. 'total' always reports how many matched. |
| `owner_limit` | query | integer or null | no | Owning classes listed per property. Default 10, clamped to 50; 0 returns counts alone, which costs one statement instead of two. 'class_count' is unaffected — it always covers the whole version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for search workspace properties. | `application/json` [`WorkspacePropertySearch`](#schema-workspacepropertysearch) |
| 404 | Version not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/workspace/{tenant_slug}/version/{version_id}/summary` {#get-workspace-summary-v1-workspace-tenant-slug-version-version-id-summary-get}

**Get Workspace Summary**

Every domain folder of a version, counted, with shallow member lists.

Enough to render all three tree lens panels — combined, schemas and paths — with no further
request: each folder arrives with its four counts, its class rows (kind-labelled, so the
``Schemas`` and ``Enums & unions`` groups need no second pass) and its path rows with their
operations.

Operation id: `get_workspace_summary_v1_workspace__tenant_slug__version__version_id__summary_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `member_limit` | query | integer or null | no | Shallow member rows per folder, per kind. Default 50, clamped to 200; 0 returns counts alone, which is what a tree needs after an edit that changed a badge but not the folder on screen. Counts are unaffected — they always cover the whole folder. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get workspace summary. | `application/json` [`WorkspaceSummary`](#schema-workspacesummary) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ConsumptionIndex` {#schema-consumptionindex}

Which operations consume which classes, and how (DUW-1.4).

Computed on read from the version's own content, never persisted, and content-addressed with a
strong ``ETag`` so a repeat read is a 304 until the version changes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `scope` | string | yes | Which question was answered: 'version', 'domain' or 'path_ids'. |
| `domain_id` | string or null | no | The folder scoped to, when scope is 'domain'. Null means the 'shared/' bucket, not 'unscoped' — read scope to tell them apart. |
| `path_ids` | array of string | no | The paths scoped to, when scope is 'path_ids'. |
| `class_ids` | array of string | no | The class filter applied, if any. Combines with either path scope: it narrows the class side of every edge, never the path side. |
| `missing_ids` | array of string | no | Ids the caller named — paths or classes — that this version does not hold. Reported rather than dropped: a silently short answer would leave a hole on the canvas with no way to know why. |
| `edges` | array of `ConsumptionEdgeOut` | no | One entry per operation↔class pair, ordered by pathname, then method, then direct before nested, then class name. |
| `paths` | array of `ConsumptionPath` | no | The same facts rolled up per path — the tree's per-path Schemas block. Paths that consume nothing are absent rather than present-and-empty. |
| `link_count` | integer | yes | Edges returned — what the canvas draws and the status bar's 'N schema↔path links' chip counts. |
| `path_link_count` | integer | yes | Distinct path↔class pairs, for a status bar that counts links per path rather than per operation. |
| `depth_cap` | integer | yes | How far a nested edge may sit from its direct root. |
| `depth_capped` | boolean | no | A reference graph continued past depth_cap, so some far nested edges are not in this answer. |
| `edge_limit` | integer | yes | Most edges one response may carry. |
| `truncated` | boolean | no | The edge list was cut at edge_limit. Narrow the scope — by domain, by path set, or by class set — rather than paging: an edge only means something beside the members it connects. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ScopedCatalogPage` {#schema-scopedcatalogpage}

One bounded slice of a version's catalog (DUW-1.2).

Shared by the scoped class and path reads, because a client pages both the same way and a
second identically-shaped model would only invite the two to drift apart. ``items`` stays
loosely typed for the same reason the legacy full-version read does: a class carries JSONB
``schema``/``canvas_metadata`` and nested property rows, a path carries JSONB ``metadata`` and
operations, and pinning either here would make an additive column a breaking change.

``total`` is the size of the *whole* selection, not of this page — the folder's membership for
a domain listing — so the workspace can compare it against its node budget before hydrating
anything further.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of object | yes | Items. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | The most items this response could have carried: the effective page size for a domain listing, or the server's id cap for an explicit selection. |
| `scope` | string | yes | Which selector produced this page: 'ids' or 'domain'. |
| `domain_id` | string or null | no | The domain listed, or null for the derived 'shared/' bucket and for id selections. |
| `missing_ids` | array of string | no | Ids the caller named that resolved to nothing in this version — deleted since the selection was made, belonging to another version, or malformed. Always empty for a domain listing. |
| `next_cursor` | string or null | no | Opaque token for the following page, or null when this page is the last. Same cursor format as the export and import manifest surfaces. |

### `WorkspaceCustomActionCreate` {#schema-workspacecustomactioncreate}

Request body for creating a custom palette action.

Field-level validation (vocabulary, lengths, URL scheme) lives in
``workspace_custom_action_rules`` rather than here, so the rules stay pure, testable and
shared with PATCH; ``extra="forbid"`` still rejects unknown top-level fields at the schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `subject` | string | yes | Subject. |
| `nameContains` | string or null | no | Name Contains. |
| `effects` | array of object | yes | Effects. |

### `WorkspaceCustomActionListResponse` {#schema-workspacecustomactionlistresponse}

Envelope for listing a tenant's custom palette actions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | no | Success. |
| `actions` | array of [`WorkspaceCustomActionOut`](#schema-workspacecustomactionout) | no | Actions. |

### `WorkspaceCustomActionOut` {#schema-workspacecustomactionout}

One tenant-defined ⌘K palette action (DUW-5.5).

A declaration, never a script: the matcher (``subject`` kind plus the optional
``nameContains`` narrowing) says when the palette offers the row, and ``effects`` is an
ordered list from the closed vocabulary of ``workspace_custom_action_rules`` saying what ⏎
performs. The workspace client interprets it; nothing here executes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | The sentence the palette row draws; may carry one {subject} placeholder. |
| `subject` | enum `"class"`, `"path"`, `"property"`, `"any"` | yes | Which kind of palette subject the action offers itself for. |
| `nameContains` | string or null | no | Case-insensitive substring the subject's label must contain; null matches every subject of the kind. |
| `effects` | array of object | yes | Ordered declarative effects, each validated against the closed vocabulary. |
| `createdBy` | string or null | no | Created By. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) | yes | Updated At. |

### `WorkspaceCustomActionUpdate` {#schema-workspacecustomactionupdate}

Request body for patching a custom palette action (all fields optional).

``nameContains`` distinguishes absent from null: absent leaves the narrowing alone, an
explicit null clears it. The route reads ``model_fields_set`` to tell the two apart.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `subject` | string or null | no | Subject. |
| `nameContains` | string or null | no | Name Contains. |
| `effects` | array of object or null | no | Effects. |

### `WorkspacePropertySearch` {#schema-workspacepropertysearch}

Properties of one version whose name matches a query (DUW-5.3).

The ⌘K palette's `Properties` band in one read. The usage counts are the point: they are an
aggregate over ``apiome.class_properties`` that a client could only reproduce by hydrating
every class in the version, which is the read the unified workspace exists to delete.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | The version record UUID this searched. |
| `query` | string | yes | The query these hits answer, normalized (trimmed). |
| `properties` | array of `WorkspacePropertyHit` | no | Properties. |
| `total` | integer | yes | Property names that matched in total, before the cap — so a client can say its answer is a slice rather than implying it is the whole. |
| `limit` | integer | yes | Property names returned at most: the limit actually applied. |
| `owner_limit` | integer | yes | Owning classes per property: the limit actually applied. |
| `truncated` | boolean | no | More names matched than this response lists. |

### `WorkspaceSummary` {#schema-workspacesummary}

Every domain folder of one version, counted and shallowly listed (DUW-1.3).

One response the workspace tree renders all three lens panels from — combined, schemas and
paths — with no further request. The per-path *schema* rows the combined lens nests under a
path are the schema↔path index of DUW-1.4 and are not part of this response.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_id` | string | yes | The version record UUID this summarizes. |
| `version_badge` | string or null | no | The version's own badge, e.g. 'v2.1'. Repeated on every class row so a tree row is renderable on its own. |
| `member_limit` | integer | yes | Member rows returned per folder, per kind — the limit actually applied after clamping, not necessarily the one requested. |
| `domains` | array of `WorkspaceDomainSummary` | no | Tree order: live domains by sort_order then slug, then 'shared/' last. Empty folders are included, with zeroes. |
| `totals` | `WorkspaceDomainCounts` | yes | The same four counts across the whole version — the sum of every folder's, so a client sizing a full hydration against its node budget need not add up. |
