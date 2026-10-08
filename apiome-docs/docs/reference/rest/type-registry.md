---
title: "Type registry"
description: "REST endpoints tagged type-registry: 8 operations."
sidebar_position: 73
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `type-registry` · 8 operations

## `GET /v1/types/{tenant_slug}/namespaces` {#list-namespaces-v1-types-tenant-slug-namespaces-get}

**List Namespaces**

List namespaces visible to the tenant: system-core (``std/*``) plus the tenant's own.

Args:
    tenant_slug: The tenant slug (caller scope comes from the authenticated token).
    auth_data: Authentication data (injected by dependency).

Returns:
    Namespaces (system-core first, then alphabetical), each with its tenant-scoped type count.

Operation id: `list_namespaces_v1_types__tenant_slug__namespaces_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list namespaces. | `application/json` array of [`TypeNamespaceSchema`](#schema-typenamespaceschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/types/{tenant_slug}/namespaces` {#create-namespace-v1-types-tenant-slug-namespaces-post}

**Create Namespace**

Create a namespace.

A tenant administrator may create a tenant-scoped namespace. Creating a system-core namespace
requires a platform admin, which this API does not expose, so ``scope='system'`` is rejected
with 403 — system namespaces are read-only here.

Args:
    tenant_slug: The tenant slug.
    request: Namespace creation data.
    auth_data: Authentication data (injected by dependency).

Returns:
    The created namespace.

Operation id: `create_namespace_v1_types__tenant_slug__namespaces_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create namespace.

- `application/json` — [`TypeNamespaceCreateRequest`](#schema-typenamespacecreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create namespace. | `application/json` [`TypeNamespaceSchema`](#schema-typenamespaceschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/types/{tenant_slug}/namespaces/{namespace_id}` {#update-namespace-v1-types-tenant-slug-namespaces-namespace-id-put}

**Update Namespace**

Update a tenant namespace's base URI, version root, description, visibility, or default flag.

The namespace path itself is immutable (it links the namespace to its primitives). System-core
namespaces are read-only and return 403.

Args:
    tenant_slug: The tenant slug.
    namespace_id: The namespace row id.
    request: Namespace update data.
    auth_data: Authentication data (injected by dependency).

Returns:
    The updated namespace.

Operation id: `update_namespace_v1_types__tenant_slug__namespaces__namespace_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `namespace_id` | path | string | yes | Path parameter identifying the namespace id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update namespace.

- `application/json` — [`TypeNamespaceUpdateRequest`](#schema-typenamespaceupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update namespace. | `application/json` [`TypeNamespaceSchema`](#schema-typenamespaceschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/types/{tenant_slug}/namespaces/{namespace_id}` {#delete-namespace-v1-types-tenant-slug-namespaces-namespace-id-delete}

**Delete Namespace**

Remove a tenant namespace registration.

The namespace list is referential: ``apiome.primitives.namespace`` is a string column with no
foreign key to ``apiome.type_namespaces``, so this unregisters the namespace and leaves its
types untouched. They keep their namespace path and surface as "unregistered" on the Primitives
dashboard, from which the namespace can be registered again. ``type_count`` is returned so the
caller can report how many types are now unregistered.

System-core namespaces are read-only and return 403.

Args:
    tenant_slug: The tenant slug.
    namespace_id: The namespace row id.
    auth_data: Authentication data (injected by dependency).

Returns:
    The deleted namespace's path and the number of types left unregistered.

Operation id: `delete_namespace_v1_types__tenant_slug__namespaces__namespace_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `namespace_id` | path | string | yes | Path parameter identifying the namespace id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete namespace. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/types/{tenant_slug}/resolve` {#resolve-refs-v1-types-tenant-slug-resolve-post}

**Resolve Refs**

Re-resolve the tenant's ``$ref`` edges and return the dependency listing (#3459).

The resolver API for the UI and Designer (#3470). It walks every primitive visible to
the tenant (system-core ∪ own), re-evaluates each stored dependency edge's
resolved/unresolved status against the *current* registry — so a target created since
the edge was last computed now resolves, and a deleted one now dangles — and persists
the refreshed edges for any of the tenant's own primitives whose status changed
("re-resolve updates statuses"). Each resolved edge is enriched with its dependency
target's id and name so the response is the dependency graph the resolver UI lists.

Only primitives that carry at least one ``$ref`` edge appear in ``primitives``; the
flat system-core seed (no refs) is omitted. System-core rows are read-only, so a status
change on one is reflected in the response but never written back.

Args:
    tenant_slug: The tenant slug (caller scope comes from the authenticated token).
    auth_data: Authentication data (injected by dependency).

Returns:
    ``ResolveResponse`` with tenant-wide edge counts, the number of primitives whose
    stored statuses were updated by this pass, and the per-primitive dependency listing.

Operation id: `resolve_refs_v1_types__tenant_slug__resolve_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for resolve refs. | `application/json` [`ResolveResponse`](#schema-resolveresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/types/{tenant_slug}/settings` {#get-registry-settings-v1-types-tenant-slug-settings-get}

**Get Registry Settings**

Return the tenant's type-registry settings (#3472).

Serves the saved row when one exists. A tenant that has never saved settings receives the
model defaults with ``is_default = true`` (a pure read never materializes a row), so the
Settings UI always has a complete, effective configuration to render.

Args:
    tenant_slug: The tenant slug (caller scope comes from the authenticated token).
    auth_data: Authentication data (injected by dependency).

Returns:
    The tenant's effective type-registry settings.

Operation id: `get_registry_settings_v1_types__tenant_slug__settings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get registry settings. | `application/json` [`TypeRegistrySettingsSchema`](#schema-typeregistrysettingsschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/types/{tenant_slug}/settings` {#update-registry-settings-v1-types-tenant-slug-settings-put}

**Update Registry Settings**

Save the tenant's type-registry settings (#3472).

Tenant-administrator only. The request may be partial — omitted fields keep their current
persisted value (or the table default on the first save). Enum and range validation happens
on the request model, so an invalid value is rejected with 422 before the upsert. The saved
settings become the source of truth the resolver and the validation gate (#3479) read.

Args:
    tenant_slug: The tenant slug.
    request: The settings to persist (partial allowed).
    auth_data: Authentication data (injected by dependency).

Returns:
    The full persisted settings after the write.

Operation id: `update_registry_settings_v1_types__tenant_slug__settings_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update registry settings.

- `application/json` — [`TypeRegistrySettingsUpdateRequest`](#schema-typeregistrysettingsupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update registry settings. | `application/json` [`TypeRegistrySettingsSchema`](#schema-typeregistrysettingsschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/types/{tenant_slug}/stats` {#get-registry-coverage-stats-v1-types-tenant-slug-stats-get}

**Get Registry Coverage Stats**

Return aggregate registry coverage KPIs for the Primitives overview (#3454).

Counts core vs tenant types, imported schemas, property bindings, unresolved ``$ref``
edges, and distinct namespaces. Feeds the Governance → Primitives KPI strip (#3467).

Args:
    tenant_slug: The tenant slug.
    auth_data: Authentication data (injected by dependency).

Returns:
    ``RegistryCoverageStatsResponse`` with the tenant's registry coverage counts.

Operation id: `get_registry_coverage_stats_v1_types__tenant_slug__stats_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get registry coverage stats. | `application/json` [`RegistryCoverageStatsResponse`](#schema-registrycoveragestatsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `RegistryCoverageStatsResponse` {#schema-registrycoveragestatsresponse}

Aggregate registry coverage KPIs for the Primitives overview (#3454).

Counts are scoped to the caller's tenant: system-core types are seeded per tenant
(``is_system = true`` rows owned by the tenant), tenant types are private rows
(``is_system = false``). ``unresolved_ref_count`` mirrors ``GET …/unresolved`` (#3457).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `core_type_count` | integer | no | Number of core type. |
| `tenant_type_count` | integer | no | Number of tenant type. |
| `imported_count` | integer | no | Number of imported. |
| `properties_bound_count` | integer | no | Number of properties bound. |
| `bound_class_count` | integer | no | Number of bound class. |
| `unresolved_ref_count` | integer | no | Number of unresolved ref. |
| `namespace_count` | integer | no | Number of namespace. |

### `ResolveResponse` {#schema-resolveresponse}

Result of a tenant-wide ``$ref`` re-resolution pass (#3459).

``POST /v1/types/{tenant_slug}/resolve`` recomputes the resolved/unresolved status
of every dependency edge across the tenant's primitives against the current registry
state, persists any edge whose status changed, and returns the per-primitive
dependency listing the resolver UI consumes (#3470). The top-level counts mirror the
coverage KPIs of ``GET …/unresolved`` (#3457/#3454); ``reresolved_primitive_count``
is how many primitives had at least one edge status flip during this pass.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `total_primitives` | integer | no | Total Primitives. |
| `ref_count` | integer | no | Number of ref. |
| `resolved_ref_count` | integer | no | Number of resolved ref. |
| `unresolved_ref_count` | integer | no | Number of unresolved ref. |
| `affected_primitive_count` | integer | no | Number of affected primitive. |
| `reresolved_primitive_count` | integer | no | Number of reresolved primitive. |
| `primitives` | array of `ResolvedPrimitiveRefs` | no | Primitives. |

### `TypeNamespaceCreateRequest` {#schema-typenamespacecreaterequest}

Request model for creating a namespace.

``scope`` selects system-core vs tenant ownership; system namespaces require a platform admin
(currently unavailable via the API, so they are effectively read-only). ``base_uri`` and
``version_root`` are derived from the namespace path when omitted.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `namespace` | string | yes | Registry namespace segment for the primitive. |
| `scope` | enum `"system"`, `"tenant"` | no | Scope. |
| `base_uri` | string or null | no | Base URI used to resolve relative ``$ref`` values. |
| `version_root` | string or null | no | Version Root. |
| `description` | string or null | no | Free-text description. |
| `is_public` | boolean or null | no | True when the primitive is visible outside the authoring tenant. |
| `is_default` | boolean | no | Whether default. |

### `TypeNamespaceSchema` {#schema-typenamespaceschema}

A type-registry namespace: scope, base URI, version root, visibility, and default flag.

``scope`` is derived from ``is_system`` for the client. ``type_count`` is the number of
primitives the caller's tenant has in this namespace.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string or null | no | Tenant that owns the resource. |
| `namespace` | string | yes | Registry namespace segment for the primitive. |
| `base_uri` | string | yes | Base URI used to resolve relative ``$ref`` values. |
| `version_root` | string or null | no | Version Root. |
| `description` | string or null | no | Free-text description. |
| `scope` | string | yes | Scope. |
| `is_system` | boolean | no | True when the primitive is shipped by the platform. |
| `is_public` | boolean | no | True when the primitive is visible outside the authoring tenant. |
| `is_default` | boolean | no | Whether default. |
| `type_count` | integer | no | Number of type. |
| `created_by` | string or null | no | Created By. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `TypeNamespaceUpdateRequest` {#schema-typenamespaceupdaterequest}

Request model for updating a namespace. The namespace path is immutable (it links the
namespace to its primitives); only base URI, version root, description, visibility, and the
default flag may change.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `base_uri` | string or null | no | Base URI used to resolve relative ``$ref`` values. |
| `version_root` | string or null | no | Version Root. |
| `description` | string or null | no | Free-text description. |
| `is_public` | boolean or null | no | True when the primitive is visible outside the authoring tenant. |
| `is_default` | boolean or null | no | Whether default. |

### `TypeRegistrySettingsSchema` {#schema-typeregistrysettingsschema}

Per-tenant type-registry behavior settings (#3472).

Configures the default JSON Schema dialect, the ``$ref`` resolution policy, import
defaults, and the validation/publishing governance toggles read by the validation gate
(#3479). A tenant that has never saved settings receives the column defaults below.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `default_draft` | enum `"2020-12"`, `"2019-09"`, `"draft-07"` | no | Default Draft. |
| `strict_validation` | boolean | no | Strict Validation. |
| `allow_annotation_keywords` | boolean | no | Allow Annotation Keywords. |
| `coerce_imported_drafts` | boolean | no | Coerce Imported Drafts. |
| `resolution_base_url` | string | no | Resolution Base URL. |
| `ref_style` | enum `"relative"`, `"absolute"`, `"anchor"` | no | Ref Style. |
| `allow_remote_refs` | boolean | no | Allow Remote Refs. |
| `remote_host_allowlist` | array of string | no | Remote Host Allowlist. |
| `max_resolution_depth` | integer | no | Max Resolution Depth. |
| `circular_ref_policy` | enum `"error"`, `"warn"` | no | Circular Ref Policy. |
| `default_import_scope` | enum `"tenant"`, `"system"` | no | Default Import Scope. |
| `default_target_namespace` | string or null | no | Default Target Namespace. |
| `rewrite_refs_on_import` | boolean | no | Rewrite Refs On Import. |
| `accepted_formats` | array of string | no | Accepted Formats. |
| `dedupe_identical_types` | boolean | no | Dedupe Identical Types. |
| `validate_on_save` | boolean | no | Validate On Save. |
| `block_publish_on_errors` | boolean | no | Block Publish On Errors. |
| `core_publish_role` | enum `"platform_admin"`, `"tenant_admin"`, `"maintainer"` | no | Core Publish Role. |
| `is_default` | boolean | no | Whether default. |
| `updated_by` | string or null | no | Updated By. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |

### `TypeRegistrySettingsUpdateRequest` {#schema-typeregistrysettingsupdaterequest}

Request model for saving a tenant's type-registry settings (#3472).

Every field is optional so the UI may send a partial update; omitted fields keep their
current persisted value (or the default when no row exists yet). Enum and range checks
here mirror the ``apiome.type_registry_settings`` CHECK constraints so an invalid value is
rejected with a clean 422 before it ever reaches the database.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `default_draft` | enum `"2020-12"`, `"2019-09"`, `"draft-07"` or null | no | Default Draft. |
| `strict_validation` | boolean or null | no | Strict Validation. |
| `allow_annotation_keywords` | boolean or null | no | Allow Annotation Keywords. |
| `coerce_imported_drafts` | boolean or null | no | Coerce Imported Drafts. |
| `resolution_base_url` | string or null | no | Resolution Base URL. |
| `ref_style` | enum `"relative"`, `"absolute"`, `"anchor"` or null | no | Ref Style. |
| `allow_remote_refs` | boolean or null | no | Allow Remote Refs. |
| `remote_host_allowlist` | array of string or null | no | Remote Host Allowlist. |
| `max_resolution_depth` | integer or null | no | Max Resolution Depth. |
| `circular_ref_policy` | enum `"error"`, `"warn"` or null | no | Circular Ref Policy. |
| `default_import_scope` | enum `"tenant"`, `"system"` or null | no | Default Import Scope. |
| `default_target_namespace` | string or null | no | Default Target Namespace. |
| `rewrite_refs_on_import` | boolean or null | no | Rewrite Refs On Import. |
| `accepted_formats` | array of string or null | no | Accepted Formats. |
| `dedupe_identical_types` | boolean or null | no | Dedupe Identical Types. |
| `validate_on_save` | boolean or null | no | Validate On Save. |
| `block_publish_on_errors` | boolean or null | no | Block Publish On Errors. |
| `core_publish_role` | enum `"platform_admin"`, `"tenant_admin"`, `"maintainer"` or null | no | Core Publish Role. |
