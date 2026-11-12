---
title: "Component library"
description: "REST endpoints tagged component-library: 12 operations."
sidebar_position: 24
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.544.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `component-library` · 12 operations

## `GET /v1/component-library/{tenant_slug}/components` {#list-components-v1-component-library-tenant-slug-components-get}

**List Components**

List the tenant's live library components with publication summary.

Operation id: `list_components_v1_component_library__tenant_slug__components_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | query | string or null | no | Query parameter: kind. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list components. | `application/json` [`ComponentListResponse`](#schema-componentlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components` {#create-component-v1-component-library-tenant-slug-components-post}

**Create Component**

Create a component and its initial draft revision (TYPES/CREATE).

Operation id: `create_component_v1_component_library__tenant_slug__components_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create component.

- `application/json` — [`ComponentCreateRequest`](#schema-componentcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create component. | `application/json` [`ComponentCreateResponse`](#schema-componentcreateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/components/{component_id}` {#get-component-v1-component-library-tenant-slug-components-component-id-get}

**Get Component**

One component with its revisions, highest semver first.

Operation id: `get_component_v1_component_library__tenant_slug__components__component_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get component. | `application/json` [`ComponentDetailBody`](#schema-componentdetailbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/component-library/{tenant_slug}/components/{component_id}` {#delete-component-v1-component-library-tenant-slug-components-component-id-delete}

**Delete Component**

Soft-delete a component (TYPES/DELETE); blocked while pinned (409).

Operation id: `delete_component_v1_component_library__tenant_slug__components__component_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete component. | `application/json` [`DeletedResponse`](#schema-deletedresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components/{component_id}/revisions` {#create-revision-v1-component-library-tenant-slug-components-component-id-revisions-post}

**Create Revision**

Add a draft revision to a component (TYPES/EDIT).

Operation id: `create_revision_v1_component_library__tenant_slug__components__component_id__revisions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create revision.

- `application/json` — [`RevisionCreateRequest`](#schema-revisioncreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create revision. | `application/json` [`RevisionMutationResponse`](#schema-revisionmutationresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}` {#update-revision-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-put}

**Update Revision**

Replace a draft revision's payload (TYPES/EDIT); published answers 409.

Operation id: `update_revision_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update revision.

- `application/json` — [`RevisionUpdateRequest`](#schema-revisionupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update revision. | `application/json` [`RevisionMutationResponse`](#schema-revisionmutationresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}` {#delete-revision-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-delete}

**Delete Revision**

Delete a draft revision (TYPES/DELETE); published or pinned answers 409.

Operation id: `delete_revision_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete revision. | `application/json` [`DeletedResponse`](#schema-deletedresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}/publish` {#publish-revision-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-publish-post}

**Publish Revision**

Publish a draft revision (TYPES/PUBLISH) — immutable from then on.

Enforces the no-unsafe-downgrade rule inside the transaction: the revision
must be strictly greater than the highest already-published revision.
Republishing a published revision is an idempotent no-op.

Operation id: `publish_revision_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__publish_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for publish revision. | `application/json` [`PublishResponse`](#schema-publishresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/materialization` {#materialization-preview-v1-component-library-tenant-slug-projects-project-id-versions-version-record-id-materialization-get}

**Materialization Preview**

Deterministic preview of materializing the version's pins.

Runs the same materializer export uses against the version's generated
document (with pins excluded from generation so nothing double-counts),
reporting the final local component names and every collision-safe
rename. Never mutates anything; local components are never overwritten.

Operation id: `materialization_preview_v1_component_library__tenant_slug__projects__project_id__versions__version_record_id__materialization_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `includeOrigin` | query | boolean | no | Query parameter: include origin. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for materialization preview. | `application/json` [`MaterializationPreviewResponse`](#schema-materializationpreviewresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins` {#list-pins-v1-component-library-tenant-slug-projects-project-id-versions-version-record-id-pins-get}

**List Pins**

The version's live pins with component/revision identity.

Operation id: `list_pins_v1_component_library__tenant_slug__projects__project_id__versions__version_record_id__pins_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list pins. | `application/json` [`PinListResponse`](#schema-pinlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins` {#create-pin-v1-component-library-tenant-slug-projects-project-id-versions-version-record-id-pins-post}

**Create Pin**

Pin a published library revision to the draft version (VERSIONS/EDIT).

Operation id: `create_pin_v1_component_library__tenant_slug__projects__project_id__versions__version_record_id__pins_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create pin.

- `application/json` — [`PinCreateRequest`](#schema-pincreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create pin. | `application/json` [`PinCreateResponse`](#schema-pincreateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/component-library/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins/{pin_id}` {#delete-pin-v1-component-library-tenant-slug-projects-project-id-versions-version-record-id-pins-pin-id-delete}

**Delete Pin**

Unpin one live pin from the draft version (VERSIONS/EDIT).

Operation id: `delete_pin_v1_component_library__tenant_slug__projects__project_id__versions__version_record_id__pins__pin_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `pin_id` | path | string | yes | Path parameter identifying the pin id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete pin. | `application/json` [`DeletedResponse`](#schema-deletedresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ComponentCreateRequest` {#schema-componentcreaterequest}

Create a component plus its initial draft revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Stable library name (component-key safe). |
| `kind` | string | yes | parameter \| header \| requestBody \| response \| securityBundle \| schema |
| `description` | string or null | no | Free-text description. |
| `ownerId` | string or null | no | Accountable member; defaults to the creator. |
| `initialRevision` | `InitialRevisionBody` | no | Initial Revision. |

### `ComponentCreateResponse` {#schema-componentcreateresponse}

ComponentCreateResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `componentId` | string | yes | Component ID. |
| `revisionId` | string | yes | Revision ID. |

### `ComponentDetailBody` {#schema-componentdetailbody}

Component detail: the summary plus its revisions, highest semver first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `kind` | string | yes | Kind. |
| `description` | string or null | no | Free-text description. |
| `ownerId` | string or null | no | Owner ID. |
| `revisionCount` | integer | no | Number of revision. |
| `publishedCount` | integer | no | Number of published. |
| `headRevision` | string or null | no | Highest published semver, or null while draft-only. |
| `revisions` | array of `ComponentLibraryRevisionBody` | no | Revisions. |

### `ComponentListResponse` {#schema-componentlistresponse}

ComponentListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `components` | array of `ComponentSummaryBody` | no | Components. |

### `DeletedResponse` {#schema-deletedresponse}

DeletedResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | Deleted. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MaterializationPreviewResponse` {#schema-materializationpreviewresponse}

The deterministic preview of materializing the version's pins.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `includeOrigin` | boolean | yes | Include Origin. |
| `entries` | array of `MaterializationEntryBody` | no | Entries. |
| `collisions` | array of `MaterializationEntryBody` | no | Collisions. |

### `PinCreateRequest` {#schema-pincreaterequest}

Pin one published library revision to the draft version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `componentRevisionId` | string | yes | Component Revision ID. |
| `localName` | string or null | no | Optional preferred local components key; collisions still resolve deterministically and never overwrite local components. |

### `PinCreateResponse` {#schema-pincreateresponse}

PinCreateResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pinId` | string | yes | Pin ID. |

### `PinListResponse` {#schema-pinlistresponse}

PinListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pins` | array of `PinBody` | no | Pins. |

### `PublishResponse` {#schema-publishresponse}

PublishResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `published` | boolean | yes | Published. |
| `alreadyPublished` | boolean | yes | Already Published. |
| `revision` | string | yes | Revision. |

### `RevisionCreateRequest` {#schema-revisioncreaterequest}

Create a new draft revision of an existing component.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revision` | string | yes | Semver revision string, unique per component. |
| `payload` | any | no | Payload. |
| `schemaPrimitiveId` | string or null | no | Schema Primitive ID. |

### `RevisionMutationResponse` {#schema-revisionmutationresponse}

RevisionMutationResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revisionId` | string | yes | Revision ID. |

### `RevisionUpdateRequest` {#schema-revisionupdaterequest}

Replace a draft revision's canonical payload.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `payload` | any | no | Payload. |
| `schemaPrimitiveId` | string or null | no | Schema Primitive ID. |
