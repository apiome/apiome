---
title: "Compatibility"
description: "REST endpoints tagged compatibility: 3 operations."
sidebar_position: 14
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `compatibility` · 3 operations

## `POST /v1/versions/{tenant_slug}/{project_id}/compatibility` {#check-revision-compatibility-v1-versions-tenant-slug-project-id-compatibility-post}

**Check Revision Compatibility**

Compare **baseRevisionId** (older / consumer expectation) to **headRevisionId** (newer).
Returns structured safe / breaking / unknown findings for CI-style merge gates.

Operation id: `check_revision_compatibility_v1_versions__tenant_slug___project_id__compatibility_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for check revision compatibility.

- `application/json` — [`CompatibilityCheckRequest`](#schema-compatibilitycheckrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for check revision compatibility. | `application/json` [`CompatibilityCheckResponse`](#schema-compatibilitycheckresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/versions/{tenant_slug}/{project_id}/compatibility/evidence` {#create-compatibility-evidence-v1-versions-tenant-slug-project-id-compatibility-evidence-post}

**Create Compatibility Evidence**

Run oasdiff, persist evidence on the head revision, return gate output.

Emits normalized JSON by default. Pass ``?format=sarif`` or ``?format=junit``
(or matching ``Accept``) for CI-compatible artifacts.

Operation id: `create_compatibility_evidence_v1_versions__tenant_slug___project_id__compatibility_evidence_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `format` | query | string or null | no | Gate output format: json (default), sarif, or junit. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create compatibility evidence.

- `application/json` — [`CompatibilityEvidenceRequest`](#schema-compatibilityevidencerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for create compatibility evidence. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_id}/compatibility/evidence` {#list-compatibility-evidence-v1-versions-tenant-slug-project-id-version-id-compatibility-evidence-get}

**List Compatibility Evidence**

List persisted oasdiff compatibility evidence runs for a revision.

Operation id: `list_compatibility_evidence_v1_versions__tenant_slug___project_id___version_id__compatibility_evidence_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_id` | path | string | yes | Version identifier or semantic version label, depending on the route. |
| `format` | query | string or null | no | When set to sarif/junit, emit gate output for the latest oasdiff run. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list compatibility evidence. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CompatibilityCheckRequest` {#schema-compatibilitycheckrequest}

Compare two schema revisions (versions.id) for backward compatibility.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `baseRevisionId` | string | yes | Older / merge-base side revision (versions.id UUID). |
| `headRevisionId` | string | yes | Newer / branch tip side revision (versions.id UUID). |
| `rules` | `CompatibilityRulesPayload` or null | no | Rules. |
| `policy` | `CompatibilityPolicyPayload` or null | no | Policy. |

### `CompatibilityCheckResponse` {#schema-compatibilitycheckresponse}

CompatibilityCheckResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `overall` | string | yes | Overall. |
| `baseRevisionId` | string | yes | Base Revision ID. |
| `headRevisionId` | string | yes | Head Revision ID. |
| `findings` | array of `CompatibilityFindingOut` | yes | Findings. |
| `ruleHits` | map of integer | no | Count of findings per rule id (deterministic classification; #2589). |
| `breakingChangeDocumentationIssueUrl` | string or null | no | Breaking Change Documentation Issue URL. |
| `reportFingerprint` | string | yes | Report Fingerprint. |
| `tenantCompatGateActive` | boolean | no | True when project metadata requests merge-time compat gating. |
| `mergeBlockedByCompatGate` | boolean | no | True when tenant gate is on and the revision pair is not fully safe. |
| `deprecationWarnings` | array of `RevisionDeprecationWarningOut` | no | Deprecation Warnings. |
| `deprecatedRevisionBlocked` | boolean | no | True when project metadata requests strict deprecation handling and a revision is deprecated. |

### `CompatibilityEvidenceRequest` {#schema-compatibilityevidencerequest}

Run independent oasdiff compatibility evidence for two revisions (CLX-2.3).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `baseRevisionId` | string | yes | Baseline revision (versions.id UUID) or CI-provided base. |
| `headRevisionId` | string | yes | Candidate / head revision (versions.id UUID). |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
