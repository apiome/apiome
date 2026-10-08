---
title: "Lint"
description: "REST endpoints tagged lint: 11 operations."
sidebar_position: 30
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `lint` · 11 operations

## `POST /v1/lint/custom-rules/import` {#import-spectral-ruleset-document-v1-lint-custom-rules-import-post}

**Import Spectral Ruleset Document**

Import a Spectral ruleset (GOV-1.5, #4431).

Accepts a `.spectral.yaml` document (`content` — a paste or an uploaded file's text) or a
`url` to fetch one from, and translates it into Apiome governance state: `extends:
spectral:oas` resolves onto the built-in rule catalog (GOV-1.2), custom rule definitions are
translated into the custom-rule DSL (GOV-1.3), and everything the subset cannot express is
listed in `entries` with a machine-readable `reason`. Lossy-but-successful translations
carry `notes`, so coverage is transparent rather than silently partial.

Nothing is persisted: `yaml` is ready for
`PUT /v1/style-guides/{tenantSlug}/{guideId}/custom-rules` and `builtinRules` for
`PUT /v1/style-guides/{tenantSlug}/{guideId}/rules`.

Operation id: `import_spectral_ruleset_document_v1_lint_custom_rules_import_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for import spectral ruleset document.

- `application/json` — [`SpectralImportRequest`](#schema-spectralimportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for import spectral ruleset document. | `application/json` [`SpectralImportResponse`](#schema-spectralimportresponse) |
| 400 | The ruleset could not be read: empty, invalid YAML, not a mapping, oversized, or (for `url`) unfetchable / blocked by the SSRF guard. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/lint/custom-rules/validate` {#validate-custom-rules-v1-lint-custom-rules-validate-post}

**Validate Custom Rules**

Strictly validate a custom-rule style guide (GOV-1.3, #4429).

Accepts the Spectral-compatible subset DSL: a YAML document with `rules.<id>:
{description, severity, given, then}` where `then` uses the core functions `pattern`,
`casing`, `enumeration`, `truthy`, `defined`, `undefined`, and `length`. On success the
parsed rules are echoed back (the shape stored in `style_guide_rules.custom_def`).
A malformed guide returns HTTP 422 whose `detail` carries a `message` and a `pointer`
to the offending definition. Custom rule ids may not shadow built-in rule ids.

Operation id: `validate_custom_rules_v1_lint_custom_rules_validate_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for validate custom rules.

- `application/json` — [`CustomRulesValidateRequest`](#schema-customrulesvalidaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for validate custom rules. | `application/json` [`CustomRulesValidateResponse`](#schema-customrulesvalidateresponse) |
| 422 | Malformed guide: `detail.message` explains the problem and `detail.pointer` points at the offending YAML node (e.g. `rules.my-rule.then.functionOptions.match`). | — |

## `GET /v1/lint/external-adapters` {#list-external-lint-adapters-v1-lint-external-adapters-get}

**List External Lint Adapters**

Discover Spectral / Vacuum / Redocly OpenAPI validation packs (CLX-2.2 / #4852).

Operation id: `list_external_lint_adapters_v1_lint_external_adapters_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list external lint adapters. | `application/json` [`ExternalLintAdaptersResponse`](#schema-externallintadaptersresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/format-capabilities` {#list-format-lint-capabilities-v1-lint-format-capabilities-get}

**List Format Lint Capabilities**

Publish the per-format lint capability matrix (CLX-2.4 / #4854).

Every sniffed / importable format reports ``native``, ``adapted``, or
``unsupported``. Unsupported planned packs link their existing MFI issues
rather than duplicating parser/normalizer work.

Operation id: `list_format_lint_capabilities_v1_lint_format_capabilities_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list format lint capabilities. | `application/json` [`FormatLintCapabilitiesResponse`](#schema-formatlintcapabilitiesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/rules` {#list-lint-rules-v1-lint-rules-get}

**List Lint Rules**

List every registered built-in lint rule (GOV-1.2, #4428).

Returns the full rule-catalog registry: each rule's stable id (the exact string lint
findings carry in their ``rule`` field), its pack, category, default severity, one-line
rationale, and a docs anchor into the rule reference page. Sorted by rule id, so the
payload is deterministic. The catalog is the same for every tenant — style guides
(GOV-1.1/GOV-1.4) layer per-tenant enable/disable and severity overrides on top of it.

Operation id: `list_lint_rules_v1_lint_rules_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list lint rules. | `application/json` [`LintRuleCatalogResponse`](#schema-lintrulecatalogresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/lint/schematron/import` {#import-schematron-document-v1-lint-schematron-import-post}

**Import Schematron Document**

Import a Schematron rule set as a style guide (FMT-4.3, #5436).

Schematron is a rule language, not a schema language, so it lands on the governance engine
rather than the canonical schema model: every `assert`/`report` becomes one rule, its `@id`
the rule id, its `@role` the severity, its text the message, and its `@context` the target.

Assertions about *shape* — a child or attribute must (or must not) be declared, a value must
come from a fixed set — are imported as evaluable rules scored against the canonical model,
so an imported Peppol-shaped profile re-scores any XSD- or UBL-derived catalog item.
Assertions that need a document in hand (arithmetic, computed variables, string lengths, an
instance-selecting context predicate) are imported as **declared-but-unevaluable** rules
carrying a machine-readable `reason` — they are never dropped, and `entries` says exactly
what happened to each one.

Nothing is persisted: `yaml` is ready for
`PUT /v1/style-guides/{tenantSlug}/{guideId}/custom-rules`.

Operation id: `import_schematron_document_v1_lint_schematron_import_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for import schematron document.

- `application/json` — [`SchematronImportRequest`](#schema-schematronimportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for import schematron document. | `application/json` [`SchematronImportResponse`](#schema-schematronimportresponse) |
| 400 | The rule set could not be read: not XML, not Schematron, truncated, not UTF-8, an unresolvable `include`/`is-a`, or no assertion at all. `detail.code` carries the intake taxonomy code. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint` {#lint-revision-v1-versions-tenant-slug-project-id-version-record-id-lint-get}

**Lint Revision**

Score the quality of a schema revision and return itemized, deterministic lint findings.

The score (0-100) and A-F grade are computed by the server from the reconstructed
OpenAPI/JSON-Schema — no client-side scoring. When ``baseRevisionId`` is supplied, breaking
and unknown compatibility findings relative to that revision are folded into the report.

Operation id: `lint_revision_v1_versions__tenant_slug___project_id___version_record_id__lint_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `baseRevisionId` | query | string or null | no | Optional base revision (versions.id) to flag breaking changes against. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for lint revision. | `application/json` [`LintReportResponse`](#schema-lintreportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint/axes` {#lint-revision-axes-v1-versions-tenant-slug-project-id-version-record-id-lint-axes-get}

**Lint Revision Axes**

Return the multi-axis score and coverage evaluation for a schema revision (CLX-1.2, #4849).

Prefers the latest stored ``lint_axis_evaluations`` row for algorithm ``clx-axis-v1``.
When no evaluation has been persisted yet, computes one from the revision's captured
quality report (and optionally records it). Legacy ``qualityScore`` / ``qualityGrade``
list fields are unchanged — quality remains the backwards-compatible axis.

Operation id: `lint_revision_axes_v1_versions__tenant_slug___project_id___version_record_id__lint_axes_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for lint revision axes. | `application/json` [`LintAxesResponse`](#schema-lintaxesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint/evidence` {#lint-revision-evidence-v1-versions-tenant-slug-project-id-version-record-id-lint-evidence-get}

**Lint Revision Evidence**

Return the immutable lint evidence recorded for a schema revision (CLX-1.1, #4848).

Lists every evidence run captured for the revision — provenance (scanner, adapter,
profile, fingerprints), outcome, normalized findings, and coverage — plus a per-scanner
coverage summary in which a scanner that never ran reads as ``not_run`` (never as clean).
Raw output artifacts are access-controlled: responses expose only their availability,
never the storage reference or command metadata. Evidence is read-only by design; rows
are written at score-capture time and are immutable.

Operation id: `lint_revision_evidence_v1_versions__tenant_slug___project_id___version_record_id__lint_evidence_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for lint revision evidence. | `application/json` [`LintEvidenceResponse`](#schema-lintevidenceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint/gate` {#lint-revision-gate-v1-versions-tenant-slug-project-id-version-record-id-lint-gate-get}

**Lint Revision Gate**

Evaluate the lint CI gate for a revision and emit a machine-readable artifact (CLX-4.2).

Runs the pinned policy pack over the revision's current evidence (persisting a
reproducible ``lint_policy_evaluations`` row), optionally compares against a baseline
revision for regressions, and serializes the verdict as JSON, SARIF 2.1.0, JUnit XML,
Markdown, or a signed in-toto attestation. The HTTP status is always 200 — the pass/fail
verdict lives in the body (``gate.passed``), so CI exit codes stay under the CLI's
control and reflect only configured policy failures.

Operation id: `lint_revision_gate_v1_versions__tenant_slug___project_id___version_record_id__lint_gate_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `format` | query | string or null | no | Artifact format: json (default) \| sarif \| junit \| markdown \| attestation. The Accept header is honored when the query parameter is absent. |
| `baselineRevisionId` | query | string or null | no | Optional baseline revision (versions.id) to diff regressions against; must belong to the same project. Without it, regressions compare each scanner's latest run to its own previous run. |
| `newOnly` | query | boolean | no | Scope the CI verdict's unwaived-errors gate to newly introduced findings, so pre-existing debt does not block. Coverage and axis gates always evaluate the full head revision. |
| `policyVersionId` | query | string or null | no | Optional historical policy pack id; defaults to the latest for the assigned guide. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for lint revision gate. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint/policy` {#lint-revision-policy-v1-versions-tenant-slug-project-id-version-record-id-lint-policy-get}

**Lint Revision Policy**

Evaluate the assigned style-guide policy pack against revision evidence (CLX-1.3, #4850).

Separates raw findings from policy decisions. Waivers require rationale + expiry and reopen
when expired. Persists an append-only ``lint_policy_evaluations`` row for reproducibility.

Operation id: `lint_revision_policy_v1_versions__tenant_slug___project_id___version_record_id__lint_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `policyVersionId` | query | string or null | no | Optional historical policy pack id; defaults to the latest for the assigned guide. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for lint revision policy. | `application/json` [`LintPolicyResponse`](#schema-lintpolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CustomRulesValidateRequest` {#schema-customrulesvalidaterequest}

Request body for custom-rule DSL validation (GOV-1.3, #4429): the guide YAML source.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `yaml` | string | yes | The style-guide YAML document (`rules.<id>: {description, severity, given, then}`). |

### `CustomRulesValidateResponse` {#schema-customrulesvalidateresponse}

Successful validation of a custom-rule guide (GOV-1.3, #4429): the parsed rules.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `valid` | boolean | yes | Always true on a 200 (malformed guides return HTTP 422). |
| `count` | integer | yes | Number of validated rules (== len(rules)). |
| `rules` | array of `CustomRuleOut` | yes | Every validated rule, in author order. |

### `ExternalLintAdaptersResponse` {#schema-externallintadaptersresponse}

Discovery for Spectral / Vacuum / Redocly validation packs (CLX-2.2).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `adapters` | array of `ExternalLintAdapterOut` | yes | Adapters. |
| `count` | integer | yes | Number of count. |
| `defaultBulkRunner` | string | yes | Default Bulk Runner. |
| `profiles` | array of string | yes | Profiles. |
| `rationale` | string | yes | Why the default bulk runner was selected (parity, not speed). |

### `FormatLintCapabilitiesResponse` {#schema-formatlintcapabilitiesresponse}

Published per-format lint capability matrix (CLX-2.4 / #4854).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `formats` | array of `FormatLintCapabilityOut` | yes | Formats. |
| `count` | integer | yes | Number of count. |
| `docsPage` | string | yes | Repository-relative path of the capability matrix documentation. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `LintAxesResponse` {#schema-lintaxesresponse}

Response envelope for GET …/lint/axes (CLX-1.2, #4849).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `evaluation` | `LintAxisEvaluationOut` | yes | Evaluation. |

### `LintEvidenceResponse` {#schema-lintevidenceresponse}

All lint evidence for one catalog revision or MCP endpoint version (CLX-1.1, #4848).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `subjectType` | string | yes | Subject kind: catalog_revision or mcp_endpoint_version. |
| `subjectId` | string | yes | The revision (versions.id) or snapshot (mcp_endpoint_versions.id). |
| `runs` | array of `LintEvidenceRunOut` | no | Immutable evidence runs, most recent first. |
| `coverage` | array of `LintEvidenceCoverageOut` | no | Per-scanner coverage: expected scanners first, then any additional scanners with historical runs. Never-run scanners appear as not_run — never as clean. |
| `count` | integer | yes | Number of evidence runs (== len(runs)). |

### `LintPolicyResponse` {#schema-lintpolicyresponse}

GET …/lint/policy response: pack pin, evaluation, findings with decisions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `policyVersion` | `StyleGuidePolicyVersionOut` | yes | Policy Version. |
| `evaluation` | `LintPolicyEvaluationOut` | yes | Evaluation. |
| `findings` | array of `LintPolicyAnnotatedFindingOut` | no | Findings. |

### `LintReportResponse` {#schema-lintreportresponse}

Server-computed quality score + itemized findings for one project version (#3609).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `versionRecordId` | string | yes | Version Record ID. |
| `versionId` | string | yes | Human-readable version label (e.g. 1.0.0). |
| `score` | integer | yes | Deterministic 0-100 quality score. |
| `grade` | string | yes | A-F letter grade derived from the score. |
| `findings` | array of `LintFindingOut` | yes | Findings. |
| `ruleHits` | map of integer | no | Count of findings per rule id (deterministic). |
| `severityCounts` | map of integer | no | Count of findings per severity (error/warning/info). |
| `categories` | array of `LintCategoryScoreOut` | no | Per-category 0-100 rollup scores (MFI-25.6), sorted by name — drives the UI's category bars with real values. Empty when no categories apply. |
| `reportFingerprint` | string | yes | Stable hash over score, grade, and findings for a fixed input. |
| `baseRevisionId` | string or null | no | Base revision used for breaking-change comparison, when provided. |
| `compatibilityOverall` | string or null | no | Compatibility verdict vs base revision (safe/breaking/unknown), when compared. |
| `capturedScore` | integer or null | no | Score persisted on the version at import time (MFI-4.2), if any. |
| `capturedGrade` | string or null | no | A-F grade persisted on the version at import time, if any. |
| `capturedReportFingerprint` | string or null | no | Report fingerprint persisted on the version at import time, if any. |
| `scoreIsStale` | boolean | no | True when a captured fingerprint exists and differs from this live report's fingerprint, signalling the persisted score is out of date. Always False when a base revision is compared (the live report folds in extra findings) or when no score has been captured. |
| `guideId` | string or null | no | The style guide this report was scored under (GOV-1.4). Null when the in-code default guide applied (no guide assigned or resolvable). |
| `guideName` | string or null | no | Display name of the applied style guide (e.g. 'Apiome Recommended'). |
| `guideSource` | string or null | no | Origin of the applied guide: builtin \| custom \| fallback (in-code defaults). |
| `guideRevisionId` | string or null | no | Immutable revision of the applied style guide (GOV-1.6) — the exact ruleset this report was scored against, queryable at `GET /v1/style-guides/{tenantSlug}/{guideId}/revisions/{revisionId}`. Null when the in-code default guide applied or no revision could be resolved. |
| `algorithmId` | string or null | no | Multi-axis scoring algorithm id (CLX-1.2), e.g. clx-axis-v1. |
| `axes` | array of `LintAxisOut` or null | no | Per-axis scores and coverage (CLX-1.2). Null when not evaluated. |
| `compositeScore` | integer or null | no | Weighted composite when required coverage is met; null otherwise. |
| `compositeGrade` | string or null | no | A-F grade of the composite; null when compositeScore is null. |
| `requiredCoverageMet` | boolean or null | no | True when required axes (v1: quality) are assessed. |

### `LintRuleCatalogResponse` {#schema-lintrulecatalogresponse}

The full built-in lint-rule catalog (GOV-1.2, #4428), sorted by rule id.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `rules` | array of `LintRuleOut` | yes | Every registered built-in rule, sorted by ruleId (deterministic). |
| `count` | integer | yes | Number of registered rules (== len(rules)). |
| `docsPage` | string | yes | Repository-relative path of the rule reference page docsAnchor points into. |

### `SchematronImportRequest` {#schema-schematronimportrequest}

Import a Schematron rule set as a style guide (FMT-4.3, #5436).

``content`` is the rule set's text — the root document of the set. A rule set assembled from
modules by ``include`` additionally supplies ``members``: the other files of the upload,
keyed by their path relative to the set root. Nothing is fetched, so an ``include`` naming a
file that is not a member fails with an unresolved-reference error.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `content` | string | yes | The Schematron document text (paste or uploaded `.sch` file). |
| `sourceLabel` | string or null | no | Path of `content` within the uploaded set (e.g. `main.sch`), echoed back and used to resolve a relative `include` href. |
| `members` | map of string or null | no | Other files of a multi-file rule set, keyed by path relative to the set root. Only consulted by `include`. |

### `SchematronImportResponse` {#schema-schematronimportresponse}

A Schematron rule set translated into style-guide state (FMT-4.3, #5436).

`yaml` is the ready-to-store custom-rules document — the exact body
`PUT /v1/style-guides/{tenantSlug}/{guideId}/custom-rules` accepts. Nothing is persisted by
the import call itself. Every assertion appears in `entries` *and* in `yaml`: one that could
not be projected is stored as a declared rule carrying its reason, never dropped.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sourceLabel` | string or null | no | Label of the imported source. |
| `guideName` | string | yes | Suggested guide name: the rule set's `title`, else the source label. |
| `description` | string or null | no | The rule set's prose, for the guide's description. |
| `assertionCount` | integer | yes | Assertions the rule set declared. |
| `projectedCount` | integer | yes | Assertions that became evaluable canonical-model rules. |
| `declaredCount` | integer | yes | Assertions recorded as declared-but-unevaluable, each with a reason. |
| `coverage` | number | yes | projectedCount / assertionCount, 0.0-1.0. Reported, never gated on. |
| `yaml` | string | yes | The imported rules as a style-guide YAML document. |
| `resolvedPhase` | string | yes | The phase whose patterns are active (`#ALL` when none was selected). |
| `phases` | array of string | no | Every phase the rule set declares, in document order. |
| `namespaces` | map of string | no | The `ns` prefix bindings the rule set declares. |
| `modules` | array of string | no | Modules spliced in by `include`, in resolution order. |
| `entries` | array of `SchematronImportEntryOut` | yes | One entry per assertion, in document order. |
| `notes` | array of string | no | Document-level notes (rule ceiling reached, assembled modules, ...). |

### `SpectralImportRequest` {#schema-spectralimportrequest}

Import a Spectral ruleset (GOV-1.5, #4431): the document, or a URL to fetch it from.

Exactly one of ``content`` (a pasted document or an uploaded ``.spectral.yaml`` file's
text) and ``url`` must be supplied.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `content` | string or null | no | The `.spectral.yaml` document text (paste or uploaded file). |
| `url` | string or null | no | http/https URL of a `.spectral.yaml` to fetch (SSRF-guarded). |
| `sourceLabel` | string or null | no | Human label for the source (e.g. the uploaded filename), echoed back. |

### `SpectralImportResponse` {#schema-spectralimportresponse}

A translated Spectral ruleset (GOV-1.5, #4431): what mapped, and what did not.

``yaml`` is the ready-to-store custom-rules document — the exact body
``PUT /v1/style-guides/{tenantSlug}/{guideId}/custom-rules`` accepts — and ``builtinRules``
is the matching built-in rule state for ``PUT .../rules``. Nothing is persisted by the
import call itself.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sourceLabel` | string or null | no | Label of the imported source. |
| `ruleCount` | integer | yes | Rules declared by the source ruleset. |
| `mappedCount` | integer | yes | Rules the importer translated (custom + builtin). |
| `unsupportedCount` | integer | yes | Rules the importer could not translate; each entry carries a reason. |
| `coverage` | number | yes | mappedCount / ruleCount, 0.0-1.0 (1.0 for a ruleset with no rules). |
| `customRuleCount` | integer | yes | Custom rules in `yaml` (disabled imports are reported but not serialized). |
| `yaml` | string | yes | The imported custom rules as a style-guide YAML document. |
| `builtinRules` | array of `SpectralImportBuiltinRuleOut` | no | Built-in rule rows the ruleset resolves to, sorted by ruleId. |
| `entries` | array of `SpectralImportEntryOut` | yes | One entry per source rule, in document order. |
| `extends` | array of `SpectralImportExtendsOut` | no | One entry per `extends` target, in document order. |
| `notes` | array of string | no | Document-level notes (ignored top-level keys, dropped `overrides`, ...). |
