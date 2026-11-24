---
title: "Pact broker"
description: "REST endpoints tagged pact-broker: 57 operations."
sidebar_position: 69
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.663.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `pact-broker` · 57 operations

## `GET /v1/tenants/{tenant_slug}/pact-broker` {#pact-broker-index-v1-tenants-tenant-slug-pact-broker-get}

**Pact Broker index**

The entry point of the Pact Broker–compatible API: the links a Pact client discovers the other routes from. Give a Pact client this URL as its **broker base URL** and a workspace API key as its **token**.

`pb:publish-contracts` is what `pact-broker publish` and the Pact libraries post to; `pb:provider-pacts-for-verification` is what a Pact verifier posts its consumer-version selectors to. `pb:publish-pact`, `pb:latest-pact-version`, `pb:pact-version`, `pb:latest-provider-pacts` and the others are URI templates. `pb:environments` lists the environments `pact-broker record-deployment` looks an environment up in. `pb:can-i-deploy-pacticipant-version-to-environment` and `…-to-tag` answer whether a version can be deployed; `pact-broker can-i-deploy` asks `…/pact-broker/matrix`. `pb:webhooks` and `pb:webhook` are what `pact-broker create-webhook` and `create-or-update-webhook` use.

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

- **Events:** `contract_published`, `contract_content_changed`, `contract_requiring_verification_published` (once per provider version that has not verified the pact: the head of the provider's main branch and what is deployed or released), `provider_verification_published`, `provider_verification_succeeded`, `provider_verification_failed`, and Apiome's `consumer_version_branch_created`.
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

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
