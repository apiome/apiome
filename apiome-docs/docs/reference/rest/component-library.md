---
title: "Component library"
description: "REST endpoints tagged component-library: 22 operations."
sidebar_position: 24
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.549.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `component-library` · 22 operations

## `GET /v1/component-library/{tenant_slug}/audit/export` {#export-audit-v1-component-library-tenant-slug-audit-export-get}

**Export Audit**

Export the component-library ledger (tenant administrators).

Each row carries the actor, the policy in force, the old and new revision, the affected
projects, the decision, and the timestamp. ``format=csv`` returns ``text/csv`` with
``policy`` and ``affectedProjects`` as compact JSON cells.

Operation id: `export_audit_v1_component_library__tenant_slug__audit_export_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `format` | query | enum `"json"`, `"csv"` | no | Requested output format. |
| `since` | query | string (date-time) or null | no | Query parameter: since. |
| `until` | query | string (date-time) or null | no | Query parameter: until. |
| `componentId` | query | string or null | no | Query parameter: component id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for export audit. | `application/json` [`AuditExportResponse`](#schema-auditexportresponse); `text/csv` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/components` {#list-components-v1-component-library-tenant-slug-components-get}

**List Components**

List the tenant's live library components with publication summary.

Operation id: `list_components_v1_component_library__tenant_slug__components_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `kind` | query | string or null | no | Query parameter: kind. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list components. | `application/json` [`ComponentListResponse`](#schema-componentlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components` {#create-component-v1-component-library-tenant-slug-components-post}

**Create Component**

Create a component and its initial draft revision (TYPES/CREATE).

Operation id: `create_component_v1_component_library__tenant_slug__components_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create component.

- `application/json` — [`ComponentCreateRequest`](#schema-componentcreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create component. | `application/json` [`ComponentCreateResponse`](#schema-componentcreateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/components/{component_id}` {#get-component-v1-component-library-tenant-slug-components-component-id-get}

**Get Component**

One component with its revisions, highest semver first.

Operation id: `get_component_v1_component_library__tenant_slug__components__component_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get component. | `application/json` [`ComponentDetailBody`](#schema-componentdetailbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/component-library/{tenant_slug}/components/{component_id}` {#delete-component-v1-component-library-tenant-slug-components-component-id-delete}

**Delete Component**

Soft-delete a component (TYPES/DELETE); blocked while pinned (409).

Operation id: `delete_component_v1_component_library__tenant_slug__components__component_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete component. | `application/json` [`DeletedResponse`](#schema-deletedresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/component-library/{tenant_slug}/components/{component_id}/deprecations/{deprecation_id}` {#cancel-deprecation-v1-component-library-tenant-slug-components-component-id-deprecations-deprecation-id-delete}

**Cancel Deprecation**

Withdraw a live deprecation (TYPES/PUBLISH).

Operation id: `cancel_deprecation_v1_component_library__tenant_slug__components__component_id__deprecations__deprecation_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `deprecation_id` | path | string | yes | Path parameter identifying the deprecation id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for cancel deprecation. | `application/json` map of boolean |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components/{component_id}/revisions` {#create-revision-v1-component-library-tenant-slug-components-component-id-revisions-post}

**Create Revision**

Add a draft revision to a component (TYPES/EDIT).

Operation id: `create_revision_v1_component_library__tenant_slug__components__component_id__revisions_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create revision.

- `application/json` — [`RevisionCreateRequest`](#schema-revisioncreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create revision. | `application/json` [`RevisionMutationResponse`](#schema-revisionmutationresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `PUT /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}` {#update-revision-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-put}

**Update Revision**

Replace a draft revision's payload (TYPES/EDIT); published answers 409.

Operation id: `update_revision_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__put`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for update revision.

- `application/json` — [`RevisionUpdateRequest`](#schema-revisionupdaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for update revision. | `application/json` [`RevisionMutationResponse`](#schema-revisionmutationresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}` {#delete-revision-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-delete}

**Delete Revision**

Delete a draft revision (TYPES/DELETE); published or pinned answers 409.

Operation id: `delete_revision_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete revision. | `application/json` [`DeletedResponse`](#schema-deletedresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}/approval` {#get-revision-approval-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-approval-get}

**Get Revision Approval**

A revision's multi-stage approval assessment and decision history.

Operation id: `get_revision_approval_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__approval_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get revision approval. | `application/json` [`ApprovalResponse`](#schema-approvalresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}/approval` {#record-revision-approval-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-approval-post}

**Record Revision Approval**

Record a decision on the draft's current approval stage (TYPES/EDIT).

Decisions are immutable and bound to the payload digest they judged. Only the current stage
takes decisions: later stages wait until every earlier one is satisfied.

Operation id: `record_revision_approval_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__approval_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record revision approval.

- `application/json` — [`ApprovalDecisionRequest`](#schema-approvaldecisionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record revision approval. | `application/json` [`ApprovalResponse`](#schema-approvalresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}/deprecation` {#schedule-deprecation-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-deprecation-post}

**Schedule Deprecation**

Schedule the deprecation of a published revision (TYPES/PUBLISH).

The sunset must honour the policy's notice window. The revision itself is never modified;
after the sunset new pins to it are refused (409 ``REVISION_SUNSET``) and existing pins keep
working.

Operation id: `schedule_deprecation_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__deprecation_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for schedule deprecation.

- `application/json` — [`DeprecationRequest`](#schema-deprecationrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for schedule deprecation. | `application/json` [`DeprecationBody`](#schema-deprecationbody) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components/{component_id}/revisions/{revision_id}/publish` {#publish-revision-v1-component-library-tenant-slug-components-component-id-revisions-revision-id-publish-post}

**Publish Revision**

Publish a draft revision (TYPES/PUBLISH) — immutable from then on.

Enforces the no-unsafe-downgrade rule inside the transaction: the revision
must be strictly greater than the highest already-published revision.
Republishing a published revision is an idempotent no-op.

DCW-3.4: when the governing style guide defines component approval stages,
a draft whose stages are not all satisfied answers 409 ``APPROVAL_REQUIRED``
with the assessment, and the publish transaction rechecks that the payload
is still the one the approvers judged (409 ``APPROVAL_STALE`` otherwise).

Operation id: `publish_revision_v1_component_library__tenant_slug__components__component_id__revisions__revision_id__publish_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `revision_id` | path | string | yes | Revision UUID (``versions.id``). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for publish revision. | `application/json` [`PublishResponse`](#schema-publishresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components/{component_id}/upgrades` {#execute-upgrade-v1-component-library-tenant-slug-components-component-id-upgrades-post}

**Execute Upgrade**

Run a previewed bulk upgrade (VERSIONS/EDIT).

Refused with 422 ``CONFIRMATION_REQUIRED`` unless ``confirm`` is true, and with 409
``UPGRADE_PLAN_STALE`` when the plan changed since the preview that issued the token.

Operation id: `execute_upgrade_v1_component_library__tenant_slug__components__component_id__upgrades_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for execute upgrade.

- `application/json` — [`UpgradeRequest`](#schema-upgraderequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for execute upgrade. | `application/json` [`UpgradeResponse`](#schema-upgraderesponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/components/{component_id}/upgrades/preview` {#preview-upgrade-v1-component-library-tenant-slug-components-component-id-upgrades-preview-post}

**Preview Upgrade**

Preview moving every consumer of the component to a published target revision.

Lists every live pin with its status and, for eligible pins, the compatibility impact on
the version's document. Nothing is written; the returned token is what the upgrade call must
send back.

Operation id: `preview_upgrade_v1_component_library__tenant_slug__components__component_id__upgrades_preview_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for preview upgrade.

- `application/json` — [`UpgradePreviewRequest`](#schema-upgradepreviewrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for preview upgrade. | `application/json` [`UpgradePreviewResponse`](#schema-upgradepreviewresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/components/{component_id}/usage` {#component-usage-v1-component-library-tenant-slug-components-component-id-usage-get}

**Component Usage**

Who uses a component: dependents and every live pin (DCW-3.3, private-suite#2361).

Dependents are the library components whose published head references this one, directly
or transitively (:mod:`app.component_usage`); pins are every live pin of the component and
of those dependents, across all of the tenant's projects. Computed server-side in one pass
over the tenant's library so latency stays flat for a tenant-scale graph.

Operation id: `component_usage_v1_component_library__tenant_slug__components__component_id__usage_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `component_id` | path | string | yes | Path parameter identifying the component id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for component usage. | `application/json` [`ComponentUsageResponse`](#schema-componentusageresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/deprecations` {#list-deprecations-v1-component-library-tenant-slug-deprecations-get}

**List Deprecations**

Live deprecations with their affected pinned projects and migration guidance.

Operation id: `list_deprecations_v1_component_library__tenant_slug__deprecations_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `componentId` | query | string or null | no | Query parameter: component id. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list deprecations. | `application/json` [`DeprecationListResponse`](#schema-deprecationlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/governance/policy` {#get-governance-policy-v1-component-library-tenant-slug-governance-policy-get}

**Get Governance Policy**

The component policy of the tenant's governing style guide (any tenant member).

Operation id: `get_governance_policy_v1_component_library__tenant_slug__governance_policy_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get governance policy. | `application/json` [`GovernancePolicyResponse`](#schema-governancepolicyresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/materialization` {#materialization-preview-v1-component-library-tenant-slug-projects-project-id-versions-version-record-id-materialization-get}

**Materialization Preview**

Deterministic preview of materializing the version's pins.

Runs the same materializer export uses against the version's generated
document (with pins excluded from generation so nothing double-counts),
reporting the final local component names and every collision-safe
rename. Never mutates anything; local components are never overwritten.

Operation id: `materialization_preview_v1_component_library__tenant_slug__projects__project_id__versions__version_record_id__materialization_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `includeOrigin` | query | boolean | no | Query parameter: include origin. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for materialization preview. | `application/json` [`MaterializationPreviewResponse`](#schema-materializationpreviewresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/component-library/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins` {#list-pins-v1-component-library-tenant-slug-projects-project-id-versions-version-record-id-pins-get}

**List Pins**

The version's live pins with component/revision identity.

Operation id: `list_pins_v1_component_library__tenant_slug__projects__project_id__versions__version_record_id__pins_get`

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
| 200 | Successful response for list pins. | `application/json` [`PinListResponse`](#schema-pinlistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/component-library/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins` {#create-pin-v1-component-library-tenant-slug-projects-project-id-versions-version-record-id-pins-post}

**Create Pin**

Pin a published library revision to the draft version (VERSIONS/EDIT).

Operation id: `create_pin_v1_component_library__tenant_slug__projects__project_id__versions__version_record_id__pins_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for create pin.

- `application/json` — [`PinCreateRequest`](#schema-pincreaterequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for create pin. | `application/json` [`PinCreateResponse`](#schema-pincreateresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `DELETE /v1/component-library/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins/{pin_id}` {#delete-pin-v1-component-library-tenant-slug-projects-project-id-versions-version-record-id-pins-pin-id-delete}

**Delete Pin**

Unpin one live pin from the draft version (VERSIONS/EDIT).

Operation id: `delete_pin_v1_component_library__tenant_slug__projects__project_id__versions__version_record_id__pins__pin_id__delete`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `project_id` | path | string | yes | Project identifier that scopes the request. |
| `version_record_id` | path | string | yes | Version row identifier (``versions.id`` UUID). |
| `pin_id` | path | string | yes | Path parameter identifying the pin id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for delete pin. | `application/json` [`DeletedResponse`](#schema-deletedresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ApprovalDecisionRequest` {#schema-approvaldecisionrequest}

Record a decision on the current stage.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `decision` | enum `"approve"`, `"request_changes"` | yes | Decision. |
| `note` | string or null | no | Note. |
| `stage` | integer or null | no | The stage the reviewer was shown; refused with 409 STAGE_NOT_CURRENT when another stage is current. |

### `ApprovalResponse` {#schema-approvalresponse}

A revision's assessment plus its decision history.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revisionId` | string | yes | Revision ID. |
| `revision` | string | yes | Revision. |
| `state` | string | yes | State. |
| `assessment` | object | yes | Assessment. |
| `decisions` | array of `ApprovalDecisionBody` | no | Decisions. |

### `AuditExportResponse` {#schema-auditexportresponse}

AuditExportResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `rows` | array of object | no | Rows. |
| `truncated` | boolean | no | Truncated. |

### `ComponentCreateRequest` {#schema-componentcreaterequest}

Create a component plus its initial draft revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Stable library name (component-key safe). |
| `kind` | string | yes | parameter \| header \| requestBody \| response \| securityBundle \| schema |
| `description` | string or null | no | Free-text description. |
| `ownerId` | string or null | no | Accountable member; defaults to the creator. |
| `initialRevision` | `InitialRevisionBody` | no | Initial Revision. |

### `ComponentCreateResponse` {#schema-componentcreateresponse}

ComponentCreateResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `componentId` | string | yes | Component ID. |
| `revisionId` | string | yes | Revision ID. |

### `ComponentDetailBody` {#schema-componentdetailbody}

Component detail: the summary plus its revisions, highest semver first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `name` | string | yes | Human-readable name. |
| `kind` | string | yes | Kind. |
| `description` | string or null | no | Free-text description. |
| `ownerId` | string or null | no | Owner ID. |
| `revisionCount` | integer | no | Number of revision. |
| `publishedCount` | integer | no | Number of published. |
| `headRevision` | string or null | no | Highest published semver, or null while draft-only. |
| `revisions` | array of `ComponentLibraryRevisionBody` | no | Revisions. |

### `ComponentListResponse` {#schema-componentlistresponse}

ComponentListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `components` | array of `ComponentSummaryBody` | no | Components. |

### `ComponentUsageResponse` {#schema-componentusageresponse}

DCW-3.3 usage report: tenant-wide pins and direct/transitive dependents.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `componentId` | string | yes | Component ID. |
| `pins` | array of `UsagePinBody` | no | Pins. |
| `dependents` | array of `UsageDependentBody` | no | Reverse index of ``refs``: the visible types that reference this one, one entry per referencing edge. |

### `DeletedResponse` {#schema-deletedresponse}

DeletedResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deleted` | boolean | yes | Deleted. |

### `DeprecationBody` {#schema-deprecationbody}

One live deprecation with its consumers and guidance.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `componentId` | string | yes | Component ID. |
| `componentName` | string | yes | Component Name. |
| `kind` | string or null | no | Kind. |
| `revisionId` | string | yes | Revision ID. |
| `revision` | string | yes | Revision. |
| `replacementRevisionId` | string or null | no | Replacement Revision ID. |
| `replacementRevision` | string or null | no | Replacement Revision. |
| `sunsetAt` | string | yes | Sunset At. |
| `status` | string | yes | scheduled \| sunset |
| `migrationGuide` | string or null | no | Migration Guide. |
| `affectedProjects` | array of `AffectedProjectBody` | no | Affected Projects. |
| `guidance` | object | no | Guidance. |

### `DeprecationListResponse` {#schema-deprecationlistresponse}

DeprecationListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `deprecations` | array of [`DeprecationBody`](#schema-deprecationbody) | no | Deprecations. |

### `DeprecationRequest` {#schema-deprecationrequest}

Schedule the deprecation of a published revision.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sunsetAt` | string (date-time) | yes | When new pins to the revision stop (ISO 8601). |
| `replacementRevisionId` | string or null | no | A published, higher revision of the same component. |
| `migrationGuide` | string or null | no | Migration Guide. |

### `GovernancePolicyResponse` {#schema-governancepolicyresponse}

The resolved component policy (see ``ComponentGovernancePolicy.as_payload``).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `guideId` | string or null | no | Guide ID. |
| `guideName` | string or null | no | Guide Name. |
| `approvalStages` | array of object | no | Approval Stages. |
| `deprecationNoticeDays` | integer | no | Deprecation Notice Days. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MaterializationPreviewResponse` {#schema-materializationpreviewresponse}

The deterministic preview of materializing the version's pins.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `includeOrigin` | boolean | yes | Include Origin. |
| `entries` | array of `MaterializationEntryBody` | no | Entries. |
| `collisions` | array of `MaterializationEntryBody` | no | Collisions. |

### `PinCreateRequest` {#schema-pincreaterequest}

Pin one published library revision to the draft version.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `componentRevisionId` | string | yes | Component Revision ID. |
| `localName` | string or null | no | Optional preferred local components key; collisions still resolve deterministically and never overwrite local components. |

### `PinCreateResponse` {#schema-pincreateresponse}

PinCreateResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pinId` | string | yes | Pin ID. |

### `PinListResponse` {#schema-pinlistresponse}

PinListResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `pins` | array of `PinBody` | no | Pins. |

### `PublishResponse` {#schema-publishresponse}

PublishResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `published` | boolean | yes | Published. |
| `alreadyPublished` | boolean | yes | Already Published. |
| `revision` | string | yes | Revision. |

### `RevisionCreateRequest` {#schema-revisioncreaterequest}

Create a new draft revision of an existing component.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revision` | string | yes | Semver revision string, unique per component. |
| `payload` | any | no | Payload. |
| `schemaPrimitiveId` | string or null | no | Schema Primitive ID. |

### `RevisionMutationResponse` {#schema-revisionmutationresponse}

RevisionMutationResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `revisionId` | string | yes | Revision ID. |

### `RevisionUpdateRequest` {#schema-revisionupdaterequest}

Replace a draft revision's canonical payload.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `payload` | any | no | Payload. |
| `schemaPrimitiveId` | string or null | no | Schema Primitive ID. |

### `UpgradePreviewRequest` {#schema-upgradepreviewrequest}

UpgradePreviewRequest schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `targetRevisionId` | string | yes | Target Revision ID. |

### `UpgradePreviewResponse` {#schema-upgradepreviewresponse}

UpgradePreviewResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `componentId` | string | yes | Component ID. |
| `targetRevisionId` | string | yes | Target Revision ID. |
| `targetRevision` | string | yes | Target Revision. |
| `entries` | array of `UpgradeEntryBody` | no | Entries. |
| `eligible` | integer | no | Eligible. |
| `skipped` | integer | no | Skipped. |
| `breaking` | integer | no | Eligible versions with a breaking change. |
| `confirmationToken` | string | yes | Confirmation Token. |
| `policy` | object | no | Policy. |

### `UpgradeRequest` {#schema-upgraderequest}

Run a previewed plan.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `targetRevisionId` | string | yes | Target Revision ID. |
| `pinIds` | array of string | yes | Pin IDs. |
| `confirmationToken` | string | yes | Confirmation Token. |
| `confirm` | boolean | no | Must be true: the caller confirms the previewed impact. |

### `UpgradeResponse` {#schema-upgraderesponse}

UpgradeResponse schema.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `targetRevision` | string | yes | Target Revision. |
| `upgraded` | array of object | no | Upgraded. |
| `affectedProjects` | array of `AffectedProjectBody` | no | Affected Projects. |
