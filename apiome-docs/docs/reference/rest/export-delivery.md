---
title: "Export delivery"
description: "REST endpoints tagged export-delivery: 10 operations."
sidebar_position: 32
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.516.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `export-delivery` · 10 operations

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

## `GET /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/object-storage` {#list-export-job-object-storage-deliveries-v1-export-tenant-slug-jobs-job-id-deliveries-object-storage-get}

**List a job's object-storage deliveries**

Every object-storage delivery of one export job, newest first. Requires `projects:view`.

Operation id: `list_export_job_object_storage_deliveries_v1_export__tenant_slug__jobs__job_id__deliveries_object_storage_get`

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
| 200 | Successful response for list a job's object-storage deliveries. | `application/json` [`ExportObjectStorageDeliveryRunListResponse`](#schema-exportobjectstoragedeliveryrunlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/object-storage` {#deliver-export-job-to-object-storage-v1-export-tenant-slug-jobs-job-id-deliveries-object-storage-post}

**Deliver a completed export to an S3-compatible bucket**

Uploads a **completed** export job's bundle to `bucket` with a stored credential (`credentialId`). Objects are written under `<prefix>/<artifact>/<version>/<target>/` — `partitioning` picks and orders the partitions, `[]` writes straight under `prefix` — each at its bundle path, with its SHA-256 in `x-amz-meta-sha256`.

**Manifest, last.** A manifest listing every object's key, size and SHA-256, with the export's provenance and fidelity summary, is written after the objects at `<keyPrefix>/manifests/<sha256>.json` (content-addressed, immutable: the same export writes the same manifest) and at `<keyPrefix>/manifest.json` (the latest delivery to that prefix).

**Failures are runs.** A missing or unreadable credential, a refused endpoint, an unknown bucket, a rejected key or a failed upload answers `200` with `status: failed`, a stable `errorCode` and a redacted message; the objects written before it are listed. Credentials never appear in a response, a log line or the audit.

Requires `versions:publish`. Audited as `export.object_storage_delivery`.

Operation id: `deliver_export_job_to_object_storage_v1_export__tenant_slug__jobs__job_id__deliveries_object_storage_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `job_id` | path | string | yes | Asynchronous job identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for deliver a completed export to an s3-compatible bucket.

- `application/json` — [`ObjectStorageDeliveryRequest`](#schema-objectstoragedeliveryrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for deliver a completed export to an s3-compatible bucket. | `application/json` [`ExportObjectStorageDeliveryRunModel`](#schema-exportobjectstoragedeliveryrunmodel) |
| 400 | Invalid credential id, bucket, prefix or partitioning. | — |
| 404 | Unknown export job for this tenant. | — |
| 409 | The job is not completed, is a dry run, or its bundle cannot be read. | — |
| 410 | The export's artifact has expired; export again, then deliver. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/webhook` {#list-export-job-webhook-deliveries-v1-export-tenant-slug-jobs-job-id-deliveries-webhook-get}

**List a job's webhook deliveries**

Every webhook delivery of one export job, newest first, with every attempt. Requires `projects:view`.

Operation id: `list_export_job_webhook_deliveries_v1_export__tenant_slug__jobs__job_id__deliveries_webhook_get`

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
| 200 | Successful response for list a job's webhook deliveries. | `application/json` [`ExportWebhookDeliveryRunListResponse`](#schema-exportwebhookdeliveryrunlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/webhook` {#deliver-export-job-to-webhook-v1-export-tenant-slug-jobs-job-id-deliveries-webhook-post}

**Deliver a completed export to a webhook**

POSTs a **completed** export job's result to `url` as one JSON body (`schemaVersion: export.webhook-delivery.v1`, `event: export.delivered`): the export's coordinates, the file manifest, the fidelity summary and full report, and the bundle — inside the body (`artifact.delivery: inline`, UTF-8 text or base64 for a zip) when it fits under `APIOME_EXPORT_WEBHOOK_INLINE_MAX_BYTES` (1 MiB), otherwise as a signed, expiring fetch link (`artifact.delivery: fetch`) that needs no Apiome credentials. `artifact: fetch` always sends the link.

**Signed.** `X-Apiome-Signature: sha256=<hex>` is the HMAC-SHA256 of the exact body under `secret`. The secret is used once and never stored; retries re-send the same bytes and signature, with `X-Apiome-Delivery` (the run id, for de-duplication) and `X-Apiome-Delivery-Attempt`.

**Retried.** The first attempt is made before this answers. No answer, `408`, `425`, `429` or a `5xx` is retried after 10 s, 60 s and 5 min (longer when `Retry-After` asks); a `3xx` (redirects are not followed) or another `4xx` fails the run at once.

**Guarded.** `url` must resolve to public addresses only — checked now and on every attempt.

Every outcome is a run on the job (`GET` this path). Requires `versions:publish`. Audited as `export.webhook_delivery`.

Operation id: `deliver_export_job_to_webhook_v1_export__tenant_slug__jobs__job_id__deliveries_webhook_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `job_id` | path | string | yes | Asynchronous job identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for deliver a completed export to a webhook.

- `application/json` — [`WebhookDeliveryRequest`](#schema-webhookdeliveryrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for deliver a completed export to a webhook. | `application/json` [`ExportWebhookDeliveryRunModel`](#schema-exportwebhookdeliveryrunmodel) |
| 400 | Invalid URL or secret, or a destination the SSRF guard refuses. | — |
| 404 | Unknown export job for this tenant. | — |
| 409 | The job is not completed or is a dry run, or a fetch link is needed but the server's public address is not configured. | — |
| 410 | The export's artifact has expired; export again, then deliver. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/webhook/{delivery_id}/bundle` {#fetch-export-webhook-bundle-v1-export-tenant-slug-jobs-job-id-deliveries-webhook-delivery-id-bundle-get}

**Fetch a webhook delivery's bundle (signed link)**

The fetch link a webhook delivery hands the receiver when the bundle is too large to inline (`artifact.url` in the body). The `expires` and `signature` query parameters are the credential: no Apiome sign-in is needed, and nothing else is accepted. Streams the same bytes as the job's download (with `Digest` / `X-Content-SHA256`). `403` for a bad signature, `410` once the link or the export's artifact has expired.

Operation id: `fetch_export_webhook_bundle_v1_export__tenant_slug__jobs__job_id__deliveries_webhook__delivery_id__bundle_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `job_id` | path | string | yes | Asynchronous job identifier. |
| `delivery_id` | path | string | yes | Path parameter identifying the delivery id segment. |
| `expires` | query | integer | yes | The link's expiry, epoch seconds. |
| `signature` | query | string | yes | The link's signature. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for fetch a webhook delivery's bundle (signed link). | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/storage-credentials` {#list-storage-credentials-v1-export-tenant-slug-storage-credentials-get}

**List the workspace's bucket credentials**

Every storage credential, by name — never a secret. Requires `projects:view`.

Operation id: `list_storage_credentials_v1_export__tenant_slug__storage_credentials_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list the workspace's bucket credentials. | `application/json` [`StorageCredentialListResponse`](#schema-storagecredentiallistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/storage-credentials` {#create-storage-credential-v1-export-tenant-slug-storage-credentials-post}

**Store an S3-compatible bucket credential**

Stores an access key pair (and optional session token) for export object-storage delivery, sealed in the credential vault on arrival. The answer — and every later read — names the endpoint, region and the access key id's last four characters, never a secret. A custom `endpointUrl` must resolve to public addresses. Requires `projects:edit`. `409` for a name already in use; `503` when the deployment has no credential encryption key (`APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS`).

Operation id: `create_storage_credential_v1_export__tenant_slug__storage_credentials_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for store an s3-compatible bucket credential.

- `application/json` — [`StorageCredentialCreate`](#schema-storagecredentialcreate)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for store an s3-compatible bucket credential. | `application/json` [`StorageCredentialModel`](#schema-storagecredentialmodel) |
| 400 | Invalid field, or a refused endpoint. | — |
| 409 | A credential of that name exists. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |
| 503 | Credential encryption is not configured. | — |

## `DELETE /v1/export/{tenant_slug}/storage-credentials/{credential_id}` {#delete-storage-credential-v1-export-tenant-slug-storage-credentials-credential-id-delete}

**Delete a bucket credential**

Removes the credential from the vault; past deliveries keep their record. Requires `projects:edit`. `404` when the workspace has no such credential.

Operation id: `delete_storage_credential_v1_export__tenant_slug__storage_credentials__credential_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `credential_id` | path | string | yes | Path parameter identifying the credential id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 204 | Successful response for delete a bucket credential. | — |
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

### `ExportObjectStorageDeliveryRunListResponse` {#schema-exportobjectstoragedeliveryrunlistresponse}

A job's object-storage deliveries, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`ExportObjectStorageDeliveryRunModel`](#schema-exportobjectstoragedeliveryrunmodel) | no | Runs. |

### `ExportObjectStorageDeliveryRunModel` {#schema-exportobjectstoragedeliveryrunmodel}

One export object-storage delivery.

Attributes:
    run_id: The run record (null only when it could not be stored).
    status: ``in_progress``, ``delivered`` or ``failed``.
    job_id: The export job delivered.
    credential_id: The storage credential used.
    endpoint_url: The endpoint (null for AWS S3).
    bucket: The bucket.
    key_prefix: The resolved prefix every object is under.
    partitioning: The partitions used, in order.
    objects: Every object written (on a failure, those written before it).
    manifest_key: The content-addressed manifest (``<keyPrefix>/manifests/<sha256>.json``).
    manifest_sha256: Its SHA-256.
    fidelity: The export's fidelity summary.
    error_code: Set when the run failed.
    error_message: Set when the run failed, redacted.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runId` | string or null | no | Run ID. |
| `status` | string | yes | Status. |
| `jobId` | string | yes | Job ID. |
| `credentialId` | string or null | no | Credential ID. |
| `endpointUrl` | string or null | no | Endpoint URL. |
| `bucket` | string | yes | Bucket. |
| `keyPrefix` | string | no | Key Prefix. |
| `partitioning` | array of string | no | Partitioning. |
| `objects` | array of `ExportObjectStorageObjectModel` | no | Objects. |
| `manifestKey` | string or null | no | Manifest Key. |
| `manifestSha256` | string or null | no | Manifest Sha256. |
| `fidelity` | object | no | Fidelity. |
| `errorCode` | string or null | no | Error Code. |
| `errorMessage` | string or null | no | Error Message. |
| `startedAt` | string (date-time) or null | no | Started At. |
| `finishedAt` | string (date-time) or null | no | Finished At. |

### `ExportWebhookDeliveryRunListResponse` {#schema-exportwebhookdeliveryrunlistresponse}

A job's webhook deliveries, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`ExportWebhookDeliveryRunModel`](#schema-exportwebhookdeliveryrunmodel) | no | Runs. |

### `ExportWebhookDeliveryRunModel` {#schema-exportwebhookdeliveryrunmodel}

One export webhook delivery.

Attributes:
    run_id: The delivery — also its `X-Apiome-Delivery` header and the body's `deliveryId`.
    status: ``pending``, ``delivering``, ``retrying``, ``delivered`` or ``failed``.
    job_id: The export job delivered.
    target_url: The receiver, without its query string.
    artifact_delivery: ``inline`` or ``fetch``.
    payload_sha256: SHA-256 of the signed body.
    attempt_count: Attempts made.
    max_attempts: Attempts before the run fails.
    attempts: Every attempt, oldest first.
    next_attempt_at: When the next retry is due (``retrying``).
    last_http_status: The receiver's last status code.
    fidelity: The fidelity summary the body carried.
    error_code: The last failure's code.
    error_message: The last failure's message.
    started_at: When the delivery was requested.
    finished_at: When it was delivered or failed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runId` | string | yes | Run ID. |
| `status` | string | yes | Status. |
| `jobId` | string | yes | Job ID. |
| `targetUrl` | string | yes | Target URL. |
| `artifactDelivery` | string | yes | Artifact Delivery. |
| `payloadSha256` | string or null | no | Payload Sha256. |
| `attemptCount` | integer | no | Number of attempt. |
| `maxAttempts` | integer | yes | Max Attempts. |
| `attempts` | array of `ExportWebhookDeliveryAttemptModel` | no | Attempts. |
| `nextAttemptAt` | string (date-time) or null | no | Next Attempt At. |
| `lastHttpStatus` | integer or null | no | Last HTTP Status. |
| `fidelity` | object | no | Fidelity. |
| `errorCode` | string or null | no | Error Code. |
| `errorMessage` | string or null | no | Error Message. |
| `startedAt` | string (date-time) or null | no | Started At. |
| `finishedAt` | string (date-time) or null | no | Finished At. |

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

### `ObjectStorageDeliveryRequest` {#schema-objectstoragedeliveryrequest}

Where to deliver an export: ``POST …/jobs/{job_id}/deliveries/object-storage``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `credentialId` | string | yes | A storage credential of this workspace (`GET /v1/export/{tenant}/storage-credentials`). |
| `bucket` | string | yes | The bucket (S3 naming rules: 3–63 lowercase letters, digits, `.` and `-`). |
| `prefix` | string | no | The key prefix every object is written under (`exports/apis`). Empty means the bucket root. |
| `partitioning` | array of enum `"artifact"`, `"version"`, `"target"` | no | The partitions below the prefix, in order. Default `[artifact, version, target]` → `<prefix>/orders/1.4.0/openapi-3.1/…`; `[]` writes straight under the prefix. |

### `StorageCredentialCreate` {#schema-storagecredentialcreate}

A bucket credential for the vault: ``POST /v1/export/{tenant}/storage-credentials``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | A name unique in the workspace (`data-lake-prod`). |
| `accessKeyId` | string (password) | yes | The access key id. Sealed; only its last four characters are ever shown. |
| `secretAccessKey` | string (password) | yes | The secret access key. Sealed; never shown. |
| `sessionToken` | string (password) or null | no | A session token, for temporary credentials. |
| `endpointUrl` | string or null | no | An S3-compatible endpoint (`https://minio.example.com`, `https://<account>.r2.cloudflarestorage.com`). Empty means AWS S3. It must resolve to public addresses only. |
| `region` | string | no | The bucket's region (`auto` for R2). |
| `forcePathStyle` | boolean | no | Address buckets as `<endpoint>/<bucket>/…` instead of `<bucket>.<endpoint>/…` — most self-hosted stores (MinIO, Ceph) need it. |

### `StorageCredentialListResponse` {#schema-storagecredentiallistresponse}

A workspace's storage credentials, by name.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `credentials` | array of [`StorageCredentialModel`](#schema-storagecredentialmodel) | no | Credentials. |

### `StorageCredentialModel` {#schema-storagecredentialmodel}

A stored bucket credential, described without its secrets.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `provider` | string | no | Provider. |
| `endpointUrl` | string or null | no | The S3-compatible endpoint; null for AWS S3. |
| `region` | string | yes | Region. |
| `forcePathStyle` | boolean | no | Force Path Style. |
| `accessKeyHint` | string | yes | The access key id's last four characters. |
| `createdAt` | string (date-time) or null | no | Created At. |
| `updatedAt` | string (date-time) or null | no | Updated At. |

### `WebhookDeliveryRequest` {#schema-webhookdeliveryrequest}

Where to deliver an export: ``POST …/jobs/{job_id}/deliveries/webhook``.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | string | yes | The receiver: a public `https` (or `http`) URL. Addresses inside private, loopback or link-local networks are refused, on the first attempt and on every retry. |
| `secret` | string | yes | The shared secret (16–512 characters) the body is signed with: `X-Apiome-Signature: sha256=<HMAC-SHA256 of the body, hex>`. Apiome signs the body once and never stores the secret. |
| `artifact` | enum `"auto"`, `"fetch"` | no | How the bundle travels. `auto` (default): inside the body when it is small enough, otherwise as a signed, expiring fetch link. `fetch`: always as a fetch link. |
