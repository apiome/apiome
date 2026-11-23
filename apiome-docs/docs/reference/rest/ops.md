---
title: "Ops"
description: "REST endpoints tagged ops: 16 operations."
sidebar_position: 67
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.650.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `ops` · 16 operations

## `GET /health` {#health-check-health-get}

**Health Check**

Backward-compatible health endpoint (compose healthcheck). Equivalent to readiness.

The ``status``/``database`` keys are unchanged. The response additionally carries a
``toolchain`` block (FMT-1.3) reporting the bundled-toolchain verdict this runtime booted
with: ``status`` (``ok`` / ``degraded`` / ``failed``), whether the deployment ``enforced``
the toolchain, how many hard-required tools there are, how many resolved, and the keys of
any that are ``missing``. Availability only — resolved paths, the optional tools and the
exact third-party versions stay on the platform-admin ``GET /v1/ops/toolchain``, because
this endpoint is unauthenticated.

The ``document_store`` block (COA-5.9, #7085) reports the store as a dependency:
``status`` (``ok``; ``degraded`` when running on the ``db`` fallback; ``unavailable`` when
the store did not answer its last check), the active ``backend`` and whether a ``fallback``
is in effect. The check is cached for 30 seconds; error details and settings stay on the
platform-admin ``GET /v1/ops/document-store``. ``tenant_buckets_unavailable`` (COA-5.15,
\#7092) is how many tenants' own buckets are down — ``status`` is ``degraded`` when any is;
which tenants, and why, are on ``GET /v1/ops/document-store``.

The HTTP status reflects database readiness only: an enforcing deployment cannot serve at
all with a required tool missing (startup refuses), a non-enforcing one is degraded
deliberately, and a store outage fails the writes that need it without making the server
unready.

Operation id: `health_check_health_get`

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for health check. | `application/json` any |

## `GET /livez` {#liveness-livez-get}

**Liveness**

Liveness probe: confirms the process is up. Deliberately does not check the database.

Operation id: `liveness_livez_get`

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for liveness. | `application/json` any |

## `GET /readyz` {#readiness-readyz-get}

**Readiness**

Readiness probe: 200 when the database is reachable, 503 otherwise.

Operation id: `readiness_readyz_get`

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for readiness. | `application/json` any |

## `GET /v1/admin/document-store` {#admin-document-store-v1-admin-document-store-get}

**Admin Document Store**

The super-admin console's view of ``GET /v1/ops/document-store`` (COA-5.9, #7085).

Operation id: `admin_document_store_v1_admin_document_store_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `limit` | query | integer | no | How many `tenantBuckets` to list (by tenant slug). At most 1,000; `tenantBucketsTruncated` says whether more exist. |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for admin document store. | `application/json` [`DocumentStoreStatus`](#schema-documentstorestatus) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/admin/document-store/test` {#admin-test-document-store-v1-admin-document-store-test-post}

**Admin Test Document Store**

The super-admin console's view of ``POST /v1/ops/document-store/test`` (COA-5.9, #7085).

Operation id: `admin_test_document_store_v1_admin_document_store_test_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Admin-Session` | header | string or null | no | Header parameter: X Admin Session. |
| `admin_session` | cookie | string or null | no | Cookie parameter: admin session. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for admin test document store. | `application/json` [`DocumentStoreProbeResult`](#schema-documentstoreproberesult) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/backups` {#ops-backups-v1-ops-backups-get}

**Ops Backups**

Latest backup status (from RC1-1.3 manifests). Platform-admin only.

Operation id: `ops_backups_v1_ops_backups_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops backups. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/dashboard` {#ops-dashboard-v1-ops-dashboard-get}

**Ops Dashboard**

A minimal, self-contained HTML ops dashboard. Platform-admin only.

The page server-renders the current metrics + backup status and polls ``/v1/ops/status`` for
live refresh. It is intentionally dependency-free (no external JS/CSS) so it works in locked-down
environments and never reaches out to a CDN.

Operation id: `ops_dashboard_v1_ops_dashboard_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops dashboard. | `text/html` string |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/document-migration` {#document-migration-status-v1-ops-document-migration-get}

**Document Migration Status**

The document migration's status (COA-5.8, #7084). Platform-admin only.

Whether this instance is running a step, the last run's report or error, the active
document store backend, and every checkpoint (per scope, step and source: the last key
finished, running totals and when the step completed).

Operation id: `document_migration_status_v1_ops_document_migration_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for document migration status. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/ops/document-migration` {#start-document-migration-v1-ops-document-migration-post}

**Start Document Migration**

Start one step of the document migration in the background (COA-5.8, #7084). Platform-admin only.

The copy step writes each database-held import source, frozen schema and export artifact to
the document store, verifies it and links it; the purge step (``purgeDbCopies``) re-verifies
each stored object and drops its database copy. Answers ``202`` with the run's status; follow
it with ``GET /v1/ops/document-migration``.

Operation id: `start_document_migration_v1_ops_document_migration_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for start document migration.

- `application/json` — [`DocumentMigrationRequest`](#schema-documentmigrationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 202 | Successful response for start document migration. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/document-store` {#ops-document-store-v1-ops-document-store-get}

**Ops Document Store**

The active document store: backend, settings, health and usage (COA-5.9, #7085). Platform-admin only.

Settings come from the server environment and are read-only here; credentials are never
returned — ``credentials`` only says whether static keys or boto3's default chain are used.

Operation id: `ops_document_store_v1_ops_document_store_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `limit` | query | integer | no | How many `tenantBuckets` to list (by tenant slug). At most 1,000; `tenantBucketsTruncated` says whether more exist. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops document store. | `application/json` [`DocumentStoreStatus`](#schema-documentstorestatus) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/ops/document-store/test` {#ops-test-document-store-v1-ops-document-store-test-post}

**Ops Test Document Store**

Test the document store: write, read back and delete a probe object (COA-5.9, #7085). Platform-admin only.

Answers ``200`` whether or not the test passed; ``ok`` and each step's ``error`` say what
failed.

Operation id: `ops_test_document_store_v1_ops_document_store_test_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops test document store. | `application/json` [`DocumentStoreProbeResult`](#schema-documentstoreproberesult) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/import-export` {#ops-import-export-v1-ops-import-export-get}

**Ops Import Export**

Import/export pipeline observability aggregates (IXH-6.6). Platform-admin only.

The full operator view of the three metric families — per-stage duration histograms
and byte totals, terminal job totals keyed by adapter/target × format × outcome, and
failure counters keyed by the IXH-6.4 taxonomy code — plus the complete documented
tag set every key is drawn from, and the export health summary (X8) — success and failure
rate, per-target failures, the whole-job p95 and the failure-rate alert. Aggregates are
in-process: per replica, reset on restart (same posture as ``/v1/ops/metrics``); durable
per-job timing evidence lives in each job's ``PHASE_TIMING`` events in the shared job store.

Operation id: `ops_import_export_v1_ops_import_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops import export. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/mcp-discovery-sweep` {#ops-mcp-discovery-sweep-v1-ops-mcp-discovery-sweep-get}

**Ops Mcp Discovery Sweep**

MCP re-discovery sweep health (MCAT-5.4, #3676). Platform-admin only.

Reports the sweep's settings (enabled, tick, cadence, concurrency cap, per-endpoint timeout),
the most recent run, the recent runs newest first, and their totals. Each run carries its timing
and tick counters (due, dispatched, coalesced, enqueue failures) and outcome counts — checked,
changed, unchanged, failed, in flight — aggregated from the discovery jobs that run created, so
they reconcile with the job log by construction. See :mod:`app.mcp_sweep_status`.

Operation id: `ops_mcp_discovery_sweep_v1_ops_mcp_discovery_sweep_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `limit` | query | integer | no | How many recent sweep runs to return, newest first. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops mcp discovery sweep. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/metrics` {#ops-metrics-v1-ops-metrics-get}

**Ops Metrics**

Operational request metrics (request rate, error rate, latency). Platform-admin only.

Operation id: `ops_metrics_v1_ops_metrics_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops metrics. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/status` {#ops-status-v1-ops-status-get}

**Ops Status**

Combined metrics + backup status — one call backing the dashboard. Platform-admin only.

Operation id: `ops_status_v1_ops_status_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops status. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/ops/toolchain` {#ops-toolchain-v1-ops-toolchain-get}

**Ops Toolchain**

Bundled toolchain packaging & availability + sandbox posture. Platform-admin only.

Reports every declared external tool (buf, tsp, smithy, drafter, amf, asyncapi, rover),
its pinned version, and whether its binary resolves in this runtime — the "format
unavailable" signal a missing tool produces (MFI-5.2). Each tool additionally carries
``required`` (is it a hard dependency of this runtime?) and ``gated_formats`` (which
registered import/export formats vanish without it), so the answer to "what did this
deployment lose?" is on the same response as "what is missing?" (FMT-1.3). With
``?verify=true`` each *available* tool is additionally invoked with its version probe to
confirm it actually runs. The ``sandbox`` block reports the active security/resource posture
(MFI-5.3) every tool subprocess runs under (no-network default, rlimit clamps, input/output
caps).

Operation id: `ops_toolchain_v1_ops_toolchain_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `verify` | query | boolean | no | Also invoke each available tool's version probe to confirm it runs (slower — spawns one subprocess per available tool). |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for ops toolchain. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `DocumentMigrationRequest` {#schema-documentmigrationrequest}

One step of the document migration to start.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `purgeDbCopies` | boolean | no | Run the purge step (drop database copies whose stored object verifies) instead of the copy step. |
| `dryRun` | boolean | no | Report what the step would do; write nothing. |
| `tenantId` | string or null | no | Only this tenant (UUID); every tenant when omitted. |
| `sources` | array of enum `"adapter_source"`, `"import_snapshot"`, `"frozen_schema"`, `"export_artifact"` or null | no | Only these sources; every source when omitted. |
| `rate` | number | no | Most rows per second; 0 for no limit. |
| `batchSize` | integer | no | Rows per page and checkpoint. |
| `workers` | integer | no | Rows processed in parallel. |

### `DocumentStoreProbeResult` {#schema-documentstoreproberesult}

The outcome of writing, reading back and deleting one probe object.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `ok` | boolean | yes | True when every step succeeded. |
| `backend` | string | yes | Backend. |
| `checkedAt` | number | yes | When the test finished (epoch seconds). |
| `durationMs` | number | yes | Duration Ms. |
| `steps` | array of `DocumentStoreProbeStep` | yes | Steps. |

### `DocumentStoreStatus` {#schema-documentstorestatus}

The active document store: settings (never credentials), health and usage.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `backend` | string | yes | The backend the server runs on: db, s3 or filesystem. |
| `configuredBackend` | string | yes | The backend APIOME_DOCUMENT_STORE names. |
| `fallback` | boolean | yes | True when startup fell back to db (APIOME_DOCUMENT_STORE_FALLBACK=db). |
| `fallbackReason` | string or null | no | Why the configured backend was not usable (redacted). |
| `backends` | array of string | yes | Every backend this server supports. |
| `bucket` | string or null | no | s3: the bucket. |
| `prefix` | string | yes | The folder every object key starts with ('' for none). |
| `region` | string or null | no | s3: the signing region. |
| `endpointUrl` | string or null | no | s3: the service URL; null for AWS. |
| `addressingStyle` | string or null | no | s3: auto, path or virtual. |
| `path` | string or null | no | filesystem: the storage directory. |
| `encryption` | string or null | no | s3: none, sse-s3 or sse-kms. |
| `kmsKeyId` | string or null | no | s3 with sse-kms: the key; null for the bucket default. |
| `credentials` | enum `"static"`, `"default-chain"` or null | no | s3: 'static' (keys in the environment) or 'default-chain' (boto3's chain / IAM role). |
| `presignTtlSeconds` | integer or null | no | s3: default lifetime of a download link. |
| `maxObjectBytes` | integer or null | no | db: the largest object accepted. |
| `health` | `DocumentStoreHealth` | yes | Health. |
| `usage` | `DocumentStoreUsage` or null | no | Null when the document index cannot be read. |
| `tenantBucketsAllowed` | boolean | no | Whether tenants may use their own bucket (APIOME_DOCUMENT_STORE_ALLOW_TENANT_BUCKETS). |
| `tenantBuckets` | array of `DocumentStoreTenantBucket` | no | Tenants that have configured their own bucket, with its health. |
| `tenantBucketsTruncated` | boolean | no | True when more tenants have a bucket than `limit` listed. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
