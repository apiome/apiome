---
title: "Mock server"
description: "REST endpoints tagged mock-server: 25 operations."
sidebar_position: 62
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.638.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `mock-server` · 25 operations

## `GET /v1/mock/{mock_id}` {#serve-mock-root-get-v1-mock-mock-id-get}

**Serve Mock Root Get**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_get_v1_mock__mock_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root get. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mock/{mock_id}` {#serve-mock-root-put-v1-mock-mock-id-put}

**Serve Mock Root Put**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_put_v1_mock__mock_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root put. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mock/{mock_id}` {#serve-mock-root-post-v1-mock-mock-id-post}

**Serve Mock Root Post**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_post_v1_mock__mock_id__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root post. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/mock/{mock_id}` {#serve-mock-root-patch-v1-mock-mock-id-patch}

**Serve Mock Root Patch**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_patch_v1_mock__mock_id__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root patch. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mock/{mock_id}` {#serve-mock-root-delete-v1-mock-mock-id-delete}

**Serve Mock Root Delete**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_delete_v1_mock__mock_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root delete. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `HEAD /v1/mock/{mock_id}` {#serve-mock-root-head-v1-mock-mock-id-head}

**Serve Mock Root Head**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_head_v1_mock__mock_id__head`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root head. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `OPTIONS /v1/mock/{mock_id}` {#serve-mock-root-options-v1-mock-mock-id-options}

**Serve Mock Root Options**

Serve the mock for a request to the instance root path.

Operation id: `serve_mock_root_options_v1_mock__mock_id__options`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock root options. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-get-v1-mock-mock-id-sub-path-get}

**Serve Mock Path Get**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_get_v1_mock__mock_id___sub_path__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path get. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-put-v1-mock-mock-id-sub-path-put}

**Serve Mock Path Put**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_put_v1_mock__mock_id___sub_path__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path put. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-post-v1-mock-mock-id-sub-path-post}

**Serve Mock Path Post**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_post_v1_mock__mock_id___sub_path__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path post. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-patch-v1-mock-mock-id-sub-path-patch}

**Serve Mock Path Patch**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_patch_v1_mock__mock_id___sub_path__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path patch. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-delete-v1-mock-mock-id-sub-path-delete}

**Serve Mock Path Delete**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_delete_v1_mock__mock_id___sub_path__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path delete. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `HEAD /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-head-v1-mock-mock-id-sub-path-head}

**Serve Mock Path Head**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_head_v1_mock__mock_id___sub_path__head`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path head. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `OPTIONS /v1/mock/{mock_id}/{sub_path}` {#serve-mock-path-options-v1-mock-mock-id-sub-path-options}

**Serve Mock Path Options**

Serve the mock for any request path under the instance base URL.

Operation id: `serve_mock_path_options_v1_mock__mock_id___sub_path__options`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `sub_path` | path | string | yes | Path parameter identifying the sub path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for serve mock path options. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mocks/{tenant_slug}` {#list-mocks-v1-mocks-tenant-slug-get}

**List Mocks**

List the tenant's mock instances, newest first.

Operation id: `list_mocks_v1_mocks__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list mocks. | `application/json` array of [`MockInstanceResponse`](#schema-mockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/mocks/{tenant_slug}` {#provision-mock-v1-mocks-tenant-slug-post}

**Provision Mock**

Provision a mock instance from a published version and return its stable base URL.

The version must be published. Its OpenAPI document is generated once and frozen into the
instance so the mock is stable for its lifetime. Free-tier expiry and the per-instance rate limit
are applied from configuration (overridable within bounds).

Caller-supplied scenarios keep the RC1-2.2 request shape — a list of rules — and are folded into
the engine's settings shape at provision time (#5532, MSC-2.2), with the same translator that
migrates instances provisioned before the fold. Rules that cannot be translated are reported on
the instance rather than dropped.

Operation id: `provision_mock_v1_mocks__tenant_slug__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for provision mock.

- `application/json` — [`MockProvisionRequest`](#schema-mockprovisionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for provision mock. | `application/json` [`MockInstanceResponse`](#schema-mockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mocks/{tenant_slug}/usage` {#get-mock-usage-v1-mocks-tenant-slug-usage-get}

**Get Mock Usage**

Return mock usage counters and daily rollups for the tenant (#4420, SIM-1.5).

Note: ``project_slug`` and ``version_label`` filter the ``dailyRollups`` only.
``monthlyRequestCount``, ``monthlyQuota``, and ``mockRps`` are always tenant-wide
totals, regardless of any filter parameters.

Operation id: `get_mock_usage_v1_mocks__tenant_slug__usage_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `days` | query | integer | no | Query parameter: days. |
| `project_slug` | query | string or null | no | URL-safe project slug within the tenant. |
| `version_label` | query | string or null | no | Query parameter: version label. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mock usage. | `application/json` [`MockUsageResponse`](#schema-mockusageresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/mocks/{tenant_slug}/{mock_id}` {#get-mock-v1-mocks-tenant-slug-mock-id-get}

**Get Mock**

Inspect one mock instance owned by the tenant.

Operation id: `get_mock_v1_mocks__tenant_slug___mock_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get mock. | `application/json` [`MockInstanceResponse`](#schema-mockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/mocks/{tenant_slug}/{mock_id}` {#destroy-mock-v1-mocks-tenant-slug-mock-id-delete}

**Destroy Mock**

Destroy a mock instance and all of its state.

Operation id: `destroy_mock_v1_mocks__tenant_slug___mock_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for destroy mock. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/mocks/{tenant_slug}/{mock_id}/active-scenario` {#switch-active-scenario-v1-mocks-tenant-slug-mock-id-active-scenario-put}

**Switch Active Scenario**

Switch the instance's default scenario (takes effect immediately, no restart).

The switch writes ``activeScenario`` into the instance's settings — the same key, read the same
way, as a version's stored active scenario (#5531, MSC-2.1). The two spellings that used to
describe this one concept are now one.

Operation id: `switch_active_scenario_v1_mocks__tenant_slug___mock_id__active_scenario_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `mock_id` | path | string | yes | Path parameter identifying the mock id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for switch active scenario.

- `application/json` — [`MockScenarioSwitchRequest`](#schema-mockscenarioswitchrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for switch active scenario. | `application/json` [`MockInstanceResponse`](#schema-mockinstanceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/mock/broker-bindings` {#list-mock-broker-bindings-v1-versions-tenant-slug-project-id-version-record-id-mock-broker-bindings-get}

**List a version's mock broker bindings (metadata only)**

Where the version's hosted mock publishes AsyncAPI events, beyond WebSocket/SSE. A version with event channels and no binding is served over WebSocket/SSE only.

The SASL credential is **write-only**: it is stored envelope-encrypted and no route ever returns it. Responses carry metadata only: the bootstrap hosts, TLS flags, SASL mechanism, the master-key version that sealed the credential, whether it currently opens (`readable`), and when it was created and rotated.

Requires `versions:view`.

Operation id: `list_mock_broker_bindings_v1_versions__tenant_slug___project_id___version_record_id__mock_broker_bindings_get`

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
| 200 | Successful response for list a version's mock broker bindings (metadata only). | `application/json` [`BrokerBindingListResponse`](#schema-brokerbindinglistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/mock/broker-bindings` {#create-mock-broker-binding-v1-versions-tenant-slug-project-id-version-record-id-mock-broker-bindings-post}

**Bind a version's mock to a broker**

Bind the version's hosted mock to a Kafka broker: `bootstrap` hosts, `tls` flags, an optional `saslMechanism` (`PLAIN`, `SCRAM-SHA-256`, `SCRAM-SHA-512`) with its `credential`, and a `clientIdPrefix`. `mqtt` and `amqp` are reserved and refused.

Every bootstrap host is resolved, and a host that reaches a private, loopback, link-local or otherwise non-public address is refused `422 broker-address-disallowed`. The dev broker named by `APIOME_MOCK_DEV_BROKER_BOOTSTRAP` (the `docker compose --profile broker` Redpanda) is exempt; `APIOME_MOCK_BROKER_ALLOW_PRIVATE=true` lifts the check for local development.

The SASL credential is **write-only**: it is stored envelope-encrypted and no route ever returns it. Responses carry metadata only: the bootstrap hosts, TLS flags, SASL mechanism, the master-key version that sealed the credential, whether it currently opens (`readable`), and when it was created and rotated.

One binding per version and protocol: a second is a `409`.

Requires `versions:edit` (version creator or tenant administrator). Audited as `mock.broker_binding.create`, with metadata only.

Operation id: `create_mock_broker_binding_v1_versions__tenant_slug___project_id___version_record_id__mock_broker_bindings_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for bind a version's mock to a broker.

- `application/json` — [`BrokerBindingCreate`](#schema-brokerbindingcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for bind a version's mock to a broker. | `application/json` [`BrokerBindingOut`](#schema-brokerbindingout) |
| 404 | No such version in this project. | — |
| 409 | This version already has a binding for that protocol. | — |
| 422 | `broker-binding-invalid`, `broker-protocol-unsupported`, or `broker-address-disallowed`. | — |
| 503 | A credential was given and no broker encryption key is configured. | — |

## `DELETE /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/mock/broker-bindings/{binding_id}` {#delete-mock-broker-binding-v1-versions-tenant-slug-project-id-version-record-id-mock-broker-bindings-binding-id-delete}

**Delete a broker binding**

Remove the binding and its sealed credential. The version's events go back to WebSocket/SSE only.

Requires `versions:edit`. Audited as `mock.broker_binding.delete`.

Operation id: `delete_mock_broker_binding_v1_versions__tenant_slug___project_id___version_record_id__mock_broker_bindings__binding_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `binding_id` | path | string | yes | Path parameter identifying the binding id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a broker binding. | — |
| 404 | No such binding on this version. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/mock/broker-bindings/{binding_id}/rotate` {#rotate-mock-broker-binding-v1-versions-tenant-slug-project-id-version-record-id-mock-broker-bindings-binding-id-rotate-post}

**Rotate a broker binding's SASL credential**

Replace the SASL credential in place, atomically. The binding keeps its id, address and flags. The body is `{credential: {username, password}}`. The SASL credential is **write-only**: it is stored envelope-encrypted and no route ever returns it. Responses carry metadata only: the bootstrap hosts, TLS flags, SASL mechanism, the master-key version that sealed the credential, whether it currently opens (`readable`), and when it was created and rotated.

Requires `versions:edit`. Audited as `mock.broker_binding.rotate`.

Operation id: `rotate_mock_broker_binding_v1_versions__tenant_slug___project_id___version_record_id__mock_broker_bindings__binding_id__rotate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `binding_id` | path | string | yes | Path parameter identifying the binding id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for rotate a broker binding's sasl credential.

- `application/json` — [`BrokerBindingRotate`](#schema-brokerbindingrotate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for rotate a broker binding's sasl credential. | `application/json` [`BrokerBindingOut`](#schema-brokerbindingout) |
| 404 | No such binding on this version. | — |
| 422 | The binding has no SASL mechanism, or the credential is not acceptable. | — |
| 503 | No broker encryption key is configured. | — |

## `POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/mock/broker-bindings/{binding_id}/test` {#probe-mock-broker-binding-v1-versions-tenant-slug-project-id-version-record-id-mock-broker-bindings-binding-id-test-post}

**Test a broker binding (connect and read metadata)**

Connect to one bootstrap host, complete TLS and SASL, and read cluster metadata — nothing is produced, consumed or created. The answer is `reachable` or `unreachable` with a `reason`: `auth`, `credential-unavailable`, `address-disallowed`, `tls`, `timeout`, `connect` or `protocol`. A wrong password is `unreachable: auth`; the broker's own error text is never returned. Every host is SSRF-checked again first.

The result is cached for 60 seconds per binding state (`cached: true`); a rotation tests afresh.

Requires `versions:edit`. Audited as `mock.broker_binding.test`.

Operation id: `probe_mock_broker_binding_v1_versions__tenant_slug___project_id___version_record_id__mock_broker_bindings__binding_id__test_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `binding_id` | path | string | yes | Path parameter identifying the binding id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for test a broker binding (connect and read metadata). | `application/json` [`BrokerProbeResult`](#schema-brokerproberesult) |
| 404 | No such binding on this version. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `BrokerBindingCreate` {#schema-brokerbindingcreate}

Body for binding a version's mock to a broker.

Attributes:
    protocol: ``kafka``. ``mqtt`` / ``amqp`` are reserved (XPC-2.5) and refused.
    bootstrap: The broker's ``host:port`` entries, as a list or a comma-separated string.
    tls: TLS flags.
    sasl_mechanism: ``PLAIN``, ``SCRAM-SHA-256`` or ``SCRAM-SHA-512``; omit for no SASL.
    credential: The SASL credential; required exactly when a mechanism is given.
    client_id_prefix: The Kafka ``client.id`` prefix Apiome's connections present.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `protocol` | enum `"kafka"`, `"mqtt"`, `"amqp"` | no | `kafka`. `mqtt` and `amqp` are reserved for a later release and refused. |
| `bootstrap` | array of string or string | yes | The broker's bootstrap servers: `host:port` entries (port defaults to 9092), as a list or a comma-separated string. Every host must resolve to a public address. |
| `tls` | `BrokerTls` | no | TLS flags. |
| `saslMechanism` | enum `"PLAIN"`, `"SCRAM-SHA-256"`, `"SCRAM-SHA-512"` or null | no | The SASL mechanism, or omit it for a broker without authentication. |
| `credential` | `BrokerCredentialInput` or null | no | Write-only SASL `{username, password}`; required with `saslMechanism`. Stored encrypted; never returned by any route. |
| `clientIdPrefix` | string | no | The Kafka `client.id` prefix: 1–64 of `A-Z a-z 0-9 . _ -`. |

### `BrokerBindingListResponse` {#schema-brokerbindinglistresponse}

A version's broker bindings, described.

Attributes:
    schema_version: The projection's shape.
    version_id: The version addressed.
    encryption_configured: Whether this deployment can store a SASL credential.
    protocols: The protocols a binding can be created for now.
    reserved_protocols: Protocols reserved for a later release.
    sasl_mechanisms: The SASL mechanisms accepted.
    dev_broker_bootstrap: The dev broker's ``host:port`` entries when the compose profile is
        active, else ``None``.
    bindings: One entry per stored binding.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `versionId` | string | yes | Version ID. |
| `encryptionConfigured` | boolean | yes | Encryption Configured. |
| `protocols` | array of string | yes | Protocols. |
| `reservedProtocols` | array of string | yes | Reserved Protocols. |
| `saslMechanisms` | array of string | yes | Sasl Mechanisms. |
| `devBrokerBootstrap` | array of string or null | no | Dev Broker Bootstrap. |
| `bindings` | array of [`BrokerBindingOut`](#schema-brokerbindingout) | yes | Bindings. |

### `BrokerBindingOut` {#schema-brokerbindingout}

A stored binding, described without revealing its credential.

Attributes:
    schema_version: The projection's shape.
    id: The binding id.
    version_id: The version it belongs to.
    protocol: ``kafka``.
    bootstrap: The normalized ``host:port`` entries.
    dev_broker: Whether the binding points at the configured dev broker.
    tls: TLS flags.
    sasl_mechanism: The SASL mechanism, or ``None``.
    has_credential: Whether a SASL credential is stored.
    key_version: Which master key sealed the credential, or ``None``.
    readable: Whether the credential can be opened with the keys configured now (``True``
        when there is none to open). ``False`` means every connection would fail closed.
    client_id_prefix: The ``client.id`` prefix.
    created_at: When it was stored.
    created_by: Who stored it.
    rotated_at: When its credential was last replaced, or ``None``.
    rotated_by: Who last replaced it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `id` | string | yes | Stable resource identifier. |
| `versionId` | string | yes | Version ID. |
| `protocol` | string | yes | Protocol. |
| `bootstrap` | array of string | yes | Bootstrap. |
| `devBroker` | boolean | no | Dev Broker. |
| `tls` | `BrokerTls` | yes | Tls. |
| `saslMechanism` | string or null | no | Sasl Mechanism. |
| `hasCredential` | boolean | no | Has Credential. |
| `keyVersion` | integer or null | no | Key Version. |
| `readable` | boolean | no | Readable. |
| `clientIdPrefix` | string | yes | Client ID Prefix. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `createdBy` | string or null | no | Created By. |
| `rotatedAt` | string (date-time) or null | no | Rotated At. |
| `rotatedBy` | string or null | no | Rotated By. |

### `BrokerBindingRotate` {#schema-brokerbindingrotate}

Body for replacing a binding's SASL credential in place.

Attributes:
    credential: The replacement credential.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `credential` | `BrokerCredentialInput` | yes | The replacement `{username, password}`, in the same shape as at creation. |

### `BrokerProbeResult` {#schema-brokerproberesult}

What one connectivity test found.

Attributes:
    binding_id: The binding tested.
    status: ``reachable`` or ``unreachable``.
    reason: Why it is unreachable (one of :data:`REASONS`), or ``None`` when reachable.
    summary: ``"reachable"`` or ``"unreachable: <reason>"``, for a status line.
    bootstrap: The entry that answered (reachable) or ``None``.
    brokers: How many brokers the cluster metadata lists (reachable only).
    topics: How many topics the metadata lists (reachable only).
    checked_at: When the probe actually ran (earlier than now when ``cached``).
    cached: Whether this result came from the 60-second cache.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `bindingId` | string | yes | Binding ID. |
| `status` | enum `"reachable"`, `"unreachable"` | yes | Status. |
| `reason` | enum `"auth"`, `"credential-unavailable"`, `"address-disallowed"`, `"tls"`, `"timeout"`, `"connect"`, … or null | no | Reason. |
| `summary` | string | yes | Short summary suitable for navigation and reference docs. |
| `bootstrap` | string or null | no | Bootstrap. |
| `brokers` | integer or null | no | Brokers. |
| `topics` | integer or null | no | Topics. |
| `checkedAt` | string (date-time) | yes | Checked At. |
| `cached` | boolean | no | Cached. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MockInstanceResponse` {#schema-mockinstanceresponse}

Public view of a provisioned mock instance.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `baseUrl` | string | yes | Base URL. |
| `tenantSlug` | string | yes | Tenant Slug. |
| `projectSlug` | string | yes | Project Slug. |
| `versionSlug` | string | yes | Version Slug. |
| `status` | string | yes | Status. |
| `activeScenario` | string | yes | Active Scenario. |
| `scenarios` | array of string | yes | Scenarios. |
| `operationCount` | integer | yes | Number of operation. |
| `rateLimitPerMinute` | integer | yes | Rate Limit Per Minute. |
| `requestCount` | integer | yes | Number of request. |
| `createdAt` | string or null | no | Created At. |
| `expiresAt` | string or null | no | Expires At. |
| `lastActivityAt` | string or null | no | Last Activity At. |
| `migrationNotes` | array of string | no | Rules from the pre-#5532 configuration that could not be translated onto the single mock engine, reported rather than silently dropped. Empty when the fold was lossless. |

### `MockProvisionRequest` {#schema-mockprovisionrequest}

Request body to provision a mock instance from a published version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectSlug` | string | yes | Project Slug. |
| `versionSlug` | string | yes | Version Slug. |
| `name` | string or null | no | Display name; defaults to the coordinates. |
| `ttlHours` | integer or null | no | Auto-expiry in hours; clamped to the configured maximum. |
| `rateLimitPerMinute` | integer or null | no | Rate Limit Per Minute. |
| `seed` | integer or null | no | Deterministic data-generation seed. |
| `scenarios` | array of `MockScenario` or null | no | Scenarios. |
| `activeScenario` | string or null | no | Active Scenario. |

### `MockScenarioSwitchRequest` {#schema-mockscenarioswitchrequest}

Request body to switch a mock instance's active scenario.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `activeScenario` | string | yes | Active Scenario. |

### `MockUsageResponse` {#schema-mockusageresponse}

Mock usage counters for a tenant (#4420, SIM-1.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `monthlyRequestCount` | integer | yes | Number of monthly request. |
| `monthlyQuota` | integer | yes | Monthly Quota. |
| `mockRps` | number | yes | Mock Rps. |
| `dailyRollups` | array of `MockUsageDailyRollup` | yes | Daily Rollups. |
