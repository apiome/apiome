---
title: "Export jobs"
description: "REST endpoints tagged export-jobs: 6 operations."
sidebar_position: 22
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `export-jobs` · 6 operations

## `GET /v1/export/{tenant_slug}/jobs` {#list-export-jobs-v1-export-tenant-slug-jobs-get}

**List export jobs**

Paginated tenant export jobs from the shared store (IXH-6.3), newest first. Supports ``state`` and ``created_after`` / ``created_before`` filters. Default page size is 50 (max 200).

Operation id: `list_export_jobs_v1_export__tenant_slug__jobs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `limit` | query | integer | no | Page size (default 50, max 200). |
| `offset` | query | integer | no | Number of matching jobs to skip. |
| `state` | query | string or null | no | Exact job state filter (e.g. completed, failed, running). |
| `created_after` | query | string (date-time) or null | no | Inclusive lower bound on job created_at (ISO-8601). |
| `created_before` | query | string (date-time) or null | no | Inclusive upper bound on job created_at (ISO-8601). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list export jobs. | `application/json` [`ExportJobListResponse`](#schema-exportjoblistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/jobs` {#start-export-job-v1-export-tenant-slug-jobs-post}

**Start an asynchronous export job**

Submit an export of one artifact/version to one target through the async job pipeline: load source → fidelity report → emit → validate → package. ``dry_run: true`` stops after the fidelity report (no artifact), the async twin of ``POST …/preview``. Poll the returned ``status_path`` for progress; the status contract matches the spec-import job surface.

Operation id: `start_export_job_v1_export__tenant_slug__jobs_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for start an asynchronous export job.

- `application/json` — [`ExportJobStartRequest`](#schema-exportjobstartrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for start an asynchronous export job. | `application/json` [`ExportJobAccepted`](#schema-exportjobaccepted) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/jobs/{job_id}` {#get-export-job-status-v1-export-tenant-slug-jobs-job-id-get}

**Get export job status**

Poll payload for one export job: state, percent, structured events, and coarse progress. A terminal job is self-describing — a completed real export carries a ``result`` (resolved coordinates, fidelity envelope, transcode guard, emitted-file manifest, and a ``download_path`` for the artifact bytes); a dry-run carries the report only (no ``download_path``); a failed job carries a structured ``error``.

Operation id: `get_export_job_status_v1_export__tenant_slug__jobs__job_id__get`

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
| 200 | Successful response for get export job status. | `application/json` [`ExportJobStatus`](#schema-exportjobstatus) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/export/{tenant_slug}/jobs/{job_id}` {#cancel-export-job-v1-export-tenant-slug-jobs-job-id-delete}

**Cancel an export job**

Request cancellation. The pipeline stops at its next stage boundary; a job already in a terminal state is left unchanged (the request is a no-op).

Operation id: `cancel_export_job_v1_export__tenant_slug__jobs__job_id__delete`

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
| 204 | Successful response for cancel an export job. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/jobs/{job_id}/attestation` {#get-export-job-attestation-v1-export-tenant-slug-jobs-job-id-attestation-get}

**Fetch a delivered artifact's signed delivery attestation**

The delivery attestation for a completed export job (IXH-2.5): an **in-toto Statement v1** in a **DSSE envelope**, HMAC-SHA256 signed with the shared attestation secret (``APIOME_LINT_ATTESTATION_SIGNING_SECRET`` — the same key the CLX-4.2 lint gate attestations use, so a verifier needs no new configuration).

The statement's subject is the delivered artifact, digested with a plain ``sha256`` over the exact bytes the download route serves, so ``sha256sum`` on the downloaded file is enough to tie the two together. Its predicate records the delivery identity, the tool versions, the source lint fingerprint, the policy version and content fingerprint that were applied, any waiver the decision honoured, and the delivery decision with its named reasons — everything needed to reproduce the verdict offline. ``apiome lint verify-attestation`` verifies it as-is.

404 when the job is unknown for this tenant; 409 when the job produced no attested delivery (still running, canceled, failed, or a dry-run).

Operation id: `get_export_job_attestation_v1_export__tenant_slug__jobs__job_id__attestation_get`

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
| 200 | Successful response for fetch a delivered artifact's signed delivery attestation. | `application/json` [`DeliveryAttestation`](#schema-deliveryattestation) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/jobs/{job_id}/download` {#download-export-job-artifact-v1-export-tenant-slug-jobs-job-id-download-get}

**Download a completed export job's artifact**

Serve the artifact a completed export job produced — the target the poller was handed via ``result.download_path``. The bytes come from the job's retained emit result (no re-emit) and are **streamed** in fixed-size chunks with an up-front ``Content-Length`` (MFX-4.3), so a large bundle is not buffered whole. A **single-file** export (MFX-4.1) is served inline with the emitted file's content type and a ``Content-Disposition`` filename, byte-identical to the size the job manifest reported. A **multi-file** export (protobuf packages, WSDL+XSD, per-subject Avro) is served as an ``application/zip`` bundle (MFX-4.2) carrying every emitted file plus a root ``manifest.json``. A job that is not completed or is a dry-run (no artifact) is rejected with 409; a completed job whose retained artifact has passed its retention window (MFX-4.3) is 410 Gone.

Operation id: `download_export_job_artifact_v1_export__tenant_slug__jobs__job_id__download_get`

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
| 200 | Successful response for download a completed export job's artifact. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `DeliveryAttestation` {#schema-deliveryattestation}

The signed evidence attached to a delivered artifact.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `predicate_type` | string | yes | The in-toto predicate type of the wrapped statement. |
| `signed` | boolean | yes | Whether the envelope carries a signature. False when no attestation signing secret is configured on this server — the document is still well-formed, just not verifiable. |
| `key_id` | string or null | no | The key id a verifier uses to select the shared secret. |
| `generated_at` | string | yes | Statement timestamp (ISO-8601, UTC). |
| `envelope` | object | yes | The DSSE envelope: ``payloadType`` / base64 ``payload`` / ``signatures``. Verifiable offline with the shared secret and the standard library alone. |

### `ExportJobAccepted` {#schema-exportjobaccepted}

Returned when a job is accepted (HTTP 202) — mirrors the import acceptance.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `job_id` | string | yes | Job ID. |
| `status_path` | string | yes | Relative URL path for GET …/jobs/{job_id} until the job reaches a terminal state. |

### `ExportJobListResponse` {#schema-exportjoblistresponse}

Paginated tenant-scoped export jobs (IXH-6.3).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `jobs` | array of `ExportJobListItem` | yes | Jobs. |
| `total` | integer | no | Total jobs matching the filter (not just this page). |
| `limit` | integer | no | Page size applied to this response. |
| `offset` | integer | no | Number of matching jobs skipped before this page. |

### `ExportJobStartRequest` {#schema-exportjobstartrequest}

Submit an export job: source coordinates + target + options + dry-run flag.

The source half matches ``POST /export/preview`` / ``POST /export/document``
(MFX-2.5/11.5); ``dry_run`` selects the preview-only path (fidelity report, no
artifact), the async twin of the synchronous ``/export/preview`` endpoint.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to export. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. |
| `dry_run` | boolean | no | When true, stop after the fidelity report: no artifact is emitted. |
| `confirm` | boolean | no | When true, proceed with a **severe** conversion (MFX-3.3) the transcoding guard would otherwise fail the job on. Ignored for non-severe conversions and dry-runs. |
| `acknowledged_snapshot` | string or null | no | The projection snapshot hash (``fidelity.projection.manifest_hash``) the caller previewed and acknowledged (EFP-2.1). When set, the job recomputes the snapshot for its actual inputs and **fails with `STALE_PREVIEW`** if the hashes differ — the source revision, options, emitter version, or registry changed since the preview, so the acknowledgement no longer describes what would be generated. Null skips the check. |
| `min_severity` | `LossinessSeverity` | no | Lowest loss severity that raises the advisory (MFX-2.4); does not affect the report or counts. |

### `ExportJobStatus` {#schema-exportjobstatus}

Poll payload for an export job (same shape as the import job status).

A terminal job is self-describing: ``completed`` carries ``result`` (with a
``download_path`` for a real export), ``failed`` carries a structured ``error`` (MFX-3.4).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `job_id` | string | yes | Job ID. |
| `state` | enum `"queued"`, `"running"`, `"completed"`, `"failed"`, `"canceled"` | yes | State. |
| `percent` | integer | no | Percent. |
| `events` | array of `ExportJobEvent` | no | Events. |
| `progress` | `ExportJobProgress` or null | no | Progress. |
| `result` | `ExportJobResult` or null | no | Result. |
| `error` | `ExportJobError` or null | no | Structured failure detail; set only in the ``failed`` terminal state. |
| `correlation_id` | string or null | no | Correlation id of the request that started the job (IXH-6.6); matches the X-Request-ID of the submitting request and every log line the job emitted. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
