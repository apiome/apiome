---
title: "Primitives"
description: "REST endpoints tagged primitives: 12 operations."
sidebar_position: 47
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `primitives` · 12 operations

## `GET /v1/primitives/health` {#registry-health-v1-primitives-health-get}

**Registry Health**

Health/ping for the Primitives type-registry layer (#3450).

Reports whether the registry's storage backend — the shared
``apiome-db`` connection backing ``apiome.primitives`` — is reachable.
Like the global ``/health`` endpoint this is intentionally anonymous so
monitors can probe the registry layer without credentials; every data
access endpoint below remains authenticated and tenant-scoped.

Registered before ``GET /{tenant_slug}`` so the literal ``health`` path is
matched here rather than being captured as a tenant slug.

Returns:
    Registry health: overall ``status``, the ``apiome-db``
    ``connection`` state, and whether the ``apiome.primitives`` storage table
    is present. On failure ``status`` is ``unhealthy`` and ``error`` carries
    the driver message; the endpoint itself still responds 200 so the probe
    is always reachable (mirrors the global ``/health`` contract).

Operation id: `registry_health_v1_primitives_health_get`

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for registry health. | `application/json` [`RegistryHealthResponse`](#schema-registryhealthresponse) |

## `GET /v1/primitives/{tenant_slug}` {#list-primitives-v1-primitives-tenant-slug-get}

**List Primitives**

List a tenant's primitives — unbounded by default, bounded on request (DWX-3.1, #2683).

Two shapes behind one path, and which one a caller gets is decided by the question it asked:

- **No bounded parameter** — the classic behaviour, unchanged: a JSON array of every primitive
  the tenant can see, optionally filtered by ``category``. The classic property dialogs read
  this and are unaffected by this ticket.
- **Any of ``q``, ``scope``, ``namespace``, ``limit`` or ``cursor``** — a
  :class:`~app.models.PrimitiveSearchPage`: at most ``limit`` rows, the four type-picker tab
  counts for the query, and a cursor to continue with. A tenant that has imported a standard
  library has thousands of rows, and no surface in the unified workspace may read a catalog of
  that size; this is the shape that lets the type picker exist.

The two shapes list the same catalog — the same visibility scope, the same
``(namespace, name)`` deduplication — so a primitive is never visible through one and not the
other. See :mod:`app.primitives_search_store`.

Supports authentication via:
- JWT token in Authorization header (Bearer token)
- API key in X-API-Key header

Args:
    tenant_slug: The tenant slug. Decorative: the authoritative tenant is the token's, so a
        slug naming another tenant cannot widen what this returns.
    category: Optional category filter, honoured by both shapes.
    q: Optional text to match; see :data:`_SEARCH_Q_DESCRIPTION`.
    scope: Optional type-picker tab to restrict to.
    namespace: Optional exact namespace filter.
    limit: Optional page size, clamped to :data:`app.primitives_search_store.MAX_LIMIT`.
    cursor: Optional opaque continuation token.
    auth_data: Authentication data (injected by dependency)

Returns:
    Every visible primitive, or one bounded page of them with the tab counts.

Raises:
    HTTPException: 400 when ``scope`` is not one of the four tabs, or when ``cursor`` did not
        come from this endpoint.

Operation id: `list_primitives_v1_primitives__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `category` | query | string or null | no | Filter by category |
| `q` | query | string or null | no | Text to match, case-insensitively, anywhere in a primitive's name, namespace, registry $ref, description or tags — the five fields the type picker's client-side filter has always spanned — or in its JSON Schema $id. '%' and '_' match themselves rather than acting as wildcards. Asking this, or any other bounded parameter, switches the response to the paged envelope. |
| `scope` | query | string or null | no | Restrict to one type-picker tab: standard, core, tenant, custom. Classified server-side exactly as the designer's `classifyPrimitive` classifies it, so a tab and its badge can never disagree. An unrecognized value is a 400, never an empty page. |
| `namespace` | query | string or null | no | Restrict to one registry namespace, e.g. `std/v0/types`. Matched exactly against the namespace with its trailing slashes removed; child namespaces are not included. |
| `limit` | query | integer or null | no | Rows to return. Default 25, clamped to 100; 0 returns the tab counts alone. No response ever exceeds it — that bound is the reason this endpoint exists. |
| `cursor` | query | string or null | no | Opaque token from a previous response's `next_cursor`, to continue after its last row. Keyset rather than an offset, so a primitive created mid-scroll cannot make a row repeat or vanish. A token this endpoint did not mint is a 400. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list primitives. | `application/json` array of [`PrimitiveSchema`](#schema-primitiveschema) or [`PrimitiveSearchPage`](#schema-primitivesearchpage) |
| 400 | Unknown `scope`, or a `cursor` this endpoint did not mint. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/primitives/{tenant_slug}` {#create-primitive-v1-primitives-tenant-slug-post}

**Create Primitive**

Create a new primitive.

Supports authentication via JWT token or API key.
When using JWT, the created_by field will be set to the authenticated user.

Args:
    tenant_slug: The tenant slug
    request: Primitive creation data
    auth_data: Authentication data (injected by dependency)

Returns:
    The created primitive

Operation id: `create_primitive_v1_primitives__tenant_slug__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create primitive.

- `application/json` — [`PrimitiveCreateRequest`](#schema-primitivecreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create primitive. | `application/json` [`PrimitiveSchema`](#schema-primitiveschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/primitives/{tenant_slug}/import` {#import-primitives-v1-primitives-tenant-slug-import-post}

**Import Primitives**

Import primitives from a JSON Schema document or an Apiome type-def bundle.

For ``source_kind='json-schema'`` (the default) and ``'openapi'``, type definitions are
extracted from the document's ``$defs`` / ``definitions`` and each becomes a primitive.
For ``source_kind='type-def-bundle'`` (#3462), the request ``schema`` is expanded as an
Apiome type-definition bundle — its ``types`` (or ``$defs`` / ``definitions``)
container is read into many interlinked types, each committed as a primitive with its
inter-type ``$ref`` edges captured in the ``refs`` JSONB column for the rewrite stage
(#3463). A bundle of N types imports N rows; a malformed bundle is rejected with a clear
400 error.

Supports authentication via JWT token or API key.
When using JWT, the created_by field will be set to the authenticated user.

Args:
    tenant_slug: The tenant slug
    request: Import request with the JSON Schema document or bundle
    auth_data: Authentication data (injected by dependency)

Returns:
    Summary of imported primitives plus the id of the recorded provenance row.

Operation id: `import_primitives_v1_primitives__tenant_slug__import_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for import primitives.

- `application/json` — [`PrimitiveImportRequest`](#schema-primitiveimportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for import primitives. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/primitives/{tenant_slug}/import/review` {#review-import-primitives-v1-primitives-tenant-slug-import-review-post}

**Review Import Primitives**

Dry-run review of an import: conflicts, dedupe, and a validation report (#3464).

Resolves the source exactly as ``POST /import`` would, but **writes nothing** — it
classifies each definition against the registry (New / Identical / Conflict), attaches its
draft 2020-12 validation report and unresolved-ref mapping, and lists the resolution
choices each conflict offers. This is the report the import wizard (#3469) renders so the
user can pick keep / overwrite / rename before committing; the same classification drives
the commit, so the committed result matches the review.

Args:
    tenant_slug: The tenant slug.
    request: The import request (source document + options); ``resolutions`` is ignored.
    auth_data: Authentication data (injected by dependency).

Returns:
    A ``{"status": "review", "summary", "types", ...}`` report.

Operation id: `review_import_primitives_v1_primitives__tenant_slug__import_review_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for review import primitives.

- `application/json` — [`PrimitiveImportRequest`](#schema-primitiveimportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for review import primitives. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/primitives/{tenant_slug}/import/stage` {#stage-import-v1-primitives-tenant-slug-import-stage-post}

**Stage Import**

Stage an import through the unified pipeline (#3460).

The single orchestration path for all source kinds and intake methods: it
fetches the source (paste / file / url / git), parses it (JSON or YAML),
detects the candidate types it carries (json-schema / type-def-bundle /
openapi), records a provenance row on ``apiome.primitive_imports`` marked
``staged``, and returns the staged candidates.

Nothing is committed to the registry here — parsing into discrete types
(#3461/#3462), ``$ref`` rewrite (#3463), and conflict/dedupe review (#3464)
operate on the staged result in the subsequent pipeline stages. The legacy
``POST /{tenant_slug}/import`` (paste, commit) remains supported alongside it.

Args:
    tenant_slug: The tenant slug.
    request: The staging request (source kind/method + a method locator).
    auth_data: Authentication data (injected by dependency).

Returns:
    The staged result: detected candidates plus the recorded ``import_id``.

Raises:
    HTTPException: 400 for an invalid source kind/method or missing locator,
        422 for an unparseable source, 502 for a fetch failure.

Operation id: `stage_import_v1_primitives__tenant_slug__import_stage_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for stage import.

- `application/json` — [`PrimitiveImportStageRequest`](#schema-primitiveimportstagerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for stage import. | `application/json` [`PrimitiveImportStageResult`](#schema-primitiveimportstageresult) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/primitives/{tenant_slug}/imports` {#list-primitive-imports-v1-primitives-tenant-slug-imports-get}

**List Primitive Imports**

List primitive import provenance records for a tenant, newest first (#3448).

Registered before GET /{tenant_slug}/{primitive_id} so the literal `imports`
path is not captured as a primitive id.

Args:
    tenant_slug: The tenant slug
    limit: Maximum number of records to return
    auth_data: Authentication data (injected by dependency)

Returns:
    The tenant's import provenance records.

Operation id: `list_primitive_imports_v1_primitives__tenant_slug__imports_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Max number of records to return |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list primitive imports. | `application/json` array of [`PrimitiveImportRecord`](#schema-primitiveimportrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/primitives/{tenant_slug}/imports/{import_id}` {#get-primitive-import-v1-primitives-tenant-slug-imports-import-id-get}

**Get Primitive Import**

Get a single primitive import provenance record, including its report JSON (#3448).

Args:
    tenant_slug: The tenant slug
    import_id: The import provenance record id
    auth_data: Authentication data (injected by dependency)

Returns:
    The provenance record with its full options/report payload.

Operation id: `get_primitive_import_v1_primitives__tenant_slug__imports__import_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `import_id` | path | string | yes | Path parameter identifying the import id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get primitive import. | `application/json` [`PrimitiveImportRecord`](#schema-primitiveimportrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/primitives/{tenant_slug}/unresolved` {#list-unresolved-refs-v1-primitives-tenant-slug-unresolved-get}

**List Unresolved Refs**

Report the tenant's unresolved relative-``$ref`` edges and counts (#3457).

A primitive's relative ``$ref`` values are resolved to registry edges on save/import
and flagged ``resolved`` / ``unresolved`` (#3456). This endpoint aggregates the
unresolved ones: the two top-level counts feed the registry coverage/stats KPIs
(#3454), and ``primitives`` is the per-primitive breakdown — each with only its
unresolved edges — the resolver UI lists (#3470).

Registered before ``GET /{tenant_slug}/{primitive_id}`` so the literal ``unresolved``
path is matched here rather than being captured as a primitive id.

Args:
    tenant_slug: The tenant slug.
    auth_data: Authentication data (injected by dependency).

Returns:
    ``UnresolvedRefsResponse`` with the total unresolved-edge count, the number of
    affected primitives, and the per-primitive unresolved-edge breakdown.

Operation id: `list_unresolved_refs_v1_primitives__tenant_slug__unresolved_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list unresolved refs. | `application/json` [`UnresolvedRefsResponse`](#schema-unresolvedrefsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/primitives/{tenant_slug}/{primitive_id}` {#get-primitive-v1-primitives-tenant-slug-primitive-id-get}

**Get Primitive**

Get a specific primitive by ID.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    primitive_id: The primitive ID
    auth_data: Authentication data (injected by dependency)

Returns:
    The primitive details, its ``refs`` edges each carrying the target type's
    ``target_id`` / ``target_name`` so the detail view can link through to it, and
    its ``dependents`` — the reverse index of types referencing it (#3477).

Operation id: `get_primitive_v1_primitives__tenant_slug___primitive_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `primitive_id` | path | string | yes | Primitive type identifier in the registry. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get primitive. | `application/json` [`PrimitiveSchema`](#schema-primitiveschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/primitives/{tenant_slug}/{primitive_id}` {#update-primitive-v1-primitives-tenant-slug-primitive-id-put}

**Update Primitive**

Update an existing primitive.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    primitive_id: The primitive ID
    request: Primitive update data
    auth_data: Authentication data (injected by dependency)

Returns:
    The updated primitive

Operation id: `update_primitive_v1_primitives__tenant_slug___primitive_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `primitive_id` | path | string | yes | Primitive type identifier in the registry. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update primitive.

- `application/json` — [`PrimitiveUpdateRequest`](#schema-primitiveupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update primitive. | `application/json` [`PrimitiveSchema`](#schema-primitiveschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/primitives/{tenant_slug}/{primitive_id}` {#delete-primitive-v1-primitives-tenant-slug-primitive-id-delete}

**Delete Primitive**

Delete a primitive (soft delete).

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug
    primitive_id: The primitive ID
    auth_data: Authentication data (injected by dependency)

Returns:
    Success message

Operation id: `delete_primitive_v1_primitives__tenant_slug___primitive_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `primitive_id` | path | string | yes | Primitive type identifier in the registry. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete primitive. | `application/json` map of string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PrimitiveCreateRequest` {#schema-primitivecreaterequest}

Request body for registering a new primitive type in the tenant registry.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `category` | string | yes | Classification category for the primitive type. |
| `schema` | object | yes | Embedded JSON Schema document. |
| `tags` | array of string or null | no | Associated tag labels. |
| `namespace` | string or null | no | Registry namespace segment for the primitive. |
| `base_uri` | string or null | no | Base URI used to resolve relative ``$ref`` values. |

### `PrimitiveImportRecord` {#schema-primitiveimportrecord}

Audit record for a primitives import job or batch.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `source_kind` | string | yes | Source Kind. |
| `source_label` | string or null | no | Source Label. |
| `target_namespace` | string or null | no | Target Namespace. |
| `options` | object | no | Options. |
| `report` | object | no | Report. |
| `imported_count` | integer | no | Number of imported. |
| `skipped_count` | integer | no | Number of skipped. |
| `error_count` | integer | no | Number of error. |
| `imported_by` | string or null | no | Imported By. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |

### `PrimitiveImportRequest` {#schema-primitiveimportrequest}

Import one or more JSON Schema definitions into the primitives registry, with optional deduplication and per-type conflict resolutions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schema` | object | yes | Embedded JSON Schema document. |
| `import_all` | boolean | no | Import All. |
| `selected_definitions` | array of string or null | no | Selected Definitions. |
| `source_kind` | string | no | Source Kind. |
| `source_label` | string or null | no | Source Label. |
| `target_namespace` | string or null | no | Target Namespace. |
| `map_core_formats` | boolean | no | Map Core Formats. |
| `dedupe` | boolean | no | Dedupe. |
| `resolutions` | map of `ModelsImportResolution` or null | no | Resolutions. |

### `PrimitiveImportStageRequest` {#schema-primitiveimportstagerequest}

Stage a primitives import for review before committing types.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `source_kind` | string | no | Source Kind. |
| `source_method` | string | no | Source Method. |
| `source_label` | string or null | no | Source Label. |
| `target_namespace` | string or null | no | Target Namespace. |
| `content` | string or null | no | Content. |
| `url` | string or null | no | URL. |
| `git` | `GitSourceLocator` or null | no | Git. |

### `PrimitiveImportStageResult` {#schema-primitiveimportstageresult}

Outcome of staging a primitives import, including review classifications.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `import_id` | string or null | no | Import ID. |
| `status` | string | no | Status. |
| `source_kind` | string | yes | Source Kind. |
| `source_method` | string | yes | Source Method. |
| `source_label` | string or null | no | Source Label. |
| `target_namespace` | string or null | no | Target Namespace. |
| `detected_count` | integer | no | Number of detected. |
| `candidates` | array of `StagedTypeCandidate` | no | Candidates. |
| `warnings` | array of string | no | Warnings. |

### `PrimitiveSchema` {#schema-primitiveschema}

A tenant-scoped primitive type definition in the registry, including its JSON Schema document, namespace placement, and resolved reference edges.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `name` | string | yes | Unique primitive type name within the tenant registry. |
| `description` | string or null | no | Free-text description. |
| `category` | string | yes | Classification category for the primitive type. |
| `schema` | object | yes | Embedded JSON Schema document. |
| `tags` | array of string or null | no | Associated tag labels. |
| `created_by` | string or null | no | Created By. |
| `is_system` | boolean | no | True when the primitive is shipped by the platform. |
| `is_public` | boolean | no | True when the primitive is visible outside the authoring tenant. |
| `usage_count` | integer | no | Number of live bindings referencing the primitive. |
| `source` | string | no | Provenance source for the record (for example human or imported). |
| `schema_id` | string or null | no | Canonical JSON Schema ``$id`` for the primitive. |
| `draft` | string | no | JSON Schema draft identifier (for example 2020-12). |
| `namespace` | string or null | no | Registry namespace segment for the primitive. |
| `base_uri` | string or null | no | Base URI used to resolve relative ``$ref`` values. |
| `refs` | array of object | no | Resolved and unresolved ``$ref`` edges for the primitive schema. |
| `dependents` | array of object | no | Reverse index of ``refs``: the visible types that reference this one, one entry per referencing edge. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |
| `enabled` | boolean | no | Whether the resource is active. |

### `PrimitiveSearchPage` {#schema-primitivesearchpage}

One bounded page of the primitives registry — DWX-3.1 (private-suite#2683).

What ``GET /v1/primitives/{tenant_slug}`` answers once the caller asks a bounded question
(``q``, ``scope``, ``namespace``, ``limit`` or ``cursor``). Callers that ask none of them still
get the classic unbounded array, so the pre-existing dialogs are unaffected.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `PrimitiveSearchItem` | no | At most `limit` primitives, in the picker's order. |
| `counts` | `PrimitiveScopeCounts` | no | Per-tab totals over the match set, for the picker's badges. |
| `total` | integer | no | Rows matching within the applied scope, before the limit — so a client can say its page is a slice rather than implying it is the whole. |
| `limit` | integer | no | Rows returned at most: the limit actually applied. |
| `query` | string | no | The query these rows answer, normalized (trimmed). |
| `scope` | string or null | no | The scope filter applied, if any. |
| `namespace` | string or null | no | The namespace filter applied, normalized, if any. |
| `category` | string or null | no | The category filter applied, if any. |
| `next_cursor` | string or null | no | Opaque token for the following page, or null when this was the last one. |
| `truncated` | boolean | no | More rows matched in this scope than the page carries. |

### `PrimitiveUpdateRequest` {#schema-primitiveupdaterequest}

Partial update payload for an existing primitive type definition.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `category` | string or null | no | Classification category for the primitive type. |
| `schema` | object or null | no | Embedded JSON Schema document. |
| `tags` | array of string or null | no | Associated tag labels. |
| `enabled` | boolean or null | no | Whether the resource is active. |
| `namespace` | string or null | no | Registry namespace segment for the primitive. |
| `base_uri` | string or null | no | Base URI used to resolve relative ``$ref`` values. |

### `RegistryHealthResponse` {#schema-registryhealthresponse}

Health/ping response for the Primitives type-registry layer (#3450).

Reports whether the registry's storage backend — the shared
``apiome-db`` connection backing ``apiome.primitives`` — is reachable.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | string | yes | Status. |
| `service` | string | no | Service. |
| `database` | string | no | Database. |
| `connection` | string | yes | Connection. |
| `storage_present` | boolean | no | Storage Present. |
| `error` | string or null | no | Error. |

### `UnresolvedRefsResponse` {#schema-unresolvedrefsresponse}

Tenant-wide unresolved-``$ref`` summary for the type registry (#3457).

``unresolved_ref_count`` (every unresolved edge) and ``affected_primitive_count``
(distinct primitives carrying at least one) are the KPIs consumed by the registry
coverage/stats endpoint (#3454); ``primitives`` is the per-primitive breakdown the
resolver UI lists (#3470).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `unresolved_ref_count` | integer | no | Number of unresolved ref. |
| `affected_primitive_count` | integer | no | Number of affected primitive. |
| `primitives` | array of `UnresolvedRefPrimitive` | no | Primitives. |
