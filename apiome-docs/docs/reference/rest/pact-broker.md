---
title: "Pact broker"
description: "REST endpoints tagged pact-broker: 100 operations."
sidebar_position: 70
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.688.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `pact-broker` · 100 operations

## `GET /v1/tenants/{tenant_slug}/pact-broker` {#pact-broker-index-v1-tenants-tenant-slug-pact-broker-get}

**Pact Broker index**

The entry point of the Pact Broker–compatible API: the links a Pact client discovers the other routes from. Give a Pact client this URL as its **broker base URL** and a workspace API key as its **token**.

`pb:publish-contracts` is what `pact-broker publish` and the Pact libraries post to; `pb:provider-pacts-for-verification` is what a Pact verifier posts its consumer-version selectors to. `pb:publish-pact`, `pb:latest-pact-version`, `pb:pact-version`, `pb:latest-provider-pacts` and the others are URI templates. `pb:environments` lists the environments `pact-broker record-deployment` looks an environment up in. `pb:can-i-deploy-pacticipant-version-to-environment` and `…-to-tag` answer whether a version can be deployed; `pact-broker can-i-deploy` asks `…/pact-broker/matrix`. `pb:webhooks` and `pb:webhook` are what `pact-broker create-webhook` and `create-or-update-webhook` use.

A workspace API key may be sent as `Authorization: Bearer <key>`, or as the password of basic auth (any username), on every route under `/pact-broker`. A restricted key needs a Pact scope: `pact:read` for reads, `pact:publish` to publish pacts and record deployments, `pact:verify` to publish verification results. Requires `pacts:view`.

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

## `GET /v1/tenants/{tenant_slug}/pact-broker/can-i-deploy` {#read-can-i-deploy-v1-tenants-tenant-slug-pact-broker-can-i-deploy-get}

**Can I deploy?**

Whether one version of a pacticipant can be deployed — the index's `pb:can-i-deploy-pacticipant-version-to-environment` and `…-to-tag` links.

`pacticipant` and `version` name what is being deployed. `toEnvironment` names where: the version is checked against every version of its providers and consumers currently deployed to or released in that environment. `to` names a tag instead: it is checked against the latest version of each with that tag. Give exactly one of the two. `ignore` leaves a pacticipant out of the verdict.

The answer is the matrix document of `GET …/matrix`: `summary.deployable` is `true`, `false`, or `null` (a verification result is missing; `Retry-After` says when to ask again). An environment marked `contractRequired` refuses a version that has no pact at all (`no-pact`).

Always `200` when the query is valid. Requires `pacts:view`.

Operation id: `read_can_i_deploy_v1_tenants__tenant_slug__pact_broker_can_i_deploy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `pacticipant` | query | string | yes | The pacticipant being deployed: its name or handle. |
| `version` | query | string | yes | The version being deployed. |
| `toEnvironment` | query | string | no | The environment being deployed to. `environment` is accepted too. |
| `to` | query | string | no | A tag instead of an environment: check against the latest version of each other pacticipant with it. |
| `ignore` | query | array of string | no | A pacticipant whose rows do not count towards the verdict. Repeat for several; `ignore[][pacticipant]` with `ignore[][version]` ignores one version. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The verdict and the rows it was reached from. `summary.deployable` is `true`, `false`, or `null` when a verification result is missing — then `Retry-After` says when to ask again. | `application/hal+json` any |
| 400 | `pact-matrix-invalid`: the query is malformed, or names a pacticipant or an environment that does not exist. `detail.pointer` names the parameter. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/contracts/provider/{provider}/version/{provider_version}` {#read-contract-v1-tenants-tenant-slug-pact-broker-contracts-provider-provider-version-provider-version-get}

**Read a provider contract**

The provider contract a provider version published: `contractType`, `contentSha`, `oasVersion` and `operationCount` (`asyncapiVersion` and `messageCount` for an AsyncAPI contract), `contentType`, where it came from (`source`: `inline`, or `apiome` with the project and version it was rendered from), the `verificationResults` sent with it, and the document in `content`.

`{provider}` is a pacticipant's handle, id or name. Requires `pacts:view`.

Operation id: `read_contract_v1_tenants__tenant_slug__pact_broker_contracts_provider__provider__version__provider_version__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `provider_version` | path | string | yes | Path parameter identifying the provider version segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a provider contract. | `application/hal+json` any |
| 404 | `pacticipant-not-found` or `provider-contract-not-found`. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-broker/contracts/provider/{provider}/version/{provider_version}` {#publish-contract-v1-tenants-tenant-slug-pact-broker-contracts-provider-provider-version-provider-version-put}

**Publish a provider contract**

Register the provider's OpenAPI (or AsyncAPI) document — its **provider contract** — against a provider version, for bi-directional contract testing. Send the document inline in `content` (base64; JSON or YAML, PactFlow's shape) **or** name an Apiome version in `apiomeVersion` (`ledger-api@1.4.0`) to render it from the canonical model with the exporter `GET /v1/schema/…` uses (OpenAPI 3.1). With a provider bound to its Apiome project, `apiomeVersion` may be just the version, and `latest` is the project's newest.

- **OpenAPI 3.0, 3.1 and 3.2**, validated against its version's meta-schema — or, for message pacts, **AsyncAPI 2.x and 3.x** (`contractType: asyncapi`, read from the document when omitted; inline only), checked for its version, `info`, channels, operations and local `$ref`s. Swagger 2.0 and anything else are `422 provider-contract-invalid`, with `detail.pointer` locating the problem.
- **The provider is registered on first use**, and the version is recorded with its `branch`, `tags` and `buildUrl`, as `PUT …/pacticipants/{ref}/versions/{number}` does.
- **Content is stored once.** The document is addressed by the SHA-256 of its canonical JSON (`contentSha`), so JSON, YAML and a rendered copy of one document are one contract.
- **Write-once.** `201` for a new contract, `200` when the same contract and self-verification results are published again (nothing changes), `409` for anything different.

**Self-verification evidence.** The contract is trusted only when evidence says the provider matches it. `verificationResults` carries a report — JUnit XML (Schemathesis, Dredd, Newman or any JUnit writer), Newman JSON or Schemathesis NDJSON, at most `APIOME_PACT_EVIDENCE_MAX_BYTES` — or names an Apiome provider-verification report in `providerVerificationReportId`. The report is read and recorded with its kind, tool and SHA-256 digest in `selfVerification`: `verified`, `failed`, `inconclusive` (unreadable, nothing executed, or an Apiome report of another version) or `missing`. Without `verified` evidence the contract is unverified: its comparisons read verdict `unverified`, and under `APIOME_PACT_UNVERIFIED_PROVIDER_CONTRACT=fail` they fail.

**Bi-directional comparison.** After the contract is stored it is compared with the pacts that need it — each consumer's main-branch pact, the pacts deployed or released, the latest pact of each consumer on the provider version's branch, and every pact compared before with a contract of that branch — and each comparison is stored as a verification result with `kind: bidirectional`, which the matrix and can-i-deploy read like a native one. `comparisons` in the response reports each pact. Requires `pacts:create`, `versions:view` with `apiomeVersion`, and `verification_evidence:view` with `providerVerificationReportId`.

Operation id: `publish_contract_v1_tenants__tenant_slug__pact_broker_contracts_provider__provider__version__provider_version__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `provider_version` | path | string | yes | Path parameter identifying the provider version segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for publish a provider contract.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `content` | string | no | The OpenAPI 3.x or AsyncAPI 2.x / 3.x document (JSON or YAML), base64-encoded. Send this or `apiomeVersion`. |
| `contractType` | enum `"oas"`, `"asyncapi"` | no | `oas` for an OpenAPI 3.x document (HTTP pacts), `asyncapi` for an AsyncAPI 2.x / 3.x document (message pacts). Read from the document when omitted. An AsyncAPI contract is always sent inline in `content`. |
| `contentType` | string | no | How `content` is encoded: `application/json` or `application/yaml`. Sniffed when omitted. |
| `apiomeVersion` | string | no | `<project>@<version>`: render the contract from an Apiome version instead of sending it. `<version>` alone uses the project the provider is bound to; `latest` is the project's newest version. Send this or `content`. |
| `branch` | string | no | The repository branch the version was built from. |
| `tags` | array of string | no | Tags for the provider version (at most 50). |
| `buildUrl` | string | no | http(s) URL of the CI build. |
| `verificationResults` | object | no | The provider's self-verification (PFX-2.4): a report in `content`, or an Apiome provider-verification report in `providerVerificationReportId` — not both. Read into `selfVerification`; without passing evidence the contract is unverified. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The same contract was published again: nothing changed. `comparisons` reports the pacts compared with it, as for `201`. | `application/hal+json` any |
| 201 | The contract was published for this provider version. `selfVerification` says what the evidence proved (`status` `verified`, `failed`, `inconclusive` or `missing`, with `kind`, `tool`, `digest`, `summary` and `reasons`) and whether the contract is `providerContractVerified`. `comparisons` reports the bi-directional comparisons the publish ran: the counts (`compared`, `alreadyCompared`, `errors`, `skipped`) and one entry per pact, with its `status`, `verdict` (`unverified` when the contract has no passing evidence), `success` and `verificationNumber`. | — |
| 409 | `provider-contract-conflict`: this provider version already published a different contract (or the same one with different self-verification results). Nothing was stored. | — |
| 413 | `provider-contract-too-large`: the document or the request is over the size limit. `provider-contract-evidence-too-large`: the self-verification report is over `APIOME_PACT_EVIDENCE_MAX_BYTES`. | — |
| 422 | `provider-contract-invalid`: the document is not OpenAPI 3.0, 3.1 or 3.2 (or, as `contractType: asyncapi`, not AsyncAPI 2.x / 3.x) — `detail.pointer` is the JSON Pointer of the problem in the document (`/swagger` for Swagger 2.0, `/openapi`, `/asyncapi`, the first meta-schema error, or the first structural problem of an AsyncAPI document). `provider-contract-request-invalid` / `provider-contract-unsupported`: a field of the request (`detail.pointer` locates it). `provider-contract-source-not-found`: `apiomeVersion` names no project or version of this workspace. `provider-contract-evidence-unsupported`: the report's `contentType` is not one a report is read as. `provider-contract-evidence-invalid`: the report is not what its type says (XML that does not parse or is not JUnit, a DTD, JSON that is not JSON, text that is not UTF-8). `provider-contract-evidence-report-not-found`: `providerVerificationReportId` names no report of this workspace. | — |
| 429 | `pact-publish-rate-limited`: over the workspace's publish budget; see `Retry-After`. | — |

## `POST /v1/tenants/{tenant_slug}/pact-broker/contracts/publish` {#publish-contracts-v1-tenants-tenant-slug-pact-broker-contracts-publish-post}

**Publish the pacts of a consumer version**

Publish every pact one build of a consumer produced, in one request — what `pact-broker publish` and pact-js `publishPacts` call. The body is the Pact Broker's: the consumer (`pacticipantName`), its version, optional `branch`, `tags` and `buildUrl`, and `contracts`, each with the provider's name and the Pact document base64-encoded in `content`.

- **Applications are registered on first use.** A consumer or provider the workspace does not have yet becomes a pacticipant.
- **The version is recorded with its branch and tags**, exactly as `PUT …/pacticipants/{ref}/versions/{number}` does.
- **Content is stored once.** A pact identical to one an earlier consumer version published reuses that pact version (`pactVersionSha`), so the provider has one thing to verify.
- **All or nothing.** If any contract is refused, nothing of the request is stored.
- **Safe to repeat.** Publishing the same pacts for the same version again changes nothing. Publishing a *different* pact for a version that already has one is `409`.
- **Bi-directional comparison.** When a provider has published a provider contract, each pact is compared with the contracts of its latest provider version, the head of each provider branch and every provider version deployed or released. Each comparison is stored as a verification result with `kind: bidirectional`; the response lists them in `comparisons` and as notices.

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

## `GET /v1/tenants/{tenant_slug}/pact-broker/deployed-versions/{uuid}` {#read-deployed-version-v1-tenants-tenant-slug-pact-broker-deployed-versions-uuid-get}

**Read a deployment**

One deployment, current or not. Requires `pacts:view`.

Operation id: `read_deployed_version_v1_tenants__tenant_slug__pact_broker_deployed_versions__uuid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | The deployment's `uuid`. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a deployment. | `application/hal+json` any |
| 404 | `pact-deployed-version-not-found`: no such deployment in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/pact-broker/deployed-versions/{uuid}` {#patch-deployed-version-v1-tenants-tenant-slug-pact-broker-deployed-versions-uuid-patch}

**Record an undeployment**

`{"currentlyDeployed": false}` records that the version is no longer deployed — what `pact-broker record-undeployment` sends to each matching deployment's `self` link. The deployment stays in the history. Patching an undeployed deployment changes nothing; `true` is refused (record the deployment again instead).

Requires `pacts:edit`.

Operation id: `patch_deployed_version_v1_tenants__tenant_slug__pact_broker_deployed_versions__uuid__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | The deployment's `uuid`. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record an undeployment.

- `application/merge-patch+json` — object
- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `currentlyDeployed` | enum `false` | no | Currently Deployed. |

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `currentlyDeployed` | enum `false` | no | Currently Deployed. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record an undeployment. | `application/hal+json` any |
| 404 | `pact-deployed-version-not-found`: no such deployment in this workspace. | — |
| 422 | `pact-deployment-invalid`: `currentlyDeployed` is not `false`. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/environments` {#read-environments-v1-tenants-tenant-slug-pact-broker-environments-get}

**List environments**

The workspace's environments — what `pact-broker list-environments` prints and what `record-deployment`, `record-undeployment` and `record-support-ended` look an environment up in (`_links.pb:environments`, each named after its environment). `?name=` narrows the list to the environment with exactly that name.

Requires `pacts:view`.

Operation id: `read_environments_v1_tenants__tenant_slug__pact_broker_environments_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `name` | query | string or null | no | Only the environment with exactly this name. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list environments. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/environments` {#post-environment-v1-tenants-tenant-slug-pact-broker-environments-post}

**Create an environment**

Create an environment — what `pact-broker create-environment --name production --production` posts. `name` is one word (no spaces) and unique in the workspace; `displayName` defaults to the name; `production` defaults to `false`. Apiome adds `contractRequired`: can-i-deploy to the environment refuses a pacticipant without a contract.

Answers `201` with the environment and its URL in `Location`. Requires `pacts:create`.

Operation id: `post_environment_v1_tenants__tenant_slug__pact_broker_environments_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create an environment.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | The name tooling uses: one word, no spaces. |
| `displayName` | string | no | The name people read; the name when omitted. |
| `production` | boolean | no | Production. |
| `contractRequired` | boolean | no | Apiome only: can-i-deploy to this environment refuses a pacticipant that has no contract. |
| `contacts` | array of object | no | Contacts. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create an environment. | `application/hal+json` any |
| 409 | `pact-environment-name-taken`: another environment has this name. | — |
| 422 | `pact-environment-invalid`: the body is malformed; `detail.pointer` names the field. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/environments/{uuid}` {#read-environment-v1-tenants-tenant-slug-pact-broker-environments-uuid-get}

**Read an environment**

One environment by its `uuid` — the index's `pb:environment` template, and what `pact-broker describe-environment` reads. Requires `pacts:view`.

Operation id: `read_environment_v1_tenants__tenant_slug__pact_broker_environments__uuid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read an environment. | `application/hal+json` any |
| 404 | `pact-environment-not-found`: no such environment in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-broker/environments/{uuid}` {#put-environment-v1-tenants-tenant-slug-pact-broker-environments-uuid-put}

**Replace an environment**

Replace every field of an environment — what `pact-broker update-environment` sends. The body is the same as for creating one; a field left out returns to its default. Renaming is allowed: deployments refer to the environment by `uuid`.

Requires `pacts:edit`.

Operation id: `put_environment_v1_tenants__tenant_slug__pact_broker_environments__uuid__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace an environment.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | The name tooling uses: one word, no spaces. |
| `displayName` | string | no | The name people read; the name when omitted. |
| `production` | boolean | no | Production. |
| `contractRequired` | boolean | no | Apiome only: can-i-deploy to this environment refuses a pacticipant that has no contract. |
| `contacts` | array of object | no | Contacts. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace an environment. | `application/hal+json` any |
| 404 | `pact-environment-not-found`: no such environment in this workspace. | — |
| 409 | `pact-environment-name-taken`: another environment has this name. | — |
| 422 | `pact-environment-invalid`: the body is malformed. | — |

## `DELETE /v1/tenants/{tenant_slug}/pact-broker/environments/{uuid}` {#remove-environment-v1-tenants-tenant-slug-pact-broker-environments-uuid-delete}

**Delete an environment**

Delete an environment and every deployment and release recorded to it — what `pact-broker delete-environment` calls. can-i-deploy can no longer be asked about it. Answers `204`. Requires `pacts:delete`.

Operation id: `remove_environment_v1_tenants__tenant_slug__pact_broker_environments__uuid__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete an environment. | — |
| 404 | `pact-environment-not-found`: no such environment in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/environments/{uuid}/deployed-versions/currently-deployed` {#read-currently-deployed-v1-tenants-tenant-slug-pact-broker-environments-uuid-deployed-versions-currently-deployed-get}

**List the versions currently deployed to an environment**

What is deployed to the environment now, newest first, under `_embedded.deployedVersions` — what `pact-broker record-undeployment` reads before it patches each match.

- `pacticipant` narrows to one pacticipant (handle or name; an unknown one lists nothing).
- `applicationInstance` narrows to one instance; sent empty, to the unnamed instance. `target` is its deprecated name.

Requires `pacts:view`.

Operation id: `read_currently_deployed_v1_tenants__tenant_slug__pact_broker_environments__uuid__deployed_versions_currently_deployed_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `pacticipant` | query | string or null | no | Only this pacticipant (handle or name). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the versions currently deployed to an environment. | `application/hal+json` any |
| 404 | `pact-environment-not-found`: no such environment in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/environments/{uuid}/released-versions/currently-supported` {#read-currently-supported-v1-tenants-tenant-slug-pact-broker-environments-uuid-released-versions-currently-supported-get}

**List the versions released and supported in an environment**

The releases still supported in the environment, newest first, under `_embedded.releasedVersions` — what `pact-broker record-support-ended` reads. `pacticipant` and `version` narrow the list.

Requires `pacts:view`.

Operation id: `read_currently_supported_v1_tenants__tenant_slug__pact_broker_environments__uuid__released_versions_currently_supported_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `pacticipant` | query | string or null | no | Only this pacticipant (handle or name). |
| `version` | query | string or null | no | Only this version number. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the versions released and supported in an environment. | `application/hal+json` any |
| 404 | `pact-environment-not-found`: no such environment in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/labels` {#read-broker-labels-v1-tenants-tenant-slug-pact-broker-labels-get}

**List every label (Pact Broker shape)**

Every distinct label on the workspace's pacticipants, by name, under `_embedded.labels`. Requires `pacts:view`.

Operation id: `read_broker_labels_v1_tenants__tenant_slug__pact_broker_labels_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list every label (pact broker shape). | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/matrix` {#read-matrix-v1-tenants-tenant-slug-pact-broker-matrix-get}

**Query the matrix**

The matrix: which consumer versions were verified against which provider versions, and the verdict on deploying the versions asked about. This is the Pact Broker's `GET /matrix`, and what `pact-broker can-i-deploy` calls.

- **Selectors** (`q[][pacticipant]` …) name the versions in question. One selector with a destination asks *can I deploy this?*; two or more ask *do these work together?*
- **Destination**: `environment` checks against every version currently deployed to or released in that environment; `tag` with `latest=true` against the latest version with that tag; `latest=true` alone against the latest version of each other pacticipant; `mainBranch=true` (with `latest=true`) against main branches. The other pacticipants are worked out from the pacts.
- **Verdict** (`summary.deployable`): `true` when every row that counts succeeded (or nothing depends on the version); `false` when a verification failed or a named version does not exist; `null` when a result is missing. A consumer needs its providers to be there; a provider does not need its consumers.
- **Reasons**: `summary.reason` and `notices` use the Pact Broker's wording. Each notice has a `code` and each row a `reason` (`verified`, `verification-failed`, `pact-pending`, `no-verification-result`); `no-pact` is the notice when the environment requires a contract and the version has none.
- **Ignore**: rows of an `ignore[][pacticipant]` are returned with `ignored: true` and do not count.
- **Retry while unknown**: a `null` verdict comes with `Retry-After`.

Always `200` when the query is valid — read `summary.deployable`, not the status. Requires `pacts:view`.

Operation id: `read_matrix_v1_tenants__tenant_slug__pact_broker_matrix_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `q[][pacticipant]` | query | array of string | no | A pacticipant to put in the matrix. Repeat `q[][pacticipant]` (each followed by its own `q[][version]`, `q[][latest]`, `q[][tag]`, `q[][branch]`, `q[][environment]` or `q[][mainBranch]`) for several. |
| `q[][version]` | query | array of string | no | Exactly this version of the pacticipant. |
| `q[][latest]` | query | array of string | no | `true`: only the latest of the versions described. |
| `q[][tag]` | query | array of string | no | Versions with this tag. |
| `q[][branch]` | query | array of string | no | Versions recorded on this branch. |
| `q[][environment]` | query | array of string | no | Versions currently deployed to, or released and supported in, this environment. |
| `q[][mainBranch]` | query | array of string | no | `true`: versions on the pacticipant's main branch. |
| `latestby` | query | enum `"cvp"`, `"cvpv"`, `"cp"` | no | Collapse rows to the latest result per consumer version and provider (`cvp`), per consumer version and provider version (`cvpv`), or per consumer and provider (`cp`). Without it every result is a row. |
| `limit` | query | integer | no | The most rows to return. |
| `environment` | query | string | no | The destination: check against every version currently in this environment (`can-i-deploy --to-environment`). |
| `tag` | query | string | no | The destination: check against versions with this tag (`can-i-deploy --to`, with `latest=true`). |
| `latest` | query | boolean | no | `true`: check against the latest version of each other pacticipant. |
| `mainBranch` | query | boolean | no | `true`: check against each other pacticipant's main branch. |
| `ignore[][pacticipant]` | query | array of string | no | A pacticipant whose rows do not count towards the verdict; `ignore[][version]` narrows it to one version. |
| `success[]` | query | array of string | no | Keep only rows with this result: `true`, `false`, or empty for rows without a result. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The verdict and the rows it was reached from. `summary.deployable` is `true`, `false`, or `null` when a verification result is missing — then `Retry-After` says when to ask again. | `application/hal+json` any |
| 400 | `pact-matrix-invalid`: the query is malformed, or names a pacticipant or an environment that does not exist. `detail.pointer` names the parameter. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacticipants/label/{label}` {#read-broker-pacticipants-with-label-v1-tenants-tenant-slug-pact-broker-pacticipants-label-label-get}

**List the pacticipants with a label (Pact Broker shape)**

The pacticipants carrying `{label}`, under `_embedded.pacticipants` and `pb:pacticipants`; an empty list when none does. Requires `pacts:view`.

Operation id: `read_broker_pacticipants_with_label_v1_tenants__tenant_slug__pact_broker_pacticipants_label__label__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `label` | path | string | yes | Path parameter identifying the label segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the pacticipants with a label (pact broker shape). | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

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

## `DELETE /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}` {#delete-broker-pacticipant-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-delete}

**Delete a pacticipant (Pact Broker shape)**

Delete a pacticipant with its versions, pacts, verification results and deployments. Soft: it can be restored through `POST /v1/tenants/{tenant_slug}/pacticipants/{p}/restore` until it is purged (`APIOME_PACT_DELETION_GRACE_DAYS`, default 30). `409 pacticipant-version-in-use` while a version is deployed or released, unless `force=true`. Requires `pacts:delete`.

Operation id: `delete_broker_pacticipant_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `reason` | query | string or null | no | Why; stored with the delete and audited. |
| `force` | query | boolean | no | Delete even when a version is currently deployed or released. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a pacticipant (pact broker shape). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/branches/{branch}/versions/{version}` {#put-branch-version-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-branches-branch-versions-version-put}

**Record a version on a branch (Pact Broker shape)**

Record a pacticipant version on a branch — the `pb:branch-version` link a Pact verifier follows to record the provider's branch before it publishes a result. The pacticipant and the version are registered when the workspace does not have them yet; the branch head moves only to a version recorded later. The body is ignored.

Answers `201` when the version is new, `200` otherwise. `{branch}` may contain `/`. Requires `pacts:create`.

Operation id: `put_branch_version_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__branches__branch__versions__version__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `branch` | path | string | yes | Git branch name. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record a version on a branch (pact broker shape). | `application/hal+json` any |
| 201 | The version was created and recorded on the branch. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/labels/{label}` {#read-broker-label-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-labels-label-get}

**Read a label (Pact Broker shape)**

One label of a pacticipant; 404 when it does not carry it. Requires `pacts:view`.

Operation id: `read_broker_label_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__labels__label__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `label` | path | string | yes | Path parameter identifying the label segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a label (pact broker shape). | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/labels/{label}` {#put-broker-label-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-labels-label-put}

**Label a pacticipant (Pact Broker shape)**

Put a label on a pacticipant. `201` with a `Location` header when the label is new, `200` when the pacticipant already had it. Unlike the Pact Broker, an unknown pacticipant is `404`, not created. Requires `pacts:edit`.

Operation id: `put_broker_label_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__labels__label__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `label` | path | string | yes | Path parameter identifying the label segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for label a pacticipant (pact broker shape). | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/labels/{label}` {#delete-broker-label-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-labels-label-delete}

**Remove a label (Pact Broker shape)**

Take a label off a pacticipant; 404 when it does not carry it. Requires `pacts:edit`.

Operation id: `delete_broker_label_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__labels__label__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `label` | path | string | yes | Path parameter identifying the label segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for remove a label (pact broker shape). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{number}` {#read-broker-pacticipant-version-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-versions-number-get}

**Read a pacticipant version (Pact Broker shape)**

One version of a pacticipant in the Pact Broker's shape: `number`, `buildUrl`, and its branches and tags under `_embedded` — what the `pb:consumer-version` and `pb:pacticipant-version` links of this API lead to. `pb:record-deployment` and `pb:record-release` list one link per environment of the workspace, named after it — what `pact-broker record-deployment` and `record-release` post to.

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

## `DELETE /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{number}` {#delete-broker-pacticipant-version-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-versions-number-delete}

**Delete a pacticipant version (Pact Broker shape)**

Delete one version with its pacts, the verification results it published and its deployments. Soft: restorable through `POST /v1/tenants/{tenant_slug}/pacticipants/{p}/versions/{v}/restore` until it is purged. `409 pacticipant-version-in-use` while it is deployed or released, unless `force=true`. Requires `pacts:delete`.

Operation id: `delete_broker_pacticipant_version_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__versions__number__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `number` | path | string | yes | Path parameter identifying the number segment. |
| `reason` | query | string or null | no | Why; stored with the delete and audited. |
| `force` | query | boolean | no | Delete even when a version is currently deployed or released. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a pacticipant version (pact broker shape). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{version}/deployed-versions/environment/{uuid}` {#read-deployments-of-version-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-versions-version-deployed-versions-environment-uuid-get}

**List the deployments of a version to an environment**

Every deployment of this version to the environment, current or not, newest first. Requires `pacts:view`.

Operation id: `read_deployments_of_version_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__versions__version__deployed_versions_environment__uuid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | The pacticipant's handle, id or name. |
| `version` | path | string | yes | The version number, exactly as recorded. |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the deployments of a version to an environment. | `application/hal+json` any |
| 404 | `pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`: the version must have been recorded (published a pact, or verified one) first. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{version}/deployed-versions/environment/{uuid}` {#post-deployment-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-versions-version-deployed-versions-environment-uuid-post}

**Record a deployment**

Record that this version is now deployed to the environment — the version's `pb:record-deployment` link, which `pact-broker record-deployment --pacticipant Ledger --version 4f1e2d0 --environment production` posts to.

- The pacticipant's previous deployment to the same environment and application instance is marked undeployed; it stays in the history.
- Deployments to other application instances are not touched.
- Recording the version that is already deployed there returns that deployment, `200`.

Answers `201` with the deployment and its URL in `Location`. Requires `pacts:create`.

Operation id: `post_deployment_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__versions__version__deployed_versions_environment__uuid__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | The pacticipant's handle, id or name. |
| `version` | path | string | yes | The version number, exactly as recorded. |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for record a deployment.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applicationInstance` | string | no | The instance of the environment deployed to (a region, a customer). Omit it when the environment has one instance. |
| `target` | string | no | Deprecated name of `applicationInstance`. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | This version was already the current deployment; it is returned. | — |
| 201 | Successful response for record a deployment. | `application/hal+json` any |
| 404 | `pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`: the version must have been recorded (published a pact, or verified one) first. | — |
| 422 | `pact-deployment-invalid`: the body is malformed; `detail.pointer` names the field. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{version}/released-versions/environment/{uuid}` {#read-releases-of-version-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-versions-version-released-versions-environment-uuid-get}

**Read the release of a version to an environment**

The release of this version to the environment, if any, under `_embedded.releasedVersions`. Requires `pacts:view`.

Operation id: `read_releases_of_version_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__versions__version__released_versions_environment__uuid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | The pacticipant's handle, id or name. |
| `version` | path | string | yes | The version number, exactly as recorded. |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the release of a version to an environment. | `application/hal+json` any |
| 404 | `pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`: the version must have been recorded (published a pact, or verified one) first. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{version}/released-versions/environment/{uuid}` {#post-release-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-versions-version-released-versions-environment-uuid-post}

**Record a release**

Record that this version is released to the environment — the version's `pb:record-release` link, which `pact-broker record-release` posts to. Releases do not replace each other: every released version stays supported until `record-support-ended`. Recording a release again starts supporting it again and answers `200`.

The body is ignored. Requires `pacts:create`.

Operation id: `post_release_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__versions__version__released_versions_environment__uuid__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | The pacticipant's handle, id or name. |
| `version` | path | string | yes | The version number, exactly as recorded. |
| `uuid` | path | string | yes | The environment's `uuid`, as `GET …/environments` lists it. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The version was already released there; it is supported again. | — |
| 201 | Successful response for record a release. | `application/hal+json` any |
| 404 | `pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`: the version must have been recorded (published a pact, or verified one) first. | — |
| 422 | `pact-deployment-invalid`: the body is malformed; `detail.pointer` names the field. | — |

## `PUT /v1/tenants/{tenant_slug}/pact-broker/pacticipants/{pacticipant}/versions/{version}/tags/{tag}` {#put-version-tag-v1-tenants-tenant-slug-pact-broker-pacticipants-pacticipant-versions-version-tags-tag-put}

**Tag a version (Pact Broker shape)**

Put a tag on a pacticipant version — the `pb:version-tag` link a Pact verifier follows to record the provider's tags before it publishes a result. The pacticipant and the version are registered when the workspace does not have them yet. The body is ignored.

Answers `201` when the version is new, `200` otherwise. Requires `pacts:create`.

Operation id: `put_version_tag_v1_tenants__tenant_slug__pact_broker_pacticipants__pacticipant__versions__version__tags__tag__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `pacticipant` | path | string | yes | Path parameter identifying the pacticipant segment. |
| `version` | path | string | yes | Endpoint or API version metadata. |
| `tag` | path | string | yes | Path parameter identifying the tag segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for tag a version (pact broker shape). | `application/hal+json` any |
| 201 | The version was created with the tag. | — |
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

## `POST /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/external-verification-results` {#ingest-external-result-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-external-verification-results-post}

**Ingest a verification report produced elsewhere**

Publish the result of a verification that ran **elsewhere** — the report a team's own CI already has — instead of asking Apiome's hosted verifier to replay the pact (PFX-3.5).

The body is the report itself, not a Pact Broker result:

- **`pact_verifier_cli --json`** output (`Content-Type: application/json`): the verifier's `result` / `errors` / `pendingErrors`, or a `pacts[].interactions[]` listing;
- **JUnit XML** (`application/xml`): one `<testcase>` per interaction; a `<failure>` or `<error>` fails it, a `<skipped>` case is not verified and makes the result unsuccessful.

The format is taken from `format`, else the content type, else the body. The report is mapped to the verification-result model of `POST …/verification-results` and stored as an ordinary result, so the matrix, can-i-deploy, pending pacts and webhooks see it. Nothing is dropped silently: the answer is the stored result plus an `ingestion` object whose `notices` name, with a JSON Pointer or location, every field the reader could not use and every judgement it made. A report with no interactions is refused (`422 pact-verification-invalid`) rather than published as a pass. The report is the verifier's word: it is not cross-checked against the interactions of the pact version.

`providerApplicationVersion` is required because neither format carries it. `branch` and `tag` record the provider version first, as a verifier's `PUT` calls would. Requires `pacts:create`.

Operation id: `ingest_external_result_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__pact_version__sha__external_verification_results_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | Path parameter identifying the sha segment. |
| `providerApplicationVersion` | query | string | yes | The provider version the report verified (a commit SHA). |
| `buildUrl` | query | string or null | no | http(s) URL of the CI build. |
| `branch` | query | string or null | no | Record the provider version on this branch first. |
| `tag` | query | array of string or null | no | Tag the provider version first (repeatable). |
| `format` | query | string | no | One of auto, pact-verifier-json, junit; `auto` reads the content type, then the body. |
| `verifier` | query | string or null | no | The verifier's name, recorded in `verifiedBy`. |
| `verifierVersion` | query | string or null | no | The verifier's version, recorded in `verifiedBy`. |
| `providerVerificationReportId` | query | string or null | no | Link a CTG-4.3 provider verification report (a UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for ingest a verification report produced elsewhere.

- `application/json` — object
- `application/xml` — string

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | The stored result, with an `ingestion` object (`format`, `interactions`, `notices`). | `application/hal+json` any |
| 404 | `pacticipant-not-found` or `pact-not-found`: no such pair or pact version. | — |
| 422 | `pact-verification-invalid`: the body is malformed (`detail.pointer` names the field); `pact-verification-report-not-found`: `providerVerificationReportId` is not this workspace's. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/metadata/{metadata}` {#read-pact-version-with-metadata-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-metadata-metadata-get}

**Read a pact by its content version (for-verification link)**

The same pact as `…/pact-version/{sha}`. The last segment is the metadata a for-verification response encodes in its links (which selectors chose the pact, for which consumer version, whether it was pending); it does not change the pact returned, and `pb:publish-verification-results` carries it on, so the result records it.

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
| `metadata` | path | string | yes | The selection metadata of a for-verification link (URL-safe base64); kept for the result. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a pact by its content version (for-verification link). | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/metadata/{metadata}/verification-results` {#publish-result-with-metadata-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-metadata-metadata-verification-results-post}

**Publish a verification result (for-verification link)**

Publish the result of verifying this pact version — what a Pact verifier posts to the pact's `pb:publish-verification-results` link when it runs with `publishVerificationResult: true`.

- `success` and `providerApplicationVersion` are required. The provider version is recorded if the workspace does not have it yet.
- `testResults` is stored as sent, so a failed result keeps every mismatch.
- The result is immutable and numbered 1, 2, 3 … per pact version; the answer is `201` with its URL in `Location`.
- The provider branch recorded with it is the branch the provider version was recorded on last (verifiers record it with `pb:branch-version` just before publishing).
- `providerVerificationReportId` (Apiome only) links the CTG-4.3 provider verification report the result was produced with.

Requires `pacts:create`.

This form carries the metadata of the for-verification link the pact was fetched with; the result records whether the pact was pending then.

Operation id: `publish_result_with_metadata_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__pact_version__sha__metadata__metadata__verification_results_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | Path parameter identifying the sha segment. |
| `metadata` | path | string | yes | The selection metadata of the for-verification link (URL-safe base64). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for publish a verification result (for-verification link).

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | yes | Whether every interaction passed. |
| `providerApplicationVersion` | string | yes | The provider version that verified (a commit SHA). |
| `buildUrl` | string | no | http(s) URL of the CI build. |
| `testResults` | array of object | no | Per-interaction results, stored as sent (at most 10,000). |
| `verifiedBy` | object | no | Verified By. |
| `providerVerificationReportId` | string (uuid) | no | Apiome only: the CTG-4.3 provider verification report this result was produced with. Linked, not copied. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for publish a verification result (for-verification link). | `application/hal+json` any |
| 404 | `pacticipant-not-found` or `pact-not-found`: no such pair or pact version. | — |
| 422 | `pact-verification-invalid`: the body is malformed (`detail.pointer` names the field); `pact-verification-report-not-found`: `providerVerificationReportId` is not this workspace's. | — |

## `POST /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/verification-results` {#publish-result-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-verification-results-post}

**Publish a verification result**

Publish the result of verifying this pact version — what a Pact verifier posts to the pact's `pb:publish-verification-results` link when it runs with `publishVerificationResult: true`.

- `success` and `providerApplicationVersion` are required. The provider version is recorded if the workspace does not have it yet.
- `testResults` is stored as sent, so a failed result keeps every mismatch.
- The result is immutable and numbered 1, 2, 3 … per pact version; the answer is `201` with its URL in `Location`.
- The provider branch recorded with it is the branch the provider version was recorded on last (verifiers record it with `pb:branch-version` just before publishing).
- `providerVerificationReportId` (Apiome only) links the CTG-4.3 provider verification report the result was produced with.

Requires `pacts:create`.

Operation id: `publish_result_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__pact_version__sha__verification_results_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | Path parameter identifying the sha segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for publish a verification result.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `success` | boolean | yes | Whether every interaction passed. |
| `providerApplicationVersion` | string | yes | The provider version that verified (a commit SHA). |
| `buildUrl` | string | no | http(s) URL of the CI build. |
| `testResults` | array of object | no | Per-interaction results, stored as sent (at most 10,000). |
| `verifiedBy` | object | no | Verified By. |
| `providerVerificationReportId` | string (uuid) | no | Apiome only: the CTG-4.3 provider verification report this result was produced with. Linked, not copied. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for publish a verification result. | `application/hal+json` any |
| 404 | `pacticipant-not-found` or `pact-not-found`: no such pair or pact version. | — |
| 422 | `pact-verification-invalid`: the body is malformed (`detail.pointer` names the field); `pact-verification-report-not-found`: `providerVerificationReportId` is not this workspace's. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/verification-results/latest` {#read-latest-result-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-verification-results-latest-get}

**Read the latest verification result of a pact version**

The result published last for this pact version, by any provider version. Requires `pacts:view`.

Operation id: `read_latest_result_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__pact_version__sha__verification_results_latest_get`

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
| 200 | Successful response for read the latest verification result of a pact version. | `application/hal+json` any |
| 404 | `pact-verification-not-found`: the pact version has no results. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/verification-results/{number}` {#read-result-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-verification-results-number-get}

**Read a verification result**

One result of a pact version, by its number (1, 2, 3 …). Requires `pacts:view`.

Operation id: `read_result_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__pact_version__sha__verification_results__number__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | Path parameter identifying the sha segment. |
| `number` | path | integer | yes | The result's number among the results of this pact version. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a verification result. | `application/hal+json` any |
| 404 | `pact-verification-not-found`: no result with that number. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/verification-results/{number}/triggered-webhooks` {#read-verification-triggered-webhooks-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-pact-version-sha-verification-results-number-triggered-webhooks-get}

**Webhooks a verification result triggered**

The webhooks fired by the publication of this verification result, newest first, each with its status and a `pb:logs` link. Requires `pacts:view`.

Operation id: `read_verification_triggered_webhooks_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__pact_version__sha__verification_results__number__triggered_webhooks_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | Path parameter identifying the sha segment. |
| `number` | path | integer | yes | Path parameter identifying the number segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for webhooks a verification result triggered. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
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

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/version/{consumer_version}/triggered-webhooks` {#read-pact-triggered-webhooks-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-version-consumer-version-triggered-webhooks-get}

**Webhooks a publication triggered**

The webhooks fired by this consumer version's publication of its pact for the provider, newest first, each with its status and a `pb:logs` link. Requires `pacts:view`.

Operation id: `read_pact_triggered_webhooks_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__version__consumer_version__triggered_webhooks_get`

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
| 200 | Successful response for webhooks a publication triggered. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/webhooks` {#read-scoped-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-webhooks-get}

**List the webhooks of a pact**

The webhooks defined for exactly this scope (a webhook for all pacts is not listed here; see `GET …/webhooks`). Requires `pacts:view`.

Operation id: `read_scoped_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__webhooks_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `provider` | path | string | yes | The provider. |
| `consumer` | path | string | yes | The consumer. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the webhooks of a pact. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/webhooks` {#post-scoped-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-webhooks-post}

**Create a webhook for a pact**

Create a webhook for this scope: the consumer and provider of the URL replace any in the body. Otherwise as `POST …/webhooks`. Requires `pacts:create`.

Operation id: `post_scoped_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__webhooks_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `provider` | path | string | yes | The provider. |
| `consumer` | path | string | yes | The consumer. |

**Request body** (required)

Request body for create a webhook for a pact.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `description` | string | no | Free-text description. |
| `consumer` | object | no | Only pacts of this consumer. Omit for any. |
| `provider` | object | no | Only pacts of this provider. Omit for any. |
| `enabled` | boolean | no | Whether the resource is active. |
| `events` | array of object | no | Default: `contract_content_changed`. |
| `request` | object | no | The HTTP request to send. Send this or `target`. |
| `target` | object | no | Apiome: a GitHub Actions `repository_dispatch`, in place of `request`. |
| `signingSecret` | string | no | Apiome: when set, every delivery carries `X-Apiome-Signature: sha256=<hex>`, the HMAC-SHA256 of the body. Sealed; a webhook that has one reads `signed: true`. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a webhook for a pact. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 409 | `pact-webhook-limit-reached`: the workspace already has 200 webhooks. | — |
| 422 | `pact-webhook-invalid`: the body is malformed; `detail.pointer` names the field. | — |
| 503 | `pact-webhook-secrets-unavailable`: the webhook carries a secret and the server has no key to seal it with. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/consumer/{consumer}/webhooks/status` {#read-pact-webhooks-status-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-consumer-consumer-webhooks-status-get}

**Webhook status of a pact**

The latest firing of each webhook and event for the pacts between a consumer and a provider, with a `summary` (`successful`, `failed`, `retrying`, `notRun`) and a `pb:error-logs` link per firing that failed or is being retried. `failed` means dead-lettered: every attempt was used. Requires `pacts:view`.

Operation id: `read_pact_webhooks_status_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__consumer__consumer__webhooks_status_get`

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
| 200 | Successful response for webhook status of a pact. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/pacts/provider/{provider}/for-verification` {#pacts-for-verification-by-query-v1-tenants-tenant-slug-pact-broker-pacts-provider-provider-for-verification-get}

**The pacts a provider must verify (query-string form)**

The `GET` form of `POST …/for-verification`, which the Pact Broker keeps for its first clients — and which the Rust verifier inside pact-js, pact-python and pact-go fetches before it posts its selectors. Same answer as the `POST`; the parameters are the broker's snake-case Rack query parameters: `provider_version_branch`, `provider_version_tags[]`, `include_pending_status`, `include_wip_pacts_since` and `consumer_version_selectors[][<field>]` (`main_branch`, `branch`, `matching_branch`, `fallback_branch`, `fallback_to_main_branch`, `tag`, `fallback_tag`, `latest`, `consumer`, `deployed`, `released`, `deployed_or_released`, `environment`). A field that repeats starts the next selector. Without parameters, the broker's default selectors apply. Prefer the `POST`. Requires `pacts:view`.

Operation id: `pacts_for_verification_by_query_v1_tenants__tenant_slug__pact_broker_pacts_provider__provider__for_verification_get`

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
| 200 | Successful response for the pacts a provider must verify (query-string form). | `application/hal+json` any |
| 400 | `pact-selector-invalid`: a selector is ambiguous or malformed; see `detail.pointer`. | — |
| 404 | `pacticipant-not-found`: the workspace has no such provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

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

`includePendingStatus: true` adds `pending` and the pending notices. A pact is pending until the provider has verified its content successfully — from `providerVersionBranch` (or on any branch before that branch was created), with each of `providerVersionTags`, or, with neither, at all. A failure of a pending pact does not fail the provider build.

`includeWipPactsSince: <date>` (with a `providerVersionBranch` or `providerVersionTags`) adds **work-in-progress** pacts after the selected ones: the latest pact of each consumer branch and tag, published on or after the date, that no selector chose and that is still pending. They carry `wip: true` and `pending: true`, so they never fail the build.

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

## `GET /v1/tenants/{tenant_slug}/pact-broker/released-versions/{uuid}` {#read-released-version-v1-tenants-tenant-slug-pact-broker-released-versions-uuid-get}

**Read a release**

One release, supported or not. Requires `pacts:view`.

Operation id: `read_released_version_v1_tenants__tenant_slug__pact_broker_released_versions__uuid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | The release's `uuid`. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a release. | `application/hal+json` any |
| 404 | `pact-released-version-not-found`: no such release in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PATCH /v1/tenants/{tenant_slug}/pact-broker/released-versions/{uuid}` {#patch-released-version-v1-tenants-tenant-slug-pact-broker-released-versions-uuid-patch}

**Record the end of support for a release**

`{"currentlySupported": false}` records that the release is no longer supported — what `pact-broker record-support-ended` sends. The release stays in the history; `true` is refused (record the release again instead).

Requires `pacts:edit`.

Operation id: `patch_released_version_v1_tenants__tenant_slug__pact_broker_released_versions__uuid__patch`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | The release's `uuid`. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record the end of support for a release.

- `application/merge-patch+json` — object
- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `currentlySupported` | enum `false` | no | Currently Supported. |

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `currentlySupported` | enum `false` | no | Currently Supported. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record the end of support for a release. | `application/hal+json` any |
| 404 | `pact-released-version-not-found`: no such release in this workspace. | — |
| 422 | `pact-deployment-invalid`: `currentlySupported` is not `false`. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/triggered-webhooks/{uuid}/logs` {#read-triggered-webhook-logs-v1-tenants-tenant-slug-pact-broker-triggered-webhooks-uuid-logs-get}

**Execution log of a triggered webhook**

What each attempt of one firing sent and received — a triggered webhook's `pb:logs` link. As `text/plain` (the default, as a Pact Broker answers) the logs of every attempt, in order; with `Accept: application/hal+json`, one entry per attempt under `executions` (`attempt`, `success`, `status`, `logs`, `createdAt`).

Secret header values read `**********`, and every secret value of the webhook is removed from the whole log, the receiver's response included. Requires `pacts:view`.

Operation id: `read_triggered_webhook_logs_v1_tenants__tenant_slug__pact_broker_triggered_webhooks__uuid__logs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | Path parameter identifying the uuid segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for execution log of a triggered webhook. | `application/json` any; `text/plain` any; `application/hal+json` any |
| 404 | `pact-triggered-webhook-not-found`: no such triggered webhook. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-broker/webhooks` {#read-webhooks-v1-tenants-tenant-slug-pact-broker-webhooks-get}

**List webhooks**

Every webhook of the workspace — the index's `pb:webhooks` link. Each is linked under `_links.pb:webhooks` and embedded under `_embedded.webhooks`. Secrets are never returned: a password and a secret header read `**********`, a signing secret reads `signed: true`.

Requires `pacts:view`.

Operation id: `read_webhooks_v1_tenants__tenant_slug__pact_broker_webhooks_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list webhooks. | `application/hal+json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/webhooks` {#post-webhook-v1-tenants-tenant-slug-pact-broker-webhooks-post}

**Create a webhook**

Create a webhook — what `pact-broker create-webhook` posts. The body is the Pact Broker's: `events` (default `contract_content_changed`), an optional `consumer` and `provider` (omit both for every pact of the workspace) and the `request` to send.

- **Events:** `contract_published`, `contract_content_changed`, `contract_requiring_verification_published` (once per provider version that has not verified the pact: the head of the provider's main branch and what is deployed or released), `provider_verification_published`, `provider_verification_succeeded`, `provider_verification_failed`, and Apiome's `consumer_version_branch_created` and stale-pact remediation events (`contract_became_stale`, `contract_no_longer_stale`, `contract_republish_requested`, `contract_republish_request_expired`).
- **Templates:** `${pactbroker.*}` parameters are substituted in the URL's path and query, the headers, the credentials and the body when the webhook fires. Template parameters: `${pactbroker.consumerName}`, `${pactbroker.providerName}`, `${pactbroker.consumerVersionNumber}`, `${pactbroker.providerVersionNumber}`, `${pactbroker.providerVersionTags}`, `${pactbroker.providerVersionDescriptions}`, `${pactbroker.providerVersionBranch}`, `${pactbroker.consumerVersionTags}`, `${pactbroker.consumerVersionBranch}`, `${pactbroker.pactUrl}`, `${pactbroker.verificationResultUrl}`, `${pactbroker.githubVerificationStatus}`, `${pactbroker.bitbucketVerificationStatus}`, `${pactbroker.azureDevOpsVerificationStatus}`, `${pactbroker.gitlabVerificationStatus}`, `${pactbroker.consumerLabels}`, `${pactbroker.providerLabels}`, `${pactbroker.eventName}`, `${pactbroker.buildUrl}`, `${pactbroker.currentlyDeployedProviderVersionNumber}`.
- **Target:** send `request` for any HTTP endpoint (POST, PUT or PATCH), or Apiome's `target` of type `github_repository_dispatch` to start a GitHub Actions workflow.
- **Where it may go:** http or https, to a public address. Loopback, private and link-local addresses are refused when the webhook is saved and again on every send; redirects are not followed.
- **Secrets:** `password`, the `target` token, secret headers (`Authorization`, anything naming a token, secret, API key or cookie) and `signingSecret` are sealed in the credential vault and never returned or logged.
- **Signing:** with `signingSecret`, each delivery carries `X-Apiome-Signature: sha256=<hex>`, the HMAC-SHA256 of the body.
- **Limit:** 200 webhooks per workspace.
- **Delivery:** up to 4 attempts (after 10 s, 60 s and 5 min; `Retry-After` is honoured), then the firing is dead-lettered.

Answers `201` with the webhook and its URL in `Location`. Requires `pacts:create`.

Operation id: `post_webhook_v1_tenants__tenant_slug__pact_broker_webhooks_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create a webhook.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `description` | string | no | Free-text description. |
| `consumer` | object | no | Only pacts of this consumer. Omit for any. |
| `provider` | object | no | Only pacts of this provider. Omit for any. |
| `enabled` | boolean | no | Whether the resource is active. |
| `events` | array of object | no | Default: `contract_content_changed`. |
| `request` | object | no | The HTTP request to send. Send this or `target`. |
| `target` | object | no | Apiome: a GitHub Actions `repository_dispatch`, in place of `request`. |
| `signingSecret` | string | no | Apiome: when set, every delivery carries `X-Apiome-Signature: sha256=<hex>`, the HMAC-SHA256 of the body. Sealed; a webhook that has one reads `signed: true`. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a webhook. | `application/hal+json` any |
| 409 | `pact-webhook-limit-reached`: the workspace already has 200 webhooks. | — |
| 422 | `pact-webhook-invalid`: the body is malformed; `detail.pointer` names the field. | — |
| 503 | `pact-webhook-secrets-unavailable`: the webhook carries a secret and the server has no key to seal it with. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/webhooks/consumer/{consumer}` {#read-scoped-v1-tenants-tenant-slug-pact-broker-webhooks-consumer-consumer-get}

**List the webhooks of a consumer**

The webhooks defined for exactly this scope (a webhook for all pacts is not listed here; see `GET …/webhooks`). Requires `pacts:view`.

Operation id: `read_scoped_v1_tenants__tenant_slug__pact_broker_webhooks_consumer__consumer__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `consumer` | path | string | yes | The consumer. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the webhooks of a consumer. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/webhooks/consumer/{consumer}` {#post-scoped-v1-tenants-tenant-slug-pact-broker-webhooks-consumer-consumer-post}

**Create a webhook for a consumer**

Create a webhook for this scope: the consumer and provider of the URL replace any in the body. Otherwise as `POST …/webhooks`. Requires `pacts:create`.

Operation id: `post_scoped_v1_tenants__tenant_slug__pact_broker_webhooks_consumer__consumer__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `consumer` | path | string | yes | The consumer. |

**Request body** (required)

Request body for create a webhook for a consumer.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `description` | string | no | Free-text description. |
| `consumer` | object | no | Only pacts of this consumer. Omit for any. |
| `provider` | object | no | Only pacts of this provider. Omit for any. |
| `enabled` | boolean | no | Whether the resource is active. |
| `events` | array of object | no | Default: `contract_content_changed`. |
| `request` | object | no | The HTTP request to send. Send this or `target`. |
| `target` | object | no | Apiome: a GitHub Actions `repository_dispatch`, in place of `request`. |
| `signingSecret` | string | no | Apiome: when set, every delivery carries `X-Apiome-Signature: sha256=<hex>`, the HMAC-SHA256 of the body. Sealed; a webhook that has one reads `signed: true`. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a webhook for a consumer. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 409 | `pact-webhook-limit-reached`: the workspace already has 200 webhooks. | — |
| 422 | `pact-webhook-invalid`: the body is malformed; `detail.pointer` names the field. | — |
| 503 | `pact-webhook-secrets-unavailable`: the webhook carries a secret and the server has no key to seal it with. | — |

## `POST /v1/tenants/{tenant_slug}/pact-broker/webhooks/execute` {#execute-unsaved-webhook-v1-tenants-tenant-slug-pact-broker-webhooks-execute-post}

**Run an unsaved webhook**

Send the webhook in the body once, now, without saving it — to try a request before creating the webhook. Parameters are filled from the latest pact of the named consumer and provider, or with placeholders. The answer shows the request (secrets redacted), the response and the execution log. A workspace may make 30 test runs per rate-limit window. Requires `pacts:create`.

Operation id: `execute_unsaved_webhook_v1_tenants__tenant_slug__pact_broker_webhooks_execute_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for run an unsaved webhook.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `description` | string | no | Free-text description. |
| `consumer` | object | no | Only pacts of this consumer. Omit for any. |
| `provider` | object | no | Only pacts of this provider. Omit for any. |
| `enabled` | boolean | no | Whether the resource is active. |
| `events` | array of object | no | Default: `contract_content_changed`. |
| `request` | object | no | The HTTP request to send. Send this or `target`. |
| `target` | object | no | Apiome: a GitHub Actions `repository_dispatch`, in place of `request`. |
| `signingSecret` | string | no | Apiome: when set, every delivery carries `X-Apiome-Signature: sha256=<hex>`, the HMAC-SHA256 of the body. Sealed; a webhook that has one reads `signed: true`. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for run an unsaved webhook. | `application/hal+json` any |
| 409 | `pact-webhook-limit-reached`: the workspace already has 200 webhooks. | — |
| 422 | `pact-webhook-invalid`: the body is malformed; `detail.pointer` names the field. | — |
| 429 | `pact-webhook-test-rate-limited`: too many test runs; `Retry-After` says when to retry. | — |
| 503 | `pact-webhook-secrets-unavailable`: the webhook carries a secret and the server has no key to seal it with. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/webhooks/provider/{provider}` {#read-scoped-v1-tenants-tenant-slug-pact-broker-webhooks-provider-provider-get}

**List the webhooks of a provider**

The webhooks defined for exactly this scope (a webhook for all pacts is not listed here; see `GET …/webhooks`). Requires `pacts:view`.

Operation id: `read_scoped_v1_tenants__tenant_slug__pact_broker_webhooks_provider__provider__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `provider` | path | string | yes | The provider. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the webhooks of a provider. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/webhooks/provider/{provider}` {#post-scoped-v1-tenants-tenant-slug-pact-broker-webhooks-provider-provider-post}

**Create a webhook for a provider**

Create a webhook for this scope: the consumer and provider of the URL replace any in the body. Otherwise as `POST …/webhooks`. Requires `pacts:create`.

Operation id: `post_scoped_v1_tenants__tenant_slug__pact_broker_webhooks_provider__provider__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `provider` | path | string | yes | The provider. |

**Request body** (required)

Request body for create a webhook for a provider.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `description` | string | no | Free-text description. |
| `consumer` | object | no | Only pacts of this consumer. Omit for any. |
| `provider` | object | no | Only pacts of this provider. Omit for any. |
| `enabled` | boolean | no | Whether the resource is active. |
| `events` | array of object | no | Default: `contract_content_changed`. |
| `request` | object | no | The HTTP request to send. Send this or `target`. |
| `target` | object | no | Apiome: a GitHub Actions `repository_dispatch`, in place of `request`. |
| `signingSecret` | string | no | Apiome: when set, every delivery carries `X-Apiome-Signature: sha256=<hex>`, the HMAC-SHA256 of the body. Sealed; a webhook that has one reads `signed: true`. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a webhook for a provider. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 409 | `pact-webhook-limit-reached`: the workspace already has 200 webhooks. | — |
| 422 | `pact-webhook-invalid`: the body is malformed; `detail.pointer` names the field. | — |
| 503 | `pact-webhook-secrets-unavailable`: the webhook carries a secret and the server has no key to seal it with. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/webhooks/provider/{provider}/consumer/{consumer}` {#read-scoped-v1-tenants-tenant-slug-pact-broker-webhooks-provider-provider-consumer-consumer-get}

**List the webhooks of an integration**

The webhooks defined for exactly this scope (a webhook for all pacts is not listed here; see `GET …/webhooks`). Requires `pacts:view`.

Operation id: `read_scoped_v1_tenants__tenant_slug__pact_broker_webhooks_provider__provider__consumer__consumer__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `provider` | path | string | yes | The provider. |
| `consumer` | path | string | yes | The consumer. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the webhooks of an integration. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/webhooks/provider/{provider}/consumer/{consumer}` {#post-scoped-v1-tenants-tenant-slug-pact-broker-webhooks-provider-provider-consumer-consumer-post}

**Create a webhook for an integration**

Create a webhook for this scope: the consumer and provider of the URL replace any in the body. Otherwise as `POST …/webhooks`. Requires `pacts:create`.

Operation id: `post_scoped_v1_tenants__tenant_slug__pact_broker_webhooks_provider__provider__consumer__consumer__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |
| `provider` | path | string | yes | The provider. |
| `consumer` | path | string | yes | The consumer. |

**Request body** (required)

Request body for create a webhook for an integration.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `description` | string | no | Free-text description. |
| `consumer` | object | no | Only pacts of this consumer. Omit for any. |
| `provider` | object | no | Only pacts of this provider. Omit for any. |
| `enabled` | boolean | no | Whether the resource is active. |
| `events` | array of object | no | Default: `contract_content_changed`. |
| `request` | object | no | The HTTP request to send. Send this or `target`. |
| `target` | object | no | Apiome: a GitHub Actions `repository_dispatch`, in place of `request`. |
| `signingSecret` | string | no | Apiome: when set, every delivery carries `X-Apiome-Signature: sha256=<hex>`, the HMAC-SHA256 of the body. Sealed; a webhook that has one reads `signed: true`. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create a webhook for an integration. | `application/hal+json` any |
| 404 | `pacticipant-not-found`: no such consumer or provider. | — |
| 409 | `pact-webhook-limit-reached`: the workspace already has 200 webhooks. | — |
| 422 | `pact-webhook-invalid`: the body is malformed; `detail.pointer` names the field. | — |
| 503 | `pact-webhook-secrets-unavailable`: the webhook carries a secret and the server has no key to seal it with. | — |

## `GET /v1/tenants/{tenant_slug}/pact-broker/webhooks/{uuid}` {#read-webhook-v1-tenants-tenant-slug-pact-broker-webhooks-uuid-get}

**Read a webhook**

One webhook by its `uuid` — the index's `pb:webhook` template. Requires `pacts:view`.

Operation id: `read_webhook_v1_tenants__tenant_slug__pact_broker_webhooks__uuid__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | Path parameter identifying the uuid segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a webhook. | `application/hal+json` any |
| 404 | `pact-webhook-not-found`: no such webhook in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-broker/webhooks/{uuid}` {#put-webhook-v1-tenants-tenant-slug-pact-broker-webhooks-uuid-put}

**Create or replace a webhook**

Replace the webhook with this `uuid`, or create it when the workspace has none — what `pact-broker create-or-update-webhook --uuid …` puts, so a pipeline can declare its webhook on every run. The body is the same as for creating one, and replaces the whole webhook.

A secret sent back as `**********` keeps the stored value; a secret left out is removed.

Answers `200` for a replacement and `201` for a new webhook. Requires `pacts:edit` (`pacts:create` when it creates).

Operation id: `put_webhook_v1_tenants__tenant_slug__pact_broker_webhooks__uuid__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | Path parameter identifying the uuid segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create or replace a webhook.

- `application/json` — object

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `description` | string | no | Free-text description. |
| `consumer` | object | no | Only pacts of this consumer. Omit for any. |
| `provider` | object | no | Only pacts of this provider. Omit for any. |
| `enabled` | boolean | no | Whether the resource is active. |
| `events` | array of object | no | Default: `contract_content_changed`. |
| `request` | object | no | The HTTP request to send. Send this or `target`. |
| `target` | object | no | Apiome: a GitHub Actions `repository_dispatch`, in place of `request`. |
| `signingSecret` | string | no | Apiome: when set, every delivery carries `X-Apiome-Signature: sha256=<hex>`, the HMAC-SHA256 of the body. Sealed; a webhook that has one reads `signed: true`. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create or replace a webhook. | `application/hal+json` any |
| 201 | The webhook did not exist and was created. | — |
| 409 | `pact-webhook-limit-reached`: the workspace already has 200 webhooks. | — |
| 422 | `pact-webhook-invalid`: the body is malformed; `detail.pointer` names the field. | — |
| 503 | `pact-webhook-secrets-unavailable`: the webhook carries a secret and the server has no key to seal it with. | — |

## `DELETE /v1/tenants/{tenant_slug}/pact-broker/webhooks/{uuid}` {#remove-webhook-v1-tenants-tenant-slug-pact-broker-webhooks-uuid-delete}

**Delete a webhook**

Delete a webhook. Its queued deliveries, its triggered-webhook history and their logs go with it. Requires `pacts:delete`.

Operation id: `remove_webhook_v1_tenants__tenant_slug__pact_broker_webhooks__uuid__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | Path parameter identifying the uuid segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a webhook. | — |
| 404 | `pact-webhook-not-found`: no such webhook in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-broker/webhooks/{uuid}/execute` {#execute-saved-webhook-v1-tenants-tenant-slug-pact-broker-webhooks-uuid-execute-post}

**Run a webhook now**

Send a saved webhook once, now — a webhook's `pb:execute` link and what `pact-broker test-webhook` posts. Parameters are filled from the latest pact of the webhook's consumer and provider, or with placeholders; `${pactbroker.eventName}` is `test`. Nothing is queued or retried. The answer shows the request (secrets redacted), the response and `logs`. A workspace may make 30 test runs per rate-limit window.

Requires `pacts:edit`.

Operation id: `execute_saved_webhook_v1_tenants__tenant_slug__pact_broker_webhooks__uuid__execute_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `uuid` | path | string | yes | Path parameter identifying the uuid segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for run a webhook now. | `application/hal+json` any |
| 404 | `pact-webhook-not-found`: no such webhook in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 429 | `pact-webhook-test-rate-limited`: too many test runs; `Retry-After` says when to retry. | — |
| 503 | `pact-webhook-secrets-unavailable`: the webhook's secrets cannot be opened. | — |

## `GET /v1/tenants/{tenant_slug}/pact-comparisons` {#list-comparisons-v1-tenants-tenant-slug-pact-comparisons-get}

**List recent bi-directional comparisons**

The workspace's most recent bi-directional verification results (PFX-2.3), newest first, each with its verdict, how strong it is (`full`, `partial`, `failed`, `none`), one sentence to read it by, and the counts of its fidelity report. Requires `pacts:view`.

Operation id: `list_comparisons_v1_tenants__tenant_slug__pact_comparisons_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | How many to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list recent bi-directional comparisons. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-comparisons/{result_id}/fidelity` {#read-fidelity-v1-tenants-tenant-slug-pact-comparisons-result-id-fidelity-get}

**Read the fidelity report of a bi-directional comparison**

What a bi-directional comparison compared and what it could not: for every interaction the checks with their status (`compared`, `partial`, `failed`, `not-run` with the reason), the matching rules it could not prove, and the items it could not compare. A green verdict is only as strong as `strength` says. Requires `pacts:view`.

Operation id: `read_fidelity_v1_tenants__tenant_slug__pact_comparisons__result_id__fidelity_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `result_id` | path | string | yes | Path parameter identifying the result id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the fidelity report of a bi-directional comparison. | `application/json` object |
| 404 | `pact-verification-not-found`: no bi-directional result with that id in this workspace, or the result was published by a Pact verifier and has no comparison. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-environments` {#read-environment-topology-v1-tenants-tenant-slug-pact-environments-get}

**Environments and what is deployed to them**

Every Pact environment of the workspace (by name) with each pacticipant version currently deployed to it (`deployed`: pacticipant, version, application instance, when) and each release it currently supports (`released`). `truncated` is true when either list stopped at 2000 entries. Requires `pacts:view`.

Operation id: `read_environment_topology_v1_tenants__tenant_slug__pact_environments_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for environments and what is deployed to them. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-environments/{environment}/deployments` {#read-deployment-history-v1-tenants-tenant-slug-pact-environments-environment-deployments-get}

**Deployment history of an environment**

Every deployment recorded to the environment, current or replaced, newest first: pacticipant, version, application instance, `currentlyDeployed`, `deployedAt`, `undeployedAt` and who recorded it. `pacticipant` narrows to one pacticipant (handle or name). Pass `nextCursor` back as `cursor` for the next page. Requires `pacts:view`.

Operation id: `read_deployment_history_v1_tenants__tenant_slug__pact_environments__environment__deployments_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `environment` | path | string | yes | Path parameter identifying the environment segment. |
| `pacticipant` | query | string or null | no | Only this pacticipant's deployments (handle or name). |
| `cursor` | query | string or null | no | The `nextCursor` of the previous page. |
| `limit` | query | integer | no | The page size. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for deployment history of an environment. | `application/json` object |
| 400 | `pact-deployment-cursor-invalid`. | — |
| 404 | `pact-environment-not-found` or `pacticipant-not-found`. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-environments/{environment}/simulate` {#read-deployment-simulation-v1-tenants-tenant-slug-pact-environments-environment-simulate-get}

**Simulate a deployment**

What would happen if `pacticipant` `version` were deployed to the environment (to `applicationInstance`, or the unnamed instance) — without recording anything. Answers the candidate's own can-i-deploy `verdict`, the version it would `replace`, and `impacts`: for each version of a pacticipant it has a pact with that is **running** in the environment or **pending** (deployed or released elsewhere, not here), its verdict `before` and `after` and the `effect` (`breaks`, `fixes`, `clears`, `blocks`, `changes`, `unchanged`). At most 20 versions are checked; the rest are in `notChecked` with the reason. Requires `pacts:view`.

Operation id: `read_deployment_simulation_v1_tenants__tenant_slug__pact_environments__environment__simulate_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `environment` | path | string | yes | Path parameter identifying the environment segment. |
| `pacticipant` | query | string | yes | The pacticipant to deploy (handle or name). |
| `version` | query | string | yes | The version to deploy. |
| `applicationInstance` | query | string or null | no | The instance to deploy to; the unnamed one when omitted. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for simulate a deployment. | `application/json` object |
| 400 | `pact-simulation-invalid`: a malformed `applicationInstance`. | — |
| 404 | `pact-environment-not-found`, `pacticipant-not-found` or `pacticipant-version-not-found`. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-health` {#read-health-v1-tenants-tenant-slug-pact-health-get}

**Read the workspace's contract health**

Every consumer ↔ provider pair with a pact (PFX-6.3), rolled up into one state — `healthy`, `degraded`, `failing` or `unknown` — fused from its signals: the newest pact's latest verdict, the window's pass rate and flakiness (how often the verdict flips between consecutive results), whether the stale-pact sweep found it overdue, an open re-publish request, and failed contract-webhook deliveries. Each signal says `ok`, `warn`, `fail` or `unknown` with a reason code. Pairs are listed worst first, at most 500 (`truncated`, `omitted_pairs`). Narrow by `provider`, `consumer` and `state`; the `counts` cover every pair the provider/consumer filter matches. Computed on every read. Requires `pacts:view`.

Operation id: `read_health_v1_tenants__tenant_slug__pact_health_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `window` | query | string or null | no | `7d`, `30d` or `90d` (default `30d`). |
| `provider` | query | string or null | no | Only this provider's pairs. |
| `consumer` | query | string or null | no | Only this consumer's pairs. |
| `state` | query | string or null | no | Only pairs in this state: `healthy`, `degraded`, `failing` or `unknown`. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the workspace's contract health. | `application/json` [`PactHealthOverview`](#schema-pacthealthoverview) |
| 400 | `pact-health-window-invalid` or `pact-health-state-invalid`. | — |
| 404 | `pacticipant-not-found` for the `provider` or `consumer` filter. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-health/providers/{provider}/consumers/{consumer}` {#read-pair-health-v1-tenants-tenant-slug-pact-health-providers-provider-consumers-consumer-get}

**Read one pair's contract health and trends**

One consumer ↔ provider pair's health (PFX-6.3) — its state, every fused signal and the window's analytics — and its **trend**: one bucket per day for `7d` and `30d`, per week for `90d`, oldest first and empty ones included, each with runs, pass rate, verdict flips, flakiness and mean duration. `{provider}` and `{consumer}` are handles, ids or names. Requires `pacts:view`.

Operation id: `read_pair_health_v1_tenants__tenant_slug__pact_health_providers__provider__consumers__consumer__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `window` | query | string or null | no | `7d`, `30d` or `90d` (default `30d`). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one pair's contract health and trends. | `application/json` [`PactPairHealthDetail`](#schema-pactpairhealthdetail) |
| 400 | `pact-health-window-invalid`. | — |
| 404 | `pacticipant-not-found`, or `pact-health-pair-not-found` when the consumer has published no pact for the provider. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-postman-collections` {#export-pact-postman-collection-v1-tenants-tenant-slug-pact-postman-collections-post}

**Export a pact as a Postman collection**

Writes a **Postman Collection v2.1** from a pact: one request per HTTP interaction against a `{{baseUrl}}` variable, a saved example of the expected response, and (`tests`, default on) a test script that checks the status, the expected headers and the body by Pact's default rules (extra object keys allowed, arrays of the same length, other values equal). Provider states are named in each request's description.

Send `provider` + `consumer` and at most one of `consumerVersion`, `tag`, `branch`, `pactVersionSha` for a stored pact (none: the latest), or `pact` for an inline document. Nothing is stored.

`notices` lists what the collection does not carry, each with a code, outcome (`left-out`, `not-asserted`, `not-applied`, `info`), JSON Pointer and reason: message and gRPC interactions, non-text bodies, values governed by matching rules, generators, and the provider states to set up. A pact with no HTTP interaction to export is `422 pact-postman-no-http-interactions`. Requires `pacts:view`.

Operation id: `export_pact_postman_collection_v1_tenants__tenant_slug__pact_postman_collections_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for export a pact as a postman collection.

- `application/json` — [`PactPostmanRequest`](#schema-pactpostmanrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export a pact as a postman collection. | `application/json` object |
| 404 | `pacticipant-not-found` or `pact-not-found`: no such stored pact in this workspace. | — |
| 413 | `pact-too-large`: the inline pact is over the workspace's pact size limit. | — |
| 422 | `pact-postman-export-invalid` (no pact named, two selections, an inline pact with a selection, a bad `baseUrl`), `pact-invalid` (the inline document is not a pact) or `pact-postman-no-http-interactions` (with `notices`). | — |

## `GET /v1/tenants/{tenant_slug}/pact-republish-requests` {#read-requests-v1-tenants-tenant-slug-pact-republish-requests-get}

**List re-publish requests**

The workspace's re-publish requests (PFX-6.2), newest first: each stale pact the sweep asked its consumer to re-publish, its state (`requested`, `acknowledged`, `republished`, `cleared` — verified meanwhile — or `expired`, escalated), its window, and what notifying the consumer's owners did. Narrow by `provider`, `consumer` and `state` (`open` for requested and acknowledged); pass `next_cursor` as `cursor` for the next page. Requires `pacts:view`.

Operation id: `read_requests_v1_tenants__tenant_slug__pact_republish_requests_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | query | string or null | no | Only this provider's. |
| `consumer` | query | string or null | no | Only this consumer's. |
| `state` | query | string or null | no | A state, or `open`. |
| `cursor` | query | string or null | no | The `next_cursor` of the previous page. |
| `limit` | query | integer | no | Page size. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list re-publish requests. | `application/json` [`RepublishRequestPage`](#schema-republishrequestpage) |
| 400 | `pact-republish-request-cursor-invalid`. | — |
| 404 | `pacticipant-not-found` for the `provider` or `consumer` filter. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-republish-requests/{request_id}` {#read-request-v1-tenants-tenant-slug-pact-republish-requests-request-id-get}

**Read one re-publish request**

One re-publish request of the workspace (PFX-6.2). Requires `pacts:view`.

Operation id: `read_request_v1_tenants__tenant_slug__pact_republish_requests__request_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `request_id` | path | string | yes | Path parameter identifying the request id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one re-publish request. | `application/json` [`RepublishRequestRecord`](#schema-republishrequestrecord) |
| 404 | `pact-republish-request-not-found` in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-republish-requests/{request_id}/acknowledge` {#acknowledge-v1-tenants-tenant-slug-pact-republish-requests-request-id-acknowledge-post}

**Acknowledge a re-publish request**

The consumer acknowledges an open re-publish request (PFX-6.2), optionally with a `note` (what it will do, and when; at most 1000 characters). Acknowledging again updates the note. The request still expires at the end of its window unless the consumer re-publishes the pact or the provider verifies it. A request that is no longer open is a `409` (`pact-republish-request-closed`). Requires `pacts:edit`.

Operation id: `acknowledge_v1_tenants__tenant_slug__pact_republish_requests__request_id__acknowledge_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `request_id` | path | string | yes | Path parameter identifying the request id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for acknowledge a re-publish request.

- `application/json` — [`AcknowledgeRequest`](#schema-acknowledgerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for acknowledge a re-publish request. | `application/json` [`RepublishRequestRecord`](#schema-republishrequestrecord) |
| 404 | `pact-republish-request-not-found` in this workspace. | — |
| 409 | `pact-republish-request-closed`. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-suites/provider/{provider}/consumer/{consumer}/pact-version/{sha}` {#compile-pact-version-suite-v1-tenants-tenant-slug-pact-suites-provider-provider-consumer-consumer-pact-version-sha-post}

**Compile a pact version into a contract suite**

Compile one pact version into an executable contract suite (PFX-3.1): one case per HTTP interaction, with `source: pact_interaction` and `synthetic: false`. A case's `request` is the request the consumer recorded; its `pact` block carries the provider states, the expected response (status, headers, body) and the matching rules and generators of both sides.

**Deterministic per pact version.** The same pact version and the same options produce a byte-identical manifest and the same `sha256:` `digest`, whichever consumer version published it. `options.interactions` narrows the suite to named interactions (description or Pact 4 key); `options.max_interactions` caps it.

**Nothing is skipped silently.** Message and plugin interactions, interactions with no method or path, and request bodies that cannot be decoded are listed under `unsupported` and in `findings`; embedded Pact 1 matchers, unknown matchers, request generators and unreadable response bodies are `degraded` findings; each provider state the runner must set up is an `info` finding.

Nothing is persisted. Requires `pacts:view`.

Operation id: `compile_pact_version_suite_v1_tenants__tenant_slug__pact_suites_provider__provider__consumer__consumer__pact_version__sha__post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | The pact version's SHA-256 (64 hex characters). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for compile a pact version into a contract suite.

- `application/json` — [`PactSuiteCompileRequest`](#schema-pactsuitecompilerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for compile a pact version into a contract suite. | `application/json` [`PactSuiteResponse`](#schema-pactsuiteresponse) |
| 404 | `pacticipant-not-found` or `pact-not-found`: no such provider, consumer or pact version in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-verification-settings` {#read-settings-v1-tenants-tenant-slug-pact-verification-settings-get}

**Read the workspace's Pact verification settings**

The workspace's verification settings (PFX-6.2): the **cadence** on which Apiome's hosted verifier runs each pair (`on-publish`, `hourly`, `nightly` or `manual-only`), the **stale threshold** in hours (a pact not verified for longer is stale and opens a re-publish request), how many scheduled verifications may run at once, how long a re-publish request stays open, and whether stale pacts open requests. A workspace that never saved any reads the defaults (`customised: false`: manual-only, 72 h, 2, 72 h, on). Requires `pacts:view`.

Operation id: `read_settings_v1_tenants__tenant_slug__pact_verification_settings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read the workspace's pact verification settings. | `application/json` [`VerificationSettings`](#schema-verificationsettings) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-verification-settings` {#update-settings-v1-tenants-tenant-slug-pact-verification-settings-put}

**Save the workspace's Pact verification settings**

Replace the workspace's verification settings (PFX-6.2); every field is required. A cadence other than `manual-only` runs a pair only where an override names a verification target. Out-of-range values are a `422` naming the field. Requires `pacts:edit`.

Operation id: `update_settings_v1_tenants__tenant_slug__pact_verification_settings_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save the workspace's pact verification settings.

- `application/json` — [`VerificationSettingsInput`](#schema-verificationsettingsinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save the workspace's pact verification settings. | `application/json` [`VerificationSettings`](#schema-verificationsettings) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-verification-settings/overrides` {#read-overrides-v1-tenants-tenant-slug-pact-verification-settings-overrides-get}

**List the Pact verification overrides**

Every provider-wide and per-pair override of the workspace (PFX-6.2), by provider then consumer: its cadence, stale threshold and verification target (null inherits). `target_deleted` flags an override whose target was deleted. Requires `pacts:view`.

Operation id: `read_overrides_v1_tenants__tenant_slug__pact_verification_settings_overrides_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the pact verification overrides. | `application/json` [`OverrideList`](#schema-overridelist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-verification-settings/overrides` {#save-override-v1-tenants-tenant-slug-pact-verification-settings-overrides-put}

**Save a Pact verification override**

Create or replace the override of a provider (omit `consumer`) or of one consumer ↔ provider pair (PFX-6.2). Set at least one of `cadence`, `stale_threshold_hours` and `target_ref` (the verification target scheduled runs replay against); a null field inherits — the pair's override wins over the provider's, which wins over the workspace's. A workspace has at most 500 overrides. Requires `pacts:edit`.

Operation id: `save_override_v1_tenants__tenant_slug__pact_verification_settings_overrides_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save a pact verification override.

- `application/json` — [`OverrideInput`](#schema-overrideinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save a pact verification override. | `application/json` [`OverrideRecord`](#schema-overriderecord) |
| 404 | `pacticipant-not-found` or `target-not-found` in this workspace. | — |
| 422 | `pact-verification-override-invalid`, or a value out of range. | — |

## `DELETE /v1/tenants/{tenant_slug}/pact-verification-settings/overrides/{override_id}` {#remove-override-v1-tenants-tenant-slug-pact-verification-settings-overrides-override-id-delete}

**Remove a Pact verification override**

Remove one override (PFX-6.2); the provider or pair inherits again. Requires `pacts:edit`.

Operation id: `remove_override_v1_tenants__tenant_slug__pact_verification_settings_overrides__override_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `override_id` | path | string | yes | Path parameter identifying the override id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for remove a pact verification override. | — |
| 404 | `pact-verification-override-not-found` in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-verifier/pacts/provider/{provider}/consumer/{consumer}/pact-version/{sha}/reverify` {#reverify-v1-tenants-tenant-slug-pact-verifier-pacts-provider-provider-consumer-consumer-pact-version-sha-reverify-post}

**Re-run the verification of one pact**

Verify one pact version again on a registered verification target (PFX-5.5), with the hosted verifier (PFX-3.2): the same replay, matching, evidence and publishing. Without `provider_version` the run verifies as the provider version and branch of the pact version's newest result. The published result records `trigger: manual`.

A console run of the same consumer ↔ provider pair that is still running makes this a `409` (`pact-verify-in-progress`). Like the hosted verifier, a run that happened is `200` whatever it found: read `success` and `outcome`. Requires `pacts:create` and `verification_evidence:create`.

Operation id: `reverify_v1_tenants__tenant_slug__pact_verifier_pacts_provider__provider__consumer__consumer__pact_version__sha__reverify_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | path | string | yes | Path parameter identifying the consumer segment. |
| `sha` | path | string | yes | Path parameter identifying the sha segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for re-run the verification of one pact.

- `application/json` — [`ConsoleRunRequest`](#schema-consolerunrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for re-run the verification of one pact. | `application/json` [`ConsoleRunResponse`](#schema-consolerunresponse) |
| 400 | A malformed provider version, branch or build URL. | — |
| 404 | `pacticipant-not-found`, `pact-not-found` or `target-not-found` in this workspace. | — |
| 409 | `pact-verify-in-progress`: a console run of this pair is already running. | — |
| 422 | `pact-verify-provider-version-required`, `pact-verify-target-auth-unavailable`, or a target that cannot be used (`target-disabled`, `target-protocol-mismatch`, a URL refusal). | — |

## `GET /v1/tenants/{tenant_slug}/pact-verifier/pacts/provider/{provider}/results` {#read-results-v1-tenants-tenant-slug-pact-verifier-pacts-provider-provider-results-get}

**List a provider's verification results**

Every verification result of the provider, newest first (PFX-5.5): native results a Pact verifier published, the hosted verifier's, console re-runs and bi-directional comparisons. Each has its provider version and branch, build URL, verifier, trigger (`published`, `hosted`, `manual`, `stale-recheck`, `bidirectional`, or null before triggers were recorded), run duration and interaction counts. `consumer` narrows to one consumer; pass `next_cursor` as `cursor` for the next page. Requires `pacts:view`.

Operation id: `read_results_v1_tenants__tenant_slug__pact_verifier_pacts_provider__provider__results_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `consumer` | query | string or null | no | Only this consumer's results. |
| `cursor` | query | string or null | no | The `next_cursor` of the previous page. |
| `limit` | query | integer | no | Page size. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a provider's verification results. | `application/json` [`ResultHistoryPage`](#schema-resulthistorypage) |
| 400 | `pact-history-cursor-invalid`. | — |
| 404 | `pacticipant-not-found` or `pact-verification-not-found` in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-verifier/pacts/provider/{provider}/results/{result_id}` {#read-one-result-v1-tenants-tenant-slug-pact-verifier-pacts-provider-provider-results-result-id-get}

**Read one verification result with its log**

One verification result of the provider (PFX-5.5): its summary, its `test_results` as stored (each failed interaction's mismatches with `expected` and `actual` where the verifier sent them), a bi-directional result's `comparison`, and — when Apiome ran it — its evidence run, every request with its assertions. `evidence_status` says why the run is absent: `not-recorded` (a Pact verifier published the result), `not-found` (pruned) or `forbidden` (the caller lacks `verification_evidence:view`). Requires `pacts:view`.

Operation id: `read_one_result_v1_tenants__tenant_slug__pact_verifier_pacts_provider__provider__results__result_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `result_id` | path | string | yes | Path parameter identifying the result id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one verification result with its log. | `application/json` [`ResultDetail`](#schema-resultdetail) |
| 404 | `pacticipant-not-found` or `pact-verification-not-found` in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-verifier/pacts/provider/{provider}/verification-status` {#read-verification-status-v1-tenants-tenant-slug-pact-verifier-pacts-provider-provider-verification-status-get}

**Where a provider's verification stands**

Each consumer's newest pact for the provider (PFX-5.5), with the newest verification result of that pact version and whether it is **stale**: a pact version with no result at all — it changed since the provider last verified, or was never verified. `counts` is the KPI strip (pacts, verified, failing, stale, interactions, passing interactions, last verified). At most 500 consumers (`truncated`). Requires `pacts:view`.

Operation id: `read_verification_status_v1_tenants__tenant_slug__pact_verifier_pacts_provider__provider__verification_status_get`

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
| 200 | Successful response for where a provider's verification stands. | `application/json` [`VerificationStatus`](#schema-verificationstatus) |
| 404 | `pacticipant-not-found` or `pact-verification-not-found` in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-verifier/pacts/provider/{provider}/verify` {#verify-provider-v1-tenants-tenant-slug-pact-verifier-pacts-provider-provider-verify-post}

**Verify a provider against its pacts (hosted verifier)**

Run provider verification from Apiome (PFX-3.2): select the pacts the provider must honour, replay each interaction against a registered verification target, and publish a verification result per pact — no Pact library on the provider's side.

**Selection.** `selection` is the body of `…/pact-broker/pacts/provider/{provider}/for-verification`, unchanged (consumer-version selectors, pending and work-in-progress pacts). At most 25 pacts per run.

**Replay.** Each pact is compiled into its contract suite (the manifest and digest of `POST …/pact-suites/…`) and replayed on the contract runner under the target's policy: SSRF guard, timeouts, retries (transport failures only) and credentials come from the target, never from this request.

**Matching.** The status, the recorded headers and the body are compared under the pact's matching rules. Each mismatch names the interaction, the field (a JSON Pointer into the response body, or the header), the rule that failed, and the expected and actual values. A rule the verifier cannot apply fails the interaction; it never passes silently.

**Mutating interactions** (`POST`, `PUT`, `PATCH`, `DELETE`) are sent only when the target's policy allows mutating methods **and** `verification.allow_mutating` is true. A run cannot widen the target's policy.

**Provider states.** An interaction that names a provider state is skipped with `provider-state-not-set-up` unless `verification.replay_without_state_setup` is true (the target already holds the data).

**Publishing.** A pact is `passed` when every interaction was replayed and matched, `failed` when one did not match, and `incomplete` when nothing failed but something was skipped, unreachable or cannot be replayed. `passed` and `failed` are published as verification results against `provider_version` (and `provider_branch`), and show in the matrix and can-i-deploy; `incomplete` publishes nothing. `publish: false` is a dry run.

The answer is `200` for any run that happened; read `success` and `outcome`. Requires `pacts:create` and `verification_evidence:create`.

Operation id: `verify_provider_v1_tenants__tenant_slug__pact_verifier_pacts_provider__provider__verify_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for verify a provider against its pacts (hosted verifier).

- `application/json` — [`PactVerifyRequest`](#schema-pactverifyrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for verify a provider against its pacts (hosted verifier). | `application/json` [`PactVerifyResponse`](#schema-pactverifyresponse) |
| 400 | `pact-selector-invalid`, or a malformed provider version, branch or build URL. | — |
| 404 | `pacticipant-not-found` or `target-not-found` in this workspace. | — |
| 422 | `pact-verify-too-many-pacts`, `pact-verify-target-auth-unavailable`, or a target that cannot be used (`target-disabled`, `target-protocol-mismatch`, a URL refusal). | — |

## `POST /v1/tenants/{tenant_slug}/pact-verifier/pacts/provider/{provider}/verify-stale` {#verify-stale-v1-tenants-tenant-slug-pact-verifier-pacts-provider-provider-verify-stale-post}

**Verify every stale pact of a provider**

Verify each consumer's newest pact that has no verification result yet (PFX-5.5) in one run of the hosted verifier, as `provider_version` (required) on a registered verification target. The published results record `trigger: stale-recheck`. At most 25 pacts are verified; the rest are listed in `skipped` with `pact-verify-over-limit`, and a pair whose console run is still running with `pact-verify-in-progress` — none is dropped. No stale pact is `outcome: no-pacts`. Requires `pacts:create` and `verification_evidence:create`.

Operation id: `verify_stale_v1_tenants__tenant_slug__pact_verifier_pacts_provider__provider__verify_stale_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for verify every stale pact of a provider.

- `application/json` — [`ConsoleRunRequest`](#schema-consolerunrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for verify every stale pact of a provider. | `application/json` [`ConsoleRunResponse`](#schema-consolerunresponse) |
| 400 | A malformed provider version, branch or build URL. | — |
| 404 | `pacticipant-not-found`, `pact-not-found` or `target-not-found` in this workspace. | — |
| 409 | `pact-verify-in-progress`: a console run of this pair is already running. | — |
| 422 | `pact-verify-provider-version-required`, `pact-verify-target-auth-unavailable`, or a target that cannot be used (`target-disabled`, `target-protocol-mismatch`, a URL refusal). | — |

## `GET /v1/tenants/{tenant_slug}/pact-verifier/providers/{provider}/provider-states` {#list-states-route-v1-tenants-tenant-slug-pact-verifier-providers-provider-provider-states-get}

**List a provider's registered provider states**

The provider states the provider has registered (PFX-3.3), by name, each with its parameters, its default setup and its per-target overrides. Requires `pacts:view`.

Operation id: `list_states_route_v1_tenants__tenant_slug__pact_verifier_providers__provider__provider_states_get`

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
| 200 | Successful response for list a provider's registered provider states. | `application/json` array of [`ProviderStateRecord`](#schema-providerstaterecord) |
| 404 | `pacticipant-not-found` or `provider-state-not-found` in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-verifier/providers/{provider}/provider-states` {#create-state-route-v1-tenants-tenant-slug-pact-verifier-providers-provider-provider-states-post}

**Register a provider state**

Register a state the provider's pacts name, and how the hosted verifier sets it up (PFX-3.3).

**Name** — exactly as consumers write it (`an invoice 1042 exists`); unique per provider.

**Parameters** — `[{name, required, default, description}]`. An interaction that leaves out a required parameter without a default is held back with `provider-state-param-missing`; one that passes an undeclared parameter is reported, and the parameter passed on.

**Setup** — `{kind: "state_change", url, teardown}` posts the Pact state-change body `{state, params, action}` to `url`: a path is sent to the verification target with its credential, an absolute http(s) URL through the SSRF guard with none. `{kind: "fixture", requests, teardown_requests}` sends recorded requests to the target, `${param}` substituted; empty `requests` means the target already holds the data. Credentials are never stored in a fixture.

**Overrides** — `[{target_ref, setup}]`: a different setup on one verification target.

Requires `pacts:create`.

Operation id: `create_state_route_v1_tenants__tenant_slug__pact_verifier_providers__provider__provider_states_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for register a provider state.

- `application/json` — [`ProviderStateInput`](#schema-providerstateinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for register a provider state. | `application/json` [`ProviderStateRecord`](#schema-providerstaterecord) |
| 403 | The credential lacks the `pacts` permission this route needs. | — |
| 404 | `pacticipant-not-found` or `provider-state-not-found` in this workspace. | — |
| 409 | `provider-state-name-taken`. | — |
| 422 | `provider-state-invalid`, with a JSON Pointer to the place. | — |

## `POST /v1/tenants/{tenant_slug}/pact-verifier/providers/{provider}/provider-states/check` {#check-states-route-v1-tenants-tenant-slug-pact-verifier-providers-provider-provider-states-check-post}

**Check a provider's pacts against its provider states**

Before a hosted verification (PFX-3.3): select the pacts a run would (`selection`, as on `…/verify`), and report every provider state their interactions name — registered or not, the setup it would use on `target_ref`, and each problem: `provider-state-not-registered`, `provider-state-param-missing`, `provider-state-setup-blocked` (blocking — the run holds the interaction back) and `provider-state-param-undeclared` (a warning). `ready` is true when nothing blocks. Nothing is sent to the target. Requires `pacts:view`.

Operation id: `check_states_route_v1_tenants__tenant_slug__pact_verifier_providers__provider__provider_states_check_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for check a provider's pacts against its provider states.

- `application/json` — [`StateCheckRequest`](#schema-statecheckrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for check a provider's pacts against its provider states. | `application/json` [`StateCheckResponse`](#schema-statecheckresponse) |
| 400 | `pact-selector-invalid`. | — |
| 403 | The credential lacks the `pacts` permission this route needs. | — |
| 404 | `pacticipant-not-found` or `provider-state-not-found` in this workspace. | — |
| 422 | `pact-verify-too-many-pacts`. | — |

## `GET /v1/tenants/{tenant_slug}/pact-verifier/providers/{provider}/provider-states/{state_id}` {#get-state-route-v1-tenants-tenant-slug-pact-verifier-providers-provider-provider-states-state-id-get}

**Read a provider state**

One registered provider state (PFX-3.3). Requires `pacts:view`.

Operation id: `get_state_route_v1_tenants__tenant_slug__pact_verifier_providers__provider__provider_states__state_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `state_id` | path | string | yes | Path parameter identifying the state id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a provider state. | `application/json` [`ProviderStateRecord`](#schema-providerstaterecord) |
| 404 | `pacticipant-not-found` or `provider-state-not-found` in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/pact-verifier/providers/{provider}/provider-states/{state_id}` {#replace-state-route-v1-tenants-tenant-slug-pact-verifier-providers-provider-provider-states-state-id-put}

**Replace a provider state**

Replace a registered state's name, parameters, setup and overrides (PFX-3.3); the body is the one `POST` takes, and the overrides it lists replace the stored ones. Requires `pacts:edit`.

Operation id: `replace_state_route_v1_tenants__tenant_slug__pact_verifier_providers__provider__provider_states__state_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `state_id` | path | string | yes | Path parameter identifying the state id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace a provider state.

- `application/json` — [`ProviderStateInput`](#schema-providerstateinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace a provider state. | `application/json` [`ProviderStateRecord`](#schema-providerstaterecord) |
| 403 | The credential lacks the `pacts` permission this route needs. | — |
| 404 | `pacticipant-not-found` or `provider-state-not-found` in this workspace. | — |
| 409 | `provider-state-name-taken`. | — |
| 422 | `provider-state-invalid`, with a JSON Pointer to the place. | — |

## `DELETE /v1/tenants/{tenant_slug}/pact-verifier/providers/{provider}/provider-states/{state_id}` {#delete-state-route-v1-tenants-tenant-slug-pact-verifier-providers-provider-provider-states-state-id-delete}

**Delete a provider state**

Delete a registered state and its overrides (PFX-3.3). Interactions that name it are then held back with `provider-state-not-registered`. Requires `pacts:delete`.

Operation id: `delete_state_route_v1_tenants__tenant_slug__pact_verifier_providers__provider__provider_states__state_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `provider` | path | string | yes | Path parameter identifying the provider segment. |
| `state_id` | path | string | yes | Path parameter identifying the state id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a provider state. | — |
| 404 | `pacticipant-not-found` or `provider-state-not-found` in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-webhook-deliveries` {#read-deliveries-v1-tenants-tenant-slug-pact-webhook-deliveries-get}

**List webhook deliveries**

The firings of the workspace's contract webhooks, newest first: each with its status (`success`, `failure` — dead-lettered after every attempt, `retrying`, `not_run`), attempts, the event, the pact that caused it and how it was triggered (`resource_creation` or `user` for a redelivery). `webhook` narrows to one webhook, `status` to one status. Pass `nextCursor` back as `cursor` for the next page. Requires `pacts:view`.

Operation id: `read_deliveries_v1_tenants__tenant_slug__pact_webhook_deliveries_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `webhook` | query | string or null | no | Only this webhook's deliveries (its `uuid`). |
| `status` | query | enum `"success"`, `"failure"`, `"retrying"`, `"not_run"` or null | no | Only deliveries with this status. |
| `cursor` | query | string or null | no | The `nextCursor` of the previous page. |
| `limit` | query | integer | no | The page size. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list webhook deliveries. | `application/json` object |
| 400 | `pact-webhook-delivery-cursor-invalid` or `pact-webhook-invalid` (unknown status). | — |
| 404 | `pact-webhook-not-found`: no such webhook in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-webhook-deliveries/latest` {#read-latest-deliveries-v1-tenants-tenant-slug-pact-webhook-deliveries-latest-get}

**Latest delivery of each webhook**

The newest firing of each of the workspace's contract webhooks, keyed by webhook `uuid`; a webhook that never fired is absent. Requires `pacts:view`.

Operation id: `read_latest_deliveries_v1_tenants__tenant_slug__pact_webhook_deliveries_latest_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for latest delivery of each webhook. | `application/json` object |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/pact-webhook-deliveries/{delivery_id}` {#read-delivery-v1-tenants-tenant-slug-pact-webhook-deliveries-delivery-id-get}

**Read a webhook delivery**

One firing and the log of each attempt (`attempt`, `success`, `status`, `logs`, `createdAt`), oldest first — what was sent and what came back, every secret removed. Requires `pacts:view`.

Operation id: `read_delivery_v1_tenants__tenant_slug__pact_webhook_deliveries__delivery_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `delivery_id` | path | string | yes | Path parameter identifying the delivery id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a webhook delivery. | `application/json` object |
| 404 | `pact-triggered-webhook-not-found`: no such delivery in this workspace. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/pact-webhook-deliveries/{delivery_id}/redeliver` {#post-redeliver-v1-tenants-tenant-slug-pact-webhook-deliveries-delivery-id-redeliver-post}

**Redeliver a webhook delivery**

Send a finished firing (`success` or `failure`) again: a new firing of the same webhook, with the same event and template parameters, queued now and retried as any other (`triggerType` `user`). The original and its log are kept. Answers `202` with the new delivery. Requires `pacts:edit`.

Operation id: `post_redeliver_v1_tenants__tenant_slug__pact_webhook_deliveries__delivery_id__redeliver_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `delivery_id` | path | string | yes | Path parameter identifying the delivery id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for redeliver a webhook delivery. | `application/json` object |
| 404 | `pact-triggered-webhook-not-found`: no such delivery in this workspace. | — |
| 409 | `pact-webhook-delivery-in-progress`: the delivery is still queued or being retried; `pact-webhook-disabled`: its webhook is disabled. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AcknowledgeRequest` {#schema-acknowledgerequest}

The consumer acknowledges a re-publish request.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `note` | string or null | no | What the consumer will do, and when. |

### `ConsoleRunRequest` {#schema-consolerunrequest}

A re-run or verify-all-stale from the Verification console.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target_ref` | string | yes | Slug or id of the registered verification target to replay against. |
| `provider_version` | string or null | no | The provider version being verified. A re-run defaults to the provider version of the pact's newest result; verify-all-stale requires it. |
| `provider_branch` | string or null | no | Its branch. A re-run that takes the provider version from a result takes its branch too. |
| `build_url` | string or null | no | http(s) URL of the CI build. |
| `verification` | `PactVerificationOptions` | no | What the run may send: the mutating-method opt-in, fixtures and the provider-state choice. |
| `context` | object | no | Non-secret context stored with the evidence. Never credentials. |

### `ConsoleRunResponse` {#schema-consolerunresponse}

A console run: the hosted verifier's answer, its trigger, and what it did not run.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | string | yes | The provider's handle. |
| `provider_version` | string | yes | The provider version verified. |
| `provider_branch` | string or null | no | Its branch, when stated. |
| `target` | `VerifiedTarget` | yes | The verification target replayed against. |
| `success` | boolean | yes | What a CI job should exit on: true when at least one pact was verified and every pact that is not pending `passed`. |
| `outcome` | string | yes | `passed`, `failed` (a non-pending pact failed), `incomplete` (none failed, but one could not be fully replayed) or `no-pacts` (the selectors chose nothing). |
| `pacts` | array of `PactVerification` | no | One entry per pact verified. |
| `trigger` | string | yes | `manual` (re-run), `stale-recheck` (verify all stale) or `scheduled`. |
| `skipped` | array of `SkippedPact` | no | Chosen but not verified, each with why. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `OverrideInput` {#schema-overrideinput}

A provider-wide or per-pair override, as ``PUT …/overrides`` creates or replaces it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | string | yes | The provider's handle, id or name. |
| `consumer` | string or null | no | The consumer's handle, id or name; omit for every consumer of the provider. |
| `cadence` | string or null | no | The cadence; null inherits. |
| `stale_threshold_hours` | integer or null | no | The stale threshold (1 … 2160); null inherits. |
| `target_ref` | string or null | no | Slug or id of the verification target scheduled runs replay against; null inherits. |

### `OverrideList` {#schema-overridelist}

Every override of the workspace, by provider then consumer.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `overrides` | array of [`OverrideRecord`](#schema-overriderecord) | no | Overrides. |

### `OverrideRecord` {#schema-overriderecord}

A stored override.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | The override's id (what `DELETE …/overrides/{id}` removes). |
| `provider` | string | yes | The provider's handle. |
| `provider_name` | string | yes | The provider's display name. |
| `consumer` | string or null | no | The consumer's handle; null for every consumer. |
| `consumer_name` | string or null | no | The consumer's display name. |
| `cadence` | string or null | no | The cadence; null inherits. |
| `stale_threshold_hours` | integer or null | no | The threshold; null inherits. |
| `target` | string or null | no | The verification target's handle; null inherits. |
| `target_name` | string or null | no | Its display name. |
| `target_deleted` | boolean | no | True when the target was deleted: scheduled runs of this override cannot run. |
| `updated_at` | string or null | no | When it was last saved. |

### `PactHealthOverview` {#schema-pacthealthoverview}

The workspace's contract health over a window.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `window` | string | yes | `7d`, `30d` or `90d`. |
| `since` | string | yes | The window's first instant (inclusive). |
| `until` | string | yes | The window's end (exclusive): the end of today, UTC. |
| `bucket_days` | integer | yes | The length of one trend bucket, in days. |
| `generated_at` | string | yes | When this rollup was computed (it is computed on every read). |
| `counts` | `PactHealthCounts` | yes | Pairs per state. |
| `totals` | `PactPairMetrics` | yes | The analytics of every listed pair together. |
| `pairs` | array of `PactPairHealth` | no | Worst first, then by provider and consumer handle. |
| `truncated` | boolean | no | True when more than 500 pairs match (the rest are left out and counted). |
| `omitted_pairs` | integer | no | How many matching pairs were left out by the cap. |

### `PactPairHealthDetail` {#schema-pactpairhealthdetail}

One pair's health with its trend.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `window` | string | yes | `7d`, `30d` or `90d`. |
| `since` | string | yes | The window's first instant (inclusive). |
| `until` | string | yes | The window's end (exclusive). |
| `bucket_days` | integer | yes | The length of one trend bucket, in days. |
| `generated_at` | string | yes | When this was computed. |
| `pair` | `PactPairHealth` | yes | The pair's health over the whole window. |
| `trend` | array of `PactTrendBucket` | yes | Every bucket of the window, oldest first (empty ones included). |

### `PactPostmanRequest` {#schema-pactpostmanrequest}

What to export: a stored pact (by pair and selection) or an inline Pact document.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | string or null | no | The provider pacticipant (handle, id or name). Required for a stored pact. |
| `consumer` | string or null | no | The consumer pacticipant (handle, id or name). Required for a stored pact. |
| `consumerVersion` | string or null | no | The pact this consumer version published. |
| `tag` | string or null | no | The latest pact of consumer versions with this tag. |
| `branch` | string or null | no | The latest pact of consumer versions on this branch. |
| `pactVersionSha` | string or null | no | The pact with this content address (64 hex characters). |
| `pact` | object or null | no | An inline Pact document (specification 1–4) instead of a stored pact. `consumer` and `provider` then only name the collection, and default to the document's own. |
| `baseUrl` | string or null | no | The value of the `{{baseUrl}}` collection variable (an http or https URL). Omitted: empty, to fill in (Newman: `--env-var baseUrl=…`). |
| `tests` | boolean | no | Give each request a test script that checks the expected response. |

### `PactSuiteCompileRequest` {#schema-pactsuitecompilerequest}

What to compile from the pact version named in the URL. An empty body compiles everything.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `options` | `PactSuiteOptions` | no | Compiler options. They are echoed on the manifest (`pact.options`) and hashed into its digest, so the same pact version compiled with the same options always yields the same suite. |

### `PactSuiteResponse` {#schema-pactsuiteresponse}

The suite compiled from one pact version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `consumer` | string | yes | The consumer's handle. |
| `provider` | string | yes | The provider's handle. |
| `pact_version_sha` | string | yes | The pact version compiled. |
| `manifest` | `ContractSuiteManifest` | yes | The compiled suite: one `pact_interaction` case per HTTP interaction, with `unsupported` and `findings` naming everything that could not be replayed. |

### `PactVerifyRequest` {#schema-pactverifyrequest}

Which pacts to verify, against which target, as which provider build.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target_ref` | string | yes | Slug or id of the registered verification target (ECA-1.2) to replay against: an `http` target for HTTP interactions, a `grpc` or `connect` target for gRPC calls recorded by the Pact protobuf plugin. |
| `provider_version` | string | yes | The provider application version being verified (a commit SHA). Results are recorded against it. |
| `provider_branch` | string or null | no | The branch of that provider version. Recorded on the version before a result is published, and used as `providerVersionBranch` for pending pacts and `matchingBranch` selectors when `selection` does not state one. |
| `build_url` | string or null | no | http(s) URL of the CI build, stored on each result. |
| `selection` | object | no | Which pacts to verify — the body of `POST …/pact-broker/pacts/provider/{provider}/for-verification`, unchanged: `consumerVersionSelectors`, `providerVersionBranch`, `providerVersionTags`, `includePendingStatus`, `includeWipPactsSince`. Empty selects what a Pact verifier gets by default. |
| `verification` | `PactVerificationOptions` | no | What this run may send: the mutating-method opt-in, fixtures and the provider-state choice. |
| `publish` | boolean | no | Publish a verification result for every pact whose run is conclusive (`passed` or `failed`). `false` is a dry run: everything is replayed and reported, nothing is published. |
| `context` | object | no | Non-secret CI context (commit, workflow URL) stored with the evidence. Never credentials. |

### `PactVerifyResponse` {#schema-pactverifyresponse}

The outcome of one hosted verification.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | string | yes | The provider's handle. |
| `provider_version` | string | yes | The provider version verified. |
| `provider_branch` | string or null | no | Its branch, when stated. |
| `target` | `VerifiedTarget` | yes | The verification target replayed against. |
| `success` | boolean | yes | What a CI job should exit on: true when at least one pact was verified and every pact that is not pending `passed`. |
| `outcome` | string | yes | `passed`, `failed` (a non-pending pact failed), `incomplete` (none failed, but one could not be fully replayed) or `no-pacts` (the selectors chose nothing). |
| `pacts` | array of `PactVerification` | no | One entry per pact verified. |

### `ProviderStateInput` {#schema-providerstateinput}

The body that registers or replaces a provider state.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | The state exactly as consumers write it (`an invoice 1042 exists`). |
| `description` | string or null | no | What the state means. |
| `parameters` | array of `StateParameter` | no | The parameters the state takes. |
| `setup` | `StateSetup` | yes | How the state is set up by default. |
| `overrides` | array of `StateOverrideInput` | no | Per-target setups, replacing the default on that target. |

### `ProviderStateRecord` {#schema-providerstaterecord}

A registered provider state, as stored.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | The state's id. |
| `provider` | string | yes | The provider's handle. |
| `name` | string | yes | The state, as consumers write it. |
| `description` | string or null | no | What it means. |
| `parameters` | array of `StateParameter` | no | The parameters it takes. |
| `setup` | `StateSetup` | yes | The default setup. |
| `overrides` | array of `StateOverrideRecord` | no | Per-target setups. |
| `created_at` | string (date-time) | yes | When it was registered. |
| `updated_at` | string (date-time) | yes | When it last changed. |

### `RepublishRequestPage` {#schema-republishrequestpage}

One page of re-publish requests, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `requests` | array of [`RepublishRequestRecord`](#schema-republishrequestrecord) | no | Requests. |
| `next_cursor` | string or null | no | Pass as `cursor` for the next page. |

### `RepublishRequestRecord` {#schema-republishrequestrecord}

A request to a consumer to re-publish a stale pact.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | The request's id. |
| `provider` | string | yes | The provider's handle. |
| `provider_name` | string | yes | The provider's display name. |
| `consumer` | string | yes | The consumer's handle. |
| `consumer_name` | string | yes | The consumer's display name. |
| `pact_version_sha` | string | yes | The stale pact version. |
| `consumer_version` | string | yes | The consumer version that published it last. |
| `state` | string | yes | `requested`, `acknowledged`, `republished`, `cleared` or `expired`. |
| `threshold_hours` | integer | yes | The stale threshold it crossed. |
| `reference_at` | string or null | no | When the pact was last verified (or published, when never verified). |
| `requested_at` | string or null | no | When the request was opened. |
| `expires_at` | string or null | no | When it expires and escalates, unless answered. |
| `acknowledged_at` | string or null | no | When the consumer acknowledged it. |
| `acknowledged_by` | string or null | no | Who acknowledged it. |
| `note` | string or null | no | The acknowledgement's note. |
| `resolved_at` | string or null | no | When it was republished, cleared or expired. |
| `resolved_consumer_version` | string or null | no | The consumer version that re-published, for `republished`. |
| `notification_status` | string or null | no | What notifying the consumer's owners did: `routed`, `throttled`, `unowned`, `catch_all`, `unlinked` (the consumer is linked to no consumer or project with owners) or `failed`. |
| `escalation_status` | string or null | no | The same, for the escalation on expiry. |
| `webhook_deliveries` | integer | no | Contract webhook deliveries queued for it. |

### `ResultDetail` {#schema-resultdetail}

One verification result in full.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `result` | `ResultSummary` | yes | The result. |
| `provider` | string | yes | The provider's handle. |
| `provider_name` | string | yes | The provider's display name. |
| `test_results` | array of any | no | The per-interaction results as stored: `interactionDescription`, `success`, and for a failure `mismatches` (`attribute`, `identifier`, `description`, and — from the hosted verifier and most Pact verifiers — `expected` and `actual`) or `exceptions`. |
| `comparison` | object or null | no | A bi-directional result's comparison. |
| `evidence_status` | string | yes | `attached`, `not-recorded`, `not-found` (pruned) or `forbidden` (no `verification_evidence:view`). |
| `evidence` | `VerificationRunRecord` or null | no | The evidence run: every request with its assertions, when `attached`. |

### `ResultHistoryPage` {#schema-resulthistorypage}

One page of a provider's verification history.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | string | yes | The provider's handle. |
| `provider_name` | string | yes | The provider's display name. |
| `consumer` | string or null | no | The consumer the page is narrowed to. |
| `results` | array of `ResultSummary` | no | Newest first. |
| `next_cursor` | string or null | no | Pass as `cursor` for the next page; null at the end. |

### `StateCheckRequest` {#schema-statecheckrequest}

Which pacts to check, and on which target.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `selection` | object | no | Which pacts — the `selection` of the verify request (the body of `…/for-verification`), unchanged. Empty selects what a Pact verifier gets by default. |
| `target_ref` | string or null | no | Slug or id of the verification target the run would use: its overrides are chosen and its mutating-method policy checked. Omit to check the default setups. |

### `StateCheckResponse` {#schema-statecheckresponse}

Whether a provider can set up every state its pacts name.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | string | yes | The provider's handle. |
| `target` | string or null | no | The target checked against, when one was named. |
| `ready` | boolean | yes | True when no interaction would be held back for its provider states. |
| `pacts` | integer | yes | How many pacts the selection chose. |
| `blocking` | integer | yes | How many blocking problems were found. |
| `warnings` | integer | yes | How many warnings were found. |
| `states` | array of `StateCheckEntry` | no | Every state the selected interactions name; unregistered ones first. |
| `unused` | array of string | no | Registered states no selected interaction names. |

### `VerificationSettings` {#schema-verificationsettings}

The workspace's verification settings, as read.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `cadence` | string | yes | `on-publish`, `hourly`, `nightly` or `manual-only`: when the hosted verifier runs a pair. |
| `stale_threshold_hours` | integer | yes | A pact not verified for longer than this is stale (1 … 2160). |
| `max_concurrent_runs` | integer | yes | How many scheduled verifications may run at once in the workspace (1 … 10). |
| `request_window_hours` | integer | yes | How long a re-publish request stays open before it expires and escalates (1 … 720). |
| `republish_requests_enabled` | boolean | yes | Whether a stale pact opens a re-publish request. |
| `customised` | boolean | yes | False while the workspace uses the defaults (never saved). |
| `updated_at` | string or null | no | When they were last saved. |

### `VerificationSettingsInput` {#schema-verificationsettingsinput}

The workspace's verification settings, as ``PUT`` replaces them.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `cadence` | string | yes | `on-publish`, `hourly`, `nightly` or `manual-only`: when the hosted verifier runs a pair. |
| `stale_threshold_hours` | integer | yes | A pact not verified for longer than this is stale (1 … 2160). |
| `max_concurrent_runs` | integer | yes | How many scheduled verifications may run at once in the workspace (1 … 10). |
| `request_window_hours` | integer | yes | How long a re-publish request stays open before it expires and escalates (1 … 720). |
| `republish_requests_enabled` | boolean | yes | Whether a stale pact opens a re-publish request. |

### `VerificationStatus` {#schema-verificationstatus}

Where a provider's verification stands.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provider` | string | yes | The provider's handle. |
| `provider_name` | string | yes | The provider's display name. |
| `counts` | `StatusCounts` | yes | The KPI strip. |
| `pacts` | array of `VerificationStatusEntry` | no | One per consumer, by handle. |
| `truncated` | boolean | no | True when the provider has more than 500 consumers (the rest are left out). |
| `settings` | `EffectiveSettings` or null | no | The cadence, stale threshold and target that apply to the provider (PFX-6.2). |
