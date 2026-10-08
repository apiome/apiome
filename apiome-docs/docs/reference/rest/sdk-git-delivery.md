---
title: "SDK git delivery"
description: "REST endpoints tagged sdk-git-delivery: 6 operations."
sidebar_position: 58
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `sdk-git-delivery` · 6 operations

## `POST /v1/projects/{tenant_slug}/{project_ref}/sdk-git-delivery` {#deliver-project-sdk-v1-projects-tenant-slug-project-ref-sdk-git-delivery-post}

**Deliver a version's SDK to its repository as a pull request**

Regenerates the SDK-4.1 package for one **published** revision and delivers it to the project's configured repository: a commit on `apiome/sdk-regen-<version>-<project>-<ecosystem>`, built on the latest base branch, and a pull request whose description carries the spec version, the generator version, a changed-files overview and the provenance.

**Idempotent.** Re-running for the same version updates the same pull request rather than opening another: `unchanged` when the open pull request already carries exactly this SDK, `updated` when its branch was rebuilt, `up_to_date` when the base branch already contains it (nothing is written), `opened` when a new pull request was needed.

**Failures are runs.** A missing or revoked credential, a token without write access, a rejected push or a refused pull request answers `200` with `status: failed`, a stable `errorCode` and an actionable log.

Requires `versions:publish`. Audited as `sdk.git_delivery`.

Operation id: `deliver_project_sdk_v1_projects__tenant_slug___project_ref__sdk_git_delivery_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for deliver a version's sdk to its repository as a pull request.

- `application/json` — [`SdkGitDeliveryRequest`](#schema-sdkgitdeliveryrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for deliver a version's sdk to its repository as a pull request. | `application/json` [`SdkGitDeliveryRunModel`](#schema-sdkgitdeliveryrunmodel) |
| 400 | Unsupported ecosystem, or the revision is not published. | — |
| 404 | Project, version or delivery target not found. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-git-delivery-runs` {#list-git-delivery-runs-v1-projects-tenant-slug-project-ref-sdk-git-delivery-runs-get}

**List a project's SDK delivery history**

Every delivery attempt, newest first — failed ones included, because a failed run is the record of why a pull request did not arrive.

Requires `versions:view`.

Operation id: `list_git_delivery_runs_v1_projects__tenant_slug___project_ref__sdk_git_delivery_runs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `ecosystem` | query | string or null | no | Narrow to one ecosystem (`npm` or `pypi`). |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `offset` | query | integer | no | Number of rows to skip before returning results. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a project's sdk delivery history. | `application/json` [`SdkGitDeliveryRunListResponse`](#schema-sdkgitdeliveryrunlistresponse) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-git-delivery-runs/{run_id}` {#get-git-delivery-run-v1-projects-tenant-slug-project-ref-sdk-git-delivery-runs-run-id-get}

**Read one SDK delivery run**

The run's outcome, the branch, commit and pull request it wrote, the changed-files overview and its event log. The log is stored redacted — a provider error quoting the repository token is replaced before it is written.

Requires `versions:view`.

Operation id: `get_git_delivery_run_v1_projects__tenant_slug___project_ref__sdk_git_delivery_runs__run_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read one sdk delivery run. | `application/json` [`SdkGitDeliveryRunModel`](#schema-sdkgitdeliveryrunmodel) |
| 404 | Project or run not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/projects/{tenant_slug}/{project_ref}/sdk-git-delivery-targets` {#list-git-delivery-targets-v1-projects-tenant-slug-project-ref-sdk-git-delivery-targets-get}

**List where a project's SDKs are delivered**

A **delivery target** says where one project's SDK for one ecosystem is delivered: a repository already registered with Apiome, the branch pull requests target (blank for the repository's default branch), and the directory inside the repository the SDK lives in (blank for the root).

**No new credential.** A delivery pushes with the repository's existing linked-account integration, so the repository must have been registered through a linked GitHub account — one registered from a public URL holds no credential and is refused.

Ecosystems: `npm`, `pypi` — the SDK-4.1 package layouts. Each delivery uses the branch `apiome/sdk-regen-<version>-<project>-<ecosystem>`.

Each target reports `deliverable` and, when it is false, the `problem` a delivery would hit (the repository was removed, or registered without a linked account).

Requires `projects:view`.

Operation id: `list_git_delivery_targets_v1_projects__tenant_slug___project_ref__sdk_git_delivery_targets_get`

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
| 200 | Successful response for list where a project's sdks are delivered. | `application/json` [`GitDeliveryTargetListResponse`](#schema-gitdeliverytargetlistresponse) |
| 404 | Project not found in this tenant. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/projects/{tenant_slug}/{project_ref}/sdk-git-delivery-targets/{ecosystem}` {#put-git-delivery-target-v1-projects-tenant-slug-project-ref-sdk-git-delivery-targets-ecosystem-put}

**Configure where a project's SDK for one ecosystem is delivered**

A **delivery target** says where one project's SDK for one ecosystem is delivered: a repository already registered with Apiome, the branch pull requests target (blank for the repository's default branch), and the directory inside the repository the SDK lives in (blank for the root).

**No new credential.** A delivery pushes with the repository's existing linked-account integration, so the repository must have been registered through a linked GitHub account — one registered from a public URL holds no credential and is refused.

Ecosystems: `npm`, `pypi` — the SDK-4.1 package layouts. Each delivery uses the branch `apiome/sdk-regen-<version>-<project>-<ecosystem>`.

Replaces any existing target for this project and ecosystem.

Requires `projects:edit` **and** `imports:edit` — a target decides what Apiome pushes into a repository with that repository's credential. Audited as `sdk.git_delivery_target.update`.

Operation id: `put_git_delivery_target_v1_projects__tenant_slug___project_ref__sdk_git_delivery_targets__ecosystem__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `ecosystem` | path | string | yes | Path parameter identifying the ecosystem segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for configure where a project's sdk for one ecosystem is delivered.

- `application/json` — [`GitDeliveryTargetPutRequest`](#schema-gitdeliverytargetputrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for configure where a project's sdk for one ecosystem is delivered. | `application/json` [`GitDeliveryTargetOut`](#schema-gitdeliverytargetout) |
| 404 | Project not found in this tenant. | — |
| 422 | A field is invalid, or the repository cannot receive a delivery (`sdk-git-delivery-repository-missing`, `…-provider-unsupported`, `…-repository-unlinked`). | — |

## `DELETE /v1/projects/{tenant_slug}/{project_ref}/sdk-git-delivery-targets/{ecosystem}` {#delete-git-delivery-target-v1-projects-tenant-slug-project-ref-sdk-git-delivery-targets-ecosystem-delete}

**Stop delivering a project's SDK for one ecosystem**

Removes the target. Past runs are kept, and nothing is changed in the repository — an open pull request stays open.

Requires `projects:edit`. Audited as `sdk.git_delivery_target.clear`.

Operation id: `delete_git_delivery_target_v1_projects__tenant_slug___project_ref__sdk_git_delivery_targets__ecosystem__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_ref` | path | string | yes | Path parameter identifying the project ref segment. |
| `ecosystem` | path | string | yes | Path parameter identifying the ecosystem segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for stop delivering a project's sdk for one ecosystem. | `application/json` object |
| 404 | Project not found in this tenant. | — |
| 422 | The ecosystem is not one git delivery supports. | — |

## Schemas used {#schemas-used}

### `GitDeliveryTargetListResponse` {#schema-gitdeliverytargetlistresponse}

A project's delivery targets.

Attributes:
    ecosystems: Which ecosystems can be delivered.
    targets: One entry per configured ecosystem.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ecosystems` | array of string | yes | Ecosystems. |
| `targets` | array of [`GitDeliveryTargetOut`](#schema-gitdeliverytargetout) | yes | Targets. |

### `GitDeliveryTargetOut` {#schema-gitdeliverytargetout}

A configured delivery target, as the API describes it.

Attributes:
    schema_version: The projection's shape.
    ecosystem: ``npm`` or ``pypi``.
    repository_id: The registered repository.
    repository_full_name: ``owner/repo``, or ``None`` when the repository has been removed.
    repository_provider: Where the repository is hosted.
    base_branch: The configured base, or ``None`` for the repository's default branch.
    target_path: The directory the SDK is committed under (``''`` for the root).
    branch_pattern: The branch a delivery of this target uses, with ``{version}`` standing in
        for the version line.
    deliverable: Whether a delivery could run with this configuration now.
    problem: Why not, when it could not.
    created_at: When the target was first configured.
    updated_at: When it was last changed.
    updated_by: Who last changed it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `schemaVersion` | string | no | Schema Version. |
| `ecosystem` | string | yes | Ecosystem. |
| `repositoryId` | string | yes | Repository ID. |
| `repositoryFullName` | string or null | no | Repository Full Name. |
| `repositoryProvider` | string or null | no | Repository Provider. |
| `baseBranch` | string or null | no | Base Branch. |
| `targetPath` | string | no | Target Path. |
| `branchPattern` | string | yes | Branch Pattern. |
| `deliverable` | boolean | no | Deliverable. |
| `problem` | map of string or null | no | Problem. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |
| `updatedBy` | string or null | no | Updated By. |

### `GitDeliveryTargetPutRequest` {#schema-gitdeliverytargetputrequest}

Body for configuring a delivery target.

Attributes:
    repository_id: The registered repository to deliver into.
    base_branch: The branch pull requests target; blank for the repository's default branch.
    target_path: The directory inside the repository; blank for the root.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `repositoryId` | string | yes | Id of a repository registered through a linked GitHub account. |
| `baseBranch` | string or null | no | The pull request's base branch. Omit for the repository's default branch. |
| `targetPath` | string or null | no | Directory inside the repository, e.g. `sdks/typescript`. Omit for the root. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `SdkGitDeliveryRequest` {#schema-sdkgitdeliveryrequest}

Body for a delivery.

Attributes:
    ecosystem: ``npm`` or ``pypi``.
    version: The revision to deliver — a revision UUID or a version label. Defaults to the
        project's latest revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ecosystem` | string | yes | `npm` or `pypi`. |
| `version` | string or null | no | Revision UUID or version label. Defaults to the latest revision. |

### `SdkGitDeliveryRunListResponse` {#schema-sdkgitdeliveryrunlistresponse}

A page of delivery history.

Attributes:
    runs: The rows, newest first.
    total: How many rows match.
    limit: The page size used.
    offset: The offset used.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`SdkGitDeliveryRunModel`](#schema-sdkgitdeliveryrunmodel) | yes | Runs. |
| `total` | integer | yes | Total. |
| `limit` | integer | yes | Limit. |
| `offset` | integer | yes | Offset. |

### `SdkGitDeliveryRunModel` {#schema-sdkgitdeliveryrunmodel}

One delivery run.

Attributes:
    run_id: The ledger row.
    status: ``in_progress``, ``opened``, ``updated``, ``unchanged``, ``up_to_date`` or
        ``failed``.
    ecosystem: ``npm`` or ``pypi``.
    version_line: The API version delivered.
    release_series: The series the package version was derived under.
    regen_counter: The counter the package version carries.
    package_name: The committed package's name.
    package_version: The committed package's version.
    repository_id: The registered repository.
    repository_full_name: ``owner/repo``.
    base_branch: The base branch used.
    target_path: The directory the SDK was committed under.
    branch_name: The delivery branch.
    base_sha: The base commit.
    commit_sha: The commit the branch points at.
    pull_request_number: The pull request opened or updated.
    pull_request_url: Its web page.
    changes: The changed-files overview.
    provenance: The provenance embedded in the committed package.
    log: The delivery event log, redacted of secrets.
    error_code: Set when the run failed.
    error_message: Set when the run failed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runId` | string or null | no | Run ID. |
| `status` | string | yes | Status. |
| `ecosystem` | string | yes | Ecosystem. |
| `versionLine` | string or null | no | Version Line. |
| `releaseSeries` | string or null | no | Release Series. |
| `regenCounter` | integer or null | no | Regen Counter. |
| `packageName` | string or null | no | Package Name. |
| `packageVersion` | string or null | no | Package Version. |
| `repositoryId` | string or null | no | Repository ID. |
| `repositoryFullName` | string or null | no | Repository Full Name. |
| `baseBranch` | string or null | no | Base Branch. |
| `targetPath` | string or null | no | Target Path. |
| `branchName` | string or null | no | Branch Name. |
| `baseSha` | string or null | no | Base Sha. |
| `commitSha` | string or null | no | Commit Sha. |
| `pullRequestNumber` | integer or null | no | Pull Request Number. |
| `pullRequestUrl` | string or null | no | Pull Request URL. |
| `changes` | object | no | Changes. |
| `provenance` | object | no | Provenance. |
| `log` | array of object | no | Log. |
| `errorCode` | string or null | no | Error Code. |
| `errorMessage` | string or null | no | Error Message. |
