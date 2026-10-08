---
title: "Slate insights"
description: "REST endpoints tagged slate-insights: 29 operations."
sidebar_position: 65
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `slate-insights` · 29 operations

## `GET /v1/slate/environments/{environment_id}/insights` {#get-insights-lane-v1-slate-environments-environment-id-insights-get}

**Get Insights Lane**

Return a lane's observability policy, residency, exports, budgets and checks together.

One read rather than five, for the reason V190 stores the residency stages in one table: an
operator deciding whether a lane is safe is reading its retention, its residency and its export
destinations at once, and a surface that made that five round trips would let the five drift on
screen.

Operation id: `get_insights_lane_v1_slate_environments__environment_id__insights_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get insights lane. | `application/json` [`InsightsLaneResponse`](#schema-insightslaneresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/alerts` {#get-budget-alerts-v1-slate-environments-environment-id-insights-alerts-get}

**Get Budget Alerts**

Return a lane's budget alerts, newest first, each showing its own arithmetic.

``budgetAmount`` is the amount captured when the alert fired rather than the budget's current
value, so a later edit does not rewrite what the alert was compared against.

Operation id: `get_budget_alerts_v1_slate_environments__environment_id__insights_alerts_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `budgetId` | query | string or null | no | Query parameter: budget id. |
| `unacknowledgedOnly` | query | boolean | no | Query parameter: unacknowledged only. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get budget alerts. | `application/json` [`BudgetAlertsResponse`](#schema-budgetalertsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/insights/alerts/{alert_id}/acknowledge` {#acknowledge-alert-v1-slate-environments-environment-id-insights-alerts-alert-id-acknowledge-post}

**Acknowledge Alert**

Acknowledge one budget alert.

An acknowledgement is a person and a time together, or neither — V190 pairs the columns by
CHECK and the store writes all three at once. No policy version is consumed: acknowledging an
alert changes no configuration, and invalidating every open editor to dismiss a notice would be
the wrong trade during the incident that produced it.

Operation id: `acknowledge_alert_v1_slate_environments__environment_id__insights_alerts__alert_id__acknowledge_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `alert_id` | path | string | yes | Path parameter identifying the alert id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for acknowledge alert.

- `application/json` — [`AcknowledgeAlertRequest`](#schema-acknowledgealertrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for acknowledge alert. | `application/json` [`AcknowledgeAlertResponse`](#schema-acknowledgealertresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/audit` {#get-insights-audit-v1-slate-environments-environment-id-insights-audit-get}

**Get Insights Audit**

Return a lane's append-only observability audit trail, most recent first.

Operation id: `get_insights_audit_v1_slate_environments__environment_id__insights_audit_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `subjectKind` | query | string or null | no | Query parameter: subject kind. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get insights audit. | `application/json` [`SlateInsightsAuditResponse`](#schema-slateinsightsauditresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/audit/export` {#export-insights-audit-v1-slate-environments-environment-id-insights-audit-export-get}

**Export Insights Audit**

Export a lane's observability audit trail as CSV.

Reading the evidence is itself audit-worthy — who exported the record of who opened a live tail
on production is part of that record — so an ``export`` audit row is written before the download
begins.

Modelled on ``access_routes.py``'s exporter and fixing the two defects that precedent carries:
formula-leading cells are neutralized, and truncation is stated in words rather than left as an
inference an auditor reads as "the rest never happened".

Operation id: `export_insights_audit_v1_slate_environments__environment_id__insights_audit_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export insights audit. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/insights/budgets` {#create-budget-v1-slate-environments-environment-id-insights-budgets-post}

**Create Budget**

Create a spend budget, refusing one that could never alert or never reconcile.

Operation id: `create_budget_v1_slate_environments__environment_id__insights_budgets_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create budget.

- `application/json` — [`WriteBudgetRequest`](#schema-writebudgetrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create budget. | `application/json` [`WriteBudgetResponse`](#schema-writebudgetresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/insights/budgets/{budget_id}` {#replace-budget-v1-slate-environments-environment-id-insights-budgets-budget-id-put}

**Replace Budget**

Replace a spend budget, running the same gates as a create.

Operation id: `replace_budget_v1_slate_environments__environment_id__insights_budgets__budget_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `budget_id` | path | string | yes | Path parameter identifying the budget id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace budget.

- `application/json` — [`WriteBudgetRequest`](#schema-writebudgetrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace budget. | `application/json` [`WriteBudgetResponse`](#schema-writebudgetresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/insights/budgets/{budget_id}` {#remove-budget-v1-slate-environments-environment-id-insights-budgets-budget-id-delete}

**Remove Budget**

Remove a budget and, by cascade, its alert history.

Operation id: `remove_budget_v1_slate_environments__environment_id__insights_budgets__budget_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `budget_id` | path | string | yes | Path parameter identifying the budget id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove budget. | `application/json` [`DeleteInsightResourceResponse`](#schema-deleteinsightresourceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/insights/checks` {#create-synthetic-check-v1-slate-environments-environment-id-insights-checks-post}

**Create Synthetic Check**

Create a synthetic check.

A check running from one region reports that region's health rather than the lane's, which is
a warning rather than a refusal: it is a real limitation and a legitimate configuration, and
the sentence is what stops it being read as the lane being healthy.

Operation id: `create_synthetic_check_v1_slate_environments__environment_id__insights_checks_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create synthetic check.

- `application/json` — [`WriteCheckRequest`](#schema-writecheckrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create synthetic check. | `application/json` [`WriteCheckResponse`](#schema-writecheckresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/insights/checks/{check_id}` {#replace-synthetic-check-v1-slate-environments-environment-id-insights-checks-check-id-put}

**Replace Synthetic Check**

Replace a synthetic check, running the same gates as a create.

Operation id: `replace_synthetic_check_v1_slate_environments__environment_id__insights_checks__check_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `check_id` | path | string | yes | Path parameter identifying the check id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace synthetic check.

- `application/json` — [`WriteCheckRequest`](#schema-writecheckrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace synthetic check. | `application/json` [`WriteCheckResponse`](#schema-writecheckresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/insights/checks/{check_id}` {#remove-synthetic-check-v1-slate-environments-environment-id-insights-checks-check-id-delete}

**Remove Synthetic Check**

Remove a synthetic check and, by cascade, its results.

Operation id: `remove_synthetic_check_v1_slate_environments__environment_id__insights_checks__check_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `check_id` | path | string | yes | Path parameter identifying the check id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove synthetic check. | `application/json` [`DeleteInsightResourceResponse`](#schema-deleteinsightresourceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/insights/exports` {#create-export-v1-slate-environments-environment-id-insights-exports-post}

**Create Export**

Create an OTLP export destination, refusing an unsafe one by name.

Operation id: `create_export_v1_slate_environments__environment_id__insights_exports_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create export.

- `application/json` — [`WriteExportRequest`](#schema-writeexportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create export. | `application/json` [`WriteExportResponse`](#schema-writeexportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/insights/exports/{export_id}` {#replace-export-v1-slate-environments-environment-id-insights-exports-export-id-put}

**Replace Export**

Replace an OTLP export destination, running the same gates as a create.

Operation id: `replace_export_v1_slate_environments__environment_id__insights_exports__export_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `export_id` | path | string | yes | Path parameter identifying the export id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for replace export.

- `application/json` — [`WriteExportRequest`](#schema-writeexportrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for replace export. | `application/json` [`WriteExportResponse`](#schema-writeexportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/insights/exports/{export_id}` {#remove-export-v1-slate-environments-environment-id-insights-exports-export-id-delete}

**Remove Export**

Remove an OTLP export destination.

Operation id: `remove_export_v1_slate_environments__environment_id__insights_exports__export_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `export_id` | path | string | yes | Path parameter identifying the export id segment. |
| `expectedPolicyVersion` | query | integer | yes | Required. Query parameter: expected policy version. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for remove export. | `application/json` [`DeleteInsightResourceResponse`](#schema-deleteinsightresourceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/logs` {#get-logs-v1-slate-environments-environment-id-insights-logs-get}

**Get Logs**

Return a lane's structured logs, newest first, with allowlisted evidence.

``traceRef`` is what connects a log line to the trace it belongs to, which is the whole point of
the three shared correlation columns: filtering on screen and filtering in a query must not be
able to mean different things.

Operation id: `get_logs_v1_slate_environments__environment_id__insights_logs_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `levels` | query | array of string or null | no | Query parameter: levels. |
| `sources` | query | array of string or null | no | Query parameter: sources. |
| `releaseId` | query | string or null | no | Query parameter: release id. |
| `region` | query | string or null | no | Query parameter: region. |
| `traceRef` | query | string or null | no | Query parameter: trace ref. |
| `query` | query | string or null | no | Query parameter: query. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get logs. | `application/json` [`LogsResponse`](#schema-logsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/metrics` {#get-metrics-v1-slate-environments-environment-id-insights-metrics-get}

**Get Metrics**

Return a lane's correlated metric points, and the ones that could not be keyed.

Correlation is a precondition rather than a feature: a point with no release is a point a
drill-down cannot land on, and a chart whose drill-down lands somewhere else is worse than a
chart with a gap in it. So an uncorrelatable point is dropped and *reported* rather than emitted
unkeyed.

Operation id: `get_metrics_v1_slate_environments__environment_id__insights_metrics_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `families` | query | array of string or null | no | Query parameter: families. |
| `releaseId` | query | string or null | no | Query parameter: release id. |
| `region` | query | string or null | no | Query parameter: region. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get metrics. | `application/json` [`MetricsResponse`](#schema-metricsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/insights/policy` {#set-insight-policy-v1-slate-environments-environment-id-insights-policy-put}

**Set Insight Policy**

Change what a lane collects, for how long, and how coarsely it reports.

Shortening log retention below the floor with no stated reason is refused here with a sentence,
and again by V190's CHECK. Both are deliberate: the operator should meet the explanation, not a
constraint violation, and no future code path should be able to skip the explanation.

Operation id: `set_insight_policy_v1_slate_environments__environment_id__insights_policy_put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set insight policy.

- `application/json` — [`SetInsightPolicyRequest`](#schema-setinsightpolicyrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set insight policy. | `application/json` [`SetInsightPolicyResponse`](#schema-setinsightpolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/slate/environments/{environment_id}/insights/residency/{stage}` {#set-residency-lane-v1-slate-environments-environment-id-insights-residency-stage-put}

**Set Residency Lane**

State where one processing stage happens, and what that promise does not cover.

A lane with no stated gap is refused rather than warned about. Every placement leaves something
uncovered — a network path, a certificate log, an exported copy — and a claim with no stated gap
is not a stronger promise, it is the same promise with the gap unwritten.

Operation id: `set_residency_lane_v1_slate_environments__environment_id__insights_residency__stage__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `stage` | path | string | yes | Path parameter identifying the stage segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for set residency lane.

- `application/json` — [`WriteResidencyLaneRequest`](#schema-writeresidencylanerequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for set residency lane. | `application/json` [`WriteResidencyLaneResponse`](#schema-writeresidencylaneresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/synthetic-results` {#get-synthetic-results-v1-slate-environments-environment-id-insights-synthetic-results-get}

**Get Synthetic Results**

Return a lane's synthetic results, newest first.

``annotatedOnly`` is how the surface answers "what regressed after the last promotion", which is
why an annotation is a property of the probe run that found it rather than a free-standing
record: a regression detached from its evidence is an alert nobody can verify.

Operation id: `get_synthetic_results_v1_slate_environments__environment_id__insights_synthetic_results_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `checkId` | query | string or null | no | Query parameter: check id. |
| `releaseId` | query | string or null | no | Query parameter: release id. |
| `annotatedOnly` | query | boolean | no | Query parameter: annotated only. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get synthetic results. | `application/json` [`SyntheticResultsResponse`](#schema-syntheticresultsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/tail` {#get-tail-sessions-v1-slate-environments-environment-id-insights-tail-get}

**Get Tail Sessions**

Return a lane's recent live tail sessions, newest first.

Operation id: `get_tail_sessions_v1_slate_environments__environment_id__insights_tail_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get tail sessions. | `application/json` [`TailSessionsResponse`](#schema-tailsessionsresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/slate/environments/{environment_id}/insights/tail` {#open-live-tail-v1-slate-environments-environment-id-insights-tail-post}

**Open Live Tail**

Open a live tail session against the lane's ceilings.

The ceilings are checked rather than clamped, deliberately. Clamping would let an operator ask
for a rate they do not get and read a stream they believe is complete, which on this surface
means concluding a route is quiet when it was merely sampled away.

A tail with no stated reason is refused. A tail is a capture of live reader traffic in front of
a person, and the question at review is never that one was opened but why.

Operation id: `open_live_tail_v1_slate_environments__environment_id__insights_tail_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for open live tail.

- `application/json` — [`OpenTailRequest`](#schema-opentailrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for open live tail. | `application/json` [`OpenTailResponse`](#schema-opentailresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/slate/environments/{environment_id}/insights/tail/{session_id}` {#close-live-tail-v1-slate-environments-environment-id-insights-tail-session-id-delete}

**Close Live Tail**

Close a live tail session.

No delivery count is written here and there is no argument by which one could be. Nothing
delivered anything, and a close that could record a stream is the one path by which this
surface could claim a capture it never had.

Operation id: `close_live_tail_v1_slate_environments__environment_id__insights_tail__session_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `session_id` | path | string | yes | Path parameter identifying the session id segment. |
| `dryRun` | query | boolean | no | When true, validate without persisting side effects. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for close live tail. | `application/json` [`CloseTailResponse`](#schema-closetailresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/traces` {#get-traces-v1-slate-environments-environment-id-insights-traces-get}

**Get Traces**

Return a lane's traces, newest first.

``minDurationMs`` is how an operator finds the traces worth opening, which is the only way a
trace list is usable at all.

Operation id: `get_traces_v1_slate_environments__environment_id__insights_traces_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `releaseId` | query | string or null | no | Query parameter: release id. |
| `region` | query | string or null | no | Query parameter: region. |
| `route` | query | string or null | no | Query parameter: route. |
| `minDurationMs` | query | integer or null | no | Query parameter: min duration ms. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get traces. | `application/json` [`TracesResponse`](#schema-tracesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/traces/{trace_id}` {#get-trace-detail-v1-slate-environments-environment-id-insights-traces-trace-id-get}

**Get Trace Detail**

Return one trace and its spans, ordered as a waterfall.

Spans arrive ordered by start offset rather than by insertion, because the waterfall is drawn
from offsets and an ordering the renderer has to redo is an ordering the two can disagree about.

Operation id: `get_trace_detail_v1_slate_environments__environment_id__insights_traces__trace_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `trace_id` | path | string | yes | Path parameter identifying the trace id segment. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get trace detail. | `application/json` [`TraceDetailResponse`](#schema-tracedetailresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/usage` {#get-usage-v1-slate-environments-environment-id-insights-usage-get}

**Get Usage**

Return a lane's daily usage, its per-service rollups and its forecast.

Three things this deliberately does not do. It never sums a forecast into a total, because a
projection added to things that happened produces a figure that is neither. It never reports
cache savings assembled from a mix of metered and modelled rows, because that is a measurement
in presentation and a model in fact. And it never marks anything billable, which is not a
decision this handler makes but a property of :class:`UsageRollupBody` — the field is a
``Literal[False]`` no handler can assign.

Operation id: `get_usage_v1_slate_environments__environment_id__insights_usage_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `services` | query | array of string or null | no | Query parameter: services. |
| `releaseId` | query | string or null | no | Query parameter: release id. |
| `region` | query | string or null | no | Query parameter: region. |
| `since` | query | string (date) or null | no | Query parameter: since. |
| `until` | query | string (date) or null | no | Query parameter: until. |
| `daysRemaining` | query | integer | no | Query parameter: days remaining. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get usage. | `application/json` [`UsageResponse`](#schema-usageresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/environments/{environment_id}/insights/usage/export` {#export-usage-v1-slate-environments-environment-id-insights-usage-export-get}

**Export Usage**

Export a lane's daily usage as CSV.

Every row carries ``basis``, ``metered`` and ``billable`` columns, and every one of them is a
constant written by this function rather than read from the row. A spreadsheet of costs is the
artifact most likely to be forwarded to somebody who never saw this surface, so the file has to
say what it is without the page around it.

VIEW rather than PUBLISH: "what did this lane cost" is the auditor's question, and gating it
behind the permission to *change* observability would put the answer out of reach.

**CSV injection is neutralized** — a cell whose first character is ``=``, ``+``, ``-``, ``@``, a
tab or a carriage return is prefixed with an apostrophe. **Nothing is silently truncated** —
this reads one row past the cap and says so in words when there was more.

Operation id: `export_usage_v1_slate_environments__environment_id__insights_usage_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `environment_id` | path | string | yes | Path parameter identifying the environment id segment. |
| `services` | query | array of string or null | no | Query parameter: services. |
| `since` | query | string (date) or null | no | Query parameter: since. |
| `until` | query | string (date) or null | no | Query parameter: until. |
| `limit` | query | integer | no | Maximum number of rows to return. |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export usage. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/insights/metric-families` {#get-metric-families-v1-slate-insights-metric-families-get}

**Get Metric Families**

Return the metric families as data, each with the question it cannot answer.

``doesNotAnswer`` is a required field rather than documentation somewhere else, because the
whole failure mode of an observability product is a number read as more than it is. A rising
error rate names no cause; a hit ratio says nothing about whether the hits were correct.

Operation id: `get_metric_families_v1_slate_insights_metric_families_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get metric families. | `application/json` [`MetricFamiliesResponse`](#schema-metricfamiliesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/insights/residency-stages` {#get-residency-stages-v1-slate-insights-residency-stages-get}

**Get Residency Stages**

Return the six processing stages and what each one's residency promise leaves uncovered.

§29.6 asks the UX to state what a residency option does not cover, which is an unusual
requirement and the correct one: a claim with no stated gap is the version somebody quotes to a
regulator. These sentences are that requirement expressed as data, so the surface renders them
rather than inventing its own.

Operation id: `get_residency_stages_v1_slate_insights_residency_stages_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get residency stages. | `application/json` [`ResidencyStagesResponse`](#schema-residencystagesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/slate/insights/services` {#get-insight-services-v1-slate-insights-services-get}

**Get Insight Services**

Return the billable services, their units, and what drives each number.

Operation id: `get_insight_services_v1_slate_insights_services_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenantSlug` | query | string or null | no | Tenant slug. Optional: the Slate routes read tenancy from the credential, so a browser call carrying a session JWT does not need to name a tenant in the URL. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get insight services. | `application/json` [`ServicesResponse`](#schema-servicesresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AcknowledgeAlertRequest` {#schema-acknowledgealertrequest}

Acknowledge one budget alert.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `note` | string or null | no | Optional note, recorded in audit. |
| `expectedPolicyVersion` | integer or null | no | Not consumed: acknowledging an alert changes no policy. |
| `dryRun` | boolean | no | Validate without writing. |

### `AcknowledgeAlertResponse` {#schema-acknowledgealertresponse}

The outcome of acknowledging a budget alert.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `acknowledged` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `alert` | `BudgetAlertBody` or null | no | The alert as acknowledged. |

### `BudgetAlertsResponse` {#schema-budgetalertsresponse}

A lane's budget alerts.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `alerts` | array of `BudgetAlertBody` | yes | Newest first. |
| `basis` | `"modelled"` | no | Always modelled. |
| `dispatched` | `false` | no | False: nothing dispatches. |
| `sentence` | string | no | What that means, in words. |

### `CloseTailResponse` {#schema-closetailresponse}

The outcome of closing a live tail session.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `closed` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `session` | `TailSessionBody` or null | no | The session as closed. |

### `DeleteInsightResourceResponse` {#schema-deleteinsightresourceresponse}

The outcome of removing an export destination, a budget or a synthetic check.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `policyVersion` | integer | yes | The version after the write. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `InsightsLaneResponse` {#schema-insightslaneresponse}

A lane's complete observability configuration, and what it actually measures.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `environmentId` | string | yes | The lane. |
| `policy` | `InsightPolicyBody` | yes | What is collected, for how long, how coarsely. |
| `residencyLanes` | array of `ResidencyLaneBody` | yes | All six stages, in request-path order. Five stages is not a promise. |
| `residencyComplete` | boolean | yes | Whether all six stages are stated. False means the promise is incomplete. |
| `effectiveResidencyClass` | string or null | no | The single promise the lane actually makes, which is the weakest any stage makes. Null when the six stages are not all stated, because an incomplete set has no effective promise to report. |
| `exports` | array of `ExportBody` | yes | OTLP destinations, by label. |
| `budgets` | array of `BudgetBody` | yes | Spend budgets, by label. |
| `syntheticChecks` | array of `SyntheticCheckBody` | yes | Synthetic probes, by label. |
| `policyVersion` | integer | yes | Optimistic-concurrency token. |
| `signalsDigest` | string | yes | Determinism receipt over the whole configuration. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Whether the policy measures anything. |
| `warnings` | array of `InsightWarningBody` | no | Non-blocking concerns about the configuration. |
| `updatedAt` | string or null | no | When the policy last changed. |
| `updatedBy` | string or null | no | Who changed it. |

### `LogsResponse` {#schema-logsresponse}

A lane's structured logs.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `logs` | array of `LogBody` | yes | Newest first. |
| `observed` | `false` | no | False: none of these were observed in a request path. |
| `sentence` | string | no | What that means. |

### `MetricFamiliesResponse` {#schema-metricfamiliesresponse}

The metric family catalog.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `families` | array of `MetricFamilyBody` | yes | Every family, in request-path order. |

### `MetricsResponse` {#schema-metricsresponse}

A lane's correlated metric points, and the ones that could not be keyed.

Drops are reported rather than silently discarded: a chart with a hole in it and no explanation
teaches operators the data is unreliable, which is more expensive than the missing point.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `points` | array of `MetricPointBody` | yes | Correlated points, by family and window. |
| `dropped` | array of `DroppedPointBody` | no | Points that could not be keyed, and why. |
| `suppressedCount` | integer | no | How many points were withheld for privacy. |
| `privacyThreshold` | integer | no | The threshold they were withheld against. |
| `warnings` | array of `InsightWarningBody` | no | Warnings. |
| `basis` | `"policy-modelled"` | no | This series is modelled from policy, not measured. |
| `observed` | `false` | no | False: no collector reported any of this. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Enforcement. |
| `sentence` | string | no | What that means, in words. |

### `OpenTailRequest` {#schema-opentailrequest}

Open a live tail session.

``expectedPolicyVersion`` is optional here and required on every configuration write, because
opening a tail changes no policy. Consuming a version to read a stream would invalidate every
other operator's open editor during exactly the incident that made somebody open it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sampleRate` | number | no | Requested sampling rate. |
| `maxEventsPerSec` | integer | no | Requested event-rate ceiling. |
| `redactionAllowlist` | array of string | no | Fields permitted through. Anything outside the allowlist is refused. |
| `filterExpression` | string or null | no | Server-side filter, or null. |
| `reason` | string | no | Why the tail is being opened. Refused when blank. |
| `expectedPolicyVersion` | integer or null | no | Not consumed: opening a tail changes no policy. |
| `dryRun` | boolean | no | Run every gate and record nothing. |

### `OpenTailResponse` {#schema-opentailresponse}

The outcome of opening a live tail session.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `session` | `TailSessionBody` or null | no | The session as recorded. |
| `policyVersion` | integer | yes | The lane's policy version, unchanged by this call. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `InsightWarningBody` | no | Warnings. |

### `ResidencyStagesResponse` {#schema-residencystagesresponse}

The residency stage catalog, and the postures a stage may take.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `stages` | array of `ResidencyStageBody` | yes | All six, in request-path order. |
| `residencyClasses` | array of `SlateInsightsResidencyClassBody` | yes | The three postures, most restrictive first. |

### `ServicesResponse` {#schema-servicesresponse}

The billable service catalog.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `services` | array of `ServiceBody` | yes | Every service §29.6 names. |
| `metered` | `false` | no | False. Nothing meters these services. |
| `billable` | `false` | no | False. A modelled cost is not a charge. |
| `sentence` | string | no | What that means, in words. |

### `SetInsightPolicyRequest` {#schema-setinsightpolicyrequest}

Change what a lane collects, for how long, and how coarsely it reports.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `telemetryEnabled` | boolean | no | Whether signals are collected. |
| `metricRetentionDays` | integer | no | Metric retention, in days. |
| `logRetentionDays` | integer | no | Log retention, in days. |
| `traceRetentionDays` | integer | no | Trace retention, in days. |
| `defaultSampleRate` | number | no | Head sampling rate. |
| `maxTailSampleRate` | number | no | Tail rate ceiling. |
| `maxTailEventsPerSec` | integer | no | Tail event-rate ceiling. |
| `privacyThreshold` | integer | no | Smallest reportable population. |
| `retentionWaiverReason` | string or null | no | Required when log retention falls below the floor. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Run every gate and write nothing. |
| `reason` | string | no | Why; recorded in audit. |

### `SetInsightPolicyResponse` {#schema-setinsightpolicyresponse}

The outcome of an observability policy change.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `policy` | `InsightPolicyBody` | yes | The policy as it now reads. |
| `policyVersion` | integer | yes | The version after the change. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `InsightWarningBody` | no | Warnings. |

### `SlateInsightsAuditResponse` {#schema-slateinsightsauditresponse}

A lane's observability audit trail.

The audit is the one table on this surface with no retention: the record that a live tail was
opened outlives the capture it took, which is the whole point of separating the two.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `entries` | array of `SlateInsightsAuditEntryBody` | yes | Most recent first. |

### `SyntheticResultsResponse` {#schema-syntheticresultsresponse}

A lane's synthetic results.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `results` | array of `SyntheticResultBody` | yes | Newest first. |
| `observed` | `false` | no | False: no probe actually ran. |
| `sentence` | string | no | What that means. |

### `TailSessionsResponse` {#schema-tailsessionsresponse}

A lane's recent live tail sessions.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sessions` | array of `TailSessionBody` | yes | Newest first. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Enforcement. |

### `TraceDetailResponse` {#schema-tracedetailresponse}

One trace and its spans, ordered as a waterfall.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `trace` | `TraceBody` | yes | The trace header. |
| `spans` | array of `SpanBody` | yes | Its spans, by start offset. |
| `observed` | `false` | no | False: nothing observed this. |
| `sentence` | string | no | What that means. |

### `TracesResponse` {#schema-tracesresponse}

A lane's traces.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `traces` | array of `TraceBody` | yes | Newest first. |
| `observed` | `false` | no | False: nothing observed these. |
| `sentence` | string | no | What that means. |

### `UsageResponse` {#schema-usageresponse}

A lane's daily usage, its per-service rollups and its forecast.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `records` | array of `UsageRecordBody` | yes | Daily records, oldest first. |
| `rollups` | array of `UsageRollupBody` | yes | One per service present in the window. |
| `forecastAmount` | number or null | no | Projected additional spend for the remainder of the period. |
| `forecastDaysRemaining` | integer | no | Days the projection covers. Zero means no projection was asked for. |
| `currency` | string | no | ISO 4217 code shared by every record. |
| `warnings` | array of `InsightWarningBody` | no | Warnings. |
| `basis` | `"modelled"` | no | Always modelled. |
| `metered` | `false` | no | False: nothing meters this lane. |
| `billable` | `false` | no | False: a modelled cost is not a charge. |
| `sentence` | string | no | What that means, in words. |
| `forecastSentence` | string | no | Why the forecast is carried separately. |

### `WriteBudgetRequest` {#schema-writebudgetrequest}

Create or replace a spend budget.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `label` | string | yes | Operator-facing name, unique per lane. |
| `service` | string or null | no | Service to scope to, or null for every service. |
| `period` | string | no | daily, weekly or monthly. |
| `amount` | number | no | Budget amount. Must be positive. |
| `currency` | string | no | ISO 4217 code. |
| `alertThresholds` | array of number | no | Fractions at which an alert fires. At least one. |
| `notifyChannelRef` | string or null | no | Reference to the notification channel, not its address. |
| `enabled` | boolean | no | Whether the budget is active. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Run every gate and write nothing. |
| `reason` | string | no | Why; recorded in audit. |

### `WriteBudgetResponse` {#schema-writebudgetresponse}

The outcome of a budget write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `budget` | `BudgetBody` or null | no | The budget as written. |
| `policyVersion` | integer | yes | The version after the write. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `InsightWarningBody` | no | Warnings. |

### `WriteCheckRequest` {#schema-writecheckrequest}

Create or replace a synthetic check.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `label` | string | yes | Operator-facing name, unique per lane. |
| `targetPath` | string | no | The path the probe requests. |
| `method` | string | no | HTTP method. |
| `regions` | array of string | no | Regions the probe runs from. |
| `intervalSeconds` | integer | no | How often it would run. |
| `expectedStatus` | integer | no | The status it treats as healthy. |
| `latencyBudgetMs` | integer | no | Above this it is degraded. |
| `enabled` | boolean | no | Whether the probe is active. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Run every gate and write nothing. |
| `reason` | string | no | Why; recorded in audit. |

### `WriteCheckResponse` {#schema-writecheckresponse}

The outcome of a synthetic check write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `check` | `SyntheticCheckBody` or null | no | The check as written. |
| `policyVersion` | integer | yes | The version after the write. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `InsightWarningBody` | no | Warnings. |

### `WriteExportRequest` {#schema-writeexportrequest}

Create or replace an OTLP export destination.

``extra="allow"`` is deliberate and is the only place on this surface where it appears. There
is nowhere in V190 to store a header value, and normalization drops one silently — so an
operator who pasted a bearer token into a form would see it accepted and reasonably believe it
had been stored and used. Accepting the field and refusing it by name is the honest behaviour,
and :func:`app.slate_insights.validate_export` is what refuses it.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `label` | string | yes | Operator-facing name, unique per lane. |
| `endpoint` | string | yes | The collector endpoint. Plaintext HTTP is refused. |
| `protocol` | string | no | grpc or http/protobuf. |
| `signals` | array of string | no | metrics, logs and/or traces. At least one. |
| `headerSecretRef` | string or null | no | Name of the secret holding the header. A reference, never a value. |
| `enabled` | boolean | no | Whether the destination is active. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Run every gate and write nothing. |
| `reason` | string | no | Why; recorded in audit. |

### `WriteExportResponse` {#schema-writeexportresponse}

The outcome of an export destination write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `export` | `ExportBody` or null | no | The destination as written. |
| `policyVersion` | integer | yes | The version after the write. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `InsightWarningBody` | no | Warnings. |

### `WriteResidencyLaneRequest` {#schema-writeresidencylanerequest}

State where one processing stage happens, and what that promise does not cover.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `residencyClass` | string | no | in-region-only, region-pinned or unrestricted. |
| `regions` | array of string | no | Regions the stage is confined to. Required unless unrestricted. |
| `uncoveredSentence` | string | no | What this promise does not cover. Falls back to the stage's catalog sentence. |
| `residencyWaiverReason` | string or null | no | Required when the stage is unrestricted. |
| `expectedPolicyVersion` | integer | yes | The version the caller read. |
| `dryRun` | boolean | no | Run every gate and write nothing. |
| `reason` | string | no | Why; recorded in audit. |

### `WriteResidencyLaneResponse` {#schema-writeresidencylaneresponse}

The outcome of a residency stage write.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `applied` | boolean | yes | False for a dry run. |
| `dryRun` | boolean | yes | Whether this was a preview. |
| `lane` | `ResidencyLaneBody` or null | no | The stage as written. |
| `effectiveResidencyClass` | string or null | no | The promise the lane as a whole now makes, when all six are stated. |
| `policyVersion` | integer | yes | The version after the write. |
| `enforcement` | `SlateInsightsEnforcementBody` | no | Enforcement. |
| `warnings` | array of `InsightWarningBody` | no | Warnings. |
