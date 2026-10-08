---
title: "Spec import"
description: "REST endpoints tagged spec-import: 14 operations."
sidebar_position: 68
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `spec-import` · 14 operations

## `POST /v1/tenants/{tenant_slug}/import/bulk` {#start-bulk-import-v1-tenants-tenant-slug-import-bulk-post}

**Start one import job per independent spec in a bulk payload**

Re-plan the payload server-side (identical bytes always yield an identical plan), **reconcile it exactly as the plan endpoint did**, and start one ordinary import job per item (MFI-29.5). Pass `keys` to import a subset of the planned items; omit it to attempt every planned item.

Each item is applied at the destination its plan row resolved to (BLK-1.2): a matched item appends its proposed version to that project, an unmatched item creates one. **`overrides` change that per item** — `mode: existing` (optionally with a `project_id`) appends where the plan would have created, `mode: new` creates where it would have appended, and `version_id` alone carries a real version number without moving the item. An item with no override applies the plan, so agreeing with the plan costs nothing to express. Every started row reports its `resolution`, `target_project_id` and `version_id`, so the response states what was done rather than only that something was.

**`dry_run` is the verify pass**, not a lesser one: it resolves and validates every item through the same computation the apply uses and persists nothing — no project, no version, no catalog row — so the rows it returns are the import it would perform.

**Send `plan_fingerprint`** and a plan that drifted since it was reviewed is refused with `TARGET_PLAN_STALE` (409), carrying a `drift` list naming each item that moved and what it moved from — checked before any item starts, so nothing is written.

Each item is otherwise gated and scheduled independently: an item whose format has no adapter, whose key is not in the plan, which the tenant's import quality policy refuses (IXH-2.3), or whose target BLK-1.1 will not honour (an unknown project, a catalog item named explicitly, a version label already taken) is reported as a **failed row with a taxonomy code** while every other item still starts — a partial failure never aborts the batch. Items that do start run the unchanged import chain, including the §0.2 routing that decides Catalog vs Projects, so nothing about a bulk import differs from importing the same document on its own.

The response is the batch's per-item start result. The batch itself holds no server state: poll the returned job ids individually or roll them up with `POST …/import/bulk/status`.

Operation id: `start_bulk_import_v1_tenants__tenant_slug__import_bulk_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for start one import job per independent spec in a bulk payload.

- `application/json` — [`BulkImportStartRequest`](#schema-bulkimportstartrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for start one import job per independent spec in a bulk payload. | `application/json` [`BulkImportStartResponse`](#schema-bulkimportstartresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/import/bulk/plan` {#plan-bulk-import-payload-v1-tenants-tenant-slug-import-bulk-plan-post}

**Plan a bulk import: partition an archive or repository into independent items**

Partition one archive upload or repository selection into the **independent** specs it holds (MFI-29.5) and describe each as a candidate import job: root document, the sibling files it compiles, the detected format and adapter, the predicted destination under the §0.2 routing policy, and a suggested catalog name and slug.

Grouping follows references between files — protobuf `import`, JSON/YAML `$ref`, XSD/WSDL `schemaLocation` — so a proto tree with cross-directory imports stays **one** item while two unrelated AsyncAPI documents are two. Files that belong to no importable item are reported in `skipped` with a reason, never dropped silently, and a payload holding more items than the batch ceiling reports `truncated` rather than importing a silent prefix.

Every item is then **reconciled** against the tenant's existing projects (BLK-1.2), so the plan answers the question that decides the batch: *which of these is a new version of something I already have?* An item resolves to `append-version` or `create-project`, naming the `matched_project`, the `match_basis` that found it (repository provenance, then slug, then the document's own identity — which is how a file that moved within the repository still matches), a `match_confidence` distinct from the format-detection `confidence`, and the `proposed_version` it would create. What a match *means* comes from the reconciliation policy — the registered repository's override, else the tenant default, else `append-when-matched` — reported as `version_policy` / `version_policy_source`. `always-create` reports the matches it is ignoring rather than hiding them, and `always-ask` marks every item `unresolved` for a per-item choice at apply time.

The response carries a `plan_fingerprint` (BLK-1.3) describing exactly these resolutions. Echo it on the submit call and the apply refuses to run a plan that has drifted since you read it — someone else creating the project one of your items was going to mint, or taking the version another proposed — naming the rows that moved rather than importing something you never saw.

Nothing is persisted and no job is created — reconciliation is reads only. Item bytes are returned only when `include_documents` is set; the submit endpoint re-plans the same payload itself, so a client that just renders the list does not need them.

Operation id: `plan_bulk_import_payload_v1_tenants__tenant_slug__import_bulk_plan_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for plan a bulk import: partition an archive or repository into independent items.

- `application/json` — [`BulkImportPlanRequest`](#schema-bulkimportplanrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for plan a bulk import: partition an archive or repository into independent items. | `application/json` [`BulkImportPlanResponse`](#schema-bulkimportplanresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/import/bulk/status` {#bulk-import-status-v1-tenants-tenant-slug-import-bulk-status-post}

**Roll up the jobs of one bulk batch into a per-item result list**

Fan out over the `(key, job_id)` pairs a bulk submit returned and report each item's state, its authoritative routing destination and created item once it completes, and its taxonomy-coded error when it fails — plus the counts a summary line needs and a `done` flag that is true once every item is terminal.

A completed row also names its **realized destination** (BLK-1.3): `outcome` is `version-appended` or `project-created`, with the `project_id`, `project_slug` and `version_id` it landed on, and the summary counts both. That is read back from the catalog rather than echoed from what the submit predicted, so the roll-up states what happened.

This is a convenience roll-up, not a second source of truth: each row is the same payload `GET …/imports/{job_id}` returns. A job id this tenant does not own is reported as state `not-found` rather than failing the whole call, so one stale id cannot blind a client to the rest of its batch.

Operation id: `bulk_import_status_v1_tenants__tenant_slug__import_bulk_status_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for roll up the jobs of one bulk batch into a per-item result list.

- `application/json` — [`BulkImportStatusRequest`](#schema-bulkimportstatusrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for roll up the jobs of one bulk batch into a per-item result list. | `application/json` [`BulkImportStatusResponse`](#schema-bulkimportstatusresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/import/bundle-inventory` {#inventory-import-bundle-v1-tenants-tenant-slug-import-bundle-inventory-post}

**Per-file inventory of a multi-file / archive candidate (no write)**

Explain a **bundle** import file by file (IXH-3.5). An uploaded archive or a packed git selection (MFI-29.1/29.2/29.3) is dozens of files, and a single grade plus a single entity tree cannot say which one failed, which was never read, or which supplied the entry point. This endpoint unpacks the candidate through the same archive intake the commit uses and returns, per file: its **role** (entry-point, dependency, unreferenced, ignored, unreadable — an ignored file always states *why*), its **verdict** and the parse diagnostic naming it, its resolved **import/include edges** and incoming references, and the **canonical entities it appears to contribute** (by declaration scan — the response carries the `attribution` method so the evidence quality is never overstated).

Alongside the files it returns every **unresolved** reference *with the search paths that were tried, in order*, and the ranked **entry-point candidates**. Overriding the detected entry point is a plain re-run: send the chosen member as `archive_root` and the pre-flight, preview manifest, and this inventory all re-derive from it.

A payload that is not an archive is **not an error**: the response is `ok: true` with `kind: single-document` and no inventory. `ok` is false only when the archive itself could not be unpacked, and then `error` carries the stable intake-taxonomy code. An ambiguous root or a failed parse still returns the **complete file list** — that is exactly the bundle this panel exists for. Files are cursor-paginated and nothing is persisted.

Operation id: `inventory_import_bundle_v1_tenants__tenant_slug__import_bundle_inventory_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for per-file inventory of a multi-file / archive candidate (no write).

- `application/json` — [`ImportBundleInventoryRequest`](#schema-importbundleinventoryrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for per-file inventory of a multi-file / archive candidate (no write). | `application/json` [`ImportBundleInventoryResponse`](#schema-importbundleinventoryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/import/git/fileset` {#fetch-git-import-fileset-v1-tenants-tenant-slug-import-git-fileset-post}

**Fetch a git repository selection as an importable fileset**

Read a repository path or glob at a ref (MFI-29.3) and return it as the payload the import flow already accepts: the selected files packed as a deterministic archive (``document_base64``), the resolved root document, the detected format, and the **commit** the files were read at.

Pass the returned bytes to ``POST /import/preflight`` and ``POST …/imports`` exactly as you would an uploaded archive, and echo ``git_source`` back in ``options.git_source`` so the created revision records repository, ref, and commit provenance. Nothing is persisted by this call.

Only github.com repositories are supported today. Private repositories are read with a **stored** linked-account credential — named either by ``repository_id`` (a registered tenant repository) or ``linked_account_id`` (the caller's own linked account); tokens are never accepted in the request. Files that cannot be imported (dotfiles, binaries, vendored trees, oversized blobs) are reported in ``skipped`` rather than silently dropped.

Operation id: `fetch_git_import_fileset_v1_tenants__tenant_slug__import_git_fileset_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for fetch a git repository selection as an importable fileset.

- `application/json` — [`GitFilesetRequest`](#schema-gitfilesetrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for fetch a git repository selection as an importable fileset. | `application/json` [`GitFilesetResponse`](#schema-gitfilesetresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/import/preflight` {#preflight-import-candidate-v1-tenants-tenant-slug-import-preflight-post}

**Pre-flight a candidate document (lint and rank, no write)**

Score a candidate document **before** importing it (IXH-2.1). Runs the same detect → parse → normalize → fingerprint → lint pipeline a real import runs, with dry-run semantics, and returns the detected adapter and confidence, the routing decision, canonical entity counts, the revision fingerprint, the full lint report with findings ranked by severity then rule weight, the resolved style guide, and the tenant quality policy verdict (IXH-2.3) with the resolution tier that produced it. Nothing is persisted: no catalog item, project, version, type row, or import job.

A document that cannot be imported is **not** an HTTP error — the response is a 200 with ``ok: false`` and a stable intake-taxonomy ``error`` code plus remediation, so callers key off the code rather than parsing exception strings. Repeated pre-flights of identical bytes are served from a tenant-scoped cache and report ``cache.hit``; the policy verdict is always re-evaluated, so a waiver recorded between two calls is reflected immediately.

Operation id: `preflight_import_candidate_v1_tenants__tenant_slug__import_preflight_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for pre-flight a candidate document (lint and rank, no write).

- `application/json` — [`ImportPreflightRequest`](#schema-importpreflightrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for pre-flight a candidate document (lint and rank, no write). | `application/json` [`ImportPreflightReport`](#schema-importpreflightreport) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/import/preview-manifest` {#preview-import-manifest-v1-tenants-tenant-slug-import-preview-manifest-post}

**Preview manifest for a candidate document (entity tree + coverage ledger, no write)**

Describe **what an import would create** before committing it (IXH-3.1). Extends the IXH-2.1 pre-flight: the same detect → parse → normalize → fingerprint → lint pipeline runs with dry-run semantics, and the response adds the canonical entity tree (services → operations, types, channels) with stable canonical keys and source locations, per-entity provenance back to the source construct, a coverage ledger that classifies source constructs as mapped / partially-mapped / unsupported-by-canonical-model / not-parsed-by-adapter (the last two are never conflated, and every not-parsed entry names its CLX-2.4 capability-registry reference), the adapter capability reference, and the routing decision (on the embedded pre-flight report). The graph reuses the CPDO-1.3 projection-manifest node/edge vocabulary, so the import graph and the conversion graph share one contract.

The manifest is deterministic and byte-stable for a fixed input, adapter version, and options (`manifest_hash` is the snapshot id), and is cursor-paginated over the entity tree for large inputs — truncation is stated in the payload (`truncated`, `total_*`), never silent. A candidate that cannot be imported is still a 200: `ok` is false, `manifest` is null, and the embedded pre-flight report carries the stable intake-taxonomy error. Nothing is persisted.

When the request names the catalog `project_slug` the commit would use and an existing catalog item lives under it, the response also carries the IXH-3.4 **re-import delta**: `canonical_diff` between the current revision's canonical model and the candidate, grouped/counted by entity family, with breaking-change grades joined where the format's classifier is available, and an explicit no-op verdict (matching fingerprints) when the re-import would create an empty revision. First-time imports have `reimport = null`.

Operation id: `preview_import_manifest_v1_tenants__tenant_slug__import_preview_manifest_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for preview manifest for a candidate document (entity tree + coverage ledger, no write).

- `application/json` — [`ImportPreviewManifestRequest`](#schema-importpreviewmanifestrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview manifest for a candidate document (entity tree + coverage ledger, no write). | `application/json` [`ImportPreviewManifestResponse`](#schema-importpreviewmanifestresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/imports` {#list-spec-import-jobs-v1-tenants-tenant-slug-imports-get}

**List specification import jobs**

Paginated tenant import jobs from the shared store (IXH-6.3), newest first. Supports ``state`` and ``created_after`` / ``created_before`` filters. Default page size is 50 (max 200).

Operation id: `list_spec_import_jobs_v1_tenants__tenant_slug__imports_get`

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
| 200 | Successful response for list specification import jobs. | `application/json` [`SpecImportJobListResponse`](#schema-specimportjoblistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/imports` {#start-spec-import-json-v1-tenants-tenant-slug-imports-post}

**Start specification import (JSON + base64)**

Create an asynchronous import job using a JSON body. The document is sent as standard base64 in ``document_base64``.

Operation id: `start_spec_import_json_v1_tenants__tenant_slug__imports_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for start specification import (json + base64).

- `application/json` — [`SpecImportStartJsonRequest`](#schema-specimportstartjsonrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for start specification import (json + base64). | `application/json` [`SpecImportJobAccepted`](#schema-specimportjobaccepted) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/imports/upload` {#start-spec-import-multipart-v1-tenants-tenant-slug-imports-upload-post}

**Start specification import (multipart file)**

Create an asynchronous import job using multipart upload. The ``metadata`` field must be a JSON string matching ``SpecImportStartMetadata`` (same structure as the ``metadata`` object in the JSON endpoint). The ``file`` part carries raw spec bytes.

Operation id: `start_spec_import_multipart_v1_tenants__tenant_slug__imports_upload_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for start specification import (multipart file).

- `multipart/form-data` — [`SpecImportMultipartUploadBody`](#schema-specimportmultipartuploadbody)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for start specification import (multipart file). | `application/json` [`SpecImportJobAccepted`](#schema-specimportjobaccepted) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/imports/{job_id}` {#get-spec-import-status-v1-tenants-tenant-slug-imports-job-id-get}

**Get specification import job status**

Operation id: `get_spec_import_status_v1_tenants__tenant_slug__imports__job_id__get`

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
| 200 | Successful response for get specification import job status. | `application/json` [`SpecImportJobStatus`](#schema-specimportjobstatus) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/tenants/{tenant_slug}/imports/{job_id}` {#cancel-spec-import-job-v1-tenants-tenant-slug-imports-job-id-delete}

**Cancel specification import job**

Operation id: `cancel_spec_import_job_v1_tenants__tenant_slug__imports__job_id__delete`

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
| 204 | Successful response for cancel specification import job. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/imports/{job_id}/commit` {#commit-spec-import-job-v1-tenants-tenant-slug-imports-job-id-commit-post}

**Commit a previewed specification import**

Operation id: `commit_spec_import_job_v1_tenants__tenant_slug__imports__job_id__commit_post`

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
| 200 | Successful response for commit a previewed specification import. | `application/json` [`SpecImportCommitResponse`](#schema-specimportcommitresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/imports/{job_id}/rollback` {#rollback-spec-import-job-v1-tenants-tenant-slug-imports-job-id-rollback-post}

**Rollback a committed specification import**

Operation id: `rollback_spec_import_job_v1_tenants__tenant_slug__imports__job_id__rollback_post`

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
| 200 | Successful response for rollback a committed specification import. | `application/json` [`SpecImportRollbackResponse`](#schema-specimportrollbackresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `BulkImportPlanRequest` {#schema-bulkimportplanrequest}

Plan a bulk import: partition the payload and describe each item.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `document_base64` | string or null | no | Standard base64 of a .zip / .tar.gz / .tgz archive holding the documents to import. Mutually exclusive with 'git'. |
| `filename` | string or null | no | Archive filename, used as the source label in messages. |
| `git` | `BulkImportGitSelector` or null | no | Repository selection to read instead of an uploaded archive (MFI-29.3). Mutually exclusive with 'document_base64'. |
| `include_documents` | boolean | no | Include each item's ready-to-import bytes in the response. Off by default: the submit endpoint re-plans the same payload server-side, so a client that only renders the plan never needs them. |

### `BulkImportPlanResponse` {#schema-bulkimportplanresponse}

The partition of one payload into independent items.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `BulkImportPlanItem` | no | Items. |
| `skipped` | array of `BulkImportSkippedMember` | no | Skipped. |
| `truncated` | boolean | no | True when the payload holds more items than one batch may carry; the extra items are listed in 'skipped' with reason 'over-item-limit'. |
| `total_items` | integer | yes | Items found before the batch ceiling was applied. |
| `max_items` | integer | yes | The batch ceiling in force for this deployment. |
| `source_label` | string | yes | Label used for the payload in messages. |
| `git_source` | `SpecImportGitSource` or null | no | Repository provenance when the payload came from a git selection. |
| `version_policy` | enum `"append-when-matched"`, `"always-create"`, `"always-ask"` | yes | The reconciliation policy this plan was resolved under (BLK-1.2): 'append-when-matched' (the default — matched items append a version, unmatched items create a project), 'always-create' (every item creates a project; matches are still reported) or 'always-ask' (every item is unresolved and needs a per-item choice at apply time). |
| `version_policy_source` | enum `"repository"`, `"tenant"`, `"default"` | yes | Which tier supplied the policy — the registered repository's override, the tenant's default, or the built-in default when neither is set. |
| `plan_fingerprint` | string | yes | Opaque token describing the reconciliation this plan reports (BLK-1.3). Echo it verbatim as the submit request's 'plan_fingerprint' and the apply refuses to run a plan that has drifted since you reviewed it — someone else creating the project one of your items was going to mint, or taking the version another proposed — naming the rows that moved instead of importing what you never saw. Do not parse it: its encoding is the server's business and may change. Two plans of the same payload with the same fingerprint would do the same thing. |
| `summary` | `BulkImportPlanSummary` | yes | Short summary suitable for navigation and reference docs. |

### `BulkImportStartRequest` {#schema-bulkimportstartrequest}

Start one import job per selected item of a bulk payload.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `document_base64` | string or null | no | Standard base64 of a .zip / .tar.gz / .tgz archive holding the documents to import. Mutually exclusive with 'git'. |
| `filename` | string or null | no | Archive filename, used as the source label in messages. |
| `git` | `BulkImportGitSelector` or null | no | Repository selection to read instead of an uploaded archive (MFI-29.3). Mutually exclusive with 'document_base64'. |
| `keys` | array of string | no | Item keys to import (from the plan). Empty imports every importable item. A key that is not in the plan is reported as a failed item, not an error. |
| `overrides` | array of `BulkImportItemOverride` | no | Per-item decisions overriding the plan's reconciliation (BLK-1.3), keyed by the plan's stable item key. Absent for an item means 'apply what the plan resolved'. |
| `plan_fingerprint` | string or null | no | The 'plan_fingerprint' of the plan you reviewed, echoed verbatim (BLK-1.3). When set, the batch re-plans and refuses with TARGET_PLAN_STALE — naming the drift per item and writing nothing — if the payload would now do something other than what you reviewed. Omit it to apply whatever re-planning produces. |
| `dry_run` | boolean | no | Verify instead of apply: every item is resolved and validated exactly as the apply would resolve and validate it — the response's per-item 'resolution', 'target_project_id' and 'version_id' are the same computation — and nothing is persisted. No project, version or catalog row is written. |

### `BulkImportStartResponse` {#schema-bulkimportstartresponse}

Per-item start results for one batch. Partial failure is normal, not fatal.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `batch_id` | string | yes | Correlation id for this submission. The batch itself is stateless — poll the per-item job ids (or the bulk status endpoint) for progress. |
| `dry_run` | boolean | no | Whether this was a verify pass. True means the rows describe what an apply would do and nothing was persisted. |
| `items` | array of `BulkImportStartItem` | no | Items. |
| `skipped` | array of `BulkImportSkippedMember` | no | Skipped. |
| `summary` | `BulkImportStartSummary` | yes | Short summary suitable for navigation and reference docs. |

### `BulkImportStatusRequest` {#schema-bulkimportstatusrequest}

Roll up the jobs of one batch into a per-item result list.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `BulkImportStatusRef` | no | The (key, job_id) pairs the submit call returned. |

### `BulkImportStatusResponse` {#schema-bulkimportstatusresponse}

Batch progress: one row per item plus the counts a summary line needs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `items` | array of `BulkImportStatusItem` | no | Items. |
| `summary` | `BulkImportStatusSummary` | yes | Short summary suitable for navigation and reference docs. |
| `done` | boolean | yes | True when every item reached a terminal state (or is unknown). |

### `GitFilesetRequest` {#schema-gitfilesetrequest}

A repository selection to fetch as an importable fileset.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `repo_url` | string | yes | Repository URL, for example https://github.com/owner/repo. |
| `ref` | string or null | no | Branch, tag, or commit sha. Defaults to the repository's default branch. |
| `path` | string | no | Path or glob selecting the files to import — a directory ('protos/'), an exact file, or a glob ('**/*.proto'). Empty selects the whole tree. The static prefix is stripped from member paths so sibling imports/refs keep resolving. |
| `root` | string or null | no | Explicit root document, relative to the selection. Required only when root auto-detection reports the selection as ambiguous. |
| `repository_id` | string or null | no | Registered tenant repository whose stored linked-account credential authorizes the read (private repositories). |
| `linked_account_id` | string or null | no | The acting user's linked account whose stored token authorizes the read, when no registered repository is used. |
| `include_document` | boolean | no | Include the packed archive bytes in the response (the import payload). Set false to preview the selection — members, root, detection, commit — without them. |

### `GitFilesetResponse` {#schema-gitfilesetresponse}

The fetched selection: import payload, detection, and commit provenance.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `git_source` | `SpecImportGitSource` | yes | Provenance to echo back in options.git_source when starting the import. |
| `filename` | string | yes | Suggested filename for the packed archive (the import's source label). |
| `document_base64` | string or null | no | Standard base64 of the packed archive, ready for /import/preflight and POST …/imports. Null when include_document was false. |
| `archive_root` | string | yes | Module-relative root document inside the packed archive. |
| `members` | array of string | no | Sorted module-relative member paths. |
| `skipped` | array of `GitFilesetSkippedMember` | no | Repository files the selection matched but did not ingest, with reasons. |
| `total_bytes` | integer | yes | Decoded size of every selected member, in bytes. |
| `source_kind` | string or null | no | Registry key of the adapter detection picked for the root, when importable. |
| `detection` | `DetectFormatResponse` | yes | Format detection for the resolved root document. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ImportBundleInventoryRequest` {#schema-importbundleinventoryrequest}

The candidate to inventory: the IXH-2.1 pre-flight intake payload plus paging.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `document_base64` | string | yes | Standard base64 (RFC 4648) of the candidate document's bytes; no data: URL prefix. |
| `source_kind` | string or null | no | Importer discriminator to pre-flight against (for example openapi, asyncapi, protobuf). When omitted the format is auto-detected and the winning adapter is used; the detection verdict is reported either way. |
| `filename` | string or null | no | Original filename for format sniffing when bytes alone are ambiguous. |
| `content_type` | string or null | no | Optional MIME type hint (for example application/yaml or application/json). |
| `url` | string or null | no | Source URL the document was fetched from, when the intake kind is 'url'. |
| `input_kind` | enum `"file"`, `"url"`, `"paste"`, `"discovery"`, `"fileset"` or null | no | How the document reached the importer; recorded on the report for parity with the import job's option of the same name. |
| `import_target` | enum `"catalog"`, `"types"`, `"project"` or null | no | Destination the commit would request (MFI-26.8). Consulted only for JSON Schema, exactly as on the import job, so the reported routing decision matches what the commit would do. |
| `archive_root` | string or null | no | Explicit module-relative root document inside an uploaded archive (.zip/.tar.gz); auto-selected when omitted. |
| `cursor` | string or null | no | Opaque cursor from a previous page; omit for the first page. |
| `page_size` | integer | no | Files per page (default 250, max 1000). |

### `ImportBundleInventoryResponse` {#schema-importbundleinventoryresponse}

The bundle-inventory endpoint's response (IXH-3.5).

``kind`` is the first thing a client reads: a single document is not a bundle, and
saying so is not an error — the panel simply has nothing to show. ``ok`` is false
only when an archive could not be unpacked at all, in which case ``error`` carries
the intake-taxonomy code.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | True when an inventory was produced; false only when the archive could not be unpacked. |
| `kind` | string | yes | 'archive' for a bundle payload, 'single-document' otherwise. |
| `inventory` | `ImportBundleInventory` or null | no | The inventory page; null when ok is false or kind is single-document. |
| `error` | `SpecImportJobError` or null | no | Stable intake-taxonomy error when the archive could not be unpacked. |

### `ImportPreflightReport` {#schema-importpreflightreport}

The verdict for a candidate document — computed without writing anything (IXH-2.1).

``ok`` is the headline: ``true`` when the candidate parsed, normalized, and linted, so
a commit would produce the reported model; ``false`` when it failed, in which case
``error`` carries the stable intake-taxonomy code and its remediation. Transport is a
200 either way — evaluating a broken candidate is a *successful* pre-flight whose
answer is "do not import this".

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Whether the candidate is importable as submitted. |
| `detection` | `ImportPreflightDetection` | yes | Which importer ran, and why. |
| `routing` | object or null | no | The Project-vs-Catalog-vs-Types decision the commit would take, with its reason. |
| `paradigm` | string or null | no | Canonical paradigm of the normalized model. |
| `format` | string or null | no | Canonical format key of the normalized model. |
| `counts` | `ImportPreflightCounts` | no | Canonical entity counts. |
| `fingerprint` | string or null | no | Revision fingerprint the commit would record for this document. |
| `lint` | `ImportPreflightLint` or null | no | The full lint verdict, or null when the candidate never reached lint. |
| `style_guide` | `ImportPreflightStyleGuide` or null | no | The style guide that governed the lint. |
| `policy` | `ImportPreflightPolicy` | yes | Policy verdict (advisory until IXH-2.3). |
| `secret_scrub` | object or null | no | What intake found in the source (IXH-1.4) — types and line numbers only, never values — plus the tenant scrub mode that governs it (MFI-29.6): 'mode' and 'applied' say whether a commit would redact the stored source or only report on it. |
| `error` | `SpecImportJobError` or null | no | Populated when ok is false: the stable taxonomy code and remediation. |
| `cache` | `ImportPreflightCache` | yes | Cache provenance for this report. |

### `ImportPreflightRequest` {#schema-importpreflightrequest}

A candidate document to score **before** anything is imported (IXH-2.1).

Carries the same intake payload as ``POST …/imports`` — base64 document bytes plus
the filename/content-type hints — minus everything that only matters once something
is written (project/version identity, naming conventions, incremental mode). The
importer is auto-detected unless ``source_kind`` names one explicitly.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `document_base64` | string | yes | Standard base64 (RFC 4648) of the candidate document's bytes; no data: URL prefix. |
| `source_kind` | string or null | no | Importer discriminator to pre-flight against (for example openapi, asyncapi, protobuf). When omitted the format is auto-detected and the winning adapter is used; the detection verdict is reported either way. |
| `filename` | string or null | no | Original filename for format sniffing when bytes alone are ambiguous. |
| `content_type` | string or null | no | Optional MIME type hint (for example application/yaml or application/json). |
| `url` | string or null | no | Source URL the document was fetched from, when the intake kind is 'url'. |
| `input_kind` | enum `"file"`, `"url"`, `"paste"`, `"discovery"`, `"fileset"` or null | no | How the document reached the importer; recorded on the report for parity with the import job's option of the same name. |
| `import_target` | enum `"catalog"`, `"types"`, `"project"` or null | no | Destination the commit would request (MFI-26.8). Consulted only for JSON Schema, exactly as on the import job, so the reported routing decision matches what the commit would do. |
| `archive_root` | string or null | no | Explicit module-relative root document inside an uploaded archive (.zip/.tar.gz); auto-selected when omitted. |

### `ImportPreviewManifestRequest` {#schema-importpreviewmanifestrequest}

The manifest request: the 2.1 pre-flight intake payload plus pagination.

Everything the pre-flight accepts (document, adapter/source hints, import target,
archive root) plus a cursor + page size over the entity tree. Repeating a request
with the next cursor re-submits the same bytes; the manifest itself is served from a
content-hash cache, so paging does not re-run the pipeline.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `document_base64` | string | yes | Standard base64 (RFC 4648) of the candidate document's bytes; no data: URL prefix. |
| `source_kind` | string or null | no | Importer discriminator to pre-flight against (for example openapi, asyncapi, protobuf). When omitted the format is auto-detected and the winning adapter is used; the detection verdict is reported either way. |
| `filename` | string or null | no | Original filename for format sniffing when bytes alone are ambiguous. |
| `content_type` | string or null | no | Optional MIME type hint (for example application/yaml or application/json). |
| `url` | string or null | no | Source URL the document was fetched from, when the intake kind is 'url'. |
| `input_kind` | enum `"file"`, `"url"`, `"paste"`, `"discovery"`, `"fileset"` or null | no | How the document reached the importer; recorded on the report for parity with the import job's option of the same name. |
| `import_target` | enum `"catalog"`, `"types"`, `"project"` or null | no | Destination the commit would request (MFI-26.8). Consulted only for JSON Schema, exactly as on the import job, so the reported routing decision matches what the commit would do. |
| `archive_root` | string or null | no | Explicit module-relative root document inside an uploaded archive (.zip/.tar.gz); auto-selected when omitted. |
| `cursor` | string or null | no | Opaque entity-page cursor from a previous response; null for the first page. |
| `page_size` | integer | no | Maximum entities per page; clamped to 1000. |
| `project_slug` | string or null | no | The catalog project slug the commit would target (the wizard computes it client-side, exactly as it will at commit time). When set and an existing catalog item lives under it, the response carries the IXH-3.4 re-import delta; omitted or unmatched, `reimport` is null (a first-time import). |

### `ImportPreviewManifestResponse` {#schema-importpreviewmanifestresponse}

The preview-manifest endpoint's response (IXH-3.1).

Embeds the full IXH-2.1 pre-flight report (detection, routing decision, counts,
lint, policy verdict, taxonomy error) and adds the manifest. ``manifest`` is null
exactly when the candidate is not importable (``preflight.ok`` false) — there is no
model to describe, and the pre-flight's ``error`` says why.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | Mirrors ``preflight.ok``: whether the candidate is importable. |
| `preflight` | [`ImportPreflightReport`](#schema-importpreflightreport) | yes | The full IXH-2.1 pre-flight report for the same run — detection, routing decision, entity counts, ranked lint, policy verdict, and the intake-taxonomy error when the candidate is not importable. |
| `manifest` | `ImportPreviewManifest` or null | no | The requested manifest page; null when the candidate is not importable. |
| `reimport` | `ImportReimportDelta` or null | no | The IXH-3.4 re-import delta against the targeted catalog item's current revision; null for a first-time import (no existing item under the request's `project_slug`), when no slug was sent, for non-catalog routing, or when the current revision's source cannot be reconstructed. |

### `SpecImportCommitResponse` {#schema-specimportcommitresponse}

Response after a successful commit.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `job_id` | string | yes | Job ID. |
| `state` | `"completed"` | no | State. |
| `project_id` | string | yes | Project identifier the resource belongs to. |
| `project_slug` | string | yes | Project Slug. |
| `version_id` | string | yes | Project version identifier or semantic version label, depending on context. |
| `version_record_id` | string | yes | Version Record ID. |

### `SpecImportJobAccepted` {#schema-specimportjobaccepted}

Returned when a job is accepted (HTTP 202).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `job_id` | string | yes | Job ID. |
| `status_path` | string | yes | Relative URL path for GET …/imports/{job_id} until the job reaches a terminal state. |

### `SpecImportJobListResponse` {#schema-specimportjoblistresponse}

Paginated tenant-scoped import jobs (IXH-6.3).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `jobs` | array of `SpecImportJobListItem` | yes | Jobs. |
| `total` | integer | no | Total jobs matching the filter (not just this page). |
| `limit` | integer | no | Page size applied to this response. |
| `offset` | integer | no | Number of matching jobs skipped before this page. |

### `SpecImportJobStatus` {#schema-specimportjobstatus}

Poll payload for an import job.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `job_id` | string | yes | Job ID. |
| `state` | enum `"queued"`, `"running"`, `"pending-approval"`, `"committing"`, `"completed"`, `"failed"`, … | yes | State. |
| `percent` | integer | no | Percent. |
| `events` | array of `SpecImportEvent` | no | Events. |
| `progress` | `SpecImportProgress` or null | no | Progress. |
| `summary` | object or null | no | Short summary suitable for navigation and reference docs. |
| `result` | `SpecImportJobResult` or null | no | Result. |
| `error` | `SpecImportJobError` or null | no | Populated when state is failed: the stable taxonomy code and remediation for the terminal failure. |
| `correlation_id` | string or null | no | Correlation id of the request that started the job (IXH-6.6); matches the X-Request-ID of the submitting request and every log line the job emitted. |

### `SpecImportMultipartUploadBody` {#schema-specimportmultipartuploadbody}

Multipart upload payload for starting a specification import (raw file bytes plus JSON metadata).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | string (binary) | yes | Raw specification file bytes. |
| `metadata` | string | yes | JSON string matching SpecImportStartMetadata (project, version, source_kind, options). |

### `SpecImportRollbackResponse` {#schema-specimportrollbackresponse}

Response after rolling back a committed import.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `job_id` | string | yes | Job ID. |
| `state` | `"rolled-back"` | no | State. |
| `project_id` | string or null | no | Project identifier the resource belongs to. |
| `version_record_id` | string or null | no | Version Record ID. |

### `SpecImportStartJsonRequest` {#schema-specimportstartjsonrequest}

Start an import using base64-encoded document bytes (application/json).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `metadata` | `SpecImportStartMetadata` | yes | Additional JSON metadata bag. |
| `document_base64` | string | yes | Standard base64 (RFC 4648) of the spec file bytes; no data: URL prefix. |
| `filename` | string or null | no | Original filename for format sniffing when bytes alone are ambiguous. |
| `content_type` | string or null | no | Optional MIME type hint (for example application/yaml or application/json). |
