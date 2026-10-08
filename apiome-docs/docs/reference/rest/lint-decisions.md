---
title: "Lint decisions"
description: "REST endpoints tagged lint-decisions: 4 operations."
sidebar_position: 31
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `lint-decisions` · 4 operations

## `GET /v1/lint/decisions` {#list-lint-finding-decisions-v1-lint-decisions-get}

**List Lint Finding Decisions**

List finding remediation / waiver decisions for the tenant (CLX-1.3, #4850).

Operation id: `list_lint_finding_decisions_v1_lint_decisions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `projectId` | query | string or null | no | Query parameter: project id. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list lint finding decisions. | `application/json` [`LintFindingDecisionListResponse`](#schema-lintfindingdecisionlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/lint/decisions` {#upsert-lint-finding-decision-v1-lint-decisions-post}

**Upsert Lint Finding Decision**

Create or update a finding decision / waiver (CLX-1.3, #4850; guarded by CLX-4.1, #4859).

Waived state requires non-empty rationale and an expiry timestamp. The transition is
RBAC-guarded on the ``lint_findings`` resource: triage transitions need ``edit``;
approval-tier transitions (entering/leaving ``waived``, resolving a ``waiver_requested``
row) need ``publish`` — the same rules the workspace bulk endpoint enforces, so bulk
authorization can never be bypassed one decision at a time.

Operation id: `upsert_lint_finding_decision_v1_lint_decisions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for upsert lint finding decision.

- `application/json` — [`LintFindingDecisionUpsertRequest`](#schema-lintfindingdecisionupsertrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for upsert lint finding decision. | `application/json` [`LintFindingDecisionOut`](#schema-lintfindingdecisionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/decisions/{decision_id}` {#get-lint-finding-decision-v1-lint-decisions-decision-id-get}

**Get Lint Finding Decision**

Fetch one finding decision by id (CLX-1.3, #4850).

Operation id: `get_lint_finding_decision_v1_lint_decisions__decision_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `decision_id` | path | string | yes | Path parameter identifying the decision id segment. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get lint finding decision. | `application/json` [`LintFindingDecisionOut`](#schema-lintfindingdecisionout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/lint/decisions/{decision_id}/events` {#list-lint-finding-decision-events-v1-lint-decisions-decision-id-events-get}

**List Lint Finding Decision Events**

Audit history for a finding decision (CLX-1.3, #4850).

Operation id: `list_lint_finding_decision_events_v1_lint_decisions__decision_id__events_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `decision_id` | path | string | yes | Path parameter identifying the decision id segment. |
| `tenant_slug` | query | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list lint finding decision events. | `application/json` array of [`LintFindingDecisionEventOut`](#schema-lintfindingdecisioneventout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `LintFindingDecisionEventOut` {#schema-lintfindingdecisioneventout}

One audit event for a finding decision (CLX-1.3, #4850).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `decisionId` | string | yes | Decision ID. |
| `beforeState` | string or null | no | Before State. |
| `afterState` | string | yes | After State. |
| `rationale` | string or null | no | Rationale. |
| `expiresAt` | string or null | no | Expires At. |
| `linkedTicket` | string or null | no | Linked Ticket. |
| `policyVersionId` | string or null | no | Policy Version ID. |
| `actorUserId` | string or null | no | Actor User ID. |
| `actorLabel` | string or null | no | Actor Label. |
| `createdAt` | string or null | no | Created At. |

### `LintFindingDecisionListResponse` {#schema-lintfindingdecisionlistresponse}

List of finding decisions (CLX-1.3, #4850).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `decisions` | array of [`LintFindingDecisionOut`](#schema-lintfindingdecisionout) | no | Decisions. |
| `count` | integer | no | Number of count. |

### `LintFindingDecisionOut` {#schema-lintfindingdecisionout}

One finding remediation / waiver decision (CLX-1.3, #4850).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenantId` | string | yes | Tenant ID. |
| `projectId` | string or null | no | Project ID. |
| `sourceFingerprint` | string | yes | Source Fingerprint. |
| `ruleId` | string or null | no | Rule ID. |
| `state` | string | yes | open \| acknowledged \| waiver_requested \| waived \| fixed \| false_positive |
| `ownerUserId` | string or null | no | Owner User ID. |
| `rationale` | string or null | no | Rationale. |
| `linkedTicket` | string or null | no | Linked Ticket. |
| `expiresAt` | string or null | no | Expires At. |
| `policyVersionId` | string or null | no | Policy Version ID. |
| `evidenceFingerprintAtDecision` | string or null | no | Evidence Fingerprint At Decision. |
| `actorUserId` | string or null | no | Actor User ID. |
| `actorLabel` | string or null | no | Actor Label. |
| `createdAt` | string or null | no | Created At. |
| `updatedAt` | string or null | no | Updated At. |

### `LintFindingDecisionUpsertRequest` {#schema-lintfindingdecisionupsertrequest}

Create or update a finding decision / waiver (CLX-1.3, #4850).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sourceFingerprint` | string | yes | Source Fingerprint. |
| `state` | string | yes | open \| acknowledged \| waiver_requested \| waived \| fixed \| false_positive |
| `projectId` | string or null | no | Project ID. |
| `ruleId` | string or null | no | Rule ID. |
| `ownerUserId` | string or null | no | Owner User ID. |
| `rationale` | string or null | no | Rationale. |
| `linkedTicket` | string or null | no | Linked Ticket. |
| `expiresAt` | string (date-time) or null | no | Required when state is waived. |
| `policyVersionId` | string or null | no | Policy Version ID. |
