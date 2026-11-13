---
title: "Internal MCP export"
description: "REST endpoints tagged internal-mcp-export: 2 operations."
sidebar_position: 46
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.548.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `internal-mcp-export` · 2 operations

## `POST /v1/internal/mcp/export/run` {#mcp-export-run-v1-internal-mcp-export-run-post}

**Run an export for the MCP `version.export` tool**

Internal (`X-Internal-Service-Token`). Starts an export job for any registered `target` (the pipeline of `POST /v1/export/{tenant}/jobs`) and waits up to `waitSeconds`; or, with `jobId`, collects a job a previous call left running. A conversion that loses fidelity (tier other than `lossless`) without `allowLossy` answers `state: blocked` with the report and the canonical `advisory` and emits nothing. A completed job answers with the fidelity envelope (including the structured `LossinessReport`), the guard and the files — inline up to `APIOME_MCP_EXPORT_INLINE_MAX_BYTES`, otherwise with `downloadPath`. `400` / `422` for an unknown target or invalid options; `429` when the tenant's export slots are full; `404` for an unknown job.

Operation id: `mcp_export_run_v1_internal_mcp_export_run_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Request body** (required)

Request body for run an export for the mcp `version.export` tool.

- `application/json` — [`McpExportRunRequest`](#schema-mcpexportrunrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for run an export for the mcp `version.export` tool. | `application/json` [`McpExportRunResponse`](#schema-mcpexportrunresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/internal/mcp/export/targets` {#mcp-export-targets-v1-internal-mcp-export-targets-post}

**Export targets for the MCP `export.targets` tool**

Internal (`X-Internal-Service-Token`). The same answer as `GET /v1/export/{tenant}/targets` for the given tenant: every registered target with its per-source fidelity tier.

Operation id: `mcp_export_targets_v1_internal_mcp_export_targets_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `X-Internal-Service-Token` | header | string or null | no | Header parameter: X Internal Service Token. |

**Request body** (required)

Request body for export targets for the mcp `export.targets` tool.

- `application/json` — [`McpExportTargetsRequest`](#schema-mcpexporttargetsrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export targets for the mcp `export.targets` tool. | `application/json` [`ExportTargetsResponse`](#schema-exporttargetsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ExportTargetsResponse` {#schema-exporttargetsresponse}

The per-target fidelity list for one source revision (MFX-2.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the fidelity was computed for. |
| `version` | string or null | no | The version selector as requested (label, UUID, or null). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label (e.g. ``1.0.0``). |
| `targets` | array of `ExportTargetFidelity` | no | Every registered target with its per-source fidelity, sorted by target key. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `McpExportRunRequest` {#schema-mcpexportrunrequest}

``version.export``: start an export (``target``) or collect one (``jobId``).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenantId` | string | yes | The MCP key's tenant (trusted: internal route). |
| `artifact` | string or null | no | The artifact id (required to start a job). |
| `version` | string or null | no | Revision id or label; the latest when omitted. |
| `target` | string or null | no | Any registered target key (`export.targets`). |
| `options` | object or null | no | The target's emit options (MFX-1.4). |
| `confirm` | boolean | no | Proceed with a severe conversion (MFX-3.3). |
| `allowLossy` | boolean | no | Emit even when the conversion loses fidelity (MFX-40.2; the CLI `--force`). Without it a lossy conversion answers `blocked` and emits nothing. |
| `jobId` | string or null | no | Collect a job a previous call left running, instead of starting one. |
| `waitSeconds` | integer | no | How long to wait for the job before answering `running`. |

### `McpExportRunResponse` {#schema-mcpexportrunresponse}

What ``version.export`` answers.

Attributes:
    job_id: The export job; ``None`` when ``blocked`` (no job was started).
    state: ``blocked`` (a lossy conversion without ``allowLossy``: nothing emitted), ``queued`` /
        ``running`` (collect it again with ``jobId``), ``completed``, ``failed`` or ``canceled``.
    advisory: The canonical fidelity advisory (MFX-2.4 ``ExportAdvisory.message``) — word for word
        what the UI, browse and the CLI show; ``None`` until the fidelity is known.
    fidelity: The full fidelity envelope of a one-target export: tier, the structured
        ``LossinessReport`` (``report``), the advisory.
    guard: The transcoding guard (MFX-3.3): verdict, whether it needs ``confirm``.
    files: The emitted files; each carries ``content`` when ``content_inline``.
    download_path: The REST download of the whole artifact, for files too large to inline.
    error: The structured failure of a failed job.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `jobId` | string or null | no | Job ID. |
| `state` | enum `"blocked"`, `"queued"`, `"running"`, `"completed"`, `"failed"`, `"canceled"` | yes | State. |
| `advisory` | string or null | no | Advisory. |
| `artifact` | string or null | no | Artifact. |
| `target` | string or null | no | Target. |
| `versionRecordId` | string or null | no | Version Record ID. |
| `versionLabel` | string or null | no | Version Label. |
| `fidelity` | object or null | no | Fidelity. |
| `guard` | object or null | no | Guard. |
| `validation` | object or null | no | Validation. |
| `delivery` | object or null | no | Delivery. |
| `mediaType` | string or null | no | Media Type. |
| `files` | array of `McpExportFile` | no | Files. |
| `contentInline` | boolean | no | Content Inline. |
| `downloadPath` | string or null | no | Download Path. |
| `error` | object or null | no | Error. |

### `McpExportTargetsRequest` {#schema-mcpexporttargetsrequest}

``export.targets``: which source's targets.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `tenantId` | string | yes | The MCP key's tenant (trusted: internal route). |
| `artifact` | string | yes | The artifact (project or catalog item) id. |
| `version` | string or null | no | Revision id or label; the latest when omitted. |
