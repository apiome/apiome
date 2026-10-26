---
title: "PR back"
description: "REST endpoints tagged pr-back: 4 operations."
sidebar_position: 60
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.319.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `pr-back` · 4 operations

## `POST /v1/tenants/{tenant_slug}/projects/{project_ref}/pr-back` {#pr-back-project-v1-tenants-tenant-slug-projects-project-ref-pr-back-post}

**Open a pull request syncing a project version back to its repository**

Renders one version of the project and opens a pull request into the repository's source files on `apiome/pr-back-<project>-<base>`, built on the latest base branch. Each file gets back only the paths and schemas it defines (multi-repository projects); content no file defines belongs to the precedence-1 file. The description is each file's change report (the project's change report templates), and new pull requests get the repository's reviewers.

**Idempotent.** One pull request per project and base branch: `updated` when the open one was refreshed, `unchanged` when it already carries exactly this sync, `up_to_date` when the base branch already holds the rendered files (nothing written), `opened` otherwise. `dryRun: true` answers `preview` with the title, description and commit message, writing nothing.

**Failures are outcomes.** A revoked token, a refused push or a rate limit answers `200` with `status: failed`, an `errorCode` and an actionable log.

Requires `versions:publish` (`projects:view` for a dry run). Every pull request opened is audited as `repository.pr_back_opened`, every one refreshed as `repository.pr_back_updated`.

Operation id: `pr_back_project_v1_tenants__tenant_slug__projects__project_ref__pr_back_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for open a pull request syncing a project version back to its repository.

- `application/json` — [`PrBackRequest`](#schema-prbackrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for open a pull request syncing a project version back to its repository. | `application/json` [`PrBackOutcomeModel`](#schema-prbackoutcomemodel) |
| 403 | The repository's settings do not let the project PR back. | — |
| 404 | Unknown project, version or repository. | — |
| 409 | The project has no source file the repository can receive. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/projects/{project_ref}/pr-back/repositories` {#list-pr-back-repositories-v1-tenants-tenant-slug-projects-project-ref-pr-back-repositories-get}

**List the repositories a project can PR back into**

Every repository the project was imported from, with its source files, whether the project may open pull requests into it (`eligible`) and, when it may not, why (`reasonCode`, `reason`).

Requires `projects:view`.

Operation id: `list_pr_back_repositories_v1_tenants__tenant_slug__projects__project_ref__pr_back_repositories_get`

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
| 200 | Successful response for list the repositories a project can pr back into. | `application/json` [`PrBackRepositoriesResponse`](#schema-prbackrepositoriesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/repositories/{repository_id}/pr-back-settings` {#get-pr-back-settings-v1-tenants-tenant-slug-repositories-repository-id-pr-back-settings-get}

**Read a repository's PR-back settings**

Which Apiome projects may open pull requests into the repository (`allow` list or `deny` list), the pull requests' target branch, the commit message template and the reviewers. `configured: false` means the repository has no settings, so no project may PR back.

Requires `imports:view`.

Operation id: `get_pr_back_settings_v1_tenants__tenant_slug__repositories__repository_id__pr_back_settings_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a repository's pr-back settings. | `application/json` [`PrBackSettingsResponse`](#schema-prbacksettingsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/tenants/{tenant_slug}/repositories/{repository_id}/pr-back-settings` {#put-pr-back-settings-v1-tenants-tenant-slug-repositories-repository-id-pr-back-settings-put}

**Save a repository's PR-back settings**

Replaces the repository's PR-back settings. `projectPolicy: allow` lets only `projectIds` open pull requests into the repository; `deny` lets every project except them. `targetBranch` blank uses the branch the files were imported from. `commitMessageTemplate` is Mustache over `project`, `version`, `repository`, `branch` and `fileCount`; blank uses the default. `reviewers` are GitHub logins or `org/team` slugs, requested on every pull request PR-back opens.

Requires `imports:edit`. Audited as `repository.pr_back_settings.update`.

Operation id: `put_pr_back_settings_v1_tenants__tenant_slug__repositories__repository_id__pr_back_settings_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `repository_id` | path | string | yes | Connected repository identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for save a repository's pr-back settings.

- `application/json` — [`PrBackSettingsPutRequest`](#schema-prbacksettingsputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for save a repository's pr-back settings. | `application/json` [`PrBackSettingsResponse`](#schema-prbacksettingsresponse) |
| 404 | Unknown repository. | — |
| 422 | Invalid policy, branch, template, reviewer or project id. | — |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `PrBackOutcomeModel` {#schema-prbackoutcomemodel}

What a PR-back did.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `status` | string | yes | `preview`, `opened`, `updated`, `unchanged`, `up_to_date` or `failed`. |
| `dryRun` | boolean | yes | Dry Run. |
| `projectId` | string | yes | Project ID. |
| `versionId` | string | yes | Version ID. |
| `versionLabel` | string or null | no | Version Label. |
| `repositoryId` | string | yes | Repository ID. |
| `repositoryFullName` | string or null | no | Repository Full Name. |
| `baseBranch` | string or null | no | Base Branch. |
| `branchName` | string or null | no | Branch Name. |
| `baseSha` | string or null | no | Base Sha. |
| `commitSha` | string or null | no | Commit Sha. |
| `pullRequestNumber` | integer or null | no | Pull Request Number. |
| `pullRequestUrl` | string or null | no | Pull Request URL. |
| `title` | string or null | no | Title. |
| `body` | string or null | no | The pull request description (change report). |
| `commitMessage` | string or null | no | Commit Message. |
| `reviewers` | array of string | no | Reviewers. |
| `files` | array of `PrBackFileReport` | no | Files. |
| `skipped` | array of string | no | Skipped. |
| `log` | array of object | no | Log. |
| `errorCode` | string or null | no | Error Code. |
| `errorMessage` | string or null | no | Error Message. |

### `PrBackRepositoriesResponse` {#schema-prbackrepositoriesresponse}

The repositories a project was imported from.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `repositories` | array of `PrBackRepositoryEntry` | no | Repositories. |

### `PrBackRequest` {#schema-prbackrequest}

Body for a PR-back.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `repositoryId` | string | yes | Repository ID. |
| `version` | string or null | no | Revision id or version label; the newest when omitted. |
| `dryRun` | boolean | no | Compare and describe; write nothing. |

### `PrBackSettingsPutRequest` {#schema-prbacksettingsputrequest}

Body for saving a repository's PR-back settings (replaces them whole).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectPolicy` | string | no | `allow` or `deny`. |
| `projectIds` | array of string | no | Project ids. |
| `targetBranch` | string or null | no | Blank for the import branch. |
| `commitMessageTemplate` | string or null | no | Mustache template with `{{project}}`, `{{version}}`, `{{repository}}`, `{{branch}}` and `{{fileCount}}`. Blank for the default. |
| `reviewers` | array of string | no | GitHub logins (`octocat`) or teams (`acme/api-reviewers`). |

### `PrBackSettingsResponse` {#schema-prbacksettingsresponse}

A repository's PR-back settings.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `repositoryId` | string | yes | Repository ID. |
| `configured` | boolean | yes | False when the repository has no settings — no project may PR back. |
| `projectPolicy` | string | yes | `allow`: only the listed projects may PR back. `deny`: every project except them. |
| `projects` | array of `PrBackProjectRef` | no | Projects. |
| `targetBranch` | string or null | no | Base branch of the pull requests; null for the branch the files were imported from. |
| `commitMessageTemplate` | string or null | no | Mustache template; null for the default. |
| `defaultCommitMessageTemplate` | string | no | Default Commit Message Template. |
| `reviewers` | array of string | no | Reviewers. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
