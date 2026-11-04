---
title: "Export delivery"
description: "REST endpoints tagged export-delivery: 2 operations."
sidebar_position: 32
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.514.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `export-delivery` · 2 operations

## `GET /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/git` {#list-export-job-git-deliveries-v1-export-tenant-slug-jobs-job-id-deliveries-git-get}

**List a job's git deliveries**

Every git delivery of one export job, newest first. Requires `projects:view`.

Operation id: `list_export_job_git_deliveries_v1_export__tenant_slug__jobs__job_id__deliveries_git_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `job_id` | path | string | yes | Asynchronous job identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a job's git deliveries. | `application/json` [`ExportGitDeliveryRunListResponse`](#schema-exportgitdeliveryrunlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/git` {#deliver-export-job-to-git-v1-export-tenant-slug-jobs-job-id-deliveries-git-post}

**Deliver a completed export to a git repository**

Writes a **completed** export job's bundle into a repository registered in this workspace through a linked GitHub account, under `targetPath` (a multi-file bundle keeps its directory tree), with a delivery manifest at `<targetPath>/.apiome/export-delivery.json`.

**`mode: pr`** (default): a commit on `apiome/export-<artifact>-<target>` built on the latest base branch, and one pull request whose description carries the export's fidelity summary and a link to the full report. A re-export updates the same branch and pull request: `opened`, `updated`, `unchanged` (nothing written) or `up_to_date` (the base already holds it).

**`mode: commit`**: one commit straight onto the base branch, fast-forward only — `committed`, or `failed` when the branch moved or is protected.

**Failures are runs.** A missing or revoked credential, a token without write access or a refused push answers `200` with `status: failed`, a stable `errorCode` and an actionable log.

Requires `versions:publish`. Audited as `export.git_delivery`.

Operation id: `deliver_export_job_to_git_v1_export__tenant_slug__jobs__job_id__deliveries_git_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `job_id` | path | string | yes | Asynchronous job identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for deliver a completed export to a git repository.

- `application/json` — [`GitDeliveryRequest`](#schema-gitdeliveryrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for deliver a completed export to a git repository. | `application/json` [`ExportGitDeliveryRunModel`](#schema-exportgitdeliveryrunmodel) |
| 400 | Invalid repository, path or base branch. | — |
| 404 | Unknown export job for this tenant. | — |
| 409 | The job is not completed, is a dry run, or its bundle cannot be read. | — |
| 410 | The export's artifact has expired; export again, then deliver. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ExportGitDeliveryRunListResponse` {#schema-exportgitdeliveryrunlistresponse}

A job's deliveries, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`ExportGitDeliveryRunModel`](#schema-exportgitdeliveryrunmodel) | no | Runs. |

### `ExportGitDeliveryRunModel` {#schema-exportgitdeliveryrunmodel}

One export git delivery.

Attributes:
    run_id: The run record.
    status: ``in_progress``, ``opened``, ``updated``, ``unchanged``, ``up_to_date``, ``committed``
        or ``failed``.
    mode: ``pr`` or ``commit``.
    job_id: The export job delivered.
    repository_id: The registered repository.
    repository_full_name: ``owner/repo``.
    base_branch: The base branch used.
    target_path: The directory the bundle was written under.
    branch_name: The delivery branch (the base branch in commit mode).
    base_sha: The base commit.
    commit_sha: The commit the branch points at.
    pull_request_number: The pull request opened or updated.
    pull_request_url: Its web page.
    changes: The changed-files overview.
    fidelity: The fidelity summary the pull request carried.
    log: The delivery event log, redacted of secrets.
    error_code: Set when the run failed.
    error_message: Set when the run failed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runId` | string or null | no | Run ID. |
| `status` | string | yes | Status. |
| `mode` | string | yes | Mode. |
| `jobId` | string | yes | Job ID. |
| `repositoryId` | string or null | no | Repository ID. |
| `repositoryFullName` | string or null | no | Repository Full Name. |
| `baseBranch` | string or null | no | Base Branch. |
| `targetPath` | string | no | Target Path. |
| `branchName` | string or null | no | Branch Name. |
| `baseSha` | string or null | no | Base Sha. |
| `commitSha` | string or null | no | Commit Sha. |
| `pullRequestNumber` | integer or null | no | Pull Request Number. |
| `pullRequestUrl` | string or null | no | Pull Request URL. |
| `changes` | object | no | Changes. |
| `fidelity` | object | no | Fidelity. |
| `log` | array of object | no | Log. |
| `errorCode` | string or null | no | Error Code. |
| `errorMessage` | string or null | no | Error Message. |

### `GitDeliveryRequest` {#schema-gitdeliveryrequest}

Where to deliver an export: ``POST …/jobs/{job_id}/deliveries/git``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `repositoryId` | string | yes | A repository registered in this workspace through a linked GitHub account (`GET /v1/tenants/{tenant}/repositories`). Its linked account is the credential. |
| `targetPath` | string | no | Directory inside the repository the bundle is written under (`specs/orders`). Empty means the repository root. A multi-file bundle keeps its own directory tree below it. |
| `baseBranch` | string or null | no | The branch the pull request targets (mode `pr`) or the commit lands on (mode `commit`). Empty means the repository's default branch. |
| `mode` | enum `"pr"`, `"commit"` | no | `pr` (default): commit to a delivery branch and open — or update — one pull request. `commit`: commit straight onto the base branch, fast-forward only. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
