---
title: "Compatibility"
description: "REST endpoints tagged compatibility: 4 operations."
sidebar_position: 25
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.596.17**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `compatibility` · 4 operations

## `GET /v1/compatibility/rules` {#get-compatibility-rules-v1-compatibility-rules-get}

**Get Compatibility Rules**

List every compatibility rule id with its severity per mode, category and description.

The same table the Compatibility modes docs page is generated from. Rules are grouped by
family (Avro, JSON Schema, Protobuf, AsyncAPI) and sorted by id within each. Static reference
data, identical for every tenant, so no tenant is named; ``diff:read`` and ``registry:read``
API keys may call it.

Operation id: `get_compatibility_rules_v1_compatibility_rules_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `format` | query | string or null | no | Narrow to one format family (``avro``, ``json-schema``, ``protobuf``, ``asyncapi``) or format key (``asyncapi-3``, ``jsonschema``). A format with no mode-aware rules returns an empty list. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get compatibility rules. | `application/json` [`CompatibilityRuleCatalogueOut`](#schema-compatibilityrulecatalogueout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/versions/{tenant_slug}/{project_id}/compatibility` {#check-revision-compatibility-v1-versions-tenant-slug-project-id-compatibility-post}

**Check Revision Compatibility**

Compare **baseRevisionId** (older / consumer expectation) to **headRevisionId** (newer).
Returns structured safe / breaking / unknown findings for CI-style merge gates.

``mode`` (BACKWARD / FORWARD / FULL / NONE), ``transitive`` and ``category`` (Protobuf) default
to the project's style-guide policy. Avro, JSON Schema and AsyncAPI revisions are graded by
mode, Protobuf revisions at the category; other formats keep the OpenAPI engine and report
``evaluatedUnder.modeApplied: false``. With ``transitive`` the head is also compared against
every earlier revision of the base, and each finding names the revision it was found against.

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
| `mode` | string or null | no | Compatibility mode (XPC-4.5): BACKWARD, FORWARD, FULL or NONE, any case. A ``_TRANSITIVE`` name (``FULL_TRANSITIVE``) also sets ``transitive``. Omit to use the project's style-guide policy. |
| `transitive` | boolean or null | no | Also check the head against every earlier revision of the base, not only the base (XPC-4.5). Omit to use the project's policy. |
| `category` | string or null | no | buf breaking category Protobuf changes are graded at (XPC-4.5): WIRE, WIRE_JSON, PACKAGE or FILE. Omit to use the project's policy. |

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
| `evaluatedUnder` | `EvaluatedUnderOut` or null | no | What the verdict was graded under: mode, transitivity, Protobuf category, the formats compared, whether the mode was applied, the ruleset and the revisions compared (XPC-4.5). |

### `CompatibilityEvidenceRequest` {#schema-compatibilityevidencerequest}

Run independent oasdiff compatibility evidence for two revisions (CLX-2.3).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `baseRevisionId` | string | yes | Baseline revision (versions.id UUID) or CI-provided base. |
| `headRevisionId` | string | yes | Candidate / head revision (versions.id UUID). |

### `CompatibilityRuleCatalogueOut` {#schema-compatibilityrulecatalogueout}

The rule catalogue, optionally narrowed to one format.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `format` | string or null | no | The ``?format=`` filter, when one was sent. |
| `modes` | array of string | yes | The compatibility modes ``severities`` is keyed by. |
| `categories` | array of string | yes | The buf breaking categories ``categorySeverities`` is keyed by. |
| `defaults` | object | yes | What a project gets without a policy: ``mode``, ``transitive`` and ``category``. |
| `rules` | array of `CompatibilityRuleOut` | yes | Rules. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
