---
title: "Schema registry"
description: "REST endpoints tagged schema-registry: 11 operations."
sidebar_position: 61
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.248.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `schema-registry` · 11 operations

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
| `createdAt` | string (date-time) | yes | Created At. |
| `schema` | string or null | no | The schema text (single-version reads only). |
