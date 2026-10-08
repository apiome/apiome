---
title: "Ops"
description: "REST endpoints tagged ops: 9 operations."
sidebar_position: 44
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `ops` · 9 operations

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

The HTTP status reflects readiness only: an enforcing deployment cannot serve at all with a
required tool missing (startup refuses), and a non-enforcing one is degraded deliberately.

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

## `GET /v1/ops/import-export` {#ops-import-export-v1-ops-import-export-get}

**Ops Import Export**

Import/export pipeline observability aggregates (IXH-6.6). Platform-admin only.

The full operator view of the three metric families — per-stage duration histograms
and byte totals, terminal job totals keyed by adapter/target × format × outcome, and
failure counters keyed by the IXH-6.4 taxonomy code — plus the complete documented
tag set every key is drawn from. Aggregates are in-process: per replica, reset on
restart (same posture as ``/v1/ops/metrics``); durable per-job timing evidence lives
in each job's ``PHASE_TIMING`` events in the shared job store.

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

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
