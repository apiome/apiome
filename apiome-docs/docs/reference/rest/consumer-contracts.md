---
title: "Consumer contracts"
description: "REST endpoints tagged consumer-contracts: 10 operations."
sidebar_position: 15
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `consumer-contracts` · 10 operations

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/consumer-pact-imports` {#import-pact-contract-v1-tenants-tenant-slug-projects-project-ref-consumer-pact-imports-post}

**Import a Pact file into a consumer contract**

Import a Pact document (specification 1.x-4.x). Each interaction's method and path is resolved onto the project's path **template** — `/pets/42` becomes `/pets/{petId}` — and the keys of its example request and response bodies become the fields the consumer declares, resolved against that operation's schemas at the interaction's own status code. Query parameters are declared as parameter usage.

**Nothing is dropped.** An interaction naming a retired endpoint, a status the specification does not declare, or a field that has been removed comes back in `unresolved` with a stable reason code and is stored on the revision. An import whose interactions all fail to resolve stores a visibly empty surface rather than succeeding quietly.

`matchingRules`, `providerStates`, and generators are deliberately not read: they say how a value is compared, not which fields are used.

The consumer is **registered if it does not exist**, under the handle in `consumer_slug` or one derived from the document's own `consumer.name` — so a CI job uploading a pact for a new service succeeds on its first run.

Requires `consumer_contracts:create`.

Operation id: `import_pact_contract_v1_tenants__tenant_slug__projects__project_ref__consumer_pact_imports_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for import a pact file into a consumer contract.

- `application/json` — [`PactImportRequest`](#schema-pactimportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for import a pact file into a consumer contract. | `application/json` [`ContractResponse`](#schema-contractresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/consumer-surface` {#read-available-surface-v1-tenants-tenant-slug-projects-project-ref-consumer-surface-get}

**List the operations and fields a consumer could declare**

Every operation of a stored version, with the request, response, and parameter fields a consumer can declare against it. This is the catalogue the UI picker draws.

Field enumeration is bounded — recursive schemas terminate and very wide operations are cut short — and an operation whose list was cut says so with `truncated: true`. A field the catalogue omitted can still be declared by naming it explicitly.

Requires `consumer_contracts:view`.

Operation id: `read_available_surface_v1_tenants__tenant_slug__projects__project_ref__consumer_surface_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `version` | query | string or null | no | Version label, revision id, or `latest`. Defaults to the latest revision. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the operations and fields a consumer could declare. | `application/json` [`AvailableSurfaceResponse`](#schema-availablesurfaceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers` {#list-project-consumers-v1-tenants-tenant-slug-projects-project-ref-consumers-get}

**List a project's consumers**

Every live consumer of the project, newest first, each with its **current** contract revision — the operations and fields it declares it uses, plus how many interactions could not be resolved.

A consumer that has never declared a contract is still listed, with `contract: null`. That is the state a newly registered consumer is in, and hiding it would make the registration look like it failed.

Requires `consumer_contracts:view`.

Operation id: `list_project_consumers_v1_tenants__tenant_slug__projects__project_ref__consumers_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's consumers. | `application/json` [`ConsumerListResponse`](#schema-consumerlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers` {#register-consumer-v1-tenants-tenant-slug-projects-project-ref-consumers-post}

**Register a consumer**

Register a named client of this project. The handle (`slug`) is what CI and Pact files name; it is derived from `name` when omitted, and is **not** editable afterwards — renaming it would orphan every reference to it.

Registering a consumer declares nothing on its own. The surface it uses arrives separately, either by importing a Pact file or by declaring a picked selection.

Requires `consumer_contracts:create`.

Operation id: `register_consumer_v1_tenants__tenant_slug__projects__project_ref__consumers_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register a consumer.

- `application/json` — [`ConsumerInput`](#schema-consumerinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for register a consumer. | `application/json` [`ConsumerRecord`](#schema-consumerrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}` {#read-consumer-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-get}

**Read one consumer and its current contract**

Read a consumer by its handle or its id, together with the full surface of its current contract revision.

Requires `consumer_contracts:view`.

Operation id: `read_consumer_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one consumer and its current contract. | `application/json` [`ConsumerDetailResponse`](#schema-consumerdetailresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}` {#patch-consumer-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-patch}

**Update a consumer**

Apply a partial update to a consumer's identity — its name, description, owner, contact, or metadata. Omitted fields are left alone.

The handle is not updatable. It is the name CI and Pact files use, and changing it would silently orphan every reference to it; retire the consumer and register a new one instead.

Requires `consumer_contracts:edit`.

Operation id: `patch_consumer_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update a consumer.

- `application/json` — [`ConsumerPatch`](#schema-consumerpatch)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update a consumer. | `application/json` [`ConsumerRecord`](#schema-consumerrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}` {#delete-consumer-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-delete}

**Retire a consumer**

Retire a consumer. Its contract revisions are **kept**: a published version's per-consumer verdict has to stay explicable after the consumer is decommissioned, and the handle becomes available again for a new registration.

Requires `consumer_contracts:delete`, which the built-in grids give Owner and Admin only — removing a consumer removes a signal that guards other people's changes.

Operation id: `delete_consumer_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for retire a consumer. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/contract` {#read-contract-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-contract-get}

**Read a consumer's contract**

The consumer's current contract revision, or a specific one with `?revision=`.

Requires `consumer_contracts:view`.

Operation id: `read_contract_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__contract_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `revision` | query | integer or null | no | A specific revision number; defaults to the current one. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a consumer's contract. | `application/json` [`ConsumerContractRecord`](#schema-consumercontractrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/contract` {#declare-contract-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-contract-put}

**Declare a consumer's contract from a picked surface**

Declare which operations — and, optionally, which fields on them — this consumer uses, without a Pact file. This is what the UI picker submits.

The selection names operations and fields **the way a person picks them** (method, path template, dotted data path); the server resolves each against the stored specification and stores the resulting JSON Pointers. A client cannot supply its own pointers, so a stored surface always describes something the specification actually contains.

Anything that does not resolve is **reported, not dropped**: an operation that no longer exists, or a field that has been removed, comes back in `unresolved` with a stable reason code and is stored on the revision.

Every call writes a **new revision**; nothing is overwritten.

Requires `consumer_contracts:edit`.

Operation id: `declare_contract_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__contract_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `version` | query | string or null | no | Version label, revision id, or `latest` to resolve the selection against. Defaults to the project's latest revision. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for declare a consumer's contract from a picked surface.

- `application/json` — [`SurfaceSelection`](#schema-surfaceselection)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for declare a consumer's contract from a picked surface. | `application/json` [`ContractResponse`](#schema-contractresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/contract-revisions` {#list-contract-revisions-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-contract-revisions-get}

**List a consumer's contract history**

Every stored revision of this consumer's contract, newest first. Revisions are never overwritten, so this is the record of what the consumer claimed it used over time.

Requires `consumer_contracts:view`.

Operation id: `list_contract_revisions_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__contract_revisions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `limit` | query | integer | no | Maximum revisions to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a consumer's contract history. | `application/json` [`ContractRevisionsResponse`](#schema-contractrevisionsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AvailableSurfaceResponse` {#schema-availablesurfaceresponse}

The picker's catalogue for one stored version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version_record_id` | string | yes | The revision the catalogue was built from. |
| `version_label` | string or null | no | That revision's label. |
| `operations` | array of `AvailableOperationOut` | no | Operations. |
| `count` | integer | yes | How many operations the specification declares. |
| `truncated` | boolean | no | True when any operation's field list was cut short by the walk limits. |

### `ConsumerContractRecord` {#schema-consumercontractrecord}

One stored contract revision.

Attributes:
    id: Row id.
    consumer_id: The consumer this revision belongs to.
    revision: Per-consumer counter, from 1.
    is_current: Whether this is the consumer's current revision.
    source: ``pact`` or ``manual``.
    version_id: The specification revision the pointers were resolved against.
    version_label: That revision's version label, snapshotted.
    surface: The declared surface.
    operation_count: How many operations it declares.
    field_count: How many fields it declares.
    unresolved: Interactions that could not be placed.
    unresolved_count: How many of those there are.
    source_metadata: Pact provenance; empty for a manual declaration.
    source_digest: ``sha256:<hex>`` of the uploaded Pact document, when there was one.
    note: Free text explaining the revision.
    actor_label: Who declared it, at the time.
    created_at: When it was declared (ISO-8601).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `consumer_id` | string | yes | Consumer ID. |
| `revision` | integer | yes | Revision. |
| `is_current` | boolean | no | Whether current. |
| `source` | string | no | Provenance source for the record (for example human or imported). |
| `version_id` | string or null | no | Project version identifier or semantic version label, depending on context. |
| `version_label` | string or null | no | Version Label. |
| `surface` | `ConsumerContractSurface` | no | Surface. |
| `operation_count` | integer | no | Number of operation. |
| `field_count` | integer | no | Number of field. |
| `unresolved` | array of `UnresolvedInteraction` | no | Unresolved. |
| `unresolved_count` | integer | no | Number of unresolved. |
| `source_metadata` | object | no | Source Metadata. |
| `source_digest` | string or null | no | Source Digest. |
| `note` | string or null | no | Note. |
| `actor_label` | string or null | no | Actor Label. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |

### `ConsumerDetailResponse` {#schema-consumerdetailresponse}

One consumer with its current contract, when it has declared one.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `consumer` | [`ConsumerRecord`](#schema-consumerrecord) | yes | Consumer. |
| `contract` | [`ConsumerContractRecord`](#schema-consumercontractrecord) or null | no | The current contract revision, or null when none is declared. |

### `ConsumerInput` {#schema-consumerinput}

A new consumer, as a caller defines one.

Attributes:
    slug: Stable handle. Derived from ``name`` when omitted.
    name: Display name.
    description: What this consumer is.
    owner: Free text — the team, squad, channel, or person accountable.
    contact: Email or URL to notify when this consumer's contract would break.
    metadata: Non-secret free-form context (repository, environment, CI job).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `slug` | string or null | no | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `owner` | string or null | no | Owner. |
| `contact` | string or null | no | Contact. |
| `metadata` | object | no | Additional JSON metadata bag. |

### `ConsumerListResponse` {#schema-consumerlistresponse}

Every live consumer of a project with its current contract.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `consumers` | array of `ConsumerSummary` | no | The project's consumers, newest first. |
| `count` | integer | yes | How many consumers were returned. |

### `ConsumerPatch` {#schema-consumerpatch}

A partial update. Omitted fields are left alone.

``slug`` is deliberately absent: it is the handle CI and Pact files name, and renaming it
would silently orphan every reference to it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `owner` | string or null | no | Owner. |
| `contact` | string or null | no | Contact. |
| `metadata` | object or null | no | Additional JSON metadata bag. |

### `ConsumerRecord` {#schema-consumerrecord}

A stored consumer.

Attributes:
    id: Row id.
    tenant_id: Owning tenant.
    project_id: Project this consumer consumes.
    slug: Stable handle.
    name: Display name.
    description: What this consumer is.
    owner: Accountable team or person.
    contact: Where to reach them.
    metadata: Free-form non-secret context.
    created_at: When it was registered.
    updated_at: When it was last changed.
    deleted_at: Retirement stamp, when retired.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `owner` | string or null | no | Owner. |
| `contact` | string or null | no | Contact. |
| `metadata` | object | no | Additional JSON metadata bag. |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string or null | no | Last update timestamp (ISO 8601). |
| `deleted_at` | string or null | no | Deleted At timestamp (ISO 8601). |

### `ContractResponse` {#schema-contractresponse}

A stored contract revision plus the consumer it belongs to.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `consumer` | [`ConsumerRecord`](#schema-consumerrecord) | yes | Consumer. |
| `contract` | [`ConsumerContractRecord`](#schema-consumercontractrecord) | yes | Contract. |
| `unresolved` | array of `UnresolvedInteraction` | no | Interactions or fields that could not be resolved against the specification. Repeated from the stored contract so an importing client sees them without a second read; they are never silently dropped. |

### `ContractRevisionsResponse` {#schema-contractrevisionsresponse}

A consumer's contract history.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revisions` | array of [`ConsumerContractRecord`](#schema-consumercontractrecord) | no | Revisions, newest first. |
| `count` | integer | yes | How many revisions were returned. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PactImportRequest` {#schema-pactimportrequest}

A Pact document to import.

Attributes:
    pact: The Pact document as raw JSON text.
    consumer_slug: The handle to store it under. Derived from the document's own
        ``consumer.name`` when omitted, which is what lets a CI job upload a pact for a
        service that has never been registered.
    consumer_name: Display name for a consumer this import registers.
    version: Version label, revision id, or ``latest`` to resolve the interactions against.
    note: Free text explaining the revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pact` | string | yes | The Pact document as raw JSON text. |
| `consumer_slug` | string or null | no | Consumer Slug. |
| `consumer_name` | string or null | no | Consumer Name. |
| `version` | string or null | no | Version. |
| `note` | string or null | no | Note. |

### `SurfaceSelection` {#schema-surfaceselection}

A whole picked surface, as the UI picker submits it.

Attributes:
    operations: The picked operations. Refused when empty — an empty contract declares
        nothing and would silently exempt the consumer from every future analysis.
    note: Optional free text explaining the revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `operations` | array of `SelectedOperation` | no | Operations. |
| `note` | string or null | no | Note. |
