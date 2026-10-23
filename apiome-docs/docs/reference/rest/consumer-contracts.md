---
title: "Consumer contracts"
description: "REST endpoints tagged consumer-contracts: 16 operations."
sidebar_position: 21
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.308.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `consumer-contracts` · 16 operations

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

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/consumer-suggestions` {#list-consumer-suggestions-v1-tenants-tenant-slug-projects-project-ref-consumer-suggestions-get}

**List suggested consumers**

Clients seen in this project's usage traffic that no binding attributes to a consumer — by the product token of their user agent (`checkout-web`), or by the hashed `consumer_hint` the edge sent. Busiest first; a client a live binding already recognises is left out. A hashed client is shown by an opaque id, never by its value or its hash.

Requires `consumer_contracts:view`.

Operation id: `list_consumer_suggestions_v1_tenants__tenant_slug__projects__project_ref__consumer_suggestions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `days` | query | integer | no | Window in UTC days. |
| `limit` | query | integer | no | Most to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list suggested consumers. | `application/json` [`SuggestionListResponse`](#schema-suggestionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/consumer-suggestions/{suggestion_id}/register` {#register-consumer-suggestion-v1-tenants-tenant-slug-projects-project-ref-consumer-suggestions-suggestion-id-register-post}

**Register a suggested consumer**

Register the client as a consumer (or, with `consumer`, bind it to an existing one) and create the binding that recognises it: the glob `<token>/*` for a user agent, or a hashed binding holding the value's hash the edge already sent — so no value is typed. A hashed client needs `binding_name`, the header or claim its value arrives in. From the next ingested batch on, its calls are attributed and its runtime edges appear in the graph.

Requires `consumer_contracts:create`.

Operation id: `register_consumer_suggestion_v1_tenants__tenant_slug__projects__project_ref__consumer_suggestions__suggestion_id__register_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `suggestion_id` | path | string | yes | Path parameter identifying the suggestion id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register a suggested consumer.

- `application/json` — [`RegisterSuggestionInput`](#schema-registersuggestioninput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for register a suggested consumer. | `application/json` [`RegisteredSuggestion`](#schema-registeredsuggestion) |
| 404 | `consumer-suggestion-not-found`, or an unknown project or `consumer`. | — |
| 409 | `consumer-slug-taken`, `consumer-slug-reserved` or `consumer-binding-exists`. | — |
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

Each row's `runtime` counts its declared-and-used, declared-unused and used-undeclared operations over `runtime_days`, from the traffic its bindings attribute.

Requires `consumer_contracts:view`.

Operation id: `list_project_consumers_v1_tenants__tenant_slug__projects__project_ref__consumers_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `team` | query | string or null | no | Only consumers whose owner (confirmed, else suggested) is this team slug (CDG-2.4). |
| `runtime_days` | query | integer | no | Window, in UTC days ending today, of each row's `runtime` counts (RDG-1.8). |
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

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/bindings` {#list-consumer-bindings-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-bindings-get}

**List a consumer's bindings**

How this consumer is recognised in usage traffic: a header, an API key, a JWT claim, or a user-agent glob. A bound value is never returned — not even as a hash.

Deleted bindings are listed with `include_deleted=true`; they no longer match traffic but keep the history they attributed.

Requires `consumer_contracts:view`.

Operation id: `list_consumer_bindings_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__bindings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `include_deleted` | query | boolean | no | Also list deleted bindings. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a consumer's bindings. | `application/json` [`ConsumerBindingBindingListResponse`](#schema-consumerbindingbindinglistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/bindings` {#create-consumer-binding-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-bindings-post}

**Bind a header, API key, JWT claim or user agent to a consumer**

Attribute usage traffic to this consumer. `header`, `api_key` and `jwt_claim` take the `value` to recognise: it is accepted **once**, hashed (HMAC-SHA256 under a key derived for this workspace) before anything is stored, and never returned. `user_agent` takes no value; its `name` is a glob such as `billing-service/*`.

Matching starts with the next ingested batch. One kind, name and value can identify only one consumer per workspace (`409 consumer-binding-exists`).

Requires `consumer_contracts:create`.

Operation id: `create_consumer_binding_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__bindings_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for bind a header, api key, jwt claim or user agent to a consumer.

- `application/json` — [`BindingInput`](#schema-bindinginput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for bind a header, api key, jwt claim or user agent to a consumer. | `application/json` [`BindingRecord`](#schema-bindingrecord) |
| 409 | `consumer-binding-exists` or `consumer-binding-limit`. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 503 | `consumer-binding-key-unavailable`: no envelope master key is configured. | — |

## `DELETE /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/bindings/{binding_id}` {#delete-consumer-binding-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-bindings-binding-id-delete}

**Delete a consumer binding**

Stop attributing traffic through this binding, from the next ingested batch on. Traffic it already attributed **stays attributed** to the consumer.

Requires `consumer_contracts:delete`.

Operation id: `delete_consumer_binding_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__bindings__binding_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `binding_id` | path | string | yes | Path parameter identifying the binding id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a consumer binding. | — |
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

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/runtime` {#read-consumer-runtime-v1-tenants-tenant-slug-projects-project-ref-consumers-consumer-ref-runtime-get}

**Compare a consumer's contract with its observed traffic**

Per operation, what the consumer **declares** (its current contract) next to what its bindings show it **calls** (the usage index, by UTC day):

* `declared_and_used` — declared and called in the window;
* `declared_unused` — declared, never called in the window;
* `used_undeclared` — called, not declared. To add one to the contract, submit the current selection plus that operation to `PUT …/consumers/{consumer_ref}/contract`.

A consumer with no contract (`contract_state: undeclared`) reports everything it calls as `used_undeclared`. `anonymous` reports the traffic no binding attributes.

Requires `consumer_contracts:view`.

Operation id: `read_consumer_runtime_v1_tenants__tenant_slug__projects__project_ref__consumers__consumer_ref__runtime_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `consumer_ref` | path | string | yes | Path parameter identifying the consumer ref segment. |
| `days` | query | integer | no | Window in UTC days, ending today. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for compare a consumer's contract with its observed traffic. | `application/json` [`ConsumerRuntime`](#schema-consumerruntime) |
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

### `BindingInput` {#schema-bindinginput}

A binding to create.

Attributes:
    kind: ``header``, ``api_key``, ``jwt_claim`` or ``user_agent``.
    name: The header name, the API-key header name, the JWT claim name, or the user-agent glob.
    value: The value to recognise (not for ``user_agent``). Accepted once, hashed, and never
        stored or returned.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | enum `"header"`, `"api_key"`, `"jwt_claim"`, `"user_agent"` | yes | What identifies the consumer in traffic. |
| `name` | string | yes | The header name (`x-client-id`), the header carrying the API key (`x-api-key`), the JWT claim (`azp`), or for `user_agent` a glob such as `billing-service/*`. |
| `value` | string (password) or null | no | The value to recognise. Required for `header`, `api_key` and `jwt_claim`; refused for `user_agent`. Hashed before it is stored and never returned. |

### `BindingRecord` {#schema-bindingrecord}

A stored binding as every response shows it — never with its value or its hash.

Attributes:
    id: Row id.
    consumer_id: The consumer it attributes traffic to.
    kind: The binding kind.
    name: The header or claim name, or the user-agent glob.
    hashed: Whether a value is bound (every kind but ``user_agent``).
    key_version: The master-key version the value was hashed under.
    last_matched_at: When traffic last matched it.
    created_at: When it was created.
    deleted_at: When it was deleted (it stops matching; history keeps it).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `consumer_id` | string | yes | Consumer ID. |
| `kind` | string | yes | Kind. |
| `name` | string | yes | Human-readable name. |
| `hashed` | boolean | yes | True when a value is bound; the value itself is never returned. |
| `key_version` | integer or null | no | Key Version. |
| `last_matched_at` | string or null | no | Last Matched At timestamp (ISO 8601). |
| `created_at` | string or null | no | Creation timestamp (ISO 8601). |
| `deleted_at` | string or null | no | Deleted At timestamp (ISO 8601). |

### `ConsumerBindingBindingListResponse` {#schema-consumerbindingbindinglistresponse}

A consumer's bindings.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `bindings` | array of [`BindingRecord`](#schema-bindingrecord) | no | Newest first. |
| `count` | integer | yes | How many bindings were returned. |

### `ConsumerContractRecord` {#schema-consumercontractrecord}

One stored contract revision.

Attributes:
    id: Row id.
    consumer_id: The consumer this revision belongs to.
    revision: Per-consumer counter, from 1.
    is_current: Whether this is the consumer's current revision.
    source: ``pact``, ``manual`` or ``agent`` (CDG-5.2).
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
    runtime_last_seen_at: When usage traffic last attributed to it through a binding (RDG-1.8).

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
| `runtime_last_seen_at` | string or null | no | Runtime Last Seen At timestamp (ISO 8601). |

### `ConsumerRuntime` {#schema-consumerruntime}

Declared versus observed for one consumer.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `consumer_id` | string or null | no | Null for the anonymous consumer. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `contract_state` | string | yes | declared, undeclared, or none (anonymous). |
| `since_day` | string | yes | First UTC day of the window. |
| `until_day` | string | yes | Last UTC day of the window. |
| `summary` | `RuntimeSummary` | yes | Short summary suitable for navigation and reference docs. |
| `declared_and_used` | array of `RuntimeOperation` | no | Declared And Used. |
| `declared_unused` | array of `RuntimeOperation` | no | Declared Unused. |
| `used_undeclared` | array of `RuntimeOperation` | no | Used Undeclared. |

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

### `RegisterSuggestionInput` {#schema-registersuggestioninput}

How to register a suggestion.

Attributes:
    name: Display name for a new consumer (defaults to the suggestion's).
    slug: Handle for a new consumer (defaults to the suggestion's).
    consumer: Bind to this existing consumer (slug or id) instead of registering a new one.
    binding_name: For a hashed client: the header, API-key header or claim name.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `slug` | string or null | no | URL-safe identifier. |
| `consumer` | string or null | no | Consumer. |
| `binding_name` | string or null | no | Binding Name. |

### `RegisteredSuggestion` {#schema-registeredsuggestion}

What registering did.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `consumer` | [`ConsumerRecord`](#schema-consumerrecord) | yes | Consumer. |
| `binding` | [`BindingRecord`](#schema-bindingrecord) | yes | Binding. |
| `created_consumer` | boolean | yes | False when the client was bound to an existing consumer. |

### `SuggestionListResponse` {#schema-suggestionlistresponse}

A project's suggested consumers.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `suggestions` | array of `SuggestedConsumer` | no | Busiest first. |
| `count` | integer | yes | How many suggestions were returned. |
| `window_days` | integer | yes | The window they were drawn from, in UTC days ending today. |

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
