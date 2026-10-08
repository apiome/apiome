---
title: "Export"
description: "REST endpoints tagged export: 11 operations."
sidebar_position: 21
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `export` · 11 operations

## `GET /v1/export/{tenant_slug}/capability-registry` {#get-capability-registry-v1-export-tenant-slug-capability-registry-get}

**Get the destination capability & documentation registry**

Return the versioned destination capability registry (EFP-1.2): one reviewed capability entry per registered export destination (label, availability state, and host-allowlisted destination-format documentation with a safe fallback) plus the reviewed explanation for every projection reason code. This is static reference data — the same for every source — that lets the export UI render honest loss reasons and authoritative documentation links from reviewed data instead of hard-coding URLs in components.

Operation id: `get_capability_registry_v1_export__tenant_slug__capability_registry_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the destination capability & documentation registry. | `application/json` [`CapabilityRegistrySnapshot`](#schema-capabilityregistrysnapshot) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/dispatch` {#dispatch-export-document-v1-export-tenant-slug-dispatch-post}

**Dispatch an export: emit one target and attach its fidelity report**

The one-shot transcode (MFX-3.2): load the source artifact/version, resolve the target emitter, run it, and return the emitted document **together with** its full fidelity envelope (report + advisory + summary). The synchronous twin of submitting an export job and polling it — for small artifacts and the ``apiome export`` CLI; large or toolchain-backed exports should use ``POST …/jobs``. ``dry_run: true`` stops after the fidelity report (no artifact), the same shape ``POST …/preview`` returns.

Operation id: `dispatch_export_document_v1_export__tenant_slug__dispatch_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for dispatch an export: emit one target and attach its fidelity report.

- `application/json` — [`ExportDispatchRequest`](#schema-exportdispatchrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for dispatch an export: emit one target and attach its fidelity report. | `application/json` [`ExportDispatchResponse`](#schema-exportdispatchresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/document` {#emit-export-document-v1-export-tenant-slug-document-post}

**Emit the export document for one target**

Emit the source artifact/version to one ``target`` through the Emitter SPI and return the document itself — JSON by default, YAML when ``Accept: application/yaml`` is sent. This is the emit counterpart to ``/preview`` (which predicts the loss without emitting); the ``apiome export <target>`` CLI pairs the two to write the artifact and surface its fidelity. Gives non-OpenAPI targets (AsyncAPI) a byte source the OpenAPI-only browse reconstruction cannot supply.

Operation id: `emit_export_document_v1_export__tenant_slug__document_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `accept` | header | string or null | no | Requested response content type (``Accept`` header). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for emit the export document for one target.

- `application/json` — [`ExportDocumentRequest`](#schema-exportdocumentrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for emit the export document for one target. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/preview` {#preview-export-fidelity-v1-export-tenant-slug-preview-post}

**Preview export fidelity for one target**

Compute the full fidelity report for exporting the given source artifact/version to one target — the per-construct LossinessReport, the user-facing advisory (MFX-2.4), and the tier summary — **without producing the artifact**. Backs the export dialog's detailed fidelity panel; the same envelope is embedded in an export job result.

Operation id: `preview_export_fidelity_v1_export__tenant_slug__preview_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for preview export fidelity for one target.

- `application/json` — [`ExportPreviewRequest`](#schema-exportpreviewrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview export fidelity for one target. | `application/json` [`ExportPreviewResponse`](#schema-exportpreviewresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/preview-manifest` {#preview-export-manifest-v1-export-tenant-slug-preview-manifest-post}

**Structural manifest of the emitted artifact: entities, fidelity, locations**

Describe the emitted artifact **structurally** (IXH-4.1): every canonical entity (services → operations, channels, types → fields) with its stable canonical key, its per-entity fidelity status and reason from the shared CPDO-1.3 taxonomy, and — for entities the artifact carries — its location in the bundle (file, 1-based line in the download-serialized text, and a JSON Pointer where derivable). Entities the source has but the artifact does not carry are listed with their drop reason, never hidden. The emit runs read-only in a temporary buffer (no artifact, no job row, no field-identity persistence — the verify route's discipline) and a severe conversion is described, not blocked. Deterministic: identical (revision, target, options) yield an identical ``manifest_hash``; entities are cursor-paginated (codec shared with the import preview manifest) and the full manifest is cached per (tenant, revision, target, options) so paging re-emits nothing. Backs the Export Studio's structural artifact explorer with two-way entity ↔ code selection.

Operation id: `preview_export_manifest_v1_export__tenant_slug__preview_manifest_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for structural manifest of the emitted artifact: entities, fidelity, locations.

- `application/json` — [`ExportPreviewManifestRequest`](#schema-exportpreviewmanifestrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for structural manifest of the emitted artifact: entities, fidelity, locations. | `application/json` [`ExportPreviewManifestResponse`](#schema-exportpreviewmanifestresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/projection-evidence` {#get-projection-evidence-v1-export-tenant-slug-projection-evidence-post}

**Page through projection evidence for one configured export**

Return one bounded, cursor-paginated page of source→target projection evidence (EFP-2.1 / EFP-3.2) for the given source revision, target, and options — the traceable rows behind the projection summary that preview, verify, dispatch, and job results embed. The same inputs resolve to the same snapshot hash on every surface. Tenant-scoped. Source-native evidence is **always** redacted (EFP-3.2); `redact_source` is accepted for compatibility and ignored. How to interpret the statuses, reason categories, and destination-documentation links is documented in the *Understand export fidelity* guide, `apiome-docs/docs/ship/export-fidelity.md` (EFP-3.3).

Operation id: `get_projection_evidence_v1_export__tenant_slug__projection_evidence_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for page through projection evidence for one configured export.

- `application/json` — [`ExportProjectionEvidenceRequest`](#schema-exportprojectionevidencerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for page through projection evidence for one configured export. | `application/json` [`ExportProjectionEvidenceResponse`](#schema-exportprojectionevidenceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/projection-metrics` {#record-projection-metric-v1-export-tenant-slug-projection-metrics-post}

**Record a privacy-safe projection metric**

Increment an in-process counter and emit a structured ``export.projection`` log line for UI/ops telemetry (EFP-3.2). Payload is a strict whitelist of kinds and optional integer/reason-category fields — never construct labels or source content.

Operation id: `record_projection_metric_v1_export__tenant_slug__projection_metrics_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record a privacy-safe projection metric.

- `application/json` — [`ExportProjectionMetricRequest`](#schema-exportprojectionmetricrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record a privacy-safe projection metric. | `application/json` [`ExportProjectionMetricResponse`](#schema-exportprojectionmetricresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/roundtrip` {#roundtrip-export-v1-export-tenant-slug-roundtrip-post}

**On-demand round-trip comparison: emit → re-import → diff → reconcile with fidelity**

The Export Studio's round-trip evidence action (IXH-4.4): emit the source revision to ``target`` in a **temporary buffer**, re-import the emitted artifact through the matching import adapter, diff the re-imported canonical model against the source with ``canonical_diff``, and reconcile every difference against the fidelity report — the same loop the IXH-1.7 conformance matrix runs in CI, applied to the user's own document on demand. Differences the report explains come back ``matched`` (expected loss); ``unexplained`` differences and ``overclaims`` flag a fidelity bug worth reporting, with reproduction provenance (fingerprints + emitter/registry/apiome versions) inline. When no import adapter can re-ingest the emit format the comparison is **skipped with the matrix's own explanation** (``status: unsupported``), never silently. The run is explicit and bounded — one emit, one re-import, nothing persisted (no artifact, no job row, no field-identity rows) — and is rate-limited by the global per-tenant middleware. A severe conversion (MFX-3.3) is measured, not blocked: the round-trip exists precisely to show what a lossy conversion does.

Operation id: `roundtrip_export_v1_export__tenant_slug__roundtrip_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for on-demand round-trip comparison: emit → re-import → diff → reconcile with fidelity.

- `application/json` — [`ExportRoundtripRequest`](#schema-exportroundtriprequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for on-demand round-trip comparison: emit → re-import → diff → reconcile with fidelity. | `application/json` [`ExportRoundtripResponse`](#schema-exportroundtripresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/export/{tenant_slug}/targets` {#list-export-targets-v1-export-tenant-slug-targets-get}

**List export targets with per-source fidelity**

For the given source artifact/version, enumerate every registered export target (descriptor + capability profile + options) with a cheap per-target fidelity badge (tier + preserved-%), computed from the prediction engine without emitting an artifact. Drives the export dialog's card badges (MFX-6.1) and the version pre-summary (MFX-6.5).

Operation id: `list_export_targets_v1_export__tenant_slug__targets_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `artifact` | query | string | yes | The artifact (project) id to export. |
| `version` | query | string or null | no | Revision UUID, version label (``1.0.0``), or omitted for the latest revision. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list export targets with per-source fidelity. | `application/json` [`ExportTargetsResponse`](#schema-exporttargetsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/export/{tenant_slug}/verify` {#verify-export-v1-export-tenant-slug-verify-post}

**One-call pre-generation verify: fidelity + validation + lint + verdict**

The Verify workbench's dry run (MFX-42.5, backing MFX-42.1): emit the source artifact/version to one ``target`` in a **temporary buffer**, then run fidelity (MFX-2.5) + emitted-output validation (MFX-5.1/5.3) + emitted-artifact lint (MFX-5.2) over it, and return all three lenses plus an overall go/no-go **verdict** — **without persisting an artifact or a job row**. The emit is read-only (no field-identity persistence), so a verify never mutates tenant state. The emitted artifact rides back inline under a size cap (``include_content``) for the Monaco viewer (MFX-43.x). A severe conversion (MFX-3.3) is **verified, not blocked** — its verdict reports the loss so the user can decide. Rate-limited by the global per-tenant middleware (it does real emit work). Lint (MFX-5.2) is not yet implemented, so ``lint`` is currently ``null``. Typical p50 for the five MVP emitters (OpenAPI, AsyncAPI, GraphQL, gRPC/Protobuf, Avro) is dominated by the single emit + re-parse and runs in the tens of milliseconds for pure-Python validators; protobuf/AsyncAPI add their toolchain's startup when installed.

Operation id: `verify_export_v1_export__tenant_slug__verify_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for one-call pre-generation verify: fidelity + validation + lint + verdict.

- `application/json` — [`ExportVerifyRequest`](#schema-exportverifyrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for one-call pre-generation verify: fidelity + validation + lint + verdict. | `application/json` [`ExportVerifyResponse`](#schema-exportverifyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/export/preflight` {#preflight-export-v1-tenants-tenant-slug-export-preflight-post}

**Pre-flight an export: source lint + target-readiness ranking (no job, no artifact)**

Rank every export target for one source revision **before** a job exists (IXH-2.4). Lints the *source* under the tenant's resolved style guide — the check the export path otherwise only makes against the emitted artifact, and only after the job — then, per target, returns the projected fidelity envelope (tier, preserved %, DROP/APPROX/SYNTH counts from the same prediction engine a job embeds in its result), the capability verdict (which construct classes this source uses vs. which the target declares it can carry), the tenant export quality-policy verdict (IXH-2.3) with any honoured waiver, and a composite readiness score with a one-line rationale.

Targets are returned best-readiness first: ready → caution → blocked → unavailable, then by descending score and target key. A target the policy **blocks** is ranked and returned with its reason, never hidden. Nothing is emitted and nothing is persisted — no export job, no artifact, no field-identity rows. The ranking is deterministic for a fixed source revision, style guide, and policy; ``ranking_fingerprint`` lets a caller assert that without diffing the body. This is the pre-job counterpart to ``POST …/export/verify``.

Operation id: `preflight_export_v1_tenants__tenant_slug__export_preflight_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for pre-flight an export: source lint + target-readiness ranking (no job, no artifact).

- `application/json` — [`ExportPreflightRequest`](#schema-exportpreflightrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for pre-flight an export: source lint + target-readiness ranking (no job, no artifact). | `application/json` [`ExportPreflightReport`](#schema-exportpreflightreport) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CapabilityRegistrySnapshot` {#schema-capabilityregistrysnapshot}

The full, deterministic registry view exposed to the REST contract + UI (EFP-1.2).

Carries the :attr:`version`, the reviewed :class:`ReasonExplanation` for every reason
code (the drawer's honest wording), and a :class:`DestinationCapability` for every
runtime-available emitter, all in a stable order. Because it is derived from the
static registry and the (deterministic) emitter registry, identical inputs yield an
identical snapshot — safe to cache and to mirror in a TypeScript contract.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | string | yes | The registry contract version (``REGISTRY_VERSION``). |
| `review_date` | string | yes | When the registry links/explanations were last reviewed. |
| `reason_codes` | array of string | yes | The canonical set of valid reason-code strings, sorted. Contract tests reject any reason code outside this set. |
| `reasons` | array of `ReasonExplanation` | yes | The reviewed explanation for each reason code, in taxonomy order. |
| `destinations` | array of `DestinationCapability` | yes | One capability entry per registered destination, in key order. |

### `ExportDispatchRequest` {#schema-exportdispatchrequest}

A dispatch request: source revision + chosen target + options + dry-run flag (MFX-3.2).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to export. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. |
| `dry_run` | boolean | no | When true, stop after the fidelity report: no artifact is emitted. |
| `confirm` | boolean | no | When true, proceed with a **severe** conversion (MFX-3.3) the transcoding guard would otherwise block with 409. Ignored for non-severe conversions and dry-runs. |
| `min_severity` | `LossinessSeverity` | no | Lowest loss severity that raises the advisory (MFX-2.4); does not affect the report or counts. |

### `ExportDispatchResponse` {#schema-exportdispatchresponse}

The dispatch result: resolved coordinates + fidelity envelope + emitted artifact (MFX-3.2).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the dispatch exported. |
| `version` | string or null | no | The version selector as requested (label, UUID, or null). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label (e.g. ``1.0.0``). |
| `target` | string | yes | The resolved target format key (e.g. ``openapi-3.1``). |
| `dry_run` | boolean | yes | True when the dispatch stopped after the fidelity report. |
| `fidelity` | `ExportFidelity` | yes | The full fidelity envelope (target + tier + report + advisory). |
| `guard` | `TranscodeGuard` | yes | The pre-flight transcoding guard (MFX-3.3): the conversion band and why. A severe conversion only reaches a real (non-dry-run) dispatch when ``confirm`` was set. |
| `files` | array of `ExportDispatchFile` | no | The emitted files (inline); empty for a dry-run. |
| `media_type` | string or null | no | The bundle's primary media type; null for a dry-run. |
| `delivery` | `DeliveryGateReport` or null | no | The delivery gate decision for this dispatch (IXH-2.5) with its named reasons and the signed attestation for the returned artifact. Null for a dry-run (nothing is delivered). |

### `ExportDocumentRequest` {#schema-exportdocumentrequest}

An emit request: source revision + chosen target + per-emit options (MFX-11.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to export. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``asyncapi``) or format key (``asyncapi-3``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. |

### `ExportPreflightReport` {#schema-exportpreflightreport}

The full export pre-flight: one source lint verdict plus every target, ranked.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the pre-flight ran for. |
| `version` | string or null | no | The version selector as requested (label, UUID, or null). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label (e.g. ``1.0.0``). |
| `paradigm` | string or null | no | The source model's canonical paradigm (``rest``, ``event``…). |
| `format` | string or null | no | The source model's format key (``openapi-3.1``). |
| `lint` | `ImportPreflightLint` | yes | The source's lint verdict under the resolved style guide — the same engine and scoring formula an import pre-flight reports, run over the reconstructed source model rather than a candidate document. |
| `style_guide` | `ImportPreflightStyleGuide` or null | no | The style guide that governed the lint, when one resolved. |
| `capability_demand` | array of string | no | The capability axes this source uses — the yardstick every target's capability verdict is measured against. |
| `targets` | array of `ExportPreflightTarget` | no | Every ranked target, best readiness first. Blocked and unavailable targets are included (ranked last), never hidden. |
| `ranking_fingerprint` | string | yes | Stable hash over the ranked (target, readiness, band) triples. Identical for two pre-flights of the same revision under the same guide and policy. |

### `ExportPreflightRequest` {#schema-exportpreflightrequest}

A pre-flight request: the source revision, optionally narrowed to some targets.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to export. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `targets` | array of string or null | no | Restrict the ranking to these target keys or format keys (``openapi`` / ``openapi-3.1``); null ranks every registered target. Unknown entries are ignored — a pre-flight reports what it can rank rather than failing on a stale client's target list. |
| `include_findings` | boolean | no | When false, the source lint verdict is returned without its ranked finding list (score, grade, and tallies are always present). Lets a target-grid caller skip the findings payload it does not render. |
| `include_conformance` | boolean | no | When true, run the IXH-5.6 instance-conformance check per ranked target: source-valid instances (IXH-5.2) are validated against each target's actually-emitted schema, the per-target verdict is attached beside the fidelity envelope, and a ``ready`` target whose emitted schema rejected instances is demoted to ``caution``. Off by default because it emits every ranked target for real — heavier than the prediction-only pre-flight. |

### `ExportPreviewManifestRequest` {#schema-exportpreviewmanifestrequest}

The preview-manifest request: source coordinates + target + options + page window.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to describe. |
| `version` | string or null | no | A revision UUID, a version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `options` | object or null | no | Per-target emit options; null/empty applies the target defaults. Folded (normalized) into the manifest hash, so different options are a different snapshot. |
| `cursor` | string or null | no | Opaque entity-page cursor from a previous response; null for the first page. |
| `page_size` | integer | no | Maximum entities per page; clamped to 1000. |

### `ExportPreviewManifestResponse` {#schema-exportpreviewmanifestresponse}

The preview-manifest endpoint's response (IXH-4.1).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the manifest describes. |
| `version` | string or null | no | The requested version selector, echoed. |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label, when it has one. |
| `manifest` | `ExportPreviewManifest` | yes | The requested manifest page. |

### `ExportPreviewRequest` {#schema-exportpreviewrequest}

A dry-run fidelity preview request: source revision + chosen target (MFX-2.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to export. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. Folded (normalized) into the projection snapshot hash (EFP-2.1), so a preview, a verify, and a dispatch of the same source, target, and options reference the same snapshot. |
| `min_severity` | `LossinessSeverity` | no | Lowest loss severity that raises the advisory (MFX-2.4); does not affect the report or counts. |

### `ExportPreviewResponse` {#schema-exportpreviewresponse}

The dry-run fidelity preview: the full envelope + the resolved source coordinates (MFX-2.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the preview was computed for. |
| `version` | string or null | no | The version selector as requested (label, UUID, or null). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label (e.g. ``1.0.0``). |
| `fidelity` | `ExportFidelity` | yes | The full fidelity envelope (target + tier + report + advisory), no artifact. |
| `guard` | `TranscodeGuard` | yes | The pre-flight transcoding guard (MFX-3.3): the conversion band (clean / lossy / near-empty / severe), whether it needs an explicit confirmation, and why. Lets the UI/CLI warn (near-empty) or prompt for confirmation (severe) before dispatching the export. |

### `ExportProjectionEvidenceRequest` {#schema-exportprojectionevidencerequest}

A bounded projection-evidence page request for one configured export (EFP-2.1).

Identifies the same ``(source revision, target, options)`` triple a preview / verify /
dispatch describes, plus the cursor/limit window into the manifest's evidence rows.
Matching inputs resolve to the same snapshot (``manifest_hash``) every surface shares.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to export. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. Folded (normalized) into the snapshot hash — different options are a different snapshot. |
| `cursor` | string or null | no | Opaque cursor from a previous page, or null to start at the beginning. A malformed cursor is rejected with 422. |
| `limit` | integer | no | Maximum evidence rows per page; clamped to 500. |
| `redact_source` | boolean | no | Ignored (EFP-3.2). Source-native evidence is always redacted; kept for request-body compatibility with earlier callers. Response ``redacted`` is always true. |

### `ExportProjectionEvidenceResponse` {#schema-exportprojectionevidenceresponse}

One bounded, cursor-paginated page of projection evidence (EFP-2.1).

The authenticated evidence surface behind the preview/verify summaries: the resolved
source coordinates, the snapshot provenance (:class:`~app.export_projection.ManifestTarget`
carries the emitter/registry versions and destination documentation), the bounded
:class:`~app.export_projection.ProjectionManifestSummary`, and one
:class:`~app.export_projection.ProjectionEvidencePage` of outcome edges + their nodes.
Deterministic: the same ``(revision, target, options)`` yields the same snapshot hash a
preview / verify / dispatch / job result references, and paging the same snapshot twice
yields identical pages.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the evidence describes. |
| `version` | string or null | no | The version selector as requested (label, UUID, or null). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label (e.g. ``1.0.0``). |
| `summary` | `ProjectionManifestSummary` | yes | The bounded snapshot summary — hash, target/version provenance (emitter/registry versions), and status/reason counts. |
| `page` | `ProjectionEvidencePage` | yes | This page of outcome edges + the nodes they reference, with the opaque cursor for the next page (null on the last page). |
| `redacted` | boolean | yes | Always true (EFP-3.2): source-native evidence values are redacted. |

### `ExportProjectionMetricRequest` {#schema-exportprojectionmetricrequest}

Whitelist-only client/server projection metric event (EFP-3.2).

Rejects unknown fields. Only :data:`~app.projection_telemetry.ALLOWED_METRIC_KINDS`
are accepted; reason categories are optional and themselves whitelisted.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | enum `"preview_failure"`, `"stale_acknowledgement"`, `"evidence_page"`, `"aggregation_used"`, `"documentation_link_available"`, `"documentation_link_missing"` | yes | Privacy-safe metric kind (whitelist). |
| `page_total` | integer or null | no | Optional integer page/evidence total (no labels). |
| `reason_category` | string or null | no | Optional controlled failure category (whitelist only). |

### `ExportProjectionMetricResponse` {#schema-exportprojectionmetricresponse}

Acknowledgement that a privacy-safe metric was recorded.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `recorded` | boolean | no | Recorded. |
| `kind` | string | yes | Kind. |

### `ExportRoundtripRequest` {#schema-exportroundtriprequest}

A round-trip comparison request: source revision + chosen target + options.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to round-trip. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. |
| `min_severity` | `LossinessSeverity` | no | Lowest loss severity that raises the advisory (MFX-2.4); does not affect the round-trip verdict, the report, or the reconciliation. |

### `ExportRoundtripResponse` {#schema-exportroundtripresponse}

The round-trip comparison result the Export Studio renders (IXH-4.4).

``status`` speaks the IXH-1.7 matrix's vocabulary so a Studio run over a corpus
entry reconciles with the published matrix cell:

* ``pass`` — every empirical difference is explained by the fidelity report and
  nothing over-claims preservation;
* ``fail`` — at least one unexplained difference or over-claim (a fidelity bug
  worth reporting), or the emitted artifact could not be re-imported at all;
* ``unsupported`` — the comparison was **skipped with an explanation** (no import
  adapter can re-ingest the emit format, or the emitter is unavailable here).

The three difference groups are exactly the reconciliation's: ``matched``
(explained by the report — expected loss), ``unexplained`` (the report does not
account for them), and ``overclaims`` (the report claimed preservation reality
contradicts). The provenance fields (`emitter_version` / `apiome_version` /
`registry_version` / fingerprints) give an unexplained difference's issue report
its reproduction coordinates without shipping any source bytes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the round-trip ran for. |
| `version` | string or null | no | The version selector as requested (label, UUID, or null). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label (e.g. ``1.0.0``). |
| `target` | string | yes | The resolved target format key (e.g. ``openapi-3.1``). |
| `emit_key` | string | yes | The resolved emitter registry key (e.g. ``openapi``). |
| `adapter_key` | string or null | no | The import-adapter registry key that re-imported the emitted artifact; null when the comparison was skipped (``status: unsupported``). |
| `status` | `MatrixCellStatus` | yes | The round-trip verdict (``pass`` / ``fail`` / ``unsupported``), in the IXH-1.7 matrix's vocabulary. |
| `reason` | string or null | no | Human-readable explanation for a non-``pass`` status: why the comparison was skipped, what failed to re-import, or which differences are unaccounted for. |
| `diff_count` | integer | no | Total empirical differences between source and re-import. |
| `matched_count` | integer | no | Differences the fidelity report explains (expected loss). |
| `matched` | array of `MatchedDiff` | no | Each explained difference paired with the fidelity finding that explains it. |
| `unexplained` | array of `CanonicalDiffEntry` | no | Differences no fidelity finding accounts for — a fidelity bug the user should report. |
| `overclaims` | array of `LossItem` | no | ``OK`` findings whose construct empirically changed or vanished — the report over-claimed preservation. |
| `loss_drop` | integer | no | ``drop`` findings in the fidelity report. |
| `loss_approx` | integer | no | ``approx`` findings in the fidelity report. |
| `loss_synth` | integer | no | ``synth`` findings in the fidelity report. |
| `loss_ok` | integer | no | ``ok`` findings in the fidelity report. |
| `source_fingerprint` | string | yes | Deterministic fingerprint of the source canonical model (reproduction coordinate for issue reports; carries no source content). |
| `reimported_fingerprint` | string or null | no | Fingerprint of the re-imported canonical model; equals ``source_fingerprint`` for a byte-honest round-trip. Null when the loop did not close. |
| `emitter_version` | string | yes | The emitter implementation version. |
| `apiome_version` | string | yes | The apiome-rest package version that ran the loop. |
| `registry_version` | string | yes | The capability-registry snapshot version. |

### `ExportTargetsResponse` {#schema-exporttargetsresponse}

The per-target fidelity list for one source revision (MFX-2.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the fidelity was computed for. |
| `version` | string or null | no | The version selector as requested (label, UUID, or null). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label (e.g. ``1.0.0``). |
| `targets` | array of `ExportTargetFidelity` | no | Every registered target with its per-source fidelity, sorted by target key. |

### `ExportVerifyRequest` {#schema-exportverifyrequest}

A one-call verify request: source revision + chosen target + options (MFX-42.5).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id to export. |
| `version` | string or null | no | Revision UUID, version label (``1.0.0``), or null for the latest revision. |
| `target` | string | yes | Target emitter key (``openapi``) or format key (``openapi-3.1``). |
| `options` | object or null | no | Per-target emit options (MFX-1.4); null or empty applies the target defaults. |
| `include_content` | boolean | no | When true, return the emitted artifact inline (under the size cap) so the Monaco viewer (MFX-43.x) can render the preview from this same call; the bytes are still discarded server-side. |
| `min_severity` | `LossinessSeverity` | no | Lowest loss severity that raises the advisory (MFX-2.4); does not affect the report or counts. |

### `ExportVerifyResponse` {#schema-exportverifyresponse}

The one-call verify result: fidelity + validation + lint + verdict (MFX-42.5).

Everything the Studio's Verify workbench (MFX-42.1) needs in one round-trip, computed by
emitting the artifact to a **temporary buffer** — no artifact and no job row are persisted.
The emit is read-only (no field-identity persistence), so a verify never mutates tenant state.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `artifact` | string | yes | The artifact (project) id the verify was computed for. |
| `version` | string or null | no | The version selector as requested (label, UUID, or null). |
| `version_record_id` | string | yes | The resolved revision (``versions.id``). |
| `version_label` | string or null | no | The resolved revision's version label (e.g. ``1.0.0``). |
| `target` | string | yes | The resolved target format key (e.g. ``openapi-3.1``). |
| `fidelity` | `ExportFidelity` | yes | The full fidelity envelope (target + tier + per-construct report + advisory). |
| `guard` | `TranscodeGuard` | yes | The pre-flight transcoding guard (MFX-3.3): the conversion band and why. |
| `validation` | `EmittedValidationReport` | yes | The emitted-output validation gate + structured report (MFX-5.1/5.3). |
| `lint` | `EmittedArtifactLint` or null | no | The emitted-artifact lint report (MFX-5.2); null until MFX-5.2 lands, which the Verify workbench renders as the lint lens's empty state. |
| `verdict` | `ExportVerifyVerdict` | yes | The overall go/no-go band the Generate gate reads (clean / lossy / invalid). |
| `files` | array of `ExportDispatchFile` | no | The emitted artifact inline (under the size cap); empty when the caller opted out (``include_content: false``) or the artifact exceeded the cap (`truncated`). |
| `truncated` | boolean | no | True when the emitted artifact exceeded the inline size cap and was omitted from ``files``; the Monaco viewer should fetch it via the job/document surface instead. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
