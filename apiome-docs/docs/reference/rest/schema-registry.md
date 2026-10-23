---
title: "Schema registry"
description: "REST endpoints tagged schema-registry: 32 operations."
sidebar_position: 68
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.302.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `schema-registry` · 32 operations

## `POST /registry/schema/{tenant}/compatibility/subjects/{subject}/versions` {#confluent-compatibility-all-registry-schema-tenant-compatibility-subjects-subject-versions-post}

**Confluent Compatibility All**

Test a schema against the versions the level selects (Confluent ``…/compatibility/subjects/{s}/versions``).

Operation id: `confluent_compatibility_all_registry_schema__tenant__compatibility_subjects__subject__versions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confluent compatibility all.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent compatibility all. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /registry/schema/{tenant}/compatibility/subjects/{subject}/versions/{version}` {#confluent-compatibility-version-registry-schema-tenant-compatibility-subjects-subject-versions-version-post}

**Confluent Compatibility Version**

Test a schema against one version (Confluent ``POST /compatibility/subjects/{s}/versions/{v}``).

Operation id: `confluent_compatibility_version_registry_schema__tenant__compatibility_subjects__subject__versions__version__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confluent compatibility version.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent compatibility version. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/config` {#confluent-get-config-registry-schema-tenant-config-get}

**Confluent Get Config**

Return the tenant's default compatibility level (Confluent ``GET /config``).

Operation id: `confluent_get_config_registry_schema__tenant__config_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent get config. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /registry/schema/{tenant}/config` {#confluent-put-config-registry-schema-tenant-config-put}

**Confluent Put Config**

Set the tenant's default compatibility level (Confluent ``PUT /config``).

Operation id: `confluent_put_config_registry_schema__tenant__config_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confluent put config.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent put config. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/config/{subject}` {#confluent-get-subject-config-registry-schema-tenant-config-subject-get}

**Confluent Get Subject Config**

Return a subject's compatibility level (Confluent ``GET /config/{s}``).

Operation id: `confluent_get_subject_config_registry_schema__tenant__config__subject__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `defaultToGlobal` | query | boolean | no | Fall back to the tenant default. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent get subject config. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /registry/schema/{tenant}/config/{subject}` {#confluent-put-subject-config-registry-schema-tenant-config-subject-put}

**Confluent Put Subject Config**

Set a subject's compatibility level, creating the subject if needed (Confluent ``PUT /config/{s}``).

Operation id: `confluent_put_subject_config_registry_schema__tenant__config__subject__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confluent put subject config.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent put subject config. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/mode` {#confluent-get-mode-registry-schema-tenant-mode-get}

**Confluent Get Mode**

Return the tenant's default mode (Confluent ``GET /mode``).

Operation id: `confluent_get_mode_registry_schema__tenant__mode_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent get mode. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /registry/schema/{tenant}/mode` {#confluent-put-mode-registry-schema-tenant-mode-put}

**Confluent Put Mode**

Set the tenant's default mode, ``READWRITE`` or ``READONLY`` (Confluent ``PUT /mode``).

Operation id: `confluent_put_mode_registry_schema__tenant__mode_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confluent put mode.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent put mode. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/mode/{subject}` {#confluent-get-subject-mode-registry-schema-tenant-mode-subject-get}

**Confluent Get Subject Mode**

Return a subject's mode (Confluent ``GET /mode/{s}``).

Operation id: `confluent_get_subject_mode_registry_schema__tenant__mode__subject__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent get subject mode. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /registry/schema/{tenant}/mode/{subject}` {#confluent-put-subject-mode-registry-schema-tenant-mode-subject-put}

**Confluent Put Subject Mode**

Set a subject's mode, creating the subject if needed (Confluent ``PUT /mode/{s}``).

Operation id: `confluent_put_subject_mode_registry_schema__tenant__mode__subject__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confluent put subject mode.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent put subject mode. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/schemas/ids/{schema_id}` {#confluent-schema-by-id-registry-schema-tenant-schemas-ids-schema-id-get}

**Confluent Schema By Id**

Return a schema by id — it resolves after its subjects are deleted (Confluent ``/schemas/ids/{id}``).

Operation id: `confluent_schema_by_id_registry_schema__tenant__schemas_ids__schema_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schema_id` | path | integer | yes | Path parameter identifying the schema id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent schema by id. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/schemas/ids/{schema_id}/subjects` {#confluent-schema-subjects-registry-schema-tenant-schemas-ids-schema-id-subjects-get}

**Confluent Schema Subjects**

List the live subjects holding a schema id (Confluent ``/schemas/ids/{id}/subjects``).

Operation id: `confluent_schema_subjects_registry_schema__tenant__schemas_ids__schema_id__subjects_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schema_id` | path | integer | yes | Path parameter identifying the schema id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent schema subjects. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/schemas/ids/{schema_id}/versions` {#confluent-schema-versions-registry-schema-tenant-schemas-ids-schema-id-versions-get}

**Confluent Schema Versions**

List the live subject versions holding a schema id (Confluent ``/schemas/ids/{id}/versions``).

Operation id: `confluent_schema_versions_registry_schema__tenant__schemas_ids__schema_id__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schema_id` | path | integer | yes | Path parameter identifying the schema id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent schema versions. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/schemas/types` {#confluent-schema-types-registry-schema-tenant-schemas-types-get}

**Confluent Schema Types**

List the schema types this registry accepts (Confluent ``GET /schemas/types``).

Only types this deployment can read are listed (Protobuf needs the bundled ``buf``). With
``details=true`` each is labelled: ``compatibilityRules`` is ``available`` or ``unavailable``
(XPC-4.x) and ``registrableUnder`` names the levels a new version can be registered under.

Operation id: `confluent_schema_types_registry_schema__tenant__schemas_types_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `details` | query | boolean | no | Label each type with what it can be registered under. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent schema types. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/subjects` {#confluent-list-subjects-registry-schema-tenant-subjects-get}

**Confluent List Subjects**

List subject names (Confluent ``GET /subjects``).

Operation id: `confluent_list_subjects_registry_schema__tenant__subjects_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `deleted` | query | boolean | no | Include soft-deleted subjects. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent list subjects. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /registry/schema/{tenant}/subjects/{subject}` {#confluent-lookup-registry-schema-tenant-subjects-subject-post}

**Confluent Lookup**

Find the version of a subject that holds a schema (Confluent ``POST /subjects/{s}``).

Operation id: `confluent_lookup_registry_schema__tenant__subjects__subject__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confluent lookup.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent lookup. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /registry/schema/{tenant}/subjects/{subject}` {#confluent-delete-subject-registry-schema-tenant-subjects-subject-delete}

**Confluent Delete Subject**

Delete a subject (Confluent ``DELETE /subjects/{s}``); returns the deleted versions.

A soft delete (``imports:edit``) hides the subject and its versions; ids keep resolving.
``?permanent=true`` (``imports:delete``) removes a soft-deleted subject's rows; the catalog item
revisions are never deleted.

Operation id: `confluent_delete_subject_registry_schema__tenant__subjects__subject__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `permanent` | query | boolean | no | Hard-delete a subject that was soft-deleted first. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent delete subject. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/subjects/{subject}/versions` {#confluent-list-versions-registry-schema-tenant-subjects-subject-versions-get}

**Confluent List Versions**

List a subject's live version numbers (Confluent ``GET /subjects/{s}/versions``).

Operation id: `confluent_list_versions_registry_schema__tenant__subjects__subject__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent list versions. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /registry/schema/{tenant}/subjects/{subject}/versions` {#confluent-register-registry-schema-tenant-subjects-subject-versions-post}

**Confluent Register**

Register a schema under a subject and return its id (Confluent ``POST /subjects/{s}/versions``).

Registering content the subject already holds returns the same id. A new version under a level
other than ``NONE`` is refused with ``42290`` until XPC-4.x rules exist for the schema type.

Operation id: `confluent_register_registry_schema__tenant__subjects__subject__versions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for confluent register.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent register. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/subjects/{subject}/versions/{version}` {#confluent-get-version-registry-schema-tenant-subjects-subject-versions-version-get}

**Confluent Get Version**

Return one version (``latest`` and ``-1`` work) (Confluent ``GET /subjects/{s}/versions/{v}``).

Operation id: `confluent_get_version_registry_schema__tenant__subjects__subject__versions__version__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent get version. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /registry/schema/{tenant}/subjects/{subject}/versions/{version}/schema` {#confluent-get-version-schema-registry-schema-tenant-subjects-subject-versions-version-schema-get}

**Confluent Get Version Schema**

Return only the schema text of one version (Confluent ``…/versions/{v}/schema``).

Operation id: `confluent_get_version_schema_registry_schema__tenant__subjects__subject__versions__version__schema_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for confluent get version schema. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-registry/config` {#get-registry-config-v1-tenants-tenant-slug-schema-registry-config-get}

**Get Registry Config**

Return the tenant's registry defaults (``imports:view``).

Operation id: `get_registry_config_v1_tenants__tenant_slug__schema_registry_config_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get registry config. | `application/json` [`RegistryConfig`](#schema-registryconfig) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/schema-registry/config` {#put-registry-config-v1-tenants-tenant-slug-schema-registry-config-put}

**Put Registry Config**

Set the tenant's default compatibility level and/or mode (``imports:edit``).

Operation id: `put_registry_config_v1_tenants__tenant_slug__schema_registry_config_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put registry config.

- `application/json` — [`RegistryConfigUpdate`](#schema-registryconfigupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put registry config. | `application/json` [`RegistryConfig`](#schema-registryconfig) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-registry/schemas/ids/{schema_id}` {#get-schema-by-id-v1-tenants-tenant-slug-schema-registry-schemas-ids-schema-id-get}

**Get Schema By Id**

Resolve a schema id (``imports:view``) — it keeps resolving after its subjects are deleted.

Operation id: `get_schema_by_id_v1_tenants__tenant_slug__schema_registry_schemas_ids__schema_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `schema_id` | path | integer | yes | Path parameter identifying the schema id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get schema by id. | `application/json` [`SchemaByIdOut`](#schema-schemabyidout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-registry/subjects` {#list-schema-subjects-v1-tenants-tenant-slug-schema-registry-subjects-get}

**List Schema Subjects**

List the tenant's live subjects (``imports:view``); deleted subjects are left out.

Operation id: `list_schema_subjects_v1_tenants__tenant_slug__schema_registry_subjects_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list schema subjects. | `application/json` [`SubjectList`](#schema-subjectlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-registry/subjects/{subject}` {#get-schema-subject-v1-tenants-tenant-slug-schema-registry-subjects-subject-get}

**Get Schema Subject**

Return one live subject (``imports:view``).

Operation id: `get_schema_subject_v1_tenants__tenant_slug__schema_registry_subjects__subject__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get schema subject. | `application/json` [`SubjectOut`](#schema-subjectout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/schema-registry/subjects/{subject}` {#put-schema-subject-v1-tenants-tenant-slug-schema-registry-subjects-subject-put}

**Put Schema Subject**

Create a subject or change its strategy, compatibility level or mode (``imports:edit``).

Operation id: `put_schema_subject_v1_tenants__tenant_slug__schema_registry_subjects__subject__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for put schema subject.

- `application/json` — [`SubjectSettings`](#schema-subjectsettings)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for put schema subject. | `application/json` [`SubjectOut`](#schema-subjectout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/schema-registry/subjects/{subject}` {#delete-schema-subject-v1-tenants-tenant-slug-schema-registry-subjects-subject-delete}

**Delete Schema Subject**

Soft-delete a subject and its versions (``imports:delete``); returns the deleted versions.

The versions leave every list, but their schema ids keep resolving at ``/schemas/ids/{id}``
and the catalog item revisions are untouched.

Operation id: `delete_schema_subject_v1_tenants__tenant_slug__schema_registry_subjects__subject__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete schema subject. | `application/json` array of integer |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/schema-registry/subjects/{subject}/attach` {#attach-catalog-item-to-subject-v1-tenants-tenant-slug-schema-registry-subjects-subject-attach-post}

**Attach Catalog Item To Subject**

Back an empty subject with an existing catalog item (``imports:edit``).

The item's latest revision becomes version 1; its earlier revisions stay as they are, and later
registrations add revisions to the item.

Operation id: `attach_catalog_item_to_subject_v1_tenants__tenant_slug__schema_registry_subjects__subject__attach_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for attach catalog item to subject.

- `application/json` — [`AttachRequest`](#schema-attachrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for attach catalog item to subject. | `application/json` [`RegisterResponse`](#schema-registerresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-registry/subjects/{subject}/versions` {#list-schema-subject-versions-v1-tenants-tenant-slug-schema-registry-subjects-subject-versions-get}

**List Schema Subject Versions**

List a subject's live versions, oldest first (``imports:view``).

Operation id: `list_schema_subject_versions_v1_tenants__tenant_slug__schema_registry_subjects__subject__versions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list schema subject versions. | `application/json` [`SubjectVersionList`](#schema-subjectversionlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/schema-registry/subjects/{subject}/versions` {#register-schema-version-v1-tenants-tenant-slug-schema-registry-subjects-subject-versions-post}

**Register Schema Version**

Register a schema under a subject (``imports:create``).

The schema is read by the same import source a catalog upload uses. Registering content the
subject already holds returns its version (``created: false``); content another subject holds
reuses that schema id and revision; new content becomes a new revision of the subject's catalog
item (created on the first registration).

Operation id: `register_schema_version_v1_tenants__tenant_slug__schema_registry_subjects__subject__versions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register schema version.

- `application/json` — [`RegisterRequest`](#schema-registerrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for register schema version. | `application/json` [`RegisterResponse`](#schema-registerresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/schema-registry/subjects/{subject}/versions/{version}` {#get-schema-subject-version-v1-tenants-tenant-slug-schema-registry-subjects-subject-versions-version-get}

**Get Schema Subject Version**

Return one version (a number or ``latest``) with its schema text (``imports:view``).

Operation id: `get_schema_subject_version_v1_tenants__tenant_slug__schema_registry_subjects__subject__versions__version__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `subject` | path | string | yes | Path parameter identifying the subject segment. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get schema subject version. | `application/json` [`SubjectVersionOut`](#schema-subjectversionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AttachRequest` {#schema-attachrequest}

An existing catalog item to back an empty subject.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | The catalog item id (an Avro, JSON Schema or Protobuf item). |
| `strategy` | string or null | no | Naming strategy for a subject this creates. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `RegisterRequest` {#schema-registerrequest}

A schema to register under a subject.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schema` | string | yes | The schema text (Avro JSON, JSON Schema or .proto). |
| `schemaType` | string | no | `AVRO` (default), `JSON` or `PROTOBUF`. |
| `references` | array of any | no | Schema references, stored as sent. |
| `strategy` | string or null | no | Naming strategy for a subject this creates. |

### `RegisterResponse` {#schema-registerresponse}

The registered version; ``created`` is ``false`` when the subject already held this schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subject` | string | yes | Subject. |
| `version` | integer | yes | Version. |
| `id` | integer | yes | The schema id (shared by every subject holding the same schema). |
| `schemaType` | string | yes | Schema Type. |
| `fingerprint` | string | yes | Fingerprint. |
| `references` | array of any | no | References. |
| `projectId` | string | yes | The catalog item holding the schema. |
| `versionRecordId` | string | yes | The catalog item revision holding the schema. |
| `upstreamVersion` | integer or null | no | The upstream registry's version number of a mirrored version (MFI-12.3). |
| `upstreamSchemaId` | integer or null | no | The upstream registry's schema id of a mirrored version (MFI-12.3). |
| `createdAt` | string (date-time) | yes | Created At. |
| `schema` | string or null | no | The schema text (single-version reads only). |
| `created` | boolean | yes | Created. |

### `RegistryConfig` {#schema-registryconfig}

The tenant's registry defaults.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `compatibilityLevel` | string | yes | Default compatibility level for subjects that set none. |
| `mode` | string | yes | `READWRITE` or `READONLY`; `READONLY` refuses every new version. |

### `RegistryConfigUpdate` {#schema-registryconfigupdate}

A change to the tenant's registry defaults; an omitted field is kept.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `compatibilityLevel` | string or null | no | One of the seven Confluent levels. |
| `mode` | string or null | no | `READWRITE` or `READONLY`. |

### `SchemaByIdOut` {#schema-schemabyidout}

A schema resolved by id.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | integer | yes | Stable resource identifier. |
| `schemaType` | string | yes | Schema Type. |
| `fingerprint` | string | yes | Fingerprint. |
| `fingerprintKind` | string | yes | `canonical-model` today; `avro-pcf` once MFI-12.1 ships. |
| `references` | array of any | no | References. |
| `projectId` | string | yes | Project ID. |
| `versionRecordId` | string | yes | Version Record ID. |
| `schema` | string or null | no | Embedded JSON Schema document. |
| `subjects` | array of `SchemaSubjectRef` | no | Live subject versions holding it (empty once all are deleted). |

### `SubjectList` {#schema-subjectlist}

The tenant's live subjects, by name.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subjects` | array of [`SubjectOut`](#schema-subjectout) | yes | Subjects. |

### `SubjectOut` {#schema-subjectout}

A schema subject.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable name. |
| `strategy` | string or null | no | Strategy. |
| `compatibilityLevel` | string or null | no | `null` = the tenant default. |
| `effectiveCompatibilityLevel` | string | yes | This subject's level, else the tenant default. |
| `mode` | string | yes | Mode. |
| `projectId` | string or null | no | The catalog item new versions are registered into. |
| `versionCount` | integer | no | Number of version. |
| `latestVersion` | integer or null | no | Latest Version. |
| `sourceRef` | string or null | no | `registry:<url>` when a `schema-registry` connector mirrors this subject from an upstream registry (MFI-12.3); `null` for a subject registered or attached in Apiome. |
| `sourceConnectorId` | string or null | no | The `schema-registry` connector that mirrors this subject, if any. |
| `createdAt` | string (date-time) | yes | Created At. |
| `updatedAt` | string (date-time) | yes | Updated At. |

### `SubjectSettings` {#schema-subjectsettings}

Create a subject or change its settings; an omitted field is kept.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `strategy` | string or null | no | `topic`, `record` or `topic_record`. |
| `compatibilityLevel` | string or null | no | This subject's level; unset means the tenant default. |
| `mode` | string or null | no | `READWRITE` or `READONLY`. |

### `SubjectVersionList` {#schema-subjectversionlist}

A subject's live versions, oldest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subject` | string | yes | Subject. |
| `versions` | array of [`SubjectVersionOut`](#schema-subjectversionout) | yes | Versions. |

### `SubjectVersionOut` {#schema-subjectversionout}

One version of a subject: a schema id and the catalog item revision that holds it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subject` | string | yes | Subject. |
| `version` | integer | yes | Version. |
| `id` | integer | yes | The schema id (shared by every subject holding the same schema). |
| `schemaType` | string | yes | Schema Type. |
| `fingerprint` | string | yes | Fingerprint. |
| `references` | array of any | no | References. |
| `projectId` | string | yes | The catalog item holding the schema. |
| `versionRecordId` | string | yes | The catalog item revision holding the schema. |
| `upstreamVersion` | integer or null | no | The upstream registry's version number of a mirrored version (MFI-12.3). |
| `upstreamSchemaId` | integer or null | no | The upstream registry's schema id of a mirrored version (MFI-12.3). |
| `createdAt` | string (date-time) | yes | Created At. |
| `schema` | string or null | no | The schema text (single-version reads only). |
