---
title: "Slate git preview"
description: "REST endpoints tagged slate-git-preview: 8 operations."
sidebar_position: 64
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `slate-git-preview` · 8 operations

## `GET /v1/slate/git/connections` {#list-git-connections-v1-slate-git-connections-get}

**List Git Connections**

List the tenant's git provider connections, without their secrets.

Operation id: `list_git_connections_v1_slate_git_connections_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list git connections. | `application/json` [`ConnectionListResponse`](#schema-connectionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/git/connections` {#create-git-connection-v1-slate-git-connections-post}

**Create Git Connection**

Register or update a git provider connection. Secret and token are write-only.

Operation id: `create_git_connection_v1_slate_git_connections_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create git connection.

- `application/json` — [`CreateConnectionRequest`](#schema-createconnectionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create git connection. | `application/json` [`ConnectionBody`](#schema-connectionbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/git/connections/{connection_id}/cleanup` {#cleanup-previews-v1-slate-git-connections-connection-id-cleanup-post}

**Cleanup Previews**

Reap the tenant's expired previews (audited).

Operation id: `cleanup_previews_v1_slate_git_connections__connection_id__cleanup_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `connection_id` | path | string | yes | Path parameter identifying the connection id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for cleanup previews. | `application/json` [`CleanupResponse`](#schema-cleanupresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/git/events` {#receive-git-event-v1-slate-git-events-post}

**Receive Git Event**

Receive a signed GitHub webhook and create one immutable preview per source digest.

The signature is verified over the **raw** request body — never a re-serialisation of the
parsed JSON — against the resolved connection's secret. A ping is answered, a non-push event
or a non-buildable push is accepted and ignored, a bad signature is 401, and a genuine branch
push idempotently yields a preview.

Operation id: `receive_git_event_v1_slate_git_events_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-GitHub-Event` | header | string or null | no | Header parameter: X Git Hub Event. |
| `X-GitHub-Delivery` | header | string or null | no | Header parameter: X Git Hub Delivery. |
| `X-Hub-Signature-256` | header | string or null | no | Header parameter: X Hub Signature 256. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for receive git event. | `application/json` [`EventReceiptResponse`](#schema-eventreceiptresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/git/previews` {#list-git-previews-v1-slate-git-previews-get}

**List Git Previews**

List the tenant's previews, newest first.

Operation id: `list_git_previews_v1_slate_git_previews_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `connectionId` | query | string or null | no | Restrict to one connection's previews. |
| `limit` | query | integer | no | Maximum previews to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list git previews. | `application/json` [`PreviewListResponse`](#schema-previewlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/git/previews/{build_id}` {#get-git-preview-v1-slate-git-previews-build-id-get}

**Get Git Preview**

Load one preview with its changed-page links, expiry/access and provider-status payload.

Operation id: `get_git_preview_v1_slate_git_previews__build_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `build_id` | path | string | yes | Path parameter identifying the build id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get git preview. | `application/json` [`PreviewBody`](#schema-previewbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/git/previews/{build_id}/checks` {#record-preview-checks-v1-slate-git-previews-build-id-checks-post}

**Record Preview Checks**

Record a check outcome; a pass advances the branch alias to this preview.

Operation id: `record_preview_checks_v1_slate_git_previews__build_id__checks_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `build_id` | path | string | yes | Path parameter identifying the build id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record preview checks.

- `application/json` — [`RecordChecksRequest`](#schema-recordchecksrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record preview checks. | `application/json` [`PreviewBody`](#schema-previewbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/git/previews/{build_id}/retry` {#retry-preview-build-v1-slate-git-previews-build-id-retry-post}

**Retry Preview Build**

Request a build retry (audited). No worker runs yet, so the honest boundary is unchanged.

Operation id: `retry_preview_build_v1_slate_git_previews__build_id__retry_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `build_id` | path | string | yes | Path parameter identifying the build id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for retry preview build. | `application/json` [`PreviewBody`](#schema-previewbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CleanupResponse` {#schema-cleanupresponse}

CleanupResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `reaped` | integer | yes | Reaped. |

### `ConnectionBody` {#schema-connectionbody}

A git provider connection, without its secret or token.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `siteId` | string | yes | Site ID. |
| `provider` | string | yes | Provider. |
| `repoOwner` | string | yes | Repo Owner. |
| `repoName` | string | yes | Repo Name. |
| `repoFullName` | string | yes | Repo Full Name. |
| `defaultBranch` | string | yes | Default Branch. |
| `previewHost` | string | yes | Preview Host. |
| `hasWebhookSecret` | boolean | yes | Has Webhook Secret. |
| `hasToken` | boolean | yes | Has Token. |
| `createdAt` | string or null | no | Created At. |
| `updatedAt` | string or null | no | Updated At. |

### `ConnectionListResponse` {#schema-connectionlistresponse}

ConnectionListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `connections` | array of [`ConnectionBody`](#schema-connectionbody) | yes | Connections. |

### `CreateConnectionRequest` {#schema-createconnectionrequest}

Register (or update) a git provider connection for a site.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `siteId` | string | yes | Site the connection builds previews for. |
| `repoOwner` | string | yes | Repository owner (organisation or user). |
| `repoName` | string | yes | Repository name. |
| `provider` | `"github"` | no | Git provider. |
| `defaultBranch` | string | no | The repository's default branch. |
| `previewHost` | string | yes | Base host the immutable and alias preview URLs are derived from. |
| `webhookSecret` | string or null | no | Webhook signing secret. Write-only: sealed at rest and never returned. |
| `token` | string or null | no | Repository token. Write-only: envelope-sealed at rest and never returned. |

### `EventReceiptResponse` {#schema-eventreceiptresponse}

The outcome of a webhook delivery.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `accepted` | boolean | yes | Accepted. |
| `ignored` | boolean | no | Ignored. |
| `reason` | string or null | no | Reason. |
| `created` | boolean | no | Created. |
| `preview` | [`PreviewBody`](#schema-previewbody) or null | no | Preview. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PreviewBody` {#schema-previewbody}

One immutable preview and its provider-status payload.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `connectionId` | string | yes | Connection ID. |
| `siteId` | string | yes | Site ID. |
| `environmentId` | string or null | no | Environment ID. |
| `sourceCommit` | string | yes | Source Commit. |
| `sourceRef` | string | yes | Source Ref. |
| `sourceMessage` | string | yes | Source Message. |
| `sourceDigest` | string | yes | Source Digest. |
| `status` | string | yes | Status. |
| `checksState` | string | yes | Checks State. |
| `immutableUrl` | string | yes | Immutable URL. |
| `aliasUrl` | string or null | no | Alias URL. |
| `accessPolicy` | string | yes | Access Policy. |
| `robotsExcluded` | boolean | yes | Robots Excluded. |
| `buildDispatched` | boolean | yes | Build Dispatched. |
| `retryCount` | integer | yes | Number of retry. |
| `expiresAt` | string or null | no | Expires At. |
| `createdAt` | string or null | no | Created At. |
| `changedPages` | array of `ChangedPageBody` | no | Changed Pages. |
| `providerStatus` | object | no | Provider Status. |

### `PreviewListResponse` {#schema-previewlistresponse}

PreviewListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `previews` | array of [`PreviewBody`](#schema-previewbody) | yes | Previews. |

### `RecordChecksRequest` {#schema-recordchecksrequest}

Record the outcome of the checks a preview must pass before its alias advances.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `passed` | boolean | yes | Whether the checks passed. |
| `failureEvidence` | object or null | no | Evidence surfaced in the provider status on failure. |
