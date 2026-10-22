---
title: "Repository federation"
description: "REST endpoints tagged repository-federation: 5 operations."
sidebar_position: 65
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.291.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `repository-federation` · 5 operations

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/federation-merges` {#list-project-federation-merges-v1-tenants-tenant-slug-projects-project-ref-federation-merges-get}

**List a project's federation merge history**

Newest first. Requires `projects:view`.

Operation id: `list_project_federation_merges_v1_tenants__tenant_slug__projects__project_ref__federation_merges_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's federation merge history. | `application/json` [`FederationMergeList`](#schema-federationmergelist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/federation-merges` {#create-federation-merge-v1-tenants-tenant-slug-projects-project-ref-federation-merges-post}

**Record a federation merge (called by the import)**

Records what federation did to one repository-file import: `merged`, `conflicted` (nothing written; each conflict carries every source's definition — the contributing file's is read from `parentVersionId`'s rendered spec when not sent) or `replaced` (federation off). The row and its audit row (`repository.federation_merged`, `repository.federation_conflicted` or `repository.federation_replaced`) are written in one transaction.

Requires `imports:create`.

Operation id: `create_federation_merge_v1_tenants__tenant_slug__projects__project_ref__federation_merges_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record a federation merge (called by the import).

- `application/json` — [`FederationMergeCreate`](#schema-federationmergecreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for record a federation merge (called by the import). | `application/json` [`FederationMerge`](#schema-federationmerge) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/repository-federation` {#get-repository-federation-v1-tenants-tenant-slug-projects-project-ref-repository-federation-get}

**Read a project's multi-repository federation switch**

`enabled: true` (the default) merges each repository file imported into the project with the other contributing files into one API surface. `false` makes each import replace the surface with the importing file alone.

Requires `projects:view`.

Operation id: `get_repository_federation_v1_tenants__tenant_slug__projects__project_ref__repository_federation_get`

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
| 200 | Successful response for read a project's multi-repository federation switch. | `application/json` [`FederationSetting`](#schema-federationsetting) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/projects/{project_ref}/repository-federation` {#put-repository-federation-v1-tenants-tenant-slug-projects-project-ref-repository-federation-put}

**Switch a project's multi-repository federation on or off**

Applies to the next import; existing versions are not changed. Requires `projects:edit`. Audited as `repository.federation_toggled`.

Operation id: `put_repository_federation_v1_tenants__tenant_slug__projects__project_ref__repository_federation_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for switch a project's multi-repository federation on or off.

- `application/json` — [`FederationSettingUpdate`](#schema-federationsettingupdate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for switch a project's multi-repository federation on or off. | `application/json` [`FederationSetting`](#schema-federationsetting) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/federation-merges` {#list-repository-federation-merges-v1-tenants-tenant-slug-repositories-repository-id-federation-merges-get}

**List the federation merges a repository's files were imported in**

The repository's sync history: every merge, conflict and replacement where one of its files was the imported file, newest first. Requires `imports:view`.

Operation id: `list_repository_federation_merges_v1_tenants__tenant_slug__repositories__repository_id__federation_merges_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string | yes | Connected repository identifier. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the federation merges a repository's files were imported in. | `application/json` [`FederationMergeList`](#schema-federationmergelist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `FederationMerge` {#schema-federationmerge}

One row of a project's merge history.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `projectId` | string | yes | Project ID. |
| `projectName` | string or null | no | Project Name. |
| `status` | enum `"merged"`, `"conflicted"`, `"replaced"` | yes | Status. |
| `versionId` | string or null | no | Version ID. |
| `versionLabel` | string or null | no | Version Label. |
| `parentVersionId` | string or null | no | Parent Version ID. |
| `repositoryId` | string or null | no | Repository ID. |
| `repositoryFullName` | string | yes | Repository Full Name. |
| `branch` | string | yes | Branch. |
| `path` | string | yes | Path. |
| `sourceCount` | integer | yes | Number of source. |
| `classesCarried` | integer | yes | Classes Carried. |
| `pathsCarried` | integer | yes | Paths Carried. |
| `removedCount` | integer | yes | Number of removed. |
| `conflictCount` | integer | yes | Number of conflict. |
| `sources` | array of `FederationSourceRef` | no | Sources. |
| `conflicts` | array of `FederationConflict` | no | Conflicts. |
| `actorId` | string or null | no | Actor ID. |
| `createdAt` | string (date-time) | yes | Created At. |

### `FederationMergeCreate` {#schema-federationmergecreate}

What an import reports after federation acted on it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | enum `"merged"`, `"conflicted"`, `"replaced"` | yes | Status. |
| `versionId` | string or null | no | Version ID. |
| `parentVersionId` | string or null | no | Parent Version ID. |
| `repositoryId` | string or null | no | Repository ID. |
| `repositoryFullName` | string | yes | Repository Full Name. |
| `branch` | string | yes | Branch. |
| `path` | string | yes | Path. |
| `sourceCount` | integer | no | Number of source. |
| `classesCarried` | integer | no | Classes Carried. |
| `pathsCarried` | integer | no | Paths Carried. |
| `removedCount` | integer | no | Number of removed. |
| `sources` | array of `FederationSourceRef` | no | Sources. |
| `conflicts` | array of `FederationConflict` | no | Conflicts. |
| `conflictCount` | integer or null | no | How many conflicts there were in all, when more than `conflicts` lists. |

### `FederationMergeList` {#schema-federationmergelist}

A page of merge history, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `merges` | array of [`FederationMerge`](#schema-federationmerge) | no | Merges. |

### `FederationSetting` {#schema-federationsetting}

A project's federation switch.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `enabled` | boolean | yes | True: each imported repository file is merged with the other contributing files. False: each import replaces the project's surface with the importing file alone. |

### `FederationSettingUpdate` {#schema-federationsettingupdate}

Body for switching federation on or off.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | yes | Whether the resource is active. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
