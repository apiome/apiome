---
title: "Pact broker"
description: "REST endpoints tagged pact-broker: 14 operations."
sidebar_position: 69
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.656.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `pact-broker` · 14 operations

## `GET /v1/tenants/{tenant_slug}/pact-broker` {#pact-broker-index-v1-tenants-tenant-slug-pact-broker-get}

**Pact Broker index**

The entry point of the Pact Broker–compatible API: the links a Pact client discovers the other routes from. Give a Pact client this URL as its **broker base URL** and a workspace API key as its **token**.

`pb:publish-contracts` is what `pact-broker publish` and the Pact libraries post to; `pb:provider-pacts-for-verification` is what a Pact verifier posts its consumer-version selectors to. `pb:publish-pact`, `pb:latest-pact-version`, `pb:pact-version`, `pb:latest-provider-pacts` and the others are URI templates.

A workspace API key may be sent as `Authorization: Bearer <key>` on every route under `/pact-broker`. Requires `pacts:view`.

Operation id: `pact_broker_index_v1_tenants__tenant_slug__pact_broker_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for pact broker index. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/contracts/publish` {#publish-contracts-v1-tenants-tenant-slug-pact-broker-contracts-publish-post}

**Publish the pacts of a consumer version**

Publish every pact one build of a consumer produced, in one request — what `pact-broker publish` and pact-js `publishPacts` call. The body is the Pact Broker's: the consumer (`pacticipantName`), its version, optional `branch`, `tags` and `buildUrl`, and `contracts`, each with the provider's name and the Pact document base64-encoded in `content`.

- **Applications are registered on first use.** A consumer or provider the workspace does not have yet becomes a pacticipant.
- **The version is recorded with its branch and tags**, exactly as `PUT …/pacticipants/{ref}/versions/{number}` does.
- **Content is stored once.** A pact identical to one an earlier consumer version published reuses that pact version (`pactVersionSha`), so the provider has one thing to verify.
- **All or nothing.** If any contract is refused, nothing of the request is stored.
- **Safe to repeat.** Publishing the same pacts for the same version again changes nothing. Publishing a *different* pact for a version that already has one is `409`.

Pact specification 1.x to 4.x is accepted and stored as published. `merge` conflict handling and non-Pact specifications are refused with `422 pact-publish-unsupported`.

The response carries `notices` (the lines the CLI prints) and a `pb:contracts` link per pact. Requires `pacts:create`.

Operation id: `publish_contracts_v1_tenants__tenant_slug__pact_broker_contracts_publish_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for publish the pacts of a consumer version.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pacticipantName` | string | yes | The consumer publishing. |
| `pacticipantVersionNumber` | string | yes | Its application version, as the build reports it (a commit SHA). |
| `branch` | string | no | The repository branch the version was built from. |
| `tags` | array of string | no | Tags for the version (at most 50). |
| `buildUrl` | string | no | http(s) URL of the CI build. |
| `contracts` | array of object | yes | Contracts. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for publish the pacts of a consumer version. | `application/hal+json` any |
| 409 | `pact-content-conflict`: this consumer version already published a different pact for the provider. Nothing of the request was stored. Publish under a new consumer version number. | — |
| 413 | `pact-too-large`: the document or the request is over the size limit. | — |
| 422 | `pact-invalid`: the document is not a pact. `detail.pointer` is the JSON Pointer of the first problem in the document (for example `/interactions/2/request/method`) and `detail.message` says what is wrong there. | — |
| 429 | `pact-publish-rate-limited`: over the workspace's publish budget; see `Retry-After`. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}` {#read-broker-pacticipant-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-get}

**Read a pacticipant (Pact Broker shape)**

A pacticipant in the Pact Broker's shape (`name`, `repositoryUrl`, `mainBranch`, `_links`) — what the `pb:consumer`, `pb:provider` and `pb:pacticipant` links of this API lead to. To register or change a pacticipant, use `/v1/tenants/{tenant_slug}/pacticipants`.

`{pacticipant}` is its handle, id or name. Requires `pacts:view`.

Operation id: `read_broker_pacticipant_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a pacticipant (pact broker shape). | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{number}` {#read-broker-pacticipant-version-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-versions-number-get}

**Read a pacticipant version (Pact Broker shape)**

One version of a pacticipant in the Pact Broker's shape: `number`, `buildUrl`, and its branches and tags under `_embedded` — what the `pb:consumer-version` and `pb:pacticipant-version` links of this API lead to.

`{pacticipant}` is its handle, id or name. Requires `pacts:view`.

Operation id: `read_broker_pacticipant_version_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__versions__number__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a pacticipant version (pact broker shape). | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/branch/{branch}/latest` {#read-latest-branch-pact-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-branch-branch-latest-get}

**Read the latest pact for a consumer branch**

The pact of the latest consumer version recorded on branch `{branch}` that published one for the provider. A branch name with a `/` (`feat/new-invoice`) is sent as it is or with the slash encoded.

The body is the Pact document as published, plus `createdAt` and `_links`: `self`, `pb:pact-version` (the content address — the same for every consumer version that published this pact) and `pb:latest-pact-version`.

`{provider}` and `{consumer}` are a pacticipant's handle, id or name. Requires `pacts:view`.

Operation id: `read_latest_branch_pact_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__branch__branch__latest_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `branch` | path | string | yes | Git branch name. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the latest pact for a consumer branch. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/latest` {#read-latest-pact-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-latest-get}

**Read the latest pact**

The pact of the latest consumer version that published one for the provider. Latest means recorded last, not highest version number.

The body is the Pact document as published, plus `createdAt` and `_links`: `self`, `pb:pact-version` (the content address — the same for every consumer version that published this pact) and `pb:latest-pact-version`.

`{provider}` and `{consumer}` are a pacticipant's handle, id or name. Requires `pacts:view`.

Operation id: `read_latest_pact_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__latest_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the latest pact. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/latest/{tag}` {#read-latest-tagged-pact-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-latest-tag-get}

**Read the latest pact for a consumer tag**

The pact of the latest consumer version tagged `{tag}` that published one for the provider. Latest means recorded last.

The body is the Pact document as published, plus `createdAt` and `_links`: `self`, `pb:pact-version` (the content address — the same for every consumer version that published this pact) and `pb:latest-pact-version`.

`{provider}` and `{consumer}` are a pacticipant's handle, id or name. Requires `pacts:view`.

Operation id: `read_latest_tagged_pact_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__latest__tag__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `tag` | path | string | yes | Path parameter identifying the tag segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the latest pact for a consumer tag. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}` {#read-pact-version-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-get}

**Read a pact by its content version**

A pact by its content address: the SHA-256 (64 hex characters) of its interactions, messages and specification version. Every consumer version that published the same pact shares this URL, so it is the one target a provider verifies. `self` names the latest consumer version that carries it.

The body is the Pact document as published, plus `createdAt` and `_links`: `self`, `pb:pact-version` (the content address — the same for every consumer version that published this pact) and `pb:latest-pact-version`.

`{provider}` and `{consumer}` are a pacticipant's handle, id or name. Requires `pacts:view`.

Operation id: `read_pact_version_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__pact_version__sha__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | Path parameter identifying the sha segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a pact by its content version. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/metadata/{metadata}` {#read-pact-version-with-metadata-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-metadata-metadata-get}

**Read a pact by its content version (for-verification link)**

The same pact as `…/pact-version/{sha}`. The last segment is the metadata a for-verification response encodes in its links (which selectors chose the pact, for which consumer version); it does not change the pact returned.

The body is the Pact document as published, plus `createdAt` and `_links`: `self`, `pb:pact-version` (the content address — the same for every consumer version that published this pact) and `pb:latest-pact-version`.

`{provider}` and `{consumer}` are a pacticipant's handle, id or name. Requires `pacts:view`.

Operation id: `read_pact_version_with_metadata_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__pact_version__sha__metadata__metadata__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | Path parameter identifying the sha segment. |
| `metadata` | path | string | yes | The selection metadata of a for-verification link (URL-safe base64); not needed to find the pact. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a pact by its content version (for-verification link). | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/version/{consumer_version}` {#read-pact-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-version-consumer-version-get}

**Read the pact of a consumer version**

The pact one consumer version published for a provider.

The body is the Pact document as published, plus `createdAt` and `_links`: `self`, `pb:pact-version` (the content address — the same for every consumer version that published this pact) and `pb:latest-pact-version`.

`{provider}` and `{consumer}` are a pacticipant's handle, id or name. Requires `pacts:view`.

Operation id: `read_pact_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__version__consumer_version__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `consumer_version` | path | string | yes | Path parameter identifying the consumer version segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the pact of a consumer version. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/version/{consumer_version}` {#publish-pact-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-version-consumer-version-put}

**Publish one pact**

Publish the pact between a consumer version and a provider. The body is the Pact document itself (specification 1.x to 4.x), stored as published. Both applications are registered as pacticipants if the workspace does not have them, and the consumer version is recorded.

Answers `201` when this consumer version had no pact for the provider, `200` when it published the same pact before (nothing changes), and `409` when it published a different one. If the document names a consumer or provider, the names must match the URL.

To record a branch, tags or a build URL with the pact, use `POST …/pact-broker/contracts/publish` instead. Requires `pacts:create`.

Operation id: `publish_pact_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__version__consumer_version__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `consumer_version` | path | string | yes | Path parameter identifying the consumer version segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

The Pact document (specification 1.x to 4.x), exactly as the consumer's tests wrote it.

- `application/json` — object

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for publish one pact. | `application/hal+json` any |
| 201 | The pact was published for this consumer version. | — |
| 409 | `pact-content-conflict`: this consumer version already published a different pact for the provider. Nothing of the request was stored. Publish under a new consumer version number. | — |
| 413 | `pact-too-large`: the document or the request is over the size limit. | — |
| 422 | `pact-invalid`: the document is not a pact. `detail.pointer` is the JSON Pointer of the first problem in the document (for example `/interactions/2/request/method`) and `detail.message` says what is wrong there. | — |
| 429 | `pact-publish-rate-limited`: over the workspace's publish budget; see `Retry-After`. | — |

## `POST /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/for-verification` {#pacts-for-verification-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-for-verification-post}

**The pacts a provider must verify**

What a Pact verifier calls before it verifies: the pacts a provider build must verify, chosen by **consumer-version selectors**. One entry per distinct pact; a pact chosen by several selectors appears once, with every reason in its notices.

Selectors (`consumerVersionSelectors`, each optionally narrowed by `consumer`):

- `{"mainBranch": true}` — the latest version from each consumer's main branch;
- `{"branch": "x"}` — the latest version from branch `x`, with `fallbackBranch` or `fallbackToMainBranch` for a consumer that has none there;
- `{"matchingBranch": true}` — `branch` set to the request's `providerVersionBranch`;
- `{"tag": "x"}` — every version tagged `x`; with `"latest": true` the latest one, and `fallbackTag` for a consumer that has none;
- `{"latest": true}` — the latest version of each consumer;
- `deployed`, `released`, `deployedOrReleased`, `environment` — versions in an environment. Accepted; they select nothing until environments are recorded.

No selectors means the broker's defaults: each consumer's main branch (or its latest version), and whatever is deployed or released.

`includePendingStatus: true` adds `pending` and the pending notices. No verification result has been recorded yet, so every pact is pending: a failure will not fail the provider build. `includeWipPactsSince` is accepted; work-in-progress pacts are not added yet.

An ambiguous selector (for example `tag` with `branch`, or `mainBranch` with `latest: false`) is `400 pact-selector-invalid` with the pointer of the selector. Requires `pacts:view`.

Operation id: `pacts_for_verification_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__for_verification_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for the pacts a provider must verify.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `consumerVersionSelectors` | array of object | no | Consumer Version Selectors. |
| `providerVersionBranch` | string | no | Provider Version Branch. |
| `providerVersionTags` | array of string | no | Provider Version Tags. |
| `includePendingStatus` | boolean | no | Include Pending Status. |
| `includeWipPactsSince` | string (date) | no | Include Wip Pacts Since. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the pacts a provider must verify. | `application/hal+json` any |
| 400 | `pact-selector-invalid`: a selector is ambiguous or malformed; see `detail.pointer`. | — |
| 404 | `pacticipant-not-found`: the workspace has no such provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/latest` {#read-latest-provider-pacts-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-latest-get}

**The latest pact of every consumer of a provider**

One `pb:pacts` link per consumer: the pact of its latest-recorded version that published one for the provider. `{provider}` is a pacticipant's handle, id or name. Requires `pacts:view`.

Operation id: `read_latest_provider_pacts_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__latest_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the latest pact of every consumer of a provider. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/latest/{tag}` {#read-latest-tagged-provider-pacts-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-latest-tag-get}

**The latest pact of every consumer of a provider, for a tag**

One `pb:pacts` link per consumer that has a version tagged `{tag}` with a pact for the provider: the pact of the latest such version. Requires `pacts:view`.

Operation id: `read_latest_tagged_provider_pacts_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__latest__tag__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `tag` | path | string | yes | Path parameter identifying the tag segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for the latest pact of every consumer of a provider, for a tag. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
